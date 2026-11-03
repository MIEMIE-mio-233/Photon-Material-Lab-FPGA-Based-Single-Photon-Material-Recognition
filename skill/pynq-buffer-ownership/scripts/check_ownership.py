"""Validate PS/PL buffer ownership from explicit lifecycle events (offline).

Events are JSON list: alloc, cpu_write, flush, start, timeout, done, abort_ack,
invalidate, cpu_read, free. start includes reads/writes lists. All other events
except start/done/timeout/abort_ack include buffer. alloc includes coherent.
Exit 0 pass, 1 unsafe lifecycle, 2 malformed input. No hardware access.
"""
import argparse
import json
from pathlib import Path


def check(events):
    if not isinstance(events, list) or not events: raise ValueError('Nonempty event list required')
    buffers = {}; active = None; errors = []
    valid = {'alloc','cpu_write','flush','start','timeout','done','abort_ack','invalidate','cpu_read','free'}
    for i, e in enumerate(events):
        if not isinstance(e, dict) or e.get('event') not in valid: raise ValueError('Unknown event')
        kind = e['event']; name = e.get('buffer')
        try:
            if kind == 'alloc':
                if not isinstance(name, str) or not name: raise ValueError('Buffer name required')
                if type(e.get('coherent')) is not bool: raise ValueError('Explicit coherent boolean required')
                if name in buffers: raise RuntimeError('duplicate_allocation')
                buffers[name] = {'coherent':e['coherent'], 'dirty':False, 'stale':False, 'initialized':False}
            elif kind == 'start':
                if active is not None: raise RuntimeError('overlapping_jobs')
                reads=e.get('reads'); writes=e.get('writes')
                if not isinstance(reads,list) or not isinstance(writes,list) or not reads+writes:
                    raise ValueError('start requires buffer lists')
                if any(not isinstance(n,str) for n in reads+writes): raise ValueError('Invalid buffer ID')
                if len(set(reads))!=len(reads) or len(set(writes))!=len(writes): raise ValueError('Duplicate buffer ID')
                for n in reads+writes:
                    if n not in buffers: raise RuntimeError('unallocated_device_buffer')
                for n in reads:
                    if not buffers[n]['initialized']: raise RuntimeError('uninitialized_device_read')
                    if buffers[n]['dirty'] and not buffers[n]['coherent']: raise RuntimeError('missing_flush')
                active={'reads':set(reads),'writes':set(writes)}
            elif kind in {'done','timeout','abort_ack'}:
                if active is None: raise RuntimeError('completion_without_job')
                if kind != 'timeout':
                    for n in active['writes']:
                        buffers[n]['stale']=not buffers[n]['coherent']
                        buffers[n]['dirty']=False
                        buffers[n]['initialized']=(kind=='done')
                    active=None
                # A software timeout does not return ownership to PS.
            else:
                if name not in buffers: raise RuntimeError('unknown_buffer')
                b=buffers[name]
                if active and name in active['reads']|active['writes']: raise RuntimeError('device_owns_buffer')
                if kind=='cpu_write':
                    b['dirty']=True;b['stale']=False;b['initialized']=True
                elif kind=='flush':
                    if b['stale']: raise RuntimeError('flush_stale_cache')
                    b['dirty']=False
                elif kind=='invalidate':
                    if b['dirty'] and not b['coherent']: raise RuntimeError('invalidate_dirty_data')
                    b['stale']=False
                elif kind=='cpu_read':
                    if not b['initialized']: raise RuntimeError('invalid_result')
                    if b['stale']: raise RuntimeError('missing_invalidate')
                elif kind=='free': del buffers[name]
        except RuntimeError as error:
            errors.append({'event_index':i,'event':kind,'violation':str(error)})
    if active: errors.append({'event_index':len(events),'violation':'device_still_running'})
    return {'passed':not errors,'violations':errors,'remaining_allocations':sorted(buffers),
            'scope':'Declared event ordering; cache attributes and hardware completion need independent verification'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('events',type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    if a.events.resolve()==a.output.resolve():p.error('Output must differ from input')
    try: result=check(json.loads(a.events.read_text(encoding='utf-8-sig')))
    except (ValueError,OSError,TypeError,KeyError) as e:p.error(str(e))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
