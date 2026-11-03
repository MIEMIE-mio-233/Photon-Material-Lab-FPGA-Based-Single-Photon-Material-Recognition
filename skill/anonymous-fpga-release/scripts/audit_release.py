"""只读扫描匿名发布目录；不删除文件、不修改DOCX、不操作设备。"""
import argparse,hashlib,json,re,sys,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

TEXT_EXT={'.py','.md','.json','.js','.html','.css','.tcl','.sh','.ps1','.cpp','.v','.sv','.xdc','.rpt','.csv','.txt','.xci','.bd','.hwh','.yaml','.yml'}
STANDARD_NAMES={'README.md','SKILL.md','LICENSE'}

def audit(root,terms=(),strict_names=False,manifest=None):
    root=Path(root).resolve()
    if not root.is_dir():raise ValueError('root must be a directory')
    if not all(isinstance(t,str)and t.strip()for t in terms):raise ValueError('deny terms must be nonempty strings')
    terms=[re.compile(re.escape(t),re.I)for t in terms]
    findings=[];text_files=0;docx_files=0;hashes_checked=0;unreadable=[]
    def add(path,kind):
        label=path.relative_to(root).as_posix()
        for term in terms:label=term.sub('[redacted]',label)
        findings.append(dict(path=label,check=kind))
    for p in sorted(root.rglob('*')):
        if p.is_symlink():add(p,'symlink_not_followed');continue
        if strict_names and p.name not in STANDARD_NAMES and not re.fullmatch(r'[a-z0-9_.-]+',p.name):add(p,'filename_policy')
        if not p.is_file():continue
        if any(term.search(p.relative_to(root).as_posix())for term in terms):add(p,'deny_term_in_path')
        if p.suffix.lower()in TEXT_EXT or p.name in STANDARD_NAMES:
            try:s=p.read_text(encoding='utf-8-sig')
            except UnicodeError:
                unreadable.append(p.relative_to(root).as_posix());continue
            text_files+=1
            if any(term.search(s)for term in terms):add(p,'deny_term_in_text')
            if re.search(r'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----',s):add(p,'private_key_text')
        if p.suffix.lower()=='.docx':
            docx_files+=1
            try:
                with zipfile.ZipFile(p)as package:
                    for name in package.namelist():
                        if not name.endswith(('.xml','.rels')):continue
                        member=package.getinfo(name)
                        if member.file_size>8*1024*1024:raise ValueError('DOCX XML exceeds supported scan size')
                        raw=package.read(name);s=raw.decode('utf-8')
                        if any(term.search(s)for term in terms):add(p,'deny_term_in_docx')
                        if name=='docProps/core.xml':
                            for node in ET.fromstring(raw):
                                if node.tag.rsplit('}',1)[-1]in('creator','lastModifiedBy')and(node.text or'').strip():add(p,'docx_author')
                        if name.startswith('word/'):
                            for node in ET.fromstring(raw).iter():
                                if any(key.rsplit('}',1)[-1]=='author'and value.strip()for key,value in node.attrib.items()):add(p,'docx_revision_or_comment_author')
            except (OSError,UnicodeError,zipfile.BadZipFile,ET.ParseError,ValueError):add(p,'docx_scan_incomplete')
    if manifest is not None:
        manifest=Path(manifest)
        if not manifest.is_absolute():manifest=root/manifest
        if manifest.is_symlink()or not manifest.resolve().is_relative_to(root):raise ValueError('manifest must be within root')
        spec=json.loads(manifest.read_text(encoding='utf-8-sig'))
        if not isinstance(spec,dict)or not isinstance(spec.get('files'),list):raise ValueError('manifest requires files list')
        seen=set()
        for entry in spec['files']:
            if not isinstance(entry,dict):raise ValueError('manifest entries must be objects')
            rel=entry.get('path');digest=entry.get('sha256')
            if not isinstance(rel,str)or not rel or '\\'in rel or Path(rel).is_absolute()or '..'in Path(rel).parts:raise ValueError('invalid manifest path')
            if rel in seen:raise ValueError('duplicate manifest path')
            seen.add(rel);p=root/rel
            if not re.fullmatch(r'[a-f0-9]{64}',str(digest)):raise ValueError('invalid SHA256')
            if not p.resolve().is_relative_to(root):raise ValueError('manifest path outside root')
            if p.is_symlink()or not p.is_file():add(p,'missing_or_linked_manifest_file');continue
            hashes_checked+=1
            with p.open('rb')as f:
                actual=hashlib.sha256()
                for chunk in iter(lambda:f.read(1024*1024),b''):actual.update(chunk)
            if actual.hexdigest()!=digest:add(p,'manifest_hash_mismatch')
    return dict(passed=not findings and not unreadable,findings=findings,unreadable_text_files=unreadable,
                text_files=text_files,docx_files=docx_files,hashes_checked=hashes_checked,
                scope='read-only text, names, DOCX author metadata and optional listed hashes; no license or opaque binary anonymity proof')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    parser.add_argument('--deny-file',type=Path,help='仓库外JSON字符串列表，报告不回显禁词')
    parser.add_argument('--strict-names',action='store_true');parser.add_argument('--manifest',type=Path)
    parser.add_argument('--report',type=Path,required=True,help='报告放在扫描目录外，保持根目录只读')
    args=parser.parse_args()
    try:
        if args.report.resolve().is_relative_to(args.root.resolve()):raise ValueError('report must be outside scanned root')
        terms=json.loads(args.deny_file.read_text(encoding='utf-8-sig'))if args.deny_file else[]
        if not isinstance(terms,list):raise ValueError('deny file must contain a JSON list')
        result=audit(args.root,terms,args.strict_names,args.manifest)
    except (ValueError,OSError,TypeError)as error:
        print(json.dumps(dict(passed=False,error=str(error)),ensure_ascii=False));return 2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS'if result['passed']else'FAIL',len(result['findings']),'findings')
    return 0 if result['passed']else 1
if __name__=='__main__':sys.exit(main())
