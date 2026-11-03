"""按需图表回归：真实训练/绘图、去重、缓存、失败隔离和删除时取消。仅使用临时目录。"""
import hashlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'web'),str(ROOT/'tests')]
import test_model_versions as version_tests
from model_registry import ModelRegistry
from training_charts import TrainingCharts


class LazyCharts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        version_tests.ModelVersions.setUpClass();cls.fixture=version_tests.ModelVersions

    @classmethod
    def tearDownClass(cls):cls.fixture.tearDownClass()

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='tdc_charts_')
        self.registry=ModelRegistry(Path(self.temporary.name)/'models')
        self.ids={key:self.registry.register(self.fixture.project/key)['id'] for key in self.fixture.ids}
        self.blocked=True
        self.charts=TrainingCharts(self.registry,lambda:self.blocked,ROOT)

    def tearDown(self):
        self.charts.close();self.temporary.cleanup()

    def wait_chart(self,kind,model,index=0,timeout=40):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            path,status=self.charts.request(kind,model,index)
            if path:return path
            if status['state']=='failed':self.fail(status['message'])
            with self.charts.lock:
                self.assertLessEqual(sum(job['state']=='running' for job in self.charts.jobs.values()),1)
            time.sleep(.05)
        self.fail('等待真实图表超时')

    def test_model_ready_without_png_and_all_dedicated_charts(self):
        self.blocked=False
        for algorithm,model_id in self.ids.items():
            path=self.registry.path(model_id)
            self.assertTrue(path.with_suffix('.plot_data.npz').is_file())
            self.assertEqual(list(path.parent.glob('*.png')),[],'训练过程不应生成PNG')
            weights=hashlib.sha256(path.read_bytes()).hexdigest()
            image=self.wait_chart('model',model_id)
            self.assertEqual(image.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),weights)
            stamp=image.stat().st_mtime_ns
            cached,status=self.charts.request('model',model_id)
            self.assertEqual(cached,image);self.assertTrue(status['cached'])
            self.assertEqual(image.stat().st_mtime_ns,stamp)

    def test_queue_dedup_selected_class_and_single_worker(self):
        model_id=self.ids['random_forest']
        for _ in range(5):self.charts.request('overview',model_id)
        self.assertEqual(len(self.charts.jobs),1)
        self.assertIsNone(self.charts.process)
        self.charts.request('peaks',model_id,1)
        self.assertEqual(len(self.charts.jobs),2)
        self.blocked=False;self.charts.wake.set()
        self.wait_chart('overview',model_id);self.wait_chart('peaks',model_id,1)
        folder=self.registry.path(model_id).parent/'charts_v2'
        self.assertTrue((folder/'peak_01.png').is_file())
        self.assertFalse((folder/'peak_00.png').exists())
        self.assertFalse(self.registry.path(model_id).with_suffix('.peaks.png').exists())
        for bad in (-1,2):
            with self.assertRaises(ValueError):self.charts.request('peaks',model_id,bad)
        with self.assertRaises(ValueError):self.charts.request('model','../escape')

    def test_api_returns_job_json_before_png(self):
        controller=self.fixture().controller();controller.registry=self.registry;controller.charts=self.charts
        model_id=self.ids['random_forest']
        with patch.object(version_tests.server,'controller',controller):
            client=version_tests.server.app.test_client()
            response=client.get('/api/training/image/peaks?model_id='+model_id+'&class_index=1')
            self.assertEqual(response.status_code,202)
            self.assertTrue(response.is_json);self.assertEqual(response.get_json()['state'],'queued')
            self.assertEqual(client.get('/api/training/image/peaks?model_id='+model_id+'&class_index=9').status_code,400)
            self.blocked=False;self.charts.wake.set();self.wait_chart('peaks',model_id,1)
            response=client.get('/api/training/image/peaks?model_id='+model_id+'&class_index=1')
            self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'image/png');response.close()

    def test_failure_does_not_modify_model_and_retry(self):
        self.charts.project=Path(self.temporary.name)/'missing_script'
        self.blocked=False;model_id=self.ids['random_forest'];weights=self.registry.info(model_id)['parameter_hashes']
        self.charts.request('importance',model_id)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            _,status=self.charts.request('importance',model_id)
            if status['state']=='failed':break
            time.sleep(.05)
        self.assertEqual(status['state'],'failed')
        self.assertEqual(self.registry.info(model_id)['parameter_hashes'],weights)
        self.charts.project=ROOT;self.charts.request('importance',model_id,retry=True)
        self.wait_chart('importance',model_id)

    def test_cancel_before_delete_never_recreates_version(self):
        helper=Path(self.temporary.name)/'helper';helper.mkdir()
        (helper/'render_training_chart.py').write_text('import time\ntime.sleep(30)\n',encoding='utf-8')
        self.charts.project=helper;self.blocked=False;model_id=self.ids['decision_tree']
        self.charts.request('importance',model_id)
        deadline=time.monotonic()+5
        while self.charts.process is None and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNotNone(self.charts.process)
        self.charts.cancel_model(model_id);self.registry.delete(model_id)
        time.sleep(.3)
        self.assertFalse((self.registry.versions/model_id).exists())
        self.assertEqual(self.charts.jobs[(model_id,'importance',0)]['state'],'cancelled')


if __name__=='__main__':unittest.main()
