#!/usr/bin/env python3
"""Archive measured evidence and render the requested four-variant report."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import statistics
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from board_benchmark import clock_model,save,sha,write_csv
from resource_attribution import extract, parse_hierarchy, parse_capacity, unique

COLORS={'D_N':'#737b83','D_I':'#007c91','R_O':'#c36c00','R_S':'#7356a6','ORIGINAL':'#b33d60'}


def generate(board,out):
    out.mkdir(parents=True,exist_ok=True);fig=out/'figures';fig.mkdir(exist_ok=True);data=out/'data';data.mkdir(exist_ok=True)
    sources={'D_I':board/'D_I/attempt_01','D_N':board/'D_N/attempt_01','R_O':board/'production_extensions/R_O','R_S':board/'production_extensions/R_S'}
    sources['ORIGINAL']=board/'original_extension/ORIGINAL'
    summaries={};manifest={};allsummary=[]
    def copy(src,dst):
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        manifest[str(dst.relative_to(out))]=dict(source=str(src.resolve()),sha256=sha(dst),bytes=dst.stat().st_size)
    for job,source in sources.items():
        result=json.loads((source/'full.analysis.json').read_text());assert result['status']=='passed' and result['trials']==2640
        summaries[job]=result['summary'];allsummary.extend(result['summary'])
        for p in source.glob('full.*'):copy(p,data/job/p.name)
        if job in ('R_O','R_S'):
            for name in ['gate.analysis.json','gate.jsonl','admission/status.json','admission/isolation_validation.json','admission/production.csv']:copy(source/name,data/job/name)
        elif job=='ORIGINAL':
            for name in ['gate.analysis.json','gate.jsonl','original_identity.json']:copy(source/name,data/job/name)
        else:copy(source/'status.json',data/job/'status.json')
        if job in ('R_O','R_S','ORIGINAL'):
            script=(board/'production_extensions/sources/production_host_benchmark.py') if job!='ORIGINAL' else Path(__file__).parent/'production_host_benchmark.py'
            assert sha(script)==result['collector_sha256']
            copy(script,data/job/'collector.py')
    for name in ['inputs.json','cases.tsv','production_tolerances.json','board_target.json','hardware_selection.json','runtime_validation.json','notifications.jsonl']:
        copy(board/name,data/name)
    copy(board/'production_extensions/status.json',data/'production_queue_status.json')
    copy(board/'original_extension/status.json',data/'original_queue_status.json')
    copy(board/'diagnostics/R_S_parity_01/isolation_validation.json',data/'R_S/earlier_parity.json')
    for name in ['production_host_benchmark.py','production_host_queue.py','report_board_comparison.py','board_benchmark.py','parity_gate.py']:
        p=Path(__file__).parent/name;copy(p,data/'sources'/name)
    write_csv(data/'all_variant_summaries.csv',allsummary)
    raw=list(csv.DictReader((sources['D_I']/'full.csv').open()));clock=list(csv.DictReader((sources['D_I']/'full.clock.csv').open()))
    event_rows=[]
    names={6:'arm',8:'raw_first',9:'raw_last',10:'pp_first',11:'pp_last',12:'cnn_first',13:'cnn_last_input',14:'score',15:'verdict'}
    for case in summaries['D_I']:
        ident=case['case_id'];mapped,fit=clock_model([r for r in clock if r['case_id']==ident]);tick_ns=(fit['ns_per_tick_min']+fit['ns_per_tick_max'])/2
        for r in [r for r in raw if r['case_id']==ident]:
            row=dict(case_id=ident,sweep=case['sweep'],input_bytes=case['input_bytes'],trial=int(r['trial']),warmup=int(r['warmup']))
            start=int(r['host_start_ns'])
            for index,name in names.items():
                lo,hi=mapped(int(r[f'csr_{index}']));row[name+'_ms']=((lo+hi)/2-start)/1e6;row[name+'_uncertainty_ms']=(hi-lo)/1e6
            for field,key in [('host_submit_ms','submit_start_ns'),('host_dma_done_ms','host_dma_done_ns'),('host_done_ms','host_verdict_seen_ns')]:row[field]=(int(r[key])-start)/1e6
            for label,key in [('input_starve_cycles',22),('input_backpressure_cycles',23),('pixel_backpressure_cycles',24),('cnn_starve_cycles',25),('pixels_produced',27),('pixels_consumed',28),('fifo_peak',29)]:row[label]=int(r[f'csr_{key}'])
            row['cnn_ready_empty_ms']=row['cnn_starve_cycles']*tick_ns/1e6
            row['cnn_elapsed_ms']=(int(r['csr_14'])-int(r['csr_12']))*tick_ns/1e6
            row['tail_ms']=(int(r['csr_15'])-int(r['csr_11']))*tick_ns/1e6
            assert row['pixels_produced']==row['pixels_consumed']==65536
            event_rows.append(row)
    write_csv(data/'D_I_events_host_relative.csv',event_rows)
    event_summary=[]
    for case in sorted(summaries['D_I'],key=lambda r:(r['sweep'],r['input_bytes'])):
        block=[r for r in event_rows if r['case_id']==case['case_id'] and not r['warmup']]
        row={k:case[k] for k in ['case_id','sweep','input_bytes']}
        for key in block[0]:
            if key.endswith('_ms') or key.endswith('_cycles') or key=='fifo_peak':row[key]=statistics.median(r[key] for r in block)
        event_summary.append(row)
    write_csv(data/'D_I_event_medians.csv',event_summary)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})
    f,axes=plt.subplots(1,2,figsize=(12,4.8))
    for ax,sweep in zip(axes,['synthetic','real']):
        for job,rs in summaries.items():
            rows=sorted([r for r in rs if r['sweep']==sweep],key=lambda r:r['input_bytes'])
            ys=[r.get('median_host_observed_ms',r['median_ms']) for r in rows]
            # Compare host-observed endpoints for all four designs.
            ax.plot([r['input_bytes']/2**20 for r in rows],ys,'o-',color=COLORS[job],label=job)
        ax.set(xlabel='Raw payload (MiB)',ylabel='Host-observed latency (ms)',title=sweep.capitalize()+' sweep');ax.grid(alpha=.2);ax.legend()
    f.suptitle('Five designs: median host start → host result/completion',fontsize=13)
    f.tight_layout();f.savefig(fig/'latency_comparison.png');f.savefig(fig/'latency_comparison.pdf');plt.close(f)
    selected=[]
    for n in [4194304,134217664]:
        block=sorted([r for r in event_rows if r['input_bytes']==n and not r['warmup']],key=lambda r:r['verdict_ms']);selected.append(block[len(block)//2])
    f,axes=plt.subplots(3,1,figsize=(11,8.5))
    for ax,row,label,zoom in [(axes[0],selected[0],'4 MiB',False),(axes[1],selected[1],'Near-128 MiB',False),(axes[2],selected[1],'Near-128 MiB: final 60 µs',True)]:
        for y,(a,b,c,label2) in enumerate([('raw_first_ms','raw_last_ms','#4185b5','Payload acceptance'),('pp_first_ms','pp_last_ms','#d08c22','Pixel production'),('cnn_first_ms','score_ms','#279672','CNN including input waits')]):
            ax.broken_barh([(row[a],row[b]-row[a])],(y-.3,.6),facecolors=c)
            ax.plot([row[a],row[b]],[y,y],'|',color='black',markersize=11)
        ax.axvline(row['verdict_ms'],color='#333333',ls='--',label='Verdict');ax.plot(row['cnn_last_input_ms'],2,'o',color='black',ms=4,label='Last CNN input')
        ax.set(yticks=[0,1,2],yticklabels=['Payload acceptance','Pixel production','CNN incl. waits'],xlabel='Milliseconds after host start',title=f"{label} — actual measured trial {row['trial']}")
        if zoom:ax.set_xlim(row['verdict_ms']-.06,row['verdict_ms']+.003)
        else:ax.set_xlim(0,row['host_done_ms']*1.02)
        ax.grid(axis='x',alpha=.2);ax.legend(loc='lower right',fontsize=8)
    f.tight_layout();f.savefig(fig/'pipeline_timeline.png');f.savefig(fig/'pipeline_timeline.pdf');plt.close(f)
    f,axes=plt.subplots(1,2,figsize=(12,4.6))
    for sweep,marker in [('synthetic','o'),('real','s')]:
        rows=sorted([r for r in summaries['D_I'] if r['sweep']==sweep],key=lambda r:r['input_bytes']);sink={r['input_bytes']:r for r in summaries['D_N']}
        axes[0].plot([r['input_bytes']/2**20 for r in rows],[(r['median_ms']-sink[r['input_bytes']]['median_ms'])*1000 for r in rows],marker+'-',label=sweep)
    axes[0].axhline(21.332,color='#888888',ls=':',label='D_I pixel-to-verdict tail ≈21.33 µs');axes[0].set(xlabel='Raw payload (MiB)',ylabel='Difference of medians (µs)',title='D_I − sink, calibrated FPGA endpoints');axes[0].legend(fontsize=8)
    es=sorted([r for r in event_summary if r['sweep']=='synthetic'],key=lambda r:r['input_bytes'])
    for key,label in [('cnn_elapsed_ms','First CNN input → score'),('cnn_ready_empty_ms','CNN ready/empty counter duration')]:axes[1].plot([r['input_bytes']/2**20 for r in es],[r[key] for r in es],'o-',label=label)
    axes[1].set(xlabel='Raw payload (MiB)',ylabel='Milliseconds',title='CNN elapsed time grows with input waits');axes[1].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2)
    f.tight_layout();f.savefig(fig/'streaming_explanation.png');f.savefig(fig/'streaming_explanation.pdf');plt.close(f)
    jobs={'D_I':board.parent/'parallel_resume_20261009_1550/jobs/D_I','D_N':board.parent/'direct_stream_20261008_002352/jobs/D_N','R_O':board.parent/'production_isolation_20261008_132304/jobs/R_O','R_S':board.parent/'parallel_resume_20261009_1550/jobs/R_S'}
    resources={}
    for job,path in jobs.items():
        r=extract(path);resources[job]=r;save(data/job/'routed_resources.json',r)
        for name in ['source_manifest.json','artifact_manifest.json','progress.json']:
            if (path/name).exists():copy(path/name,data/job/'hardware'/name)
    frozen=board.parents[2]/'reproducibility/prod_res256_coyote_accel_downsampler_hls4ml_e2e_20260524'
    package=json.loads((frozen/'manifest.json').read_text())
    paths=[frozen/'results/reports/shell_routed_hierarchical_utilization.rpt',frozen/'results/reports/shell_utilization.rpt']
    for path in paths:
        record=next(r for r in package['files'] if frozen/r['path']==path)
        assert sha(path)==record['sha256']
        copy(path,data/'ORIGINAL/hardware'/path.name)
    hierarchy=parse_hierarchy(paths[0].read_text());capacity,_=parse_capacity(paths[1].read_text());wrapper=hierarchy[unique(hierarchy,'inst_user_wrapper_0')]
    resources['ORIGINAL']=dict(wrapper=wrapper,wrapper_percent={k:100*v/capacity[k] for k,v in wrapper.items()},scope='frozen production routed wrapper')
    save(data/'ORIGINAL/routed_resources.json',resources['ORIGINAL'])
    keys=['LUT','FF','BRAM_tiles','DSP','URAM'];f,ax=plt.subplots(figsize=(9,4.6));x=np.arange(len(keys))
    for i,job in enumerate(['D_N','D_I','R_O','R_S','ORIGINAL']):ax.bar(x+(i-2)*.16,[resources[job]['wrapper_percent'][k] for k in keys],.16,label=job,color=COLORS[job])
    ax.axhline(10,color='#ae3131',ls='--',label='10% target');ax.set(xticks=x,xticklabels=['LUT','Registers','BRAM','DSP','URAM'],ylabel='U55C device capacity (%)',title='Routed user wrapper, including interfaces and ILA');ax.legend(ncol=3,fontsize=8);f.tight_layout();f.savefig(fig/'resources.png');f.savefig(fig/'resources.pdf');plt.close(f)
    save(out/'evidence_manifest.json',manifest)
    save(out/'report_inputs.json',dict(summaries=summaries,event_summary=event_summary,resources={k:v['wrapper_percent'] for k,v in resources.items()}))
    print(out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('board',type=Path);p.add_argument('output',type=Path);a=p.parse_args();generate(a.board.resolve(),a.output.resolve())
