#!/usr/bin/env python3
"""RawCoyoteOverlay/CoyoteInference collection for direct checker and sink."""
import argparse
import csv
import json
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from pipeline.coyote_accelerator.raw_overlay import RawCoyoteOverlay
from board_benchmark import sha, save
from parity_gate import check_logit, load_tolerances
from benchmark_identity import installed_identity
from host_environment import record as record_environment


def read_cases(path):
    cases=[]
    with path.open() as source:
        for row in csv.reader(source, delimiter='\t'):
            if not row or row[0].startswith('#'): continue
            if len(row)!=6: raise ValueError('manifest requires six fields')
            ident,sweep,file,size,digest,expected=row
            p=Path(file)
            if p.stat().st_size!=int(size) or sha(p)!=digest: raise ValueError('input identity changed')
            cases.append(dict(id=ident,sweep=sweep,path=file,bytes=int(size),sha256=digest,expected_logit_hex=expected))
    if not cases: raise ValueError('empty case list')
    return cases


def collect(args):
    cases=read_cases(args.cases)
    tolerances=load_tolerances(args.tolerances) if args.tolerances else None
    image_path=getattr(args,'image_manifest',None)
    identity=installed_identity(image_path,args.variant) if image_path else None
    if not args.diagnostic and identity is None:
        raise ValueError('Explicit installed-image identity required for benchmark collection')
    if args.variant==7 and not args.diagnostic and tolerances is None:
        raise ValueError('production tolerance file required before benchmarking')
    backend='direct_checker' if args.variant==7 else 'direct_sink'
    fields=['case_id','sweep','input_sha256','variant','input_bytes','transport_bytes','trial','trial_tag','warmup',
            'status','signature','host_start_ns','submit_start_ns','submit_return_ns','host_dma_done_ns','host_verdict_seen_ns']
    fields += [f'csr_{i}' for i in range(6,30)]
    failures=[];rows=0
    environment_file=args.csv.with_suffix('.environment.jsonl')
    with args.csv.open('x') as f,args.clock.open('x') as clock,environment_file.open('x') as environment:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        clocks=csv.writer(clock);clocks.writerow(['case_id','position','host_before_ns','fpga_tick','host_after_ns'])
        with RawCoyoteOverlay.open_direct_session(args.library,backend,max(c['bytes'] for c in cases),args.allocation) as session:
            for c in cases:
                raw=np.fromfile(c['path'],dtype=np.uint8)
                session.prepare(raw)
                print('CASE_START',c['id'],c['bytes'],flush=True)
                record_environment(environment,c['id'],'before')
                for _ in range(32): clocks.writerow([c['id'],'before',*session.clock_sample()])
                clock.flush()
                for i in range(args.warmups+args.trials):
                    result=session.run()
                    row={k:v for k,v in result.items() if k in fields}
                    row.update(case_id=c['id'],sweep=c['sweep'],input_sha256=c['sha256'],variant=args.variant,
                               input_bytes=c['bytes'],trial=i,warmup=int(i<args.warmups))
                    writer.writerow(row);f.flush();rows+=1
                    if args.variant==7:
                        try:
                            check_logit(result['csr_26']&0xffffffff,result['verdict'],c,
                                        tolerances[c['sha256']] if tolerances else None)
                        except ValueError as e:
                            failure=dict(case_id=c['id'],trial=i,error=str(e),logit=result['logit'],
                                         logit_hex=f"{result['csr_26']&0xffffffff:08x}",expected=c['expected_logit_hex'])
                            failures.append(failure)
                            if not args.diagnostic: raise
                for _ in range(32): clocks.writerow([c['id'],'after',*session.clock_sample()])
                clock.flush();record_environment(environment,c['id'],'after');print('CASE_DONE',c['id'],flush=True)
    if image_path and installed_identity(image_path,args.variant)!=identity:
        raise ValueError('Installed hardware identity changed during collection')
    summary=dict(status='parity_failed' if failures else 'passed',diagnostic=args.diagnostic,rows=rows,failures=failures,
                 backend=backend,allocation=args.allocation,library_sha256=sha(args.library),cases_sha256=sha(args.cases),
                 tolerances_sha256=sha(args.tolerances) if args.tolerances else None,hardware_identity=identity)
    summary['environment_snapshots']=dict(path=str(environment_file),sha256=sha(environment_file),scope='before/after each case, outside measured calls')
    save(args.csv.with_suffix('.status.json'),summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='failures'}),flush=True)
    return 2 if failures else 0


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('cases',type=Path);p.add_argument('csv',type=Path);p.add_argument('clock',type=Path)
    p.add_argument('variant',type=int,choices=[7,8]);p.add_argument('trials',type=int);p.add_argument('warmups',type=int)
    p.add_argument('--library',type=Path,required=True);p.add_argument('--allocation',choices=['HPF','REG'],default='HPF')
    p.add_argument('--tolerances',type=Path);p.add_argument('--diagnostic',action='store_true')
    p.add_argument('--image-manifest',type=Path)
    a=p.parse_args()
    if a.trials<1 or a.warmups<0: p.error('invalid trial counts')
    try: sys.exit(collect(a))
    except Exception as e:
        save(a.csv.with_suffix('.failure.json'),dict(status='failed',error=str(e),diagnostic=a.diagnostic))
        raise
