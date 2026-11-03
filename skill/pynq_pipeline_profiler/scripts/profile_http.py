"""只读测量仪器网页状态、目录与波形API，不启动采集或改写模型。"""
import argparse,hashlib,json,statistics,time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',required=True,help='网页服务根地址，如http://board:8080')
    p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--warmup',type=int,default=1)
    p.add_argument('--timeout',type=float,default=15)
    p.add_argument('--frame-path',help='省略时读取状态中的最近一帧；无最近帧则跳过波形')
    p.add_argument('--output',required=True,help='将测量结果写到仓库外')
    args=p.parse_args()
    if not 1<=args.repeats<=100 or not 0<=args.warmup<=20 or args.timeout<=0:p.error('采样次数或超时无效')
    root=args.url.rstrip('/')
    if not root.startswith(('http://','https://')):p.error('url应为HTTP或HTTPS地址')
    def get(path):
        start=time.perf_counter()
        with urlopen(root+path,timeout=args.timeout)as r:data=r.read()
        return data,(time.perf_counter()-start)*1000
    first,_=get('/api/state');state=json.loads(first)
    frame=args.frame_path or (state.get('latest')or{}).get('path')
    endpoints=[('state','/api/state'),('catalog','/api/data')]
    if frame:endpoints.append(('plot','/api/plot?'+urlencode(dict(path=frame,view='full'))))
    report=dict(schema_version=1,scope='HTTP round trip including response read; browser rendering excluded',url=root,repeats=args.repeats,warmup=args.warmup,results={})
    for name,path in endpoints:
        samples=[]
        for i in range(args.warmup+args.repeats):
            data,elapsed=get(path);samples.append(dict(warmup=i<args.warmup,ms=elapsed,response_bytes=len(data),response_sha256=hashlib.sha256(data).hexdigest()))
        values=[s['ms']for s in samples if not s['warmup']]
        report['results'][name]=dict(samples=samples,median_ms=statistics.median(values),min_ms=min(values),max_ms=max(values))
        print('{} median {:.3f} ms, {} bytes'.format(name,statistics.median(values),samples[-1]['response_bytes']))
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
