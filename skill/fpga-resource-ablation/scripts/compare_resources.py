"""Compare HLS synthesis XML or Vivado utilization reports with an explicit scope.

Python 3.9+, standard library only. Exit 0: comparable; 1: budget exceeded;
2: missing or incomparable evidence. Reports are read-only inputs.
"""
import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_report(path):
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode('utf-8', errors='replace')
    result = {'sha256': hashlib.sha256(raw).hexdigest()}
    if text.lstrip().startswith(('<profile', '<?xml')):
        root = ET.fromstring(text)
        def field(key):
            v = root.findtext(key)
            if v is None or not v.strip():
                raise ValueError('Missing HLS field: ' + key)
            return v.strip()
        result.update(tool=field('ReportVersion/Version'),
                      device=field('UserAssignments/Part'), stage='hls_estimate',
                      top=field('UserAssignments/TopModelName'),
                      clock_ns=float(field('UserAssignments/TargetClockPeriod')),
                      uncertainty_ns=float(field('UserAssignments/ClockUncertainty')),
                      resources={k: float(field('AreaEstimates/Resources/' + k))
                                 for k in ['LUT', 'FF', 'DSP', 'BRAM_18K']})
        value = root.findtext('PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod')
        result['estimated_clock_ns'] = float(value) if value else None
    else:
        def header(name):
            m = re.search(r'^\|\s*' + re.escape(name) + r'\s*:\s*(.*?)\s*$', text, re.M)
            if not m:
                raise ValueError('Missing Vivado header: ' + name)
            return m[1].rstrip('|').strip()
        resources = {}
        for key, aliases in {'LUT': ['CLB LUTs', 'Slice LUTs'],
                             'FF': ['CLB Registers', 'Slice Registers'],
                             'BRAM_TILE': ['Block RAM Tile'], 'DSP': ['DSPs']}.items():
            for alias in aliases:
                m = re.search(r'^\|\s*' + re.escape(alias) + r'\*?\s*\|\s*([\d,.]+)\s*\|', text, re.M)
                if m:
                    resources[key] = float(m[1].replace(',', ''))
                    break
            if key not in resources:
                raise ValueError('Resource not found: ' + key)
        result.update(tool=header('Tool Version'), device=header('Device'),
                      stage=header('Design State'), top=header('Design'), resources=resources)
    if any(not math.isfinite(v) or v < 0 for v in result['resources'].values()):
        raise ValueError('Invalid resource count')
    return result


def compare(before, after, contract):
    for key in ['tool', 'device', 'stage', 'top', 'clock_ns', 'uncertainty_ns']:
        if before.get(key) != after.get(key):
            raise ValueError('Incomparable ' + key)
    for key in ['scope', 'equivalence', 'controlled_change']:
        if not isinstance(contract.get(key), str) or not contract[key].strip():
            raise ValueError('Contract requires ' + key)
    for key in ['before_source_sha256', 'after_source_sha256', 'constraints_sha256', 'fixture_sha256']:
        if not re.fullmatch('[0-9a-f]{64}', contract.get(key, '')):
            raise ValueError('Contract requires SHA256: ' + key)
    if before['resources'].keys() != after['resources'].keys():
        raise ValueError('Resource unit mismatch')
    changes = {}
    for key, value in before['resources'].items():
        new = after['resources'][key]
        changes[key] = {'before': value, 'after': new, 'delta': new-value,
                        'reduction_percent': None if value == 0 else 100*(value-new)/value}
    budgets = contract.get('budgets', {})
    for key, limit in budgets.items():
        if key not in changes or isinstance(limit, bool) or not math.isfinite(limit) or limit < 0:
            raise ValueError('Invalid budget: ' + key)
    failures = [k for k, limit in budgets.items() if after['resources'][k] > limit]
    return {'comparable': True, 'budget_passed': not failures, 'budget_failures': failures,
            'contract': contract, 'before': before, 'after': after, 'changes': changes,
            'scope_note': 'HLS estimates and routed implementation counts are separate stages; source/fixture identities are supplied by the caller.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('before', type=Path); p.add_argument('after', type=Path)
    p.add_argument('--contract', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    if a.output.resolve() in [x.resolve() for x in [a.before, a.after, a.contract]]:
        p.error('Output would overwrite input')
    try:
        result = compare(parse_report(a.before), parse_report(a.after), json.loads(a.contract.read_text(encoding='utf-8-sig')))
    except (ValueError, OSError, ET.ParseError, TypeError) as e:
        p.error(str(e))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if result['budget_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
