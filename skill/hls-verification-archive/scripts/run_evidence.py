"""Run a trusted regression plan and archive sources, commands, logs and verdicts.

Plan paths are relative to --root. Commands are argv arrays (no shell expansion).
Use only reviewed local plans; commands execute with the caller's permissions.
Return 0 all passed, 1 executed failure, 2 invalid plan. Python 3.9+.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path


def under(root, name):
    p=(root/name).resolve()
    if not p.is_relative_to(root): raise ValueError('Path outside root: '+name)
    return p


def validate(plan, root):
    if not isinstance(plan.get('tool_version'),str) or not plan['tool_version'].strip():
        raise ValueError('Explicit tool_version required')
    files=plan.get('inputs',[])
    if not files or len(files)!=len(set(files)): raise ValueError('Unique input paths required')
    for name in files:
        if not under(root,name).is_file():raise ValueError('Missing input: '+name)
    names=set()
    if not plan.get('steps'):raise ValueError('Empty steps')
    for step in plan['steps']:
        name=step.get('name','')
        if not re.fullmatch('[a-zA-Z0-9_-]+',name) or name in names:raise ValueError('Invalid step name')
        names.add(name)
        argv=step.get('argv')
        if not isinstance(argv,list) or not argv or any(not isinstance(v,str) or not v for v in argv):
            raise ValueError('Nonempty argv array required')
        if not under(root,step.get('cwd','.')).is_dir():raise ValueError('Invalid cwd')
        if not isinstance(step.get('timeout_s'),(float,int)) or not 0<step['timeout_s']<=86400:
            raise ValueError('timeout_s must be 0..86400')
        for key in ['pass_regex','fail_regex']:
            patterns=step.get(key)
            if not isinstance(patterns,list) or not patterns:raise ValueError('Explicit '+key+' required')
            for pattern in patterns:re.compile(pattern)
        for name in step.get('artifacts',[]):under(root,name)


def execute(plan, root, output):
    validate(plan,root)
    if output.exists() and any(output.iterdir()):raise ValueError('Output must be empty')
    output.mkdir(parents=True,exist_ok=True)
    fingerprint=lambda names:{n:hashlib.sha256(under(root,n).read_bytes()).hexdigest() for n in names}
    before=fingerprint(plan['inputs']); results=[]
    for step in plan['steps']:
        start=time.monotonic(); timeout=False; code=None
        logfile=output/(step['name']+'.log')
        try:
            with logfile.open('wb') as log:
                # A process group is not forcibly terminated: vendor subprocesses may
                # need their own cancellation command. Timeout is always a failure.
                proc=subprocess.Popen(step['argv'],cwd=under(root,step.get('cwd','.')),stdout=log,stderr=subprocess.STDOUT)
                try:code=proc.wait(timeout=step['timeout_s'])
                except subprocess.TimeoutExpired:
                    timeout=True;proc.kill();proc.wait()
        except OSError as error:
            logfile.write_text(str(error),encoding='utf-8')
        text=logfile.read_text(encoding='utf-8',errors='replace')
        pass_match=all(re.search(p,text,re.M) for p in step['pass_regex'])
        fail_match=any(re.search(p,text,re.M) for p in step['fail_regex'])
        artifacts={};missing=[]
        for n in step.get('artifacts',[]):
            file=under(root,n)
            if file.is_file():artifacts[n]=hashlib.sha256(file.read_bytes()).hexdigest()
            else:missing.append(n)
        ok=code==0 and not timeout and pass_match and not fail_match and not missing
        results.append({'name':step['name'],'argv':step['argv'],'cwd':step.get('cwd','.'),
                        'passed':bool(ok),'exit_code':code,'timeout':timeout,'seconds':time.monotonic()-start,
                        'log':logfile.name,'log_sha256':hashlib.sha256(logfile.read_bytes()).hexdigest(),
                        'artifacts_sha256':artifacts,'missing_artifacts':missing})
        if timeout:break
    after={n:(hashlib.sha256(under(root,n).read_bytes()).hexdigest() if under(root,n).is_file() else None) for n in plan['inputs']}
    result={'date_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'tool_version':plan['tool_version'],'scope':plan.get('scope','declared regression'),
            'inputs_sha256':before,'inputs_unchanged':before==after,'steps':results,
            'passed':len(results)==len(plan['steps']) and all(s['passed'] for s in results) and before==after}
    (output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('plan',type=Path)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:r=execute(json.loads(a.plan.read_text(encoding='utf-8-sig')),a.root.resolve(),a.output.resolve())
    except (ValueError,OSError,TypeError,KeyError,re.error) as e:p.error(str(e))
    return 0 if r['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
