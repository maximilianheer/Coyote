#!/usr/bin/env python3
"""Seal a completed matched campaign, optionally replacing complete flagged workloads."""
import argparse,csv,json,time
from pathlib import Path
from final_benchmark import read,save,sha,verify

def accept(root,recheck=None):
    cfg=verify(root);initial=read(root/'summary.json');accepted={};sealed={};admission={};profiles=initial['gpu_device_profiles']
    campaigns=[root]+([recheck] if recheck else [])
    flagged={x['case_id'] for x in initial['baseline_drift'] if abs(x['relative_change'])>.05}
    if recheck:
        rc=verify(recheck);review=read(recheck/'summary.json')
        assert rc['images']==cfg['images'] and review['status']=='passed'
        assert {x['case_id'] for x in review['baseline_drift']}==flagged
        for k in ['hostname','device','pci_bdf','gpu_bdf','board_serial','gpu','cpu','numa_node','driver_sha256','host_buffer_capacity_bytes','runtime_revision']:assert rc[k]==cfg[k],k
    else:assert initial['status']=='passed','Unresolved drift requires a matched recheck'
    for campaign in campaigns:
        for label in cfg['order']:
            attempts=[p.parent for p in (campaign/'jobs'/label).glob('attempt_*/status.json') if read(p)['status']=='passed']
            assert attempts,label
            attempt=sorted(attempts)[-1];ident=read(attempt/'status.json')['id']
            for phase in ['admission','pilot','full']+(['profile'] if campaign==root and cfg['images'][ident]['kind']=='gpu' and cfg.get('profile_enabled',True) else []):
                result=read(attempt/phase/'result.json');assert result['status']=='passed'
                for rel,h in result['files'].items():assert sha(attempt/phase/rel)==h,rel
                for p in (attempt/phase).rglob('*'):
                    if p.is_file():sealed[str(p.relative_to(root))]=sha(p)
            admission[label]=dict(image_sha256=cfg['images'][ident]['bitstream_sha256'],evidence=str(attempt/'admission/result.json'),calls=520)
            for x in read(attempt/'full/result.json')['summaries']:
                accepted[label,x['case_id'],x['scope']]=dict(iteration=label,case_id=x['case_id'],scope=x['scope'],input_bytes=x['input_bytes'],evidence=str(attempt/'full/result.json'),cohort='primary' if campaign==root else str(campaign.relative_to(root)),**x['metrics'])
    drift={(x['case_id'],x['scope']):x for x in initial['baseline_drift']}
    if recheck:drift.update({(x['case_id'],x['scope']):x for x in review['baseline_drift']})
    assert all(abs(x['relative_change'])<=.05 for x in drift.values())
    rows=list(accepted.values());expected_cases=len((root/'cases.tsv').read_text().splitlines());assert len(rows)==len(cfg['order'])*expected_cases*2
    calls=len(rows)*cfg['trials'];primary_calls=sum(not r['iteration'].endswith('_REPEAT') for r in rows)*cfg['trials']
    profile_calls=sum(row['trials'] for values in profiles.values() for row in values)//2 if cfg.get('profile_enabled',True) else 0
    def median(r):return r['file_e2e_ms' if r['scope']=='file' else 'host_observed_ms']['median']
    base={(r['case_id'],r['scope']):median(r) for r in rows if r['iteration']=='OPT_1_STREAMING'}
    initial.update(status='passed',rows=rows,baseline_drift=list(drift.values()),original_baseline_drift=initial['baseline_drift'],
        recheck=str(recheck) if recheck else None,recheck_policy='Replace complete flagged workloads across all variants/scopes; preserved original allocation and evidence.',
        speedups=[dict(iteration=r['iteration'],case_id=r['case_id'],scope=r['scope'],speedup_vs_streaming=base[r['case_id'],r['scope']]/median(r)) for r in rows if not r['iteration'].endswith('_REPEAT')],
        accepted_measured_calls=calls,accepted_primary_measured_calls=primary_calls,accepted_warmup_calls=len(rows)*cfg['warmups'],gpu_profile_calls=profile_calls,board_admission=admission,
        runtime_revision=cfg['runtime_revision'],gpu_device_profiles=profiles)
    save(root/'summary.json',initial)
    flat=[dict(iteration=r['iteration'],case_id=r['case_id'],scope=r['scope'],input_bytes=r['input_bytes'],cohort=r['cohort'],evidence=r['evidence'],metric=k,**v) for r in rows for k,v in r.items() if isinstance(v,dict)]
    with (root/'summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    save(root/'board_admission.json',dict(status='passed',target=initial['target'],variants=admission))
    for p in list((root/'diagnostics/preprocessing_validation').rglob('*'))+[root/name for name in ['summary.json','summary.csv','board_admission.json','installed_image.json','campaign.json','environment_manifest.json']]+list((root/'tooling').glob('*.py')):
        if p.is_file():sealed[str(p.relative_to(root))]=sha(p)
    save(root/'measurement_manifest.json',dict(status='passed',verified_at=time.time(),files=sealed))
    state=read(root/'status.json');state.update(status='passed',stage='complete',accepted_at=time.time());state.pop('error',None);save(root/'status.json',state)
    print('PASS accepted',calls,'measured calls; drift',max(abs(x['relative_change']) for x in drift.values()),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--recheck',type=Path);a=p.parse_args();accept(a.root.resolve(),a.recheck.resolve() if a.recheck else None)
