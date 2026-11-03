import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'report/release_manifest.json').read_text(encoding='utf-8'))
bad=[x['path']for x in manifest['files']if not(ROOT/x['path']).is_file()or hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()!=x['sha256']]
if bad:print('FAIL:',*bad,sep='\n');sys.exit(1)
print('PASS: {}个文件哈希匹配；不是来源认证或上板证明。'.format(len(manifest['files'])))
