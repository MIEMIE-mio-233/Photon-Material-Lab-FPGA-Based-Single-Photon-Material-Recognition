"""单张训练图的独立子进程入口；退出即释放绘图和临时模型内存。"""
import argparse
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--kind',choices=['overview','peaks','importance','model'],required=True)
    parser.add_argument('--class-index',type=int,default=0)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    # ARM上仅用一个CPU、降低调度优先级，避免多张图竞争训练/采集资源。
    if hasattr(os,'nice'):
        try:os.nice(10)
        except OSError:pass
    if hasattr(os,'sched_getaffinity'):
        try:os.sched_setaffinity(0,{max(os.sched_getaffinity(0))})
        except OSError:pass
    from chart_renderer import render_one
    render_one(args.model,args.kind,args.output,args.class_index)


if __name__=='__main__':main()
