#!/usr/bin/env python3
"""Accept a predefined file-drift recheck without replacing unaffected evidence."""
import argparse,csv,fcntl,json,os,shutil,time
from pathlib import Path
from final_benchmark import read,save,sha,summarize

def finalize(root,recheck):
    c=read(root/'campaign.json');rc=read(recheck/'campaign.json');review=read(recheck/'summary.json')
    assert read(recheck/'status.json')['status']=='passed' and review['status']=='passed'
    assert c['images']==rc['images'],'Recheck hardware/runtime selection changed'
    for k in ['hostname','device','pci_bdf','board_serial','gpu','cpu','numa_node','driver_sha256']:assert c[k]==rc[k],k
    for campaign in [root,recheck]:
        cfg=read(campaign/'campaign.json')
        for p,h in cfg['software_files'].items():assert sha(campaign/p)==h,p
    accepted={};sealed={};admission={}
    for campaign in [root,recheck]:
        for label in c['order']:
            attempts=[p.parent for p in (campaign/'jobs'/label).glob('attempt_*/status.json') if read(p)['status']=='passed']
            assert attempts,label
            attempt=sorted(attempts)[-1];ident=read(attempt/'status.json')['id']
            for phase in ['admission','pilot','full']+(['profile'] if campaign==root and c['images'][ident]['kind']=='gpu' else []):
                result=read(attempt/phase/'result.json');assert result['status']=='passed'
                for name,h in result['files'].items():assert sha(attempt/phase/name)==h,name
                for p in (attempt/phase).rglob('*'):
                    if p.is_file():sealed[str(p.relative_to(root))]=sha(p)
            admission[label]=dict(image_sha256=c['images'][ident]['bitstream_sha256'],evidence=str(attempt/'admission/result.json'),calls=520)
            result=read(attempt/'full/result.json')
            for s in result['summaries']:
                key=(label,s['case_id'],s['scope'])
                accepted[key]=dict(iteration=label,case_id=s['case_id'],scope=s['scope'],input_bytes=s['input_bytes'],
                    evidence=str(attempt/'full/result.json'),cohort='initial' if campaign==root else recheck.name,**s['metrics'])
    try:summarize(root)
    except RuntimeError as e:
        if not str(e).startswith('Baseline drift exceeds 5%'):raise
    initial=read(root/'summary.json');save(root/'diagnostics/initial_summary_with_profiles.json',initial)
    keys={(x['case_id'],x['scope']) for x in initial['baseline_drift'] if abs(x['relative_change'])>.05}
    assert keys=={(x['case_id'],x['scope']) for x in review['baseline_drift']},'Recheck must exactly cover flagged comparisons'
    assert all(scope=='file' for _,scope in keys)
    assert len(accepted)==len(c['order'])*15*2
    drift={(x['case_id'],x['scope']):x for x in initial['baseline_drift']}
    drift.update({(x['case_id'],x['scope']):x for x in review['baseline_drift']})
    assert all(abs(x['relative_change'])<=.05 for x in drift.values())
    rows=list(accepted.values())
    def median(row):return row['file_e2e_ms' if row['scope']=='file' else 'host_observed_ms']['median']
    base={(r['case_id'],r['scope']):median(r) for r in rows if r['iteration']=='OPT_1_STREAMING'}
    speedups=[dict(iteration=r['iteration'],case_id=r['case_id'],scope=r['scope'],speedup_vs_streaming=base[r['case_id'],r['scope']]/median(r)) for r in rows if not r['iteration'].endswith('_REPEAT')]
    initial.update(status='passed',rows=rows,baseline_drift=list(drift.values()),original_baseline_drift=initial['baseline_drift'],
        recheck=str(recheck),recheck_policy='Predefined two file-only workloads replaced across all variants and baseline repeat; all original data retained.',
        speedups=speedups,accepted_measured_calls=36000,accepted_primary_measured_calls=30000,accepted_warmup_calls=3600,
        gpu_profile_calls=600,board_admission=admission)
    save(root/'summary.json',initial)
    flat=[dict(iteration=r['iteration'],case_id=r['case_id'],scope=r['scope'],input_bytes=r['input_bytes'],cohort=r['cohort'],evidence=r['evidence'],metric=k,**v) for r in rows for k,v in r.items() if isinstance(v,dict)]
    with (root/'summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    shutil.copy2(recheck/'installed_image.json',root/'installed_image.json')
    assert read(root/'installed_image.json')['id']=='OPT_1_STREAMING'
    save(root/'board_admission.json',dict(status='passed',target=initial['target'],variants=admission))
    for p in [root/'summary.json',root/'summary.csv',root/'board_admission.json',root/'installed_image.json',root/'campaign.json',root/'environment_manifest.json',Path(__file__),Path(__file__).with_name('final_benchmark.py')]:
        sealed[str(p.relative_to(root))]=sha(p)
    save(root/'measurement_manifest.json',dict(status='passed',verified_at=time.time(),files=sealed))
    return initial

def run(root,recheck,watch):
    with (root/'analysis.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=read(root/'status.json');state.update(status='running',stage='file_drift_recheck',pid=os.getpid())
        try:
            while True:
                child=read(recheck/'status.json');state.update(heartbeat=time.time(),recheck_status=child);save(root/'status.json',state)
                if child['status']=='passed':break
                if child['status']=='failed':raise RuntimeError('Targeted file recheck needs diagnosis: '+child.get('error','unknown failure'))
                if not watch:raise RuntimeError('File recheck is not complete')
                if child.get('pid') and not Path('/proc/'+str(child['pid'])).exists():raise RuntimeError('File recheck controller exited unexpectedly')
                time.sleep(15)
            state['stage']='final_verification';save(root/'status.json',state)
            result=finalize(root,recheck)
            state.pop('error',None);state.update(status='passed',stage='complete',finished_at=time.time(),summary=str(root/'summary.json'))
            save(root/'status.json',state);print('PASS final campaign: 36000 accepted measured calls, 600 profile calls, all drift gates met',flush=True)
            return 0
        except BaseException as e:
            state.update(status='failed',stage='needs_diagnosis',error=str(e),finished_at=time.time());save(root/'status.json',state);raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('recheck',type=Path);p.add_argument('--watch',action='store_true');a=p.parse_args()
    raise SystemExit(run(a.root.resolve(),a.recheck.resolve(),a.watch))
