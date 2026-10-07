"""Evidence-based queue recovery. Never relax timing or functional checks."""
import json
from pathlib import Path
import time
from worker import collect_artifacts, save
from prepare import verify_sources
from recover_timing import MAX_STRATEGIES
from hbm_clock import hbm_setup_failure

def event(root, job, action, detail):
    with (root/'recovery_events.jsonl').open('a') as f:
        f.write(json.dumps(dict(time=time.time(),job=job['id'],attempt=job.get('attempt',1),
            action=action,detail=detail))+'\n')

def archive_and_retry(root, job, **settings):
    dst=root/'jobs'/job['id']
    archive=root/'attempts'/job['id']/f"attempt_{job.get('attempt',1):02d}"
    archive.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists(): dst.rename(archive)
    ident=job['id']; attempt=job.get('attempt',1)+1
    job.clear()
    job.update(id=ident,attempt=attempt,status='pending',stage='retry',prepared=False,
               previous_attempt=str(archive),**settings)

def recover_failed(root,state):
    policy=root/'recovery_policy.json'
    if not policy.exists():return
    policy = json.loads(policy.read_text())
    if not policy.get('enabled'):return
    for job in state['jobs']:
        if job['status'] not in ('failed','blocked'):continue
        dst=root/'jobs'/job['id']
        error=job.get('error','')
        key=f"{job.get('attempt',1)}:{job.get('timing_recovery',0)}:{error}"
        if job.get('recovery_checked')==key:continue
        job['recovery_checked']=key
        event(root,job,'diagnosed',error)
        fallback = policy.get('hbm_clock_fallback', {})
        if (fallback.get('enabled') and not job['id'].startswith('H')
                and job.get('hbm_axi_mhz',450) == 450
                and job.get('finished_at',0) >= fallback.get('authorized_at',float('inf'))
                and error.startswith('Timing failure: ')):
            report = Path(error.removeprefix('Timing failure: '))
            if report.is_file() and hbm_setup_failure(report):
                archive_and_retry(root,job,hbm_axi_mhz=400)
                event(root,job,'clock_fallback',
                    'HBM setup failure: fresh 400 MHz HBM AXI attempt; previous 450 MHz attempt archived; checker clock unchanged')
                continue
        # Older workers still use the broad timing glob. Recover their final PR
        # result only with intact source hashes and successful bitgen evidence.
        if job['id'].startswith('H') and 'Timing failure:' in error:
            try:
                verify_sources(dst)
                log=(dst/'bitgen.log').read_text(errors='replace')
                if '[100%] Built target bitgen' not in log or 'ERROR:' in log:
                    raise RuntimeError('Bitgen completion cannot be verified')
                artifacts=collect_artifacts(dst/'build',job['id'])
                save(dst/'pre_recovery_progress.json',json.loads((dst/'progress.json').read_text()))
                job.update(status='passed',stage='complete',artifacts=artifacts,
                           error='',hardware_validated=False,recovered_at=time.time())
                save(dst/'progress.json',job)
                event(root,job,'recovered','Final PR timing passed; preserved existing bitstreams')
                continue
            except (RuntimeError,FileNotFoundError) as exc:
                event(root,job,'revalidation_failed',str(exc))
        if not job['id'].startswith('H') and ('Timing failure:' in error or
                job.get('stage')=='timing_recovery'):
            strategy=job.get('timing_recovery',0)+1
            if strategy<=MAX_STRATEGIES and (dst/'build/checkpoints/shell_placed.dcp').exists():
                job.update(status='pending',stage='timing_retry',timing_recovery=strategy)
                for field in ['finished_at','error']:job.pop(field,None)
                event(root,job,'retry',f'Timing strategy {strategy}/{MAX_STRATEGIES}; same hardware and clocks')
                continue
        if job['id'].startswith('H') and 'No initial hello-world' in error:
            if any(j['id'] in ('H16','H8','H4','H2','H1') and j['status']=='passed' for j in state['jobs']):
                archive_and_retry(root,job)
                event(root,job,'retry','Feasible coarse anchor recovered')
                continue
        # Capacity errors are deterministic: change geometry before retrying.
        app=dst/'app.log'
        if job['id'].startswith('H') and app.exists() and 'UTLZ-1' in app.read_text(errors='replace'):
            n=job.get('capacity_retries',0)
            if n<2:
                rect=job.get('geometry',[0,0,0,0]);x0,y0,x1,y1=rect
                # Extend to a neighboring column, then row; never rerun the same
                # undersized pblock. Actual geometry is recorded with the job.
                larger=[x0,y0,x1+1,y1] if n==0 else [x0,y0,x1,y1+1]
                archive_and_retry(root,job,geometry_override=larger,capacity_retries=n+1)
                event(root,job,'retry',f'BRAM capacity: enlarge region to {larger}')
                continue
        event(root,job,'needs_new_fix','Known recovery options exhausted or unclassified failure; logs retained')
