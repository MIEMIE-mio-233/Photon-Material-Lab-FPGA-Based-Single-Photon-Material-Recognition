"""训练图表的单进程队列。只存任务状态；模型权重和Matplotlib留在短生命周期子进程。"""
import json
import os
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

from model_registry import file_hash


class TrainingCharts:
    KINDS={'overview','peaks','importance','model'}
    def __init__(self,registry,busy,project):
        self.registry,self.busy,self.project=registry,busy,Path(project)
        self.lock=threading.RLock();self.jobs=OrderedDict()
        self.idle=threading.Condition(self.lock)
        self.process=None;self.current_key=None;self.thread=None
        self.closed=False;self.wake=threading.Event()

    def request(self,kind,model_id=None,class_index=0,retry=False):
        if kind not in self.KINDS:raise ValueError('图表类型不正确')
        with self.registry.lock:
            model=self.registry.path(model_id);info=self.registry.info(model_id)
            if kind=='peaks' and (isinstance(class_index,bool) or not 0<=class_index<len(info['classes'])):
                raise ValueError('核验材质编号超出模型类别范围')
            index=class_index if kind=='peaks' else 0
            name='peak_{:02d}'.format(index) if kind=='peaks' else kind
            target=model.parent/'charts_v2'/(name+'.png')
            if target.parent.is_symlink() or target.parent.resolve().parent!=model.parent.resolve():
                raise ValueError('图表缓存目录无效')
            if target.is_file() and target.stat().st_size:
                return target,dict(state='ready',cached=True)
            # 旧版PNG直接复用，避免升级后重新画已有图；不把全类长图当成某一类。
            legacy=model.with_suffix('.peak_{:02d}.png'.format(index) if kind=='peaks' else '.'+kind+'.png')
            if legacy.is_file() and legacy.stat().st_size:
                return legacy,dict(state='ready',cached=True,legacy=True)
            key=(info['id'],kind,index)
            with self.lock:
                if self.closed:raise ValueError('图表服务已关闭')
                old=self.jobs.get(key)
                if old and old['state']!='ready' and not (retry and old['state'] in ('failed','cancelled')):
                    return None,self._public(old)
                pending=sum(job['state'] in ('queued','running') for job in self.jobs.values())
                if pending>=8:
                    return None,dict(state='queued',message='绘图队列已满，等待空位',retry_after_ms=1000)
                target.parent.mkdir(exist_ok=True)
                self.jobs[key]=dict(state='queued',model=str(model),output=str(target),model_id=info['id'],
                                   kind=kind,class_index=index,message='等待生成所选图表',created=time.monotonic())
                # 已结束状态最多保留64项；PNG缓存仍保留在各自版本目录。
                for stale in list(self.jobs):
                    if len(self.jobs)<=64:break
                    if self.jobs[stale]['state'] in ('ready','failed','cancelled'):self.jobs.pop(stale)
                if self.thread is None:
                    self.thread=threading.Thread(target=self._worker,daemon=True,name='training-charts')
                    self.thread.start()
                self.wake.set()
                return None,self._public(self.jobs[key])

    @staticmethod
    def _public(job):
        return {key:job[key] for key in ('state','message','render_seconds') if key in job}

    def _worker(self):
        while not self.closed:
            self.wake.wait(.25);self.wake.clear()
            with self.lock:
                if self.closed:return
                candidate=next(((key,job) for key,job in self.jobs.items() if job['state']=='queued'),None)
                if candidate is None:continue
                key,job=candidate
                if self.busy():
                    job['message']='等待当前采集、识别或训练任务结束后绘图'
                    continue
                job.update(state='running',message='正在生成所选图表');self.current_key=key
            started=time.monotonic()
            try:
                model=Path(job['model']);target=Path(job['output'])
                version=json.loads((model.parent/'version.json').read_text(encoding='utf-8'))
                # 只有模型专属图需要反序列化内部joblib；先核验版本库记录的可信参数哈希。
                for name,expected in version['parameter_hashes'].items():
                    if file_hash(model.parent/name)!=expected:raise ValueError('模型参数或报告哈希不一致')
                command=[sys.executable,str(self.project/'render_training_chart.py'),'--model',str(model),
                         '--kind',job['kind'],'--class-index',str(job['class_index']),'--output',str(target)]
                env=dict(os.environ,PYTHONIOENCODING='utf-8',MPLBACKEND='Agg',
                         OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
                with target.with_suffix('.log').open('wb') as log:
                    with self.lock:
                        if self.closed or job['state']=='cancelled':continue
                        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env)
                        self.process=process
                    deadline=time.monotonic()+120
                    while process.poll() is None:
                        if time.monotonic()>deadline:
                            process.terminate()
                            try:process.wait(timeout=3)
                            except subprocess.TimeoutExpired:process.kill();process.wait()
                            raise ValueError('绘图超时，可重新加载图表；模型仍可正常识别')
                        time.sleep(.1)
                    if process.returncode:
                        tail=target.with_suffix('.log').read_text(encoding='utf-8',errors='replace').splitlines()
                        raise ValueError((tail[-1] if tail else '绘图子进程失败')[:350])
                if not target.is_file():raise ValueError('绘图未生成完整PNG')
                with self.lock:
                    if job['state']!='cancelled':job.update(state='ready',message='图表已生成',render_seconds=round(time.monotonic()-started,3))
            except Exception as error:
                with self.lock:
                    if job['state']!='cancelled':job.update(state='failed',message=str(error))
            finally:
                with self.lock:
                    self.process=None;self.current_key=None;self.idle.notify_all()
                self.wake.set()

    def cancel_model(self,model_id):
        """删除版本前终止其绘图，避免任务完成后重新写出被删版本的文件。"""
        with self.lock:
            for key,job in self.jobs.items():
                if key[0]==model_id:job.update(state='cancelled',message='模型版本已删除')
            if self.current_key and self.current_key[0]==model_id and self.process and self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.wake.set()
            # 等待工作线程关闭日志等文件句柄，再让版本库删除目录；兼容Windows。
            deadline=time.monotonic()+5
            while self.current_key and self.current_key[0]==model_id:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ValueError('绘图任务尚未完全退出，请稍后删除模型')
                self.idle.wait(remaining)

    def close(self):
        with self.lock:
            self.closed=True
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.wake.set()
        if self.thread:self.thread.join(timeout=4)
