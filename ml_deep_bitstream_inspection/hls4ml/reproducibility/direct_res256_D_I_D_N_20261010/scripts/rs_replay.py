"""R_S production-DMA admission and host timing; no internal FPGA timestamps."""
import csv,json,shutil,statistics,sys
from board_benchmark import save,sha,percentile,write_csv
from parity_gate import load_tolerances,check_logit


def collect(package,root,attempt,config,action,process):
    project=root/'software/production_project'
    modes=['gate'] if action=='validate' else ['gate','smoke','pilot','full']
    for mode in modes:
        process(['numactl','--physcpubind='+str(config['cpu']),'--membind='+str(config['numa_node']),sys.executable,
                 package/'scripts/production_host_benchmark.py',root,'R_S',project,attempt,mode],attempt,mode)
        result=json.loads((attempt/(mode+'.analysis.json')).read_text())
        expected={'gate':260,'smoke':30,'pilot':24,'full':2640}[mode]
        if result['status']!='passed' or result['trials']!=expected:raise ValueError('Incomplete R_S '+mode)
    save(attempt/'status.json',dict(status='passed',variant='R_S',admission_checks=260,rows=2640 if action=='benchmark' else 0,internal_fpga_events='unavailable'))


def analyze_saved(package,root):
    """Recompute host-only summaries from saved R_S rows; never open hardware."""
    dest=root/'R_S';shutil.copytree(package/'results/benchmarks/R_S',dest)
    grid=json.loads((root/'inputs.json').read_text());tolerances=load_tolerances(root/'production_tolerances.json')
    for mode in ['gate','smoke','pilot','full']:
        trials,warmups={'gate':(10,0),'smoke':(2,0),'pilot':(10,2),'full':(200,20)}[mode]
        cases=grid['runtime_cases' if mode=='gate' else 'smoke' if mode=='smoke' else 'cases']
        if mode=='pilot':cases=[c for c in cases if c['bytes'] in (4194304,134217664)]
        rows=[json.loads(line) for line in (dest/(mode+'.jsonl')).read_text().splitlines()]
        if {r['case_id'] for r in rows}!={c['id'] for c in cases}:raise ValueError('Incomplete R_S grid')
        summaries=[]
        for c in cases:
            block=[r for r in rows if r['case_id']==c['id']]
            if len(block)!=trials+warmups or sorted(r['trial'] for r in block)!=list(range(trials+warmups)):raise ValueError('Incomplete R_S trials')
            for r in block:
                if r['input_sha256']!=c['sha256'] or r['variant']!='R_S' or r['warmup']!=int(r['trial']<warmups):raise ValueError('R_S trial identity mismatch')
                check_logit(r['logit_bits'],r['verdict'],c,tolerances[c['sha256']])
                times=[r[k] for k in ['host_start_ns','submit_start_ns','predict_return_ns','host_verdict_seen_ns']]
                if times!=sorted(times):raise ValueError('R_S timestamp order')
                r['host_observed_ms']=(times[3]-times[0])/1e6
            xs=[r['host_observed_ms'] for r in block if not r['warmup']]
            item=dict(case_id=c['id'],variant='R_S',input_bytes=c['bytes'],measured=trials,warmups=warmups,median_ms=statistics.median(xs),p95_ms=percentile(xs,.95),max_ms=max(xs))
            if mode=='full':item['p95_upper95_ms']=sorted(xs)[195]
            summaries.append(item)
        write_csv(dest/(mode+'.recomputed.summary.csv'),summaries)
