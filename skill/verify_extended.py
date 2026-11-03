"""Re-run portable skill checks with failure injection; no FPGA or network access."""
import argparse
import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def module(path, name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',required=True,type=Path);a=p.parse_args()
    if a.report.resolve().is_relative_to(ROOT):p.error('Report must be outside release')
    resource=module('skill/fpga-resource-ablation/scripts/compare_resources.py','resource_check')
    axi=module('skill/axi-cdc-verification/scripts/check_axil_trace.py','axi_check')
    owner=module('skill/pynq-buffer-ownership/scripts/check_ownership.py','owner_check')
    archive=module('skill/hls-verification-archive/scripts/run_evidence.py','archive_check')
    names=[]
    def ok(name,value):
        if not value:raise AssertionError(name)
        names.append(name)
    def rejects(name,call):
        try:call()
        except (ValueError,TypeError):names.append(name)
        else:raise AssertionError(name)
    # Real HLS parser and pair contract, followed by adverse metadata/resource cases.
    reports=ROOT/'build/reports/dense_sharing'
    before=resource.parse_report(reports/'separate_tdc_accelerator_csynth.xml')
    after=resource.parse_report(reports/'shared_tdc_accelerator_csynth.xml')
    contract=json.loads((reports/'contract.json').read_text(encoding='utf-8'))
    result=resource.compare(before,after,contract)
    ok('hls_real_report_dsp_delta',result['changes']['DSP']['delta']==-14)
    ok('vivado_routed_report_units',resource.parse_report(ROOT/'build/reports/utilization.rpt')['resources']['BRAM_TILE']==82)
    for key,value in [('tool','2025.2'),('device','other'),('stage','Routed'),('clock_ns',5),('uncertainty_ns',1),('top','other')]:
        bad=copy.deepcopy(after);bad[key]=value
        rejects('reject_mismatched_'+key,lambda:resource.compare(before,bad,contract))
    bad=copy.deepcopy(contract);bad['budgets']={'DSP':39}
    ok('budget_overflow',not resource.compare(before,after,bad)['budget_passed'])
    bad['budgets']={'DSP':40};ok('budget_equality',resource.compare(before,after,bad)['budget_passed'])
    bad['budgets']={'UNKNOWN':1};rejects('budget_typo',lambda:resource.compare(before,after,bad))
    bad=copy.deepcopy(contract);bad['fixture_sha256']='';rejects('missing_fixture_hash',lambda:resource.compare(before,after,bad))
    # A complete write (W before AW), a stalled response, and one read.
    def row(c,**kw):
        v={'cycle':c,'reset_n':1}
        for ch in axi.PAYLOAD:v[ch+'valid']=0;v[ch+'ready']=0
        v.update(kw);return v
    trace=[row(0,reset_n=0),row(1,wvalid=1,wready=1,wdata=7,wstrb=15),
           row(2,awvalid=1,awready=1,awaddr=16,awprot=0),
           row(3,bvalid=1,bresp=0),row(4,bvalid=1,bready=1,bresp=0),
           row(5,arvalid=1,arready=1,araddr=16,arprot=0),
           row(6,rvalid=1,rready=1,rdata=7,rresp=0)]
    ok('axil_w_before_aw',axi.check(trace)['passed'])
    flipped=copy.deepcopy(trace);flipped[1],flipped[2]=flipped[2],flipped[1]
    flipped[1]['cycle']=1;flipped[2]['cycle']=2
    ok('axil_aw_before_w',axi.check(flipped)['passed'])
    simultaneous=[row(0,awvalid=1,awready=1,awaddr=0,awprot=0,wvalid=1,wready=1,wdata=5,wstrb=15),row(1,bvalid=1,bready=1,bresp=0)]
    ok('axil_simultaneous_aw_w',axi.check(simultaneous)['passed'])
    bad=copy.deepcopy(trace);bad[3]['bresp']=2
    ok('axil_stalled_payload_violation',not axi.check(bad)['passed'])
    bad=copy.deepcopy(trace);bad[3]['bvalid']=0;bad[4]['bvalid']=0
    ok('axil_missing_response',not axi.check(bad)['passed'])
    bad=[row(0,bvalid=1,bready=1,bresp=0)]
    ok('axil_early_response',not axi.check(bad)['passed'])
    bad=copy.deepcopy(trace);bad.append(row(7,rvalid=1,rready=1,rdata=7,rresp=0))
    ok('axil_duplicate_response',not axi.check(bad)['passed'])
    reset=[row(0,awvalid=1,awready=1,awaddr=0,awprot=0),row(1,reset_n=0)]
    ok('axil_reset_clears_pending',axi.check(reset)['passed'])
    ok('axil_bounded_wait',not axi.check(trace,max_age=1)['passed'])
    bad=copy.deepcopy(trace);bad[0]['cycle']=1;rejects('axil_noncontiguous_trace',lambda:axi.check(bad))
    bad=copy.deepcopy(trace);bad[1].pop('wstrb');rejects('axil_missing_payload',lambda:axi.check(bad))
    # Generic vector-kernel ownership; tests do not import pynq.
    events=json.loads((ROOT/'skill/pynq-buffer-ownership/assets/vector_events.json').read_text())
    ok('owner_noncoherent_normal',owner.check(events)['passed'])
    coherent=copy.deepcopy(events)
    for e in coherent:
        if e['event']=='alloc':e['coherent']=True
    coherent=[e for e in coherent if e['event'] not in ['flush','invalidate']]
    ok('owner_coherent_normal',owner.check(coherent)['passed'])
    for kind in ['flush','invalidate']:
        bad=[e for e in events if e['event']!=kind]
        ok('owner_missing_'+kind,not owner.check(bad)['passed'])
    bad=copy.deepcopy(events);bad.insert(5,{'event':'free','buffer':'input'})
    ok('owner_free_in_flight',not owner.check(bad)['passed'])
    bad=copy.deepcopy(events);bad[5]={'event':'timeout'}
    ok('owner_timeout_not_completion',not owner.check(bad)['passed'])
    bad=copy.deepcopy(events);bad[5]={'event':'abort_ack'}
    ok('owner_abort_invalid_output',not owner.check(bad)['passed'])
    bad=copy.deepcopy(events);bad.insert(3,{'event':'invalidate','buffer':'input'})
    ok('owner_invalidate_dirty_input',not owner.check(bad)['passed'])
    bad=copy.deepcopy(events);bad.insert(5,{'event':'cpu_write','buffer':'input'})
    ok('owner_write_in_flight',not owner.check(bad)['passed'])
    bad=[e for e in events if e['event']!='cpu_write']
    ok('owner_uninitialized_read',not owner.check(bad)['passed'])
    bad=copy.deepcopy(events);bad[0]['coherent']='false'
    rejects('owner_explicit_cache_attribute',lambda:owner.check(bad))
    # Runner positive/negative cases use only a tiny Python subprocess.
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'input.txt').write_text('immutable')
        script=root/'test.py';script.write_text("print('PASS: compared')\n")
        plan={'tool_version':'Python '+sys.version.split()[0],'scope':'synthetic harness tests',
              'inputs':['input.txt'], 'steps':[{'name':'test','argv':[sys.executable,str(script)],'timeout_s':5,
              'pass_regex':['^PASS: compared'],'fail_regex':['^FAIL:','^ERROR:'],'artifacts':[]}]}
        ok('archive_success',archive.execute(plan,root,root/'good')['passed'])
        for name,code in [('missing_pass',"print('running')"),('error_even_with_pass',"print('PASS: compared');print('ERROR: bad')"),
                          ('nonzero_exit',"print('PASS: compared');raise SystemExit(3)"),
                          ('input_changed',"from pathlib import Path;Path('input.txt').write_text('changed');print('PASS: compared')")]:
            script.write_text(code)
            ok('archive_'+name,not archive.execute(plan,root,root/name)['passed'])
        script.write_text("print('PASS: compared')")
        bad=copy.deepcopy(plan);bad['steps'][0]['artifacts']=['absent.rpt']
        ok('archive_missing_report',not archive.execute(bad,root,root/'missing_report')['passed'])
        bad=copy.deepcopy(plan);bad['inputs']=['../escape.txt']
        rejects('archive_path_escape',lambda:archive.validate(bad,root))
        rejects('archive_nonempty_output',lambda:archive.execute(plan,root,root/'good'))
        bad=copy.deepcopy(plan);bad['steps'][0]['pass_regex']=[]
        rejects('archive_missing_pass_policy',lambda:archive.validate(bad,root))
        (root/'bad.xml').write_text('<profile></profile>')
        rejects('resource_missing_xml_fields',lambda:resource.parse_report(root/'bad.xml'))
    summary={'passed':True,'checks':len(names),'cases':names,'hardware_access':False,
             'scope':'Portable helper behavior and archived-report parsing; synthetic fault injection, not a new FPGA run'}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
