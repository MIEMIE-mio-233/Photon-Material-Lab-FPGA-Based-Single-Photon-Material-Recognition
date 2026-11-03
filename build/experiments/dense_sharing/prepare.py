"""Prepare an isolated HLS sharing ablation from this release. No deployed RTL changes."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def prepare(root, work):
    if not work.is_absolute() or not str(work).isascii():raise ValueError('Use an absolute ASCII workspace')
    if work.is_relative_to(root):raise ValueError('Workspace must be outside the release')
    if work.exists() and any(work.iterdir()):raise ValueError('Workspace must be empty')
    original=(root/'src/hls/tdc_accelerator.cpp').read_text(encoding='utf-8')
    start=original.index('static void dense_layer('); end=original.index('static bool dense_infer(')
    call='dense_layer(parameters,header,5,4,patch,next,true);'
    if original.count(call)!=1:raise ValueError('Source structure changed: review transformation')
    duplicate=original[start:end].replace('dense_layer(', 'convolution_layer(')
    separate=(original[:end]+duplicate+original[end:]).replace(call,call.replace('dense_layer','convolution_layer'))
    hashes={}
    for name,text in [('shared',original),('separate',separate)]:
        p=work/name/'kernel.cpp';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(text,encoding='utf-8');hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    shutil.copytree(root/'sim/hls',work/'fixtures')
    shutil.copy2(Path(__file__).with_name('run.tcl'),work/'run.tcl')
    info={'release_source_sha256':hashlib.sha256((root/'src/hls/tdc_accelerator.cpp').read_bytes()).hexdigest(),
          'variant_sha256':hashes,'controlled_change':'Separate convolution function copy versus existing dense_layer call sharing',
          'fixture_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (work/'fixtures').iterdir() if p.is_file()}}
    (work/'inputs.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    return info


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',required=True,type=Path);a=p.parse_args()
    prepare(Path(__file__).resolve().parents[3],a.work.absolute())
