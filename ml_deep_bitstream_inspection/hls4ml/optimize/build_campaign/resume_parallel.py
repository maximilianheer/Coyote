#!/usr/bin/env python3
"""Resume interrupted, source-identical exports on a roomy build host.

No FPGA programming. Local SSD working trees, shared durable results, independent
workers and an outcome-only notification monitor. Original attempts stay intact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

from prepare import verify_sources, sha
from worker import save, collect_artifacts, seal_artifacts, final_timing_reports
from monitor import notify

HERE = Path(__file__).resolve().parent
VIVADO = '/tools/Xilinx/Vivado/2024.2/bin/vivado'
TERMINAL = ('passed', 'failed', 'terminated')


def hashes(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def sync(local, shared):
    shared.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rsync', '-a', '--no-owner', '--no-group', '--exclude=*.lock', str(local)+'/', str(shared)+'/'], check=True)


def prepare(old, local, shared):
    digest = verify_sources(old)
    if local.exists() or shared.exists():
        raise RuntimeError('Fresh local and shared attempt directories required')
    local.mkdir(parents=True)
    subprocess.run(['rsync', '-a', '--no-owner', '--no-group', '--exclude=build', '--exclude=tmp', '--exclude=*.lock',
                    str(old)+'/', str(local)+'/'], check=True)
    # Keep sources byte-identical: relocation belongs to a separate build adapter.
    config = local/'build_config'; config.mkdir()
    text = (local/'hw/CMakeLists.txt').read_text().replace(str(old/'coyote'), str(local/'coyote'))
    text = re.sub(r'set\(COMP_CORES \d+\)', 'set(COMP_CORES 2)', text)
    (config/'CMakeLists.txt').write_text(text)
    (config/'src').symlink_to(local/'hw/src', target_is_directory=True)
    build = local/'build'; build.mkdir()
    shutil.copytree(old/'build/iprepo', build/'iprepo')
    if hashes(old/'build/iprepo') != hashes(build/'iprepo'):
        raise RuntimeError('Copied IP export mismatch')
    kernels = ['cnn_wrapper', 'preprocess_wrapper'] if old.name == 'D_I' else ['model_wrapper']
    for kernel in kernels:
        found = list((old/'build').glob('**/solution1/syn/verilog/'+kernel+'.v'))
        if len(found) != 1:
            raise RuntimeError('Ambiguous synthesized kernel '+kernel)
        target = build/'validated_hls'/kernel/'solution1/syn'
        shutil.copytree(found[0].parent.parent, target)
    if verify_sources(local) != digest:
        raise RuntimeError('Relocation changed maintained hardware sources')
    provenance = dict(original_attempt=str(old), source_manifest_sha256=digest,
        ip_files=hashes(build/'iprepo'), synthesis_files=hashes(build/'validated_hls'),
        build_adapter_sha256=sha(config/'CMakeLists.txt'), host=socket.gethostname(),
        local=str(local), shared=str(shared), prepared_at=time.time(),
        checkpoint_reuse=False,
        checkpoint_note='Fresh Vivado projects avoid stale absolute paths; completed HLS exports reused.')
    save(local/'resume_provenance.json', provenance)
    # These were copied only as prior evidence, never as the new attempt's status.
    history = local/'prior_attempt_state'; history.mkdir()
    for name in ('progress.json', 'artifact_manifest.json', 'wrapper_rtl.log'):
        if (local/name).exists(): shutil.move(local/name, history/name)
    sync(local, shared)


def validate_exports(local):
    p = json.loads((local/'resume_provenance.json').read_text())
    if verify_sources(local) != p['source_manifest_sha256']:
        raise RuntimeError('Source identity changed')
    for directory, field in [('iprepo', 'ip_files'), ('validated_hls', 'synthesis_files')]:
        if hashes(local/'build'/directory) != p[field]:
            raise RuntimeError('Validated export changed: '+directory)
    if sha(local/'build_config/CMakeLists.txt') != p['build_adapter_sha256']:
        raise RuntimeError('Build adapter changed')


def worker(root, ident):
    cfg = json.loads((root/'config.json').read_text())
    local = Path(cfg['local_root'])/'jobs'/ident
    shared = root/'jobs'/ident
    build = local/'build'
    state = dict(id=ident, status='running', stage='configure', pid=os.getpid(),
                 host=socket.gethostname(), attempt=2, started_at=time.time(), hardware_started=False)
    env = dict(os.environ, OMP_NUM_THREADS='8', OPENBLAS_NUM_THREADS='1', DRIVER_RESETS='1',
               TMPDIR=str(local/'tmp'))
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env.get('PATH','')
    (local/'tmp').mkdir(exist_ok=True)

    def publish():
        state['heartbeat']=time.time()
        save(shared/'resume_progress.json', state)

    def command(stage, args, cwd=build):
        state.update(stage=stage, stage_started_at=time.time()); publish()
        logpath=local/(stage+'.log')
        with logpath.open('w') as log:
            proc=subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            state['child_pid']=proc.pid
            try:
                while proc.poll() is None:
                    publish()
                    shutil.copy2(logpath,shared/logpath.name)
                    time.sleep(10)
                if proc.returncode: raise RuntimeError(f'{stage} exited {proc.returncode}; {shared/logpath.name}')
            except BaseException:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try: proc.wait(timeout=15)
                    except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); proc.wait()
                raise
            finally:
                state.pop('child_pid',None)
                shutil.copy2(logpath,shared/logpath.name)

    def terminated(signum, frame):
        raise InterruptedError(f'Worker received signal {signum}')

    for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT): signal.signal(sig,terminated)
    try:
        validate_exports(local)
        command('configure_resume',['cmake','-S',str(local/'build_config'),'-B',str(build),
            '-DVITIS_HLS_MODE=vitis_hls','-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2',
            '-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'])
        # Four threads per synthesis process, eight for implementation. Two OOC
        # processes per design initially; designs never share an implementation lock.
        base=build/'base.tcl'
        base.write_text(base.read_text()+'\nset_param general.maxThreads 8\n')
        pre=build/'synthesis_threads.tcl'; pre.write_text('set_param general.maxThreads 4\n')
        for name in ('synth_shell.tcl','synth_user.tcl','synth_static.tcl'):
            p=build/name
            if not p.exists(): continue
            text=p.read_text()
            text=re.sub(r'launch_runs -jobs (?:1|\$cfg\(cores\))', 'launch_runs -jobs 2',text)
            text=text.replace('reset_run synth_1', 'reset_run synth_1\n'
                +'foreach r [get_runs -filter {IS_SYNTHESIS == 1}] {\n'
                +'    set_property STEPS.SYNTH_DESIGN.TCL.PRE {'+str(pre)+'} $r\n}\n')
            p.write_text(text)
        save(local/'build_scripts.json', {str(p.relative_to(build)):sha(p) for p in build.glob('*.tcl')})
        state['hardware_started']=True
        command('project_shell',[VIVADO,'-mode','batch','-source',str(build/'cr_shell.tcl'),'-notrace'])
        command('project_user',[VIVADO,'-mode','batch','-source',str(build/'cr_user.tcl'),'-notrace'])
        validate_exports(local)
        if ident=='D_I':
            gate=json.loads((local/'direct_rtl/status.json').read_text())
            if (gate.get('status')!='passed' or gate.get('driver_resets')!=1 or
                gate.get('source_manifest_sha256')!=verify_sources(local) or len(gate.get('comparisons',[]))!=11):
                raise RuntimeError('Missing source-identical 11-frame D_I second-reset RTL gate')
            save(local/'resumed_rtl_validation.json',dict(status='passed',frames=11,driver_resets=1,
                reused_gate_sha256=sha(local/'direct_rtl/status.json'),
                unchanged_exports=sha(local/'resume_provenance.json')))
        else:
            rtl=local/'resume_rtl';rtl.mkdir()
            shutil.copytree(build/'validated_hls/model_wrapper/solution1/syn/verilog',rtl/'core')
            for name in ('production_wrapper_tb.sv','production_wrapper_sim.tcl'):
                shutil.copy2(local/'tests'/name,rtl/name)
            shutil.copy2(local/'rtl_expected.txt',rtl/'rtl_expected.txt')
            command('wrapper_rtl',[VIVADO,'-mode','batch','-source',str(rtl/'production_wrapper_sim.tcl')],rtl)
            if 'PASS production wrapper frames=8' not in (local/'wrapper_rtl.log').read_text():
                raise RuntimeError('R_S full RTL did not pass')
            save(local/'resumed_rtl_validation.json',dict(status='passed',frames=8,driver_resets=1,
                log_sha256=sha(local/'wrapper_rtl.log'),unchanged_exports=sha(local/'resume_provenance.json')))
        sync(local,shared)
        for stage in ('synth','link','shell'):
            command(stage,['make','-j1',stage])
            sync(local,shared)
        try:
            final_timing_reports(build,ident)
        except RuntimeError:
            # Existing bounded recovery retains each routed attempt separately.
            for strategy in (1,2,3):
                job=json.loads((local/'job.json').read_text());job.update(timing_recovery=strategy,attempt=2)
                save(local/'job.json',job)
                try:
                    command('recovery_'+str(strategy),[sys.executable,str(HERE/'recover_timing.py'),str(local)],local)
                    build=local/'recovery'/f'route_{strategy:02d}'
                    break
                except RuntimeError:
                    sync(local,shared)
                    if strategy==3: raise
        else:
            command('bitgen',['make','-j1','bitgen'])
        validate_exports(local)
        artifacts=collect_artifacts(build,ident)
        artifacts['sha256']={name:sha(Path(name)) for name in artifacts['bitstreams']}
        seal_artifacts(local,artifacts)
        sync(local,shared)
        # Publish durable paths, not host-local SSD locations, for downstream use.
        artifacts=json.loads(json.dumps(artifacts).replace(str(local),str(shared)))
        seal_artifacts(shared,artifacts)
        state.update(status='passed',stage='complete',artifacts=artifacts,hardware_validated=False)
    except BaseException as error:
        state.update(status='terminated' if isinstance(error,(InterruptedError,KeyboardInterrupt)) else 'failed',error=str(error))
    finally:
        state['finished_at']=time.time();publish()
        save(shared/'progress.json',state)
    return 0 if state['status']=='passed' else 1


def monitor(root):
    cfg=json.loads((root/'config.json').read_text())
    sent=set();book=root/'notification_state.json'
    if book.exists(): sent=set(json.loads(book.read_text()).get('sent',[]))
    while True:
        jobs=[]
        for ident in ('D_I','R_S'):
            p=root/'jobs'/ident/'resume_progress.json'
            if not p.exists(): jobs.append(dict(id=ident,status='pending'));continue
            state=json.loads(p.read_text())
            if state['status']=='passed' and not state.get('artifacts',{}).get('sha256'):
                # Compatibility with workers launched before the publication
                # adapter: board admission also expects hashes in progress.json.
                artifacts=state['artifacts']
                manifest=json.loads((p.parent/'artifact_manifest.json').read_text())
                digests={}
                for name in artifacts['bitstreams']:
                    bit=Path(name)
                    relative=str(bit.resolve().relative_to(p.parent.resolve()))
                    actual=sha(bit)
                    if actual!=manifest['files'][relative]['sha256']:
                        raise RuntimeError('Published bitstream does not match sealed manifest')
                    digests[name]=actual
                artifacts['sha256']=digests
                save(p,state);save(p.parent/'progress.json',state)
            if state['status']=='running' and time.time()-state.get('heartbeat',0)>180:
                cmd=Path('/proc')/str(state['pid'])/'cmdline'
                if not cmd.exists() or b'resume_parallel.py' not in cmd.read_bytes():
                    state.update(status='terminated',error='Build worker disappeared',finished_at=time.time())
                    save(p,state)
            jobs.append(state)
            key=ident+':'+state['status']
            if state['status'] in TERMINAL and state.get('hardware_started') and key not in sent:
                message=(f"{root.name}: hardware build {ident} {state['status']} on {cfg['host']}. "
                    +state.get('error','Routed timing and bitstreams passed; board parity pending.')
                    +f'\nArtifacts/logs: {root / "jobs" / ident}')
                if notify(root,message):sent.add(key);save(book,dict(sent=sorted(sent)))
        done=all(j['status'] in TERMINAL for j in jobs)
        save(root/'status.json',dict(phase='finished' if done else 'running',heartbeat=time.time(),
            host=cfg['host'],tmux_session=cfg['session'],jobs=jobs,parallel_builds=2))
        with (root/'resource_samples.jsonl').open('a') as f:
            mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
            f.write(json.dumps(dict(time=time.time(),load=os.getloadavg(),available_kib=int(mem['MemAvailable'].split()[0])))+'\n')
        if done and all(not j.get('hardware_started') or j['id']+':'+j['status'] in sent for j in jobs):return
        time.sleep(20)


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True)
    q=s.add_parser('prepare');q.add_argument('old',type=Path);q.add_argument('local',type=Path);q.add_argument('shared',type=Path)
    q=s.add_parser('worker');q.add_argument('root',type=Path);q.add_argument('ident',choices=['D_I','R_S'])
    q=s.add_parser('monitor');q.add_argument('root',type=Path)
    a=p.parse_args()
    if a.mode=='prepare':prepare(a.old.resolve(),a.local.resolve(),a.shared.resolve())
    elif a.mode=='worker':sys.exit(worker(a.root.resolve(),a.ident))
    else:monitor(a.root.resolve())
