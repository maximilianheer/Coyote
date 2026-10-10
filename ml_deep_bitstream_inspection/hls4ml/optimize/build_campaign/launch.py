#!/usr/bin/env python3
"""Launch the three direct-stream builds. Legacy campaign artifacts are read-only."""
import argparse,json,shlex,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from worker import save
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=HERE.parent/'runs'/('direct_stream_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')))
    p.add_argument('--conv0-gate',type=Path,help='Verified conv0 gate JSON from check_conv0 validation')
    a=p.parse_args();root=a.root.resolve();root.mkdir(parents=True,exist_ok=True)
    if (root/'status.json').exists():raise RuntimeError('Campaign already initialized; resume campaign.py explicitly')
    (root/'jobs').mkdir(exist_ok=True)
    if a.conv0_gate:
        import shutil
        shutil.copy2(a.conv0_gate,root/'conv0_gate.json')
    if not (root/'conv0_gate.json').exists():raise RuntimeError('Run isolated conv0 parity/synthesis checks before launching')
    session_file=root/'tmux_session.txt'
    session=session_file.read_text().strip() if session_file.exists() else 'coyote_direct_'+root.name
    if subprocess.run(['tmux','-L','coyote-opt','has-session','-t',session],capture_output=True).returncode:
        subprocess.run(['tmux','-L','coyote-opt','new-session','-d','-s',session,'-n','tracking'],check=True)
    subprocess.run(['tmux','-L','coyote-opt','set-option','-t',session,'remain-on-exit','on'],check=True)
    jobs=[]
    for ident in ['D_I','D_N','D_G']:
        path=root/'jobs'/ident/'job.json'
        job=json.loads(path.read_text()) if path.exists() else dict(id=ident,attempt=1,prepared=False)
        job.update(status='pending',stage='preparation');jobs.append(job)
    save(root/'status.json',dict(phase='preparing',heartbeat=time.time(),tmux_session=session,max_jobs=5,jobs=jobs,write_status_markdown=False))
    save(root/'recovery_policy.json',dict(enabled=True,hbm_clock_fallback=dict(enabled=False)))
    for name,script,args in [('scheduler','campaign.py',['run',str(root),'--jobs','5']),('monitor','direct_monitor.py',[str(root)])]:
        command=shlex.join([sys.executable,'-u',str(HERE/script),*args])+' >> '+shlex.quote(str(root/(name+'.log')))+' 2>&1'
        subprocess.run(['tmux','-L','coyote-opt','new-window','-d','-t',session,'-n',name,command],check=True)
    session_file.write_text(session+'\n');(HERE.parent/'active_direct_campaign.txt').write_text(str(root)+'\n')
    print(f'Campaign {root}\nAttach: tmux -L coyote-opt attach -t {session}')
if __name__=='__main__':main()
