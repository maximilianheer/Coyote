#!/usr/bin/env python3
"""Recover GPU_HOST timing using its own netlist and verified placement evidence.

Original implementation is preserved. A bounded follow-up route is permitted
only for a completed timing failure, never a tool error or weakened constraints.
"""
import argparse,fcntl,json,os,re,shutil,socket,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from prepare import sha,verify_sources
from worker import save,final_timing_reports,collect_artifacts,seal_artifacts
CELL='inst_shell/inst_shell_data_cc/genblk1[1].inst_s0_axis_dyn_in/genblk1[2].inst_reg/inst_reg_slice/inst/axisc_register_slice_0/state_reg[0]'

def check_evidence(job,evidence):
    data=json.loads(evidence.read_text())
    if data['source_manifest_sha256']!=verify_sources(job):raise RuntimeError('Changed job sources')
    if data['cell']!=CELL or not re.fullmatch(r'SLICE_X[0-9]+Y[0-9]+',data['loc']):raise RuntimeError('Invalid boundary placement')
    for p,digest in data['files'].items():
        if sha(Path(p))!=digest:raise RuntimeError('Changed placement evidence: '+p)
    failure=Path(data['failure_report']).read_text()
    if not any(block.startswith('Slack (VIOLATED)') and 'Source:                 '+CELL+'/C' in block and
               re.search(r'Destination:\s*inst_static/inst_cnvrt_static/',block) and
               re.search(r'Path Group:\s*xclk\s*\n',block)
               for block in re.split(r'(?=Slack \()',failure)):
        raise RuntimeError('Failure does not match diagnosed boundary')
    passed=Path(data['placement_log']).read_text()
    if f'BOUNDARY_CELL {{{CELL}}} LOC {data["loc"]}' not in passed:raise RuntimeError('Placement is not evidenced')
    summary=passed.split('Timing Report\n',1)[-1]
    slacks=re.findall(r'(?m)^\s+(-?[0-9]+\.[0-9]+)\s*$',summary)
    if len(slacks)!=5 or min(map(float,slacks))<=0 or 'Slack (VIOLATED)' in passed:raise RuntimeError('Reference boundary timing is not positive')
    return data

def run(job,evidence):
    lock=(job/'worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    info=check_evidence(job,evidence)
    original=job/'build';root=job/'recovery'/('host_'+time.strftime('%Y%m%d_%H%M%S'))
    root.mkdir(parents=True,exist_ok=False)
    for name in ['status.json','notification.json','monitor_status.json']:
        if (job/name).exists():shutil.copy2(job/name,root/('previous_'+name))
    status=job/'status.json'
    state=dict(id=job.name,status='running',stage='timing_recovery',started_at=time.time(),pid=os.getpid(),
               hostname=socket.gethostname(),recovery_output=str(root),clock_constraints_changed=False,
               source_manifest_sha256=info['source_manifest_sha256'],placement_cell=CELL,placement_loc=info['loc'])
    save(status,state);save(root/'inputs.json',info)
    env=dict(os.environ);env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
    env.update(OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1')
    script=root/'recover_timing.tcl'
    shutil.copy2(HERE.parent/'implementation/recover_timing.tcl',script)
    script.write_text(script.read_text().replace('general.maxThreads 8','general.maxThreads 4'))
    def command(stage,args,folder):
        state.update(stage=stage,stage_started_at=time.time());save(status,state)
        with (folder/(stage+'.log')).open('w') as out:
            child=subprocess.Popen(args,cwd=folder,env=env,stdout=out,stderr=subprocess.STDOUT)
            state['child_pid']=child.pid
            while child.poll() is None:
                state['heartbeat']=time.time();save(status,state);time.sleep(10)
            if child.returncode:raise RuntimeError(f'{stage} exited {child.returncode}; see {folder}/{stage}.log')
    try:
        # This is physical-only recovery of validated netlist: no fresh HLS/profile/RTL.
        validation=json.loads((job/'rtl_validation/validation.json').read_text())
        if validation['status']!='passed':raise RuntimeError('Missing RTL gate')
        for p,digest in validation['files'].items():
            if sha(Path(p))!=digest:raise RuntimeError('RTL-validated source changed: '+p)
        seed=original/'checkpoints/shell_opted.dcp'
        for index in [1,2]:
            out=root/f'attempt_{index:02d}';out.mkdir()
            mode='boundary_relocation' if index==1 else '1'
            args=['vivado','-mode','batch','-source',str(script),'-tclargs',str(original/'base.tcl'),str(out),str(seed),mode]
            if index==1:args+=['',CELL,info['loc']]
            provenance=dict(source_manifest_sha256=verify_sources(job),seed=str(seed),seed_sha256=sha(seed),
                            mode=mode,script_sha256=sha(script),base_sha256=sha(original/'base.tcl'),
                            bitgen_template_sha256=sha(original/'bitgen.tcl'),clock_constraints_changed=False)
            save(out/'provenance.json',provenance)
            state.update(attempt=index,attempt_output=str(out))
            command('timing_recovery',args,out)
            try:final_timing_reports(out,job.name)
            except RuntimeError as error:
                save(out/'outcome.json',dict(status='failed',error=str(error),finished_at=time.time()))
                if index==2 or not str(error).startswith('Timing failure:'):raise
                seed=out/'checkpoints/shell_routed.dcp'
                continue
            for d in ['bitstreams','logs']:(out/d).mkdir()
            base=out/'base.tcl'
            base.write_text(f'source {{{original/"base.tcl"}}}\nset_param general.maxThreads 4\n'+
                ''.join(f'set {var} {{{out/d}}}\n' for var,d in [('dcp_dir','checkpoints'),('rprt_dir','reports'),('bit_dir','bitstreams'),('log_dir','logs')]))
            text,count=re.subn(r'(?m)^source "[^"\n]+/base\.tcl"$', 'source {'+str(base)+'}',(original/'bitgen.tcl').read_text())
            if count!=1:raise RuntimeError('Bitgen base substitution not unique')
            (out/'bitgen.tcl').write_text(text)
            command('bitgen',['vivado','-mode','batch','-source',str(out/'bitgen.tcl')],out)
            if verify_sources(job)!=info['source_manifest_sha256']:raise RuntimeError('Sources changed during recovery')
            if sha(seed)!=provenance['seed_sha256']:raise RuntimeError('Seed checkpoint changed')
            if sha(original/'base.tcl')!=provenance['base_sha256']:raise RuntimeError('Original base/clock configuration changed')
            artifacts=collect_artifacts(out,job.name);seal_artifacts(job,artifacts)
            state.update(status='passed',stage='complete',artifacts=artifacts,hardware_validated=False)
            save(out/'outcome.json',dict(state,finished_at=time.time()))
            break
    except Exception as error:state.update(status='failed',error=str(error))
    state['finished_at']=time.time();save(status,state);save(root/'outcome.json',state)
    return 0 if state['status']=='passed' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('evidence',type=Path);a=p.parse_args()
    job=a.job.resolve()
    try:code=run(job,a.evidence.resolve())
    except BlockingIOError:
        raise SystemExit('Another worker already owns this job')
    except Exception as error:
        state=dict(id=job.name,status='failed',stage='recovery_preflight',pid=os.getpid(),
                   hostname=socket.gethostname(),started_at=time.time(),finished_at=time.time(),error=str(error))
        save(job/'status.json',state);print(str(error),file=sys.stderr);code=1
    sys.exit(code)
