#!/usr/bin/env python3
"""Launch authorized production/streaming recovery builds in tmux."""
import argparse, json, shlex, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from worker import save
from prepare import HARDWARE, sha
HERE=Path(__file__).resolve().parent

def verified_frame_start_gates(root, variants):
    evidence={}
    for variant in variants:
        if variant not in ('R_S','D_I'):continue
        directory=root/variant
        status=json.loads((directory/'status.json').read_text())
        if (status.get('status')!='passed' or status.get('variant')!=variant
                or status.get('driver_resets')!=1 or status.get('startup_idle_cycles')!=20000
                or status.get('rtl_frames')!=(8 if variant=='R_S' else 11)):
            raise RuntimeError('Incomplete first-pixel launch validation: '+variant)
        for manifest,base in [('sources.json',directory),('rtl_sources.json',directory/'rtl')]:
            inputs=json.loads((directory/manifest).read_text())
            if not inputs or any(sha(base/name)!=digest for name,digest in inputs.items()):
                raise RuntimeError('Changed first-pixel launch validation inputs: '+variant)
        required=[('common/frame_start.hpp','frame_start.hpp')]
        required.append(('common/production_inference.hpp','production_inference.hpp') if variant=='R_S'
                        else ('variants/cnn_wrapper.cpp','cnn_wrapper.cpp'))
        if any(sha(HARDWARE/source)!=sha(directory/'kernel'/target) for source,target in required):
            raise RuntimeError('Maintained launch sources differ from validated candidate: '+variant)
        log=(directory/'driver_reset_rtl.log').read_text()
        if 'driver_resets=1' not in log or 'Fatal:' in log:
            raise RuntimeError('Missing successful second-reset simulation evidence: '+variant)
        evidence[variant]=dict(directory=str(directory),status_sha256=sha(directory/'status.json'),
            sources_sha256=sha(directory/'sources.json'),rtl_sources_sha256=sha(directory/'rtl_sources.json'),
            rtl_log_sha256=sha(directory/'driver_reset_rtl.log'))
    return evidence

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',type=Path,required=True)
    parser.add_argument('--boundary-reference',type=Path,required=True)
    parser.add_argument('--variants',nargs='+',choices=['R_O','R_S','D_I','R_SO_T'],default=['R_O','R_S'])
    parser.add_argument('--production-prerequisites',type=Path,
                        help='Explicit R_O/R_S job and standard-driver board evidence for R_SO_T')
    parser.add_argument('--implementation-lock',type=Path,
                        help='Share an existing campaign implementation permit')
    parser.add_argument('--conv0-gate',type=Path)
    parser.add_argument('--frame-start-gates',type=Path)
    parser.add_argument('--wait-frame-start',action='store_true',help='Wait up to two hours for running launch-fix checks; stop on any failure')
    parser.add_argument('--root',type=Path,default=HERE.parent/'runs'/('production_isolation_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')))
    args=parser.parse_args();root=args.root.resolve()
    if len(set(args.variants))!=len(args.variants):raise RuntimeError('Duplicate variants')
    if not args.cases.is_file() or not args.boundary_reference.is_file():raise RuntimeError('Missing parity references')
    prerequisites=None
    if 'R_SO_T' in args.variants:
        if args.variants!=['R_SO_T'] or args.production_prerequisites is None:
            raise RuntimeError('R_SO_T requires its own campaign and explicit board prerequisites')
        from production_candidate import prerequisites as verify_prerequisites
        prerequisites=json.loads(args.production_prerequisites.read_text())
        verify_prerequisites({'production_prerequisites':prerequisites})
    if args.implementation_lock and not args.implementation_lock.resolve().is_file():
        raise RuntimeError('Shared implementation permit does not exist')
    if 'D_I' in args.variants:
        if args.conv0_gate is None:raise RuntimeError('D_I requires the existing conv0 gate')
        gate=json.loads(args.conv0_gate.read_text())
        if gate.get('status')!='passed' or gate.get('source_sha256')!=sha(HARDWARE/'common/conv0_dataflow.hpp'):
            raise RuntimeError('Invalid conv0 gate')
    if args.wait_frame_start:
        if args.frame_start_gates is None:raise RuntimeError('Missing launch-fix evidence directory')
        record=args.frame_start_gates/'launch_status.json'
        start=time.time();pending=dict(status='waiting_validation',target=str(root),variants=args.variants,started_at=start)
        try:
            while True:
                states={}
                for variant in args.variants:
                    if variant not in ('D_I','R_S'):continue
                    path=args.frame_start_gates/variant/'status.json'
                    states[variant]=json.loads(path.read_text()) if path.exists() else {'status':'pending'}
                if any(s.get('status')=='failed' for s in states.values()):
                    raise RuntimeError('First-pixel validation failed; no hardware launch')
                if all(s.get('status')=='passed' for s in states.values()):break
                if time.time()-start>7200:raise TimeoutError('First-pixel validation deadline; no hardware launch')
                pending.update(heartbeat=time.time(),checks={v:{k:s.get(k) for k in ('status','stage')} for v,s in states.items()})
                save(record,pending);time.sleep(15)
            pending.update(status='checking_evidence',heartbeat=time.time());save(record,pending)
        except BaseException as error:
            pending.update(status='failed',error=str(error),finished_at=time.time());save(record,pending);raise
    gates=verified_frame_start_gates(args.frame_start_gates.resolve(),args.variants) if args.frame_start_gates else {}
    root.mkdir(parents=True,exist_ok=False)
    if args.implementation_lock:
        (root/'implementation.lock').symlink_to(args.implementation_lock.resolve())
    if 'D_I' in args.variants:shutil.copy2(args.conv0_gate,root/'conv0_gate.json')
    if gates:save(root/'frame_start_validation.json',gates)
    (root/'jobs').mkdir()
    session='coyote_'+root.name
    subprocess.run(['tmux','-L','coyote-opt','new-session','-d','-s',session,'-n','tracking'],check=True)
    subprocess.run(['tmux','-L','coyote-opt','set-option','-t',session,'remain-on-exit','on'],check=True)
    save(root/'status.json',dict(phase='preparing',heartbeat=time.time(),tmux_session=session,max_jobs=5,
        parity_cases=str(args.cases.resolve()),boundary_reference=str(args.boundary_reference.resolve()),
        production_prerequisites=prerequisites,
        jobs=[dict(id=ident,status='pending',stage='preparation',attempt=1,prepared=False) for ident in args.variants],
        write_status_markdown=False,goal_extension='Recover D_I/R_S; build R_SO_T only after production-path board parity; benchmark accepted checkers and D_N'))
    save(root/'recovery_policy.json',dict(enabled=True,hbm_clock_fallback=dict(enabled=False)))
    for name,script,argv in [('scheduler','campaign.py',['run',str(root),'--jobs','5']),('monitor','direct_monitor.py',[str(root)])]:
        command=shlex.join([sys.executable,'-u',str(HERE/script),*argv])+' >> '+shlex.quote(str(root/(name+'.log')))+' 2>&1'
        subprocess.run(['tmux','-L','coyote-opt','new-window','-d','-t',session,'-n',name,command],check=True)
    (root/'tmux_session.txt').write_text(session+'\n')
    (HERE.parent/'active_isolation_campaign.txt').write_text(str(root)+'\n')
    if args.wait_frame_start:
        pending.update(status='launched',finished_at=time.time(),tmux_session=session);save(record,pending)
    print(root);print('tmux -L coyote-opt attach -t '+session)
if __name__=='__main__':main()
