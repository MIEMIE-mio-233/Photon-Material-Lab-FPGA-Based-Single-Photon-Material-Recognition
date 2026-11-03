"""技能结构、链接与行为自测；只在临时目录构造失败场景。"""
import argparse,hashlib,importlib.util,json,subprocess,sys,tempfile,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
if args.report.resolve().is_relative_to(ROOT.resolve()):raise ValueError('report must be outside repository')
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
window=module(ROOT/'skill/waveform-control-contract/scripts/validate_windows.py','windows')
auditor=module(ROOT/'skill/anonymous-fpga-release/scripts/audit_release.py','audit')
cases=0
for period in range(2,18):
    for phase in range(period):
        for width in range(1,period):
            for level in (0,1):
                result=window.segments(period,phase,width,level)
                assert sum(b-a for a,b in result['intervals'])==width
                for tick in range(period):
                    assert any(a<=tick<b for a,b in result['intervals'])==((tick-phase)%period<width)
                assert result['idle_level']==1-level
                cases+=1
for bad in [(0,0,1,1),(10,10,1,1),(10,0,0,1),(10,0,10,1),(10,0,1,2),(10,True,1,1),(10,0.0,1,1)]:
    try:window.segments(*bad)
    except ValueError:pass
    else:raise AssertionError(bad)
assert window.segments(2**32-1,2**32-2,2**32-2)['wraps']
with tempfile.TemporaryDirectory()as folder:
    root=Path(folder)/'repo';root.mkdir();(root/'notes.md').write_text('public content',encoding='utf-8')
    good=auditor.audit(root,['private_marker'],True);assert good['passed']
    manifest=dict(files=[dict(path='notes.md',sha256=hashlib.sha256((root/'notes.md').read_bytes()).hexdigest())])
    (root/'manifest.json').write_text(json.dumps(manifest))
    assert auditor.audit(root,manifest='manifest.json')['passed']
    (root/'notes.md').write_text('private_marker')
    result=auditor.audit(root,['private_marker'],True,'manifest.json')
    assert not result['passed']
    assert {x['check']for x in result['findings']}=={'deny_term_in_text','manifest_hash_mismatch'}
    assert 'private_marker'not in json.dumps(result)
    (root/'notes.md').write_text('public content')
    (root/'private_marker.txt').write_text('ok')
    result=auditor.audit(root,['private_marker'])
    assert not result['passed']and'private_marker'not in json.dumps(result)
    (root/'private_marker.txt').unlink()
    with zipfile.ZipFile(root/'outline.docx','w')as z:
        z.writestr('docProps/core.xml','<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>someone</dc:creator></cp:coreProperties>')
        z.writestr('word/comments.xml','<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:author="reviewer"/></w:comments>')
    result=auditor.audit(root)
    assert {'docx_author','docx_revision_or_comment_author'}<={x['check']for x in result['findings']}
    (root/'outline.docx').unlink()
    (root/'bad_name.PY').write_text('pass')
    assert not auditor.audit(root,strict_names=True)['passed']
    (root/'bad_name.PY').unlink()
    manifest['files'][0]['path']='../outside.txt'
    (root/'manifest.json').write_text(json.dumps(manifest))
    try:auditor.audit(root,manifest='manifest.json')
    except ValueError:pass
    else:raise AssertionError('path escape accepted')
    outside=Path(folder)/'synthetic_check.json'
    (root/'manifest.json').write_text(json.dumps(dict(files=[])))
    command=[sys.executable,str(ROOT/'skill/anonymous-fpga-release/scripts/audit_release.py'),str(root),'--report',str(outside)]
    assert subprocess.run(command,capture_output=True).returncode==0
    (root/'broken.MD').write_text('x')
    assert subprocess.run(command+['--strict-names'],capture_output=True).returncode==1
    assert subprocess.run(command+['--report',str(root/'bad_report.json')],capture_output=True).returncode==2
# 请求取消、相同key的新请求也不能接纳旧响应。
gate=str(ROOT/'skill/instrument-web-workflow/scripts/request_gate.js')
js="const assert=require('node:assert/strict');const {RequestGate}=require(process.argv[1]);const g=new RequestGate();const a=g.begin('model-a:overview');assert(g.accepts(a));const b=g.begin('model-b:overview');assert(!g.accepts(a)&&g.accepts(b));const c=g.begin('model-b:overview');assert(!g.accepts(b)&&g.accepts(c));g.cancel();assert(!g.accepts(c)&&!g.accepts(null));assert.throws(()=>g.begin(''));console.log('request gate passed');"
node=shutil.which('node')
if node:subprocess.run([node,'-e',js,gate],check=True)
else:print('SKIP: Node.js not found; request gate cases not executed')
# 仅检查技能文档的本地链接，不下载网页、不执行板端程序。
import re
links=0
for p in (ROOT/'skill').rglob('*.md'):
    for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
        if '://'in target or target.startswith('#'):continue
        target=target.split('#')[0]
        assert (p.parent/target).exists(),(p,target)
        links+=1
result=dict(passed=True,window_configurations=cases,window_scope='exhaustive small integer digital windows and selected invalid/overflow-boundary inputs; no hardware',
            audit_cases=['clean','text deny term','private name redaction','changed hash','docx core author','docx comment author','filename','manifest escape','cli exit 0/1/2'],
            request_gate_cases=['current','stale model','same key newer epoch','cancel','invalid key'],
            skills=sum(p.is_dir() for p in (ROOT/'skill').iterdir()),local_links_checked=links,request_gate_executed=bool(node),hardware_access=False,production_changes=False)
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))

