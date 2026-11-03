"""只读周期窗口检查。输入为JSON整数拍，不四舍五入、不访问设备。"""
import argparse,json,sys
def segments(period,phase,width,active_level=1):
    if any(type(v)is not int for v in (period,phase,width,active_level)):
        raise ValueError('period, phase, width and active_level must be integers')
    if period<2 or not 0<=phase<period or not 1<=width<period or active_level not in (0,1):
        raise ValueError('requires period>=2, 0<=phase<period, 1<=width<period and level=0/1')
    end=phase+width
    return dict(active_level=active_level,idle_level=1-active_level,wraps=end>period,
                intervals=([[0,end-period],[phase,period]]if end>period else[[phase,end]]))
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('config');args=parser.parse_args()
    try:
        with open(args.config,encoding='utf-8')as f:spec=json.load(f)
        output=segments(spec['period_ticks'],spec['phase_ticks'],spec['width_ticks'],spec.get('active_level',1))
    except (OSError,ValueError,KeyError,TypeError)as e:
        print(json.dumps(dict(passed=False,error=str(e))));return 2
    print(json.dumps(dict(passed=True,**output)));return 0
if __name__=='__main__':sys.exit(main())
