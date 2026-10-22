#!/usr/bin/env python3
"""Independent watchdog for report/runtime workflow; does not modify benchmark state."""
import json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]);path=root/'workflow_monitor.json';sent=set()
while True:
    try:s=json.loads((root/'workflow.json').read_text())
    except (OSError,ValueError):time.sleep(10);continue
    event=None
    if s['status'] in ['failed','awaiting_review','passed']:event=s['status']+': '+s.get('error',s.get('stage',''))
    elif s.get('pid') and not Path('/proc/'+str(s['pid'])).exists():event='Unexpected workflow exit: '+s.get('stage','unknown')
    if event and event not in sent:
        p=subprocess.run(['curl','-fsS','--max-time','15','-d','GPU preprocessing-v2 workflow '+event+'; '+str(root),'https://ntfy.sh/coyote-build-sdeheredia'],capture_output=True,text=True)
        if p.returncode==0:sent.add(event)
    path.write_text(json.dumps(dict(pid=os.getpid(),heartbeat=time.time(),workflow=s,sent=sorted(sent)),indent=2)+'\n')
    if s['status'] in ['awaiting_review','passed'] and event in sent:break
    time.sleep(15)
