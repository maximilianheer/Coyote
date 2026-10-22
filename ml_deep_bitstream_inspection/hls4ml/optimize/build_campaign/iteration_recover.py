#!/usr/bin/env python3
"""Timing-only recovery from an iteration's own optimized checkpoint."""
import argparse, fcntl, json, os, re, shutil, subprocess, time
from pathlib import Path
from prepare import HERE, sha, verify_sources
from worker import save, collect_artifacts, seal_artifacts, final_timing_reports
from recover_timing import BOUNDARY_CELL
from iterations import notify
from implementation_permits import permit


def verify(job):
    meta=json.loads((job/'attempt.json').read_text())
    for name,digest in meta['inputs'].items():
        if sha(job/name)!=digest:raise RuntimeError('Attempt input changed: '+name)
    source=verify_sources(job)
    manifest=json.loads((job/'source_manifest.json').read_text())
    for name,digest in manifest['build_scripts'].items():
        if sha(job/'coyote'/name)!=digest:raise RuntimeError('Build script changed: '+name)
    validation=json.loads((job/'validation.json').read_text())
    if validation['status']!='passed' or validation['source_manifest_sha256']!=source:
        raise RuntimeError('Unverified functional source')
    for name,digest in validation['evidence'].items():
        if sha(job/name)!=digest:raise RuntimeError('Validation evidence changed: '+name)
    if json.loads((job/'build_rtl_validation/result.json').read_text())['status']!='passed':
        raise RuntimeError('Actual build RTL not validated')
    return source


def run(job, output):
    root=job.parents[1];ident=job.parent.name
    output.mkdir(parents=True,exist_ok=False)
    state={'id':ident,'status':'running','stage':'verify','pid':os.getpid(),'started_at':time.time(),
           'correctness':'passed','timing':'pending','board_validated':False}
    campaign={'status':'running','pid':os.getpid(),'process_marker':'iteration_recover.py',
              'started_at':state['started_at'],'candidates':{ident:str(output)},'baseline':None}
    campaign_path=root/('recovery_'+ident+'.json')
    save(campaign_path,campaign);save(output/'status.json',state)
    try:
        digest=verify(job);original=job/'build'
        report=original/'reports/shell_timing_summary.rpt';text=report.read_text()
        failures=[b for b in re.split(r'(?=Slack \()',text) if b.startswith('Slack (VIOLATED)')]
        if not any(BOUNDARY_CELL+'/C' in b and 'inst_static/inst_cnvrt_static/' in b
                   and re.search(r'Path Group:\s*xclk\s*\n',b) and 'Setup' in b for b in failures):
            raise RuntimeError('Failure does not match the known boundary placement problem')
        shutil.copy2(report,output/'original_timing_summary.rpt')
        script=output/'recover_timing.tcl'
        script.write_text((HERE/'implementation/recover_timing.tcl').read_text().replace('general.maxThreads 8','general.maxThreads 4'))
        seed=original/'checkpoints/shell_opted.dcp'
        save(output/'provenance.json',{'source_manifest_sha256':digest,'seed':str(seed),'seed_sha256':sha(seed),
             'script_sha256':sha(script),'failing_report_sha256':sha(report),'cell':BOUNDARY_CELL,
             'location':'SLICE_X166Y196','clock_constraints_changed':False,'firmware_changed':False,
             'guidance':'Previously successful placement of the same shell/static boundary register; seed is this B2 attempt only.'})
        env=os.environ.copy();env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
        def command(stage,args):
            state.update(stage=stage,stage_started_at=time.time());save(output/'status.json',state)
            with (output/(stage+'.log')).open('w') as log:
                subprocess.run(['vivado','-mode','batch',*args],cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        state['stage']='waiting_implementation_lock';save(output/'status.json',state)
        os.environ.setdefault('HLS4ML_IMPLEMENTATION_LOCK',str(root/'implementation.lock'))
        def progress(**kw):
            state.update(kw);save(output/'status.json',state)
        with permit(progress):
            command('routing',['-source',str(script),'-tclargs',str(original/'base.tcl'),str(output),str(seed),
                 'boundary_relocation','',BOUNDARY_CELL,'SLICE_X166Y196'])
            final_timing_reports(output,ident)
            state['timing']='passed'
            for name in ['bitstreams','logs']:(output/name).mkdir()
            base=output/'base.tcl'
            base.write_text(f'source {{{original / "base.tcl"}}}\n'+''.join(
                f'set {var} {{{output / folder}}}\n' for var,folder in
                [('dcp_dir','checkpoints'),('rprt_dir','reports'),('bit_dir','bitstreams'),('log_dir','logs')]))
            bitgen,count=re.subn(r'(?m)^source "[^"\n]+/base\.tcl"$', 'source {'+str(base)+'}',(original/'bitgen.tcl').read_text())
            if count!=1:raise RuntimeError('Cannot isolate bitgen script')
            (output/'bitgen.tcl').write_text(bitgen)
            command('bitgen',['-source',str(output/'bitgen.tcl')])
        if verify(job)!=digest:raise RuntimeError('Sources changed during recovery')
        artifacts=collect_artifacts(output,ident);seal_artifacts(job,artifacts)
        state.update(status='passed',stage='complete',artifacts=artifacts)
    except Exception as error:
        state.update(status='failed',error=str(error))
        if 'Timing failure:' in str(error):state['timing']='failed'
    state['finished_at']=time.time();save(output/'status.json',state)
    campaign.update(status=state['status'],finished_at=time.time());save(campaign_path,campaign)
    notify(root,ident,f"{output.name} {state['status']}: {state.get('error','timing and bitstreams passed')}")
    return int(state['status']!='passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('job',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();raise SystemExit(run(args.job.resolve(),args.output.resolve()))
