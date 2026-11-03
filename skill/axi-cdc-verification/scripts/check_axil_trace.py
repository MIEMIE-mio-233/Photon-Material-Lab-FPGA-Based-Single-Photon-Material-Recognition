"""Single-clock AXI4-Lite trace checker; JSON list of pre-edge snapshots.

Checks decoupled AW/W, response accounting, payload stability under stalls,
reset recovery and bounded outstanding transactions. Not a CDC/metastability proof.
Exit 0 pass, 1 violation, 2 invalid input. Python 3.9+, standard library.
"""
import argparse
import json
from pathlib import Path

PAYLOAD = {'aw': ('awaddr', 'awprot'), 'w': ('wdata', 'wstrb'),
           'b': ('bresp',), 'ar': ('araddr', 'arprot'), 'r': ('rdata', 'rresp')}


def check(rows, max_pending=16, max_age=1000):
    if not isinstance(rows, list) or not rows or max_pending < 1 or max_age < 1:
        raise ValueError('Nonempty trace and positive limits required')
    pending = {'aw': [], 'w': [], 'ar': []}
    held = {}
    errors = []
    counts = {'writes': 0, 'reads': 0, 'reset_aborted': 0}
    last_cycle = -1
    for row in rows:
        cycle = row.get('cycle')
        if type(cycle) is not int or cycle != last_cycle+1:
            raise ValueError('Cycles must be contiguous starting at zero')
        last_cycle = cycle
        for key in ['reset_n'] + [c+s for c in PAYLOAD for s in ('valid', 'ready')]:
            if type(row.get(key)) not in (int, bool) or row[key] not in (0, 1):
                raise ValueError('Expected binary signal: ' + key)
        for ch, fields in PAYLOAD.items():
            if row[ch+'valid']:
                for key in fields:
                    if type(row.get(key)) is not int or row[key] < 0:
                        raise ValueError('Missing/noninteger valid payload: ' + key)
        if not row['reset_n']:
            counts['reset_aborted'] += sum(len(q) for q in pending.values())
            pending = {'aw': [], 'w': [], 'ar': []}; held = {}
            continue
        for ch, fields in PAYLOAD.items():
            if ch in held and (not row[ch+'valid'] or tuple(row.get(f) for f in fields) != held[ch]):
                errors.append({'cycle': cycle, 'rule': 'stalled_payload_changed', 'channel': ch})
            if row[ch+'valid'] and not row[ch+'ready']:
                held[ch] = tuple(row[f] for f in fields)
            else:
                held.pop(ch, None)
        # Responses must be backed by requests accepted on previous edges.
        for ch, needs, counter in [('b', ('aw', 'w'), 'writes'), ('r', ('ar',), 'reads')]:
            if row[ch+'valid']:
                if not all(pending[n] for n in needs):
                    errors.append({'cycle': cycle, 'rule': 'response_without_request', 'channel': ch})
                elif row[ch+'ready']:
                    for n in needs: pending[n].pop(0)
                    counts[counter] += 1
        for ch in pending:
            if row[ch+'valid'] and row[ch+'ready']:
                pending[ch].append(cycle)
            if len(pending[ch]) > max_pending:
                errors.append({'cycle': cycle, 'rule': 'outstanding_limit', 'channel': ch})
            if pending[ch] and cycle-pending[ch][0] > max_age:
                errors.append({'cycle': cycle, 'rule': 'request_timeout', 'channel': ch})
    if held or any(pending.values()):
        errors.append({'cycle': last_cycle, 'rule': 'incomplete_trace'})
    return {'passed': not errors, 'cycles': len(rows), 'counts': counts, 'violations': errors,
            'scope': 'Complete AXI4-Lite transaction trace; no register semantics or CDC analog proof'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trace', type=Path); p.add_argument('--output', required=True, type=Path)
    p.add_argument('--max-pending', type=int, default=16); p.add_argument('--max-age', type=int, default=1000)
    a = p.parse_args()
    if a.trace.resolve() == a.output.resolve(): p.error('Output must differ from input')
    try:
        result = check(json.loads(a.trace.read_text(encoding='utf-8-sig')), a.max_pending, a.max_age)
    except (ValueError, OSError, TypeError, KeyError) as e: p.error(str(e))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
