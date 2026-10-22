#!/usr/bin/env python3
"""Focused hls4ml-checker report; adapted from the full-report generator. No hardware access.
Run from the repository: ml_baseline/.venv/bin/python <this script>
"""
import csv, hashlib, json, sys, math, os
from pathlib import Path
from functools import lru_cache
from xml.sax.saxutils import escape
import numpy as np
os.environ.setdefault('MPLCONFIGDIR','/tmp/final_benchmark_report_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
try:
    import reportlab
except ImportError:
    sys.path.append('/usr/lib/python3/dist-packages')
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4

OUT=Path(__file__).resolve().parent
REPO=OUT.parents[4]
ROOT=REPO/'hls4ml/optimize/runs/final_benchmarks_gpu_preprocess_v2_20261021_030038'
assert json.loads((ROOT/'campaign.json').read_text())['runtime_revision']=='gpu_preprocess_v2', 'Report must stay pinned to preprocessing-only fix'
sys.path.insert(0,str(ROOT/'tooling'))
from board_benchmark import clock_model
FIG=OUT/'figures'; FIG.mkdir(exist_ok=True)
DATA=OUT/'data'; DATA.mkdir(exist_ok=True)
S=json.loads((ROOT/'summary.json').read_text())
IDS=['OPT_0_NONSTREAMING','OPT_1_STREAMING','OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288','OPT_7_GPU_HOST','OPT_8_GPU_P2P']
LABELS=['Buffering','Streaming','Resource-optimized streaming','GPU_HOST','GPU_P2P']
N=dict(zip(IDS,LABELS)); C=dict(zip(IDS,['#7b8494','#087e8b','#2c944e','#cf6a19','#7752a5']))
SHORT=dict(N);SHORT[IDS[2]]='Resource-optimized\nstreaming'
SIZES=[4194304,16777216,67108864,134217664]
SYN=[f'synthetic_{x}' for x in SIZES]
CASES=sorted({r['case_id']:r['input_bytes'] for r in S['rows'] if not r['case_id'].startswith('smoke')}.items(),key=lambda x:(x[1],x[0]))
CASE=dict(CASES); REPS=[SYN[0],SYN[-1]]
ROWS={(r['iteration'],r['case_id'],r['scope']):r for r in S['rows']}
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.titlesize':12,'axes.labelsize':11,'legend.fontsize':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':120,'savefig.dpi':210})
VERIFIED={}; STATS=[]; SEGMENTS=[]; TIMELINES=[]; FIGURES=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def savejson(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def warm(x):return str(x).lower() in ['true','1']
def pct(a,p):return float(np.percentile(a,p))
def stat(a):return dict(mean=float(np.mean(a)),median=float(np.median(a)),p95=pct(a,95))
@lru_cache(None)
def source(path):
    p=Path(path).parent
    gpu=(p/'observations.jsonl').exists()
    if gpu:
        raw=[json.loads(x) for x in (p/'observations.jsonl').read_text().splitlines()]
        derived=json.loads((p/'derived.json').read_text())
    else:
        raw=list(csv.DictReader((p/'observations.csv').open()))
        derived=list(csv.DictReader((p/'derived.csv').open()))
    return raw,derived
@lru_cache(None)
def trials(i,c,scope):
    row=ROWS[i,c,scope];a,b=source(row['evidence'])
    def select(xs):return [r for r in xs if r['case_id']==c and r['scope']==scope and not warm(r['warmup'])]
    aa,bb=select(a),select(b);assert len(aa)==len(bb)==200
    for metric,expected in row.items():
        if isinstance(expected,dict):
            vals=[float(r[metric]) for r in bb]
            for k,q in [('median',50),('p95',95)]:assert math.isclose(pct(vals,q),expected[k],rel_tol=1e-8,abs_tol=1e-8),(i,c,scope,metric,k)
    return aa,bb

def values(i,c,scope,key):return np.array([float(x[key]) for x in trials(i,c,scope)[1]])
def med(i,c,scope,key=None):return float(np.median(values(i,c,scope,key or ('file_e2e_ms' if scope=='file' else 'host_observed_ms'))))
def case_label(c):
    n=CASE[c]
    if c==SYN[-1]:return '128 MiB − 64 B'
    if c.startswith('synthetic'):return f'{n/2**20:g} MiB'
    return f'{n:,} B'

def figure(name,fig):
    fig.savefig(FIG/(name+'.png'),bbox_inches='tight',facecolor='white')
    fig.savefig(FIG/(name+'.svg'),bbox_inches='tight',facecolor='white')
    fig.savefig(FIG/(name+'.pdf'),bbox_inches='tight',facecolor='white')
    plt.close(fig);FIGURES.append(name);return name

def axes_grid(rows=1,cols=2,size=None):
    fig,axs=plt.subplots(rows,cols,figsize=size or (9,3.3*rows),squeeze=False,layout='constrained')
    for ax in axs.flat:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    return fig,axs

from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D
OLD=OUT.parent/'2026-10-20_final_benchmarks'
OLD_HASHES={str(p.relative_to(OLD)):sha(p) for p in OLD.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
COMPARE=IDS[2:]; DISPLAY={**N,IDS[2]:'FPGA_HLS4ML'}
REAL=[c for c,n in CASES if c.startswith('real')];RID={c:f'R{j+1}' for j,c in enumerate(REAL)}
assert len(SYN)==4 and len(REAL)==8 and len(CASES)==12
assert S['status']=='passed'
manifest=json.loads((ROOT/'measurement_manifest.json').read_text())
for rel,digest in manifest['files'].items():
    assert sha(ROOT/rel)==digest,rel
    VERIFIED[rel]=digest
for i in IDS:
    for c,n in CASES:
        _,ds=trials(i,c,'resident')
        STATS.append(dict(iteration=i,label=DISPLAY[i],case_id=c,input_bytes=n,timing_scope='host in-memory',evidence=ROWS[i,c,'resident']['evidence'],**stat([float(x['host_observed_ms']) for x in ds])))
print('PASS evidence hashes and all 60 selected case/variant cells',flush=True)

SPEEDUPS=[]
def labels(cases):return [case_label(c) if c in SYN else f'{RID[c]}\n{CASE[c]/2**20:.2f} MiB' for c in cases]
def latency_bars(cases,name):
    f,a=plt.subplots(figsize=(11,5.8),layout='constrained');x=np.arange(len(cases));width=.24
    for j,i in enumerate(COMPARE):
        vv=[med(i,c,'resident') for c in cases];pp=[pct(values(i,c,'resident','host_observed_ms'),95) for c in cases];xx=x+(j-1)*width
        a.bar(xx,vv,width,color=C[i],label=DISPLAY[i]);a.scatter(xx,pp,marker='_',color='black',s=65,zorder=4)
        for xx1,v,p95 in zip(xx,vv,pp):a.annotate(f'{v:.3f}',(xx1,max(v,p95)),xytext=(0,5),textcoords='offset points',ha='center',fontsize=9,rotation=90 if len(cases)>4 else 0)
    a.set_xticks(x,labels(cases));a.set(xlabel='Raw input size' if cases==SYN else 'Real bitstream / raw input size',ylabel='Host in-memory latency (ms)')
    a.set_ylim(0,max(pct(values(i,c,'resident','host_observed_ms'),95) for i in COMPARE for c in cases)*(1.26 if len(cases)>4 else 1.18))
    h,l=a.get_legend_handles_labels();h.append(Line2D([],[],marker='_',ls='',color='black'));l.append('p95 marker');a.legend(h,l,ncol=4,loc='upper left',fontsize=10)
    a.grid(axis='y',alpha=.2);a.set_axisbelow(True);figure(name,f)
def speedup_bars(cases,name):
    f,a=plt.subplots(figsize=(11,5.8),layout='constrained');x=np.arange(len(cases));width=.32
    for j,i in enumerate(IDS[3:]):
        vv=[med(i,c,'resident')/med(IDS[2],c,'resident') for c in cases];xx=x+(j-.5)*width
        a.bar(xx,vv,width,color=C[i],label='vs '+DISPLAY[i])
        for c,xx1,v in zip(cases,xx,vv):
            a.text(xx1,v+.04,f'{v:.2f}×',ha='center',va='bottom',fontsize=10)
            SPEEDUPS.append(dict(case_id=c,comparison='FPGA_HLS4ML vs '+DISPLAY[i],speedup=v))
    a.axhline(1,color='#4e5560',ls='--',lw=1);a.set_xticks(x,labels(cases));a.set(xlabel='Raw input size' if cases==SYN else 'Real bitstream / raw input size',ylabel='FPGA_HLS4ML speedup (×)');a.set_ylim(0,max(v['speedup'] for v in SPEEDUPS)*1.18);a.legend(ncol=2);a.grid(axis='y',alpha=.2);a.set_axisbelow(True);figure(name,f)
latency_bars(SYN,'01_synthetic_latency');speedup_bars(SYN,'02_synthetic_speedup')
latency_bars(REAL,'A1_real_latency');speedup_bars(REAL,'A2_real_speedup_bars')
f,a=plt.subplots(figsize=(11,5.8),layout='constrained')
for i,marker in zip(COMPARE,['o','s','D']):
    xx=[CASE[c]/2**20 for c in REAL];yy=[med(i,c,'resident') for c in REAL]
    a.scatter(xx,yy,color=C[i],marker=marker,label=DISPLAY[i],s=45)
    for c,x,y in zip(REAL,xx,yy):a.annotate(RID[c],(x,y),xytext=(4,5),textcoords='offset points',fontsize=9,color=C[i])
a.set(xlabel='Raw input size (MiB)',ylabel='Host in-memory latency (ms)',ylim=(0,24));a.legend();a.grid(alpha=.2);figure('A3_real_latency_scatter',f)

# Setup schematic: physical connectivity plus three logical data paths.
def box(ax,x,y,w,h,text,color='#e9eef4',fs=10):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.015',facecolor=color,edgecolor='#617184',lw=1));ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=fs)
def arrow(ax,p,q,color='#465e73',style='-',rad=0):
    ax.add_patch(FancyArrowPatch(p,q,arrowstyle='-|>',mutation_scale=12,lw=1.6,color=color,linestyle=style,connectionstyle=f'arc3,rad={rad}'))
def physical(ax):
    ax.set(xlim=(0,10),ylim=(0,2.4));ax.axis('off');ax.set_title('Shared machine: hacc-gpu-u55c-01',loc='left')
    box(ax,.15,1.15,2.15,.68,'Host CPU + RAM\nCPU64 / NUMA1',fs=10)
    box(ax,3.0,1.15,3.4,.68,'PCIe fabric / root complexes\nCross-root peer transactions',fs=10)
    box(ax,7.2,1.25,2.6,.65,'U55C FPGA (device2)\nPCIe Gen3 ×16',fs=10)
    box(ax,7.2,.15,2.6,.65,'MI210 GPU0 + GPU RAM\nNUMA0 · PCIe Gen4 ×16',fs=10)
    arrow(ax,(2.3,1.49),(3,1.49));arrow(ax,(6.4,1.49),(7.2,1.57));arrow(ax,(6.4,1.49),(7.2,.48));arrow(ax,(7.2,.42),(6.0,1.15),color='#7752a5',rad=-.15)
    ax.text(.15,.30,'P2P traverses the PCIe fabric; it is not a dedicated cable.\nHost controls GPU launches; FPGA polls the GPU_P2P mailbox.',fontsize=10,va='center')
def path_panel(ax,kind):
    ax.set(xlim=(0,10),ylim=(0,2.4));ax.axis('off');ax.set_title(kind,loc='left',color=C[IDS[2] if kind=='FPGA_HLS4ML' else IDS[3] if kind=='GPU_HOST' else IDS[4]],fontweight='bold')
    if kind=='FPGA_HLS4ML':
        box(ax,.15,1,2,.65,'Prepared host RAM');box(ax,3.4,1,3.0,.65,'FPGA streaming\npreprocessing + CNN',color='#e2f1e7');box(ax,7.5,1,2.2,.65,'FPGA verdict\nHost observes done')
        arrow(ax,(2.15,1.33),(3.4,1.33));arrow(ax,(6.4,1.33),(7.5,1.33),color='#23884b');ax.text(2.75,1.53,'PCIe',ha='center',fontsize=9)
        ax.text(.2,.35,'Input transfer, preprocessing, and CNN execution overlap.',fontsize=10)
    elif kind=='GPU_HOST':
        box(ax,.15,.9,1.8,.65,'Prepared\nhost RAM');box(ax,3.1,1.25,2.5,.68,'GPU preprocessing\n+ CNN',color='#fae9d9');box(ax,3.1,.15,2.5,.65,'FPGA receives input\nand waits');box(ax,6.3,1.25,1.4,.68,'Host\nresult relay');box(ax,8.3,.55,1.5,.68,'FPGA\nverdict')
        arrow(ax,(1.95,1.4),(3.1,1.58));arrow(ax,(1.95,1.0),(3.1,.48));arrow(ax,(5.6,1.58),(6.3,1.58),color='#23884b');arrow(ax,(7.7,1.58),(8.3,1.0),color='#23884b');arrow(ax,(5.6,.48),(8.3,.72))
        ax.text(2.5,1.88,'PCIe input copies',ha='center',fontsize=9)
    else:
        box(ax,.15,1.05,1.8,.65,'Prepared\nhost RAM');box(ax,3.05,1.05,2.0,.65,'FPGA bridge\n32 × 64-byte FIFO',color='#eee6f5');box(ax,6.05,1.05,3.6,.65,'GPU input → preprocessing + CNN\nPublish score + ready flag',color='#eee6f5')
        arrow(ax,(1.95,1.37),(3.05,1.37));arrow(ax,(5.05,1.37),(6.05,1.37),color='#7752a5');ax.text(5.55,1.9,'PCIe P2P',ha='center',fontsize=9)
        arrow(ax,(4.0,1.05),(7.3,1.05),color='#7752a5',style='--',rad=.22)
        arrow(ax,(7.8,1.05),(4.3,1.05),color='#23884b',rad=-.43)
        ax.text(5.7,.68,'Mailbox polling',ha='center',fontsize=9)
        ax.text(5.7,.10,'Result returned to FPGA',ha='center',fontsize=9,color='#23884b')
        ax.text(.2,.25,'GPU starts after\ncomplete input arrival.',fontsize=9)
    # Explicit control-plane note, rather than a misleading physical wire.
    ax.text(.2,2.14,'Host arms transfer and launches work  - - →',fontsize=9,color='#617184')
f=plt.figure(figsize=(11,9.5),layout='constrained');axs=f.subplots(4,1)
physical(axs[0])
for a,k in zip(axs[1:],['FPGA_HLS4ML','GPU_HOST','GPU_P2P']):path_panel(a,k)
f.suptitle('Timing: host invocation → host observes FPGA verdict',fontsize=13);figure('03_benchmark_setup',f)
for k in ['FPGA_HLS4ML','GPU_HOST','GPU_P2P']:
    f,a=plt.subplots(figsize=(11,3.2),layout='constrained');path_panel(a,k);figure('03_setup_'+k,f)
f,a=plt.subplots(figsize=(11,3.3),layout='constrained');physical(a);figure('03_setup_connectivity',f)

PHASES=['Host setup','Transfer submission','Input-completion wait','GPU preprocessing/inference calls','Synchronization/publication','Final verdict wait']
PC=['#a5b6c6','#7d9cb7','#557da5','#dda64c','#b483b5','#50616a']
def phase_values(i,c):
    aa,_=trials(i,c,'resident');allvals=[]
    for r in aa:
        if i==IDS[2]:
            keys=['host_start_ns','submit_start_ns','submit_return_ns','host_dma_done_ns','host_verdict_seen_ns'];t=[int(r[k]) for k in keys];vals=np.array([t[1]-t[0],t[2]-t[1],t[3]-t[2],0,0,t[4]-t[3]])/1e6
        else:
            keys=['host_start_ns','submit_ns','submitted_ns','input_ready_ns','relay_start_ns','relay_end_ns','verdict_seen_ns'];t=[int(r[k]) for k in keys];vals=np.diff(t)/1e6
        assert t==sorted(t) and np.min(vals)>=0 and abs(sum(vals)-(t[-1]-t[0])/1e6)<1e-7
        allvals.append(vals)
    means=np.mean(allvals,axis=0)
    assert abs(sum(means)-np.mean(values(i,c,'resident','host_observed_ms')))<1e-7
    for k,v in zip(PHASES,means):SEGMENTS.append(dict(iteration=i,label=DISPLAY[i],case_id=c,phase=k,mean_ms=float(v)))
    return means
f,axs=axes_grid(2,2,size=(11,7))
for a,c in zip(axs.flat,SYN):
    vals=np.array([phase_values(i,c) for i in [IDS[2],IDS[3]]]);left=np.zeros(2)
    for j,key in enumerate(PHASES):a.barh([0,1],vals[:,j],left=left,color=PC[j],label=key,height=.5);left+=vals[:,j]
    for j,total in enumerate(left):a.text(total,j,f' {total:.3f}',va='center',fontsize=10)
    a.set_yticks([0,1],['FPGA_HLS4ML','GPU_HOST']);a.invert_yaxis();a.set(title=case_label(c),xlabel='Mean elapsed time (ms)',xlim=(0,max(left)*1.18))
h,l=axs.flat[0].get_legend_handles_labels();f.legend(h,l,loc='outside lower center',ncol=2,fontsize=10);figure('04_invocation_breakdown',f)

@lru_cache(None)
def calibration(path):return [json.loads(x) for x in (Path(path).parent/'calibration.jsonl').read_text().splitlines()]
@lru_cache(None)
def fpga_calibration(path):return list(csv.DictReader((Path(path).parent/'clock.csv').open()))
def representative(i,c):
    aa,dd=trials(i,c,'resident');d=min(dd,key=lambda d:abs(float(d['host_observed_ms'])-med(i,c,'resident')))
    r=next(r for r in aa if str(r['trial'])==str(d['trial']));return r,d
f,axs=axes_grid(2,2,size=(11,8))
for row,c in enumerate(REPS):
    endmax=max(med(i,c,'resident') for i in [IDS[2],IDS[3]])*1.08
    for col,i in enumerate([IDS[2],IDS[3]]):
        a=axs[row,col];r,d=representative(i,c);h=int(r['host_start_ns']);ints=[]
        if col==0:
            samples=[b for b in fpga_calibration(ROWS[i,c,'resident']['evidence']) if b['case_id']==c and b['scope']=='resident' and b['session']==r['session'] and b['block']==r['block']]
            mapped,_=clock_model(samples)
            for label,k1,k2,color in [('Reception',8,9,'#557da5'),('Pixel production',10,11,'#8cc4c3'),('CNN interval',12,14,'#dda64c')]:
                lo0,hi0=mapped(r['csr_'+str(k1)]);lo1,hi1=mapped(r['csr_'+str(k2)])
                ints.append((label,((lo0+hi0)/2-h)/1e6,((lo1+hi1)/2-h)/1e6,color,max(hi0-lo0,hi1-lo1)/2e6))
            end=float(d['host_observed_ms'])
        else:
            end=(r['verdict_seen_ns']-h)/1e6
            for label,k1,k2,color in [('Input-ready wait','submit_ns','input_ready_ns','#557da5'),('GPU calls','input_ready_ns','relay_start_ns','#dda64c'),('Sync/publication','relay_start_ns','relay_end_ns','#b483b5')]:ints.append((label,(r[k1]-h)/1e6,(r[k2]-h)/1e6,color,0))
            b=next(b for b in calibration(ROWS[i,c,'resident']['evidence']) if b['case_id']==c and b['scope']=='resident' and b['first_trial']<=r['trial']<=b['last_trial']);mapped,_=clock_model(b['samples']);lo0,hi0=mapped(r['csr_8']);lo1,hi1=mapped(r['csr_9'])
            ints.append(('FPGA reception',((lo0+hi0)/2-h)/1e6,((lo1+hi1)/2-h)/1e6,'#087e8b',max(hi0-lo0,hi1-lo1)/2e6))
        for j,(label,start,stop,color,u) in enumerate(ints):
            assert stop>=start;a.barh(j,stop-start,left=start,height=.55,color=color)
            for x in [start,stop]:
                if u:a.plot([x-u,x+u],[j,j],color='black',lw=2)
            TIMELINES.append(dict(figure='05',iteration=i,label=DISPLAY[i],case_id=c,trial=str(r['trial']),activity=label,start_ms=start,end_ms=stop,uncertainty_ms=u))
        a.scatter([end],[len(ints)],marker='D',s=35,color=C[i]);a.axvline(end,color=C[i],ls=':',alpha=.6)
        a.set_yticks(range(len(ints)+1),[x[0] for x in ints]+['Host observes verdict'],fontsize=10);a.invert_yaxis();a.set(xlim=(0,endmax),xlabel='Time from host invocation (ms)',title=f'{DISPLAY[i]} · {case_label(c)}\nTrial {r["trial"]}; E2E {end:.3f} ms')
figure('05_execution_overlap',f)
# Diagnostic alternatives, never added to normal timing.
f,axs=axes_grid(2,2,size=(11,7))
PROFILE_EXPORT=[]
for row,c in enumerate(REPS):
    for col,phase in enumerate(['gpu_preprocessing','gpu_inference']):
        a=axs[row,col];q=next(x for x in S['gpu_device_profiles'][IDS[3]] if x['case_id']==c and x['phase']==phase);PROFILE_EXPORT.append(q);assert q['trials']==20
        kk=['kernel_sum_ms','device_span_ms','host_synchronized_phase_ms'];vv=[q[k]['median'] for k in kk];pp=[q[k]['p95'] for k in kk]
        a.bar(range(3),vv,color=['#dda64c','#cf6a19','#8dabc0']);a.scatter(range(3),pp,color='black',marker='_',s=65)
        for j,v in enumerate(vv):a.text(j,max(v,pp[j]),f' {v:.3f}',ha='center',va='bottom',fontsize=10)
        a.set_xticks(range(3),['Kernel sum','Device span','Host\nsynchronized']);a.set(ylabel='Diagnostic duration (ms)',title=phase.replace('gpu_','').title()+' · '+case_label(c),ylim=(0,max(pp)*1.2))
figure('06_gpu_diagnostics',f)
# Optimization comparison: only synthetic inputs, Buffering and optimized Streaming.
f,axs=axes_grid(1,2,size=(11,4.9));xx=np.array(SIZES)/2**20
for i in [IDS[0],IDS[2]]:
    yy=[med(i,c,'resident') for c in SYN];axs[0,0].plot(xx,yy,'o-',color=C[i],label=N[i]);axs[0,0].scatter(xx,[pct(values(i,c,'resident','host_observed_ms'),95) for c in SYN],color=C[i],marker='_',s=65)
axs[0,0].set(xlabel='Raw input size (MiB)',ylabel='Host in-memory latency (ms)',ylim=(0,None));axs[0,0].legend(fontsize=9)
rat=[med(IDS[0],c,'resident')/med(IDS[2],c,'resident') for c in SYN];axs[0,1].plot(xx,rat,'o-',color=C[IDS[2]],label='Resource-optimized streaming\nversus Buffering');axs[0,1].axhline(1,color='gray',ls='--');axs[0,1].set(xlabel='Raw input size (MiB)',ylabel='Speedup versus Buffering (×)',ylim=(0,max(rat)*1.15));axs[0,1].legend(fontsize=9)
for a in axs.flat:a.set_xticks([4,16,64,128],['4','16','64','128*'])
figure('07_checker_optimization',f)
# FPGA wrapper resources with matching device-percent axis.
f,axs=axes_grid(3,2,size=(10.5,9))
for a,key,titletext in zip(axs.flat,['BRAM_tiles','DSP','LUT','FF','URAM'],['BRAM tiles','DSPs','LUTs','Flip-flops','URAM blocks']):
    cap=S['resources'][IDS[0]]['capacity'][key];vv=[S['resources'][i]['wrapper'][key] for i in IDS[:3]]
    a.bar(range(3),vv,color=[C[i] for i in IDS[:3]]);a.set_xticks(range(3),['Buffering','Streaming','Resource-optimized\nstreaming'],fontsize=9);a.set(title=titletext,ylabel='Wrapper count',ylim=(0,max(vv)*1.28));a.secondary_yaxis('right',functions=(lambda x,cap=cap:x/cap*100,lambda x,cap=cap:x*cap/100)).set_ylabel('Device utilization (%)',fontsize=9)
    for j,v in enumerate(vv):a.text(j,v,f'{v:g}\n{v/cap*100:.2f}%',ha='center',va='bottom',fontsize=9)
axs.flat[-1].axis('off');axs.flat[-1].text(0,.95,'Resource-optimized streaming\nversus Streaming\n\nBRAM: −83.95%\nDSP: −51.20%\nURAM: 11 → 0\n\nRouted wrapper includes\ninterfaces and ILA.',va='top',fontsize=12);figure('08_fpga_resources',f)
f,axs=axes_grid(2,1,size=(11,8))
for a,c in zip(axs.flat,REPS):
    labs=[];ticks=[]
    for j,i in enumerate(IDS[:3]):
        r,d=representative(i,c)
        for k,(label,k1,k2,color) in enumerate([('Reception','raw_first_ms','raw_last_ms','#557da5'),('Pixel production','pp_first_ms','pp_last_ms','#8cc4c3'),('CNN interval','cnn_first_ms','logit_ms','#dda64c')]):
            start,stop=float(d[k1]),float(d[k2]);y=j*4+k;a.barh(y,stop-start,left=start,color=color,height=.65);ticks.append(y);labs.append(N[i]+' · '+label);TIMELINES.append(dict(figure='09',iteration=i,label=N[i],case_id=c,trial=str(r['trial']),activity=label,start_ms=start,end_ms=stop,uncertainty_ms=0))
    a.set_yticks(ticks,labs,fontsize=9);a.invert_yaxis();a.set(xlabel='Time from FPGA arm (ms)',title=case_label(c),xlim=(0,None))
figure('09_streaming_timelines',f)
print('PASS all focused figures generated',flush=True)
# Compact report: nine figure-led main pages, one methods page, three appendix pages.
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleR',fontName='Helvetica-Bold',fontSize=20,leading=24,textColor=colors.HexColor('#17324d'),spaceAfter=12))
styles.add(ParagraphStyle(name='BodyR',fontName='Helvetica',fontSize=10.5,leading=14.5,spaceAfter=9))
styles.add(ParagraphStyle(name='SmallR',fontName='Helvetica',fontSize=8.5,leading=11,spaceAfter=7))
styles.add(ParagraphStyle(name='CellR',fontName='Helvetica',fontSize=8,leading=10))
STORY=[];PAGES=[]
def p(s,small=False):STORY.append(Paragraph(s,styles['SmallR' if small else 'BodyR']))
def title(s):
    if PAGES:STORY.append(PageBreak())
    PAGES.append(s);STORY.append(Paragraph(s,styles['TitleR']))
def plot(name,maxh=440):
    from PIL import Image as PILImage
    path=FIG/(name+'.png');w,h=PILImage.open(path).size;scale=min(507/w,maxh/h);STORY.extend([Image(str(path),width=w*scale,height=h*scale),Spacer(1,12)])
def table(rows,widths):
    t=Table([[Paragraph(escape(str(v)),styles['CellR']) for v in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8eff5')),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f7f9')]),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));STORY.extend([t,Spacer(1,10)])
def speed(i,c):return med(i,c,'resident')/med(IDS[2],c,'resident')
small,large=REPS

title('hls4ml-checker: host in-memory latency')
p('<b>Figure 1 · Synthetic inputs · Accepted campaign: 21 October 2026</b>')
p('Host in-memory means the bitstream is already prepared in host RAM when timing starts. Every trial still transfers the complete input and ends when the host observes the FPGA verdict. File reading and host-buffer preparation are outside this timing window.')
plot('01_synthetic_latency',365)
p(f'<b>At 4 MiB:</b> FPGA_HLS4ML takes {med(IDS[2],small,"resident"):.3f} ms, GPU_HOST {med(IDS[3],small,"resident"):.3f} ms, and GPU_P2P {med(IDS[4],small,"resident"):.3f} ms. At the largest input the respective medians are {med(IDS[2],large,"resident"):.3f}, {med(IDS[3],large,"resident"):.3f}, and {med(IDS[4],large,"resident"):.3f} ms.')
p('Bars show measured medians; black ticks show p95. FPGA_HLS4ML is the Resource-optimized streaming checker. GPU_HOST sends host input to both GPU and FPGA; GPU_P2P forwards input through the FPGA and uses autonomous result polling.')
p('<b>Comparison scope:</b> FPGA W8A8 versus GPU FP32, one U55C/MI210 pairing, 200 measured trials after 20 warmups per input and implementation. These are implemented-system timings, not equal-precision kernel benchmarks. The main figures use four synthetic sizes; real bitstreams appear only in the appendix.',True)

title('hls4ml-checker speedup over GPU paths')
p('<b>Figure 2 · Synthetic inputs · Higher is better for FPGA_HLS4ML</b>')
plot('02_synthetic_speedup',385)
p('<b>Speedup = GPU median latency / FPGA_HLS4ML median latency.</b> Each ratio compares the same input size and host in-memory timing boundary. A value of 1× indicates equal latency; values above 1× favor the checker.')
p(f'Against GPU_HOST, the checker delivers {speed(IDS[3],small):.2f}× speedup at 4 MiB and {speed(IDS[3],large):.2f}× at the largest input. Against GPU_P2P, the corresponding speedups are {speed(IDS[4],small):.2f}× and {speed(IDS[4],large):.2f}×.')
p('The benefit depends on the complete transfer and execution path. GPU kernel execution alone is much shorter than GPU end-to-end latency; Figures 4–6 separate observable host phases, execution overlap, and diagnostic device timings.')
p('Ratios are formed from independent-run medians. They are not paired per-trial ratios or confidence intervals. The full preprocessing-v2 report contains the complete workload record.',True)

title('Benchmark setup and data paths')
p('<b>Figure 3 · Shared physical setup and logical paths</b>')
plot('03_benchmark_setup',475)
p('The host arms transfers and launches GPU work. Solid arrows carry input data; green arrows indicate verdict movement; dashed arrows denote control/polling. GPU_P2P reads a readiness field and result payload directly from GPU memory through the PCIe fabric.')
p('The FPGA_HLS4ML path streams pixels into the CNN while input arrives. GPU paths start their preprocessing/inference calls after GPU input readiness. The P2P bridge forwards incrementally through a 2 KiB payload FIFO; it does not buffer the complete input on the FPGA.',True)

title('Where invocation-to-verdict time is spent')
p('<b>Figure 4 · FPGA_HLS4ML versus GPU_HOST · Host in-memory</b>')
plot('04_invocation_breakdown',435)
p('Each bar adds consecutive host-observed intervals from invocation to verdict. Segments are <b>means</b> so they sum exactly to mean total latency; headline figures use medians. Tiny setup and submission intervals are retained in the exported data.')
p('For FPGA_HLS4ML, input-completion wait ends when the host observes the DMA acknowledgement. The subsequent verdict wait can include remaining FPGA work. Neither interval is a pure compute measurement: preprocessing and CNN execution overlap transfer.')
p('For GPU_HOST, input-completion wait ends when its GPU copy is ready. GPU preprocessing/inference calls include useful execution, dispatch, and gaps. Synchronization/publication can include waiting for unfinished GPU work, obtaining the score, and relaying it to the FPGA. An absent GPU-only segment in the checker bar does not mean its CNN takes zero time.',True)

title('Why overlap changes the critical path')
p('<b>Figure 5 · Representative measured host in-memory trials</b>')
plot('05_execution_overlap',450)
p('Panels within each size share an X-axis limit. Each uses an actual trial nearest that implementation’s median total, identified in the title. Diamonds mark host-observed completion; black endpoint marks show FPGA clock-alignment uncertainty, generally smaller than the plotted line width.')
p('FPGA_HLS4ML receives bytes, produces pixels, and consumes them in the CNN concurrently. GPU_HOST waits for GPU input readiness before launching preprocessing/inference. Its separate FPGA input transfer can overlap GPU activity. The checker’s advantage is therefore an execution-path result, not a claim that each individual FPGA operation is faster.')
p('Parallel lanes overlap and must not be added. The GPU HIP copy duration has no recorded host-aligned start, so this figure shows the host input-ready interval instead of inventing a device-copy timeline.',True)

title('GPU kernel time is not system latency')
p('<b>Figure 6 · GPU_HOST-only diagnostic profiling</b>')
plot('06_gpu_diagnostics',425)
p('<b>Kernel sum:</b> adds attributed GPU kernel durations, excluding gaps. <b>Device span:</b> first kernel start to last kernel completion, including gaps. <b>Host synchronized:</b> host timing around the phase and explicit output synchronization/materialization. Bars show medians; black ticks show p95.')
p('This report uses preprocessing-v2: bytes are cast to FP32 on GPU before sampling, removing the previous CPU uint8-gather fallback. Traces check for unintended input/index copies to CPU. Remaining spans can include dispatch, copies, and synchronization; they do not measure GPU arithmetic alone.')
p('These are separate, explicitly synchronized profiling runs: 20 trials per workload, with profiling/first-use effects possible. They are not parts to add together or subtract from normal host in-memory latency. They explain why a short kernel duration does not guarantee a short application response.',True)

title('Checker optimization: latency impact')
p('<b>Figure 7 · Buffering versus Resource-optimized streaming</b>')
plot('07_checker_optimization',350)
p(f'At 4 MiB, Buffering takes {med(IDS[0],small,"resident"):.3f} ms and Resource-optimized streaming takes {med(IDS[2],small,"resident"):.3f} ms: a {med(IDS[0],small,"resident")/med(IDS[2],small,"resident"):.2f}× speedup. At the largest input, the speedup is {med(IDS[0],large,"resident")/med(IDS[2],large,"resident"):.2f}×.')
p('The left panel compares host in-memory medians, with p95 ticks. The right divides Buffering median by Resource-optimized streaming median. Connecting lines guide the eye between the four measured synthetic sizes; intermediate sizes were not measured. The final point is 128 MiB − 64 B.')
p('Resource-optimized streaming combines native hls4ml FIFO optimization (profiling capacity 1024) with convolution reuse factors 72/72/288/288 for conv3/4/5/6. It retains the frozen quantized model, streaming preprocessing, and timestamp interface. The temporary profiling capacity is not a uniform final FIFO depth.',True)

title('Checker optimization: resource impact')
p('<b>Figure 8 · FPGA variants only</b>')
plot('08_fpga_resources',465)
p('Relative to Streaming, Resource-optimized streaming reduces wrapper BRAM from <b>339.5 to 54.5 tiles</b> (83.95%) and DSPs from <b>1328 to 648</b> (51.20%). URAM falls from 11 blocks to zero.')
p('Counts are routed user-wrapper resources, including interfaces and ILA. Right axes and labels use total U55C capacity as the denominator. These are not full-design counts: the shell occupies additional resources. Resource changes come from build reports; latency comes from measured board runs.',True)

title('How streaming hides preprocessing and CNN time')
p('<b>Figure 9 · Same FPGA timestamp definitions across three variants</b>')
plot('09_streaming_timelines',470)
p('Buffering waits for the complete input and pixel frame before CNN consumption. Streaming starts CNN consumption as pixels become available. Resource-optimized streaming preserves this overlap while reducing memory and multiplier resources.')
p('All lanes use the FPGA clock relative to arm. Pixel production begins at the first emitted pixel; reception starts with the first accepted payload byte. The CNN interval ends at the score and includes stalls waiting for incoming pixels. A long CNN interval at large sizes is not standalone arithmetic time. Selected trial IDs are in data/timelines.json.',True)

title('Measurement definitions and evidence')
table([['Item','Definition / scope'],['Host in-memory timing','Prepared host input invocation to host-observed FPGA verdict. Full input transferred on every call.'],['Primary data shown','4 synthetic sizes + 8 real bitstreams; 200 measured trials per implementation/input after 20 warmups.'],['FPGA labels','Buffering = OPT_0; Streaming = OPT_1; Resource-optimized streaming / FPGA_HLS4ML = OPT_6 combined FIFO1024 + aggressive B2.'],['GPU labels','GPU_HOST = OPT_7; GPU_P2P = OPT_8. Both use original FP32 TensorFlow model.'],['Board / host','hacc-gpu-u55c-01; U55C device2 at 81:00.0; MI210 GPU0 at 03:00.0; CPU64 / NUMA1; GPU on NUMA0.'],['Correctness','520-call per-image admission. FPGA logits exact; GPU scores within CPU FP32 tolerances 1e-4 absolute/relative, exact verdicts.'],['Stability',f'Maximum accepted baseline median drift: {max(abs(x["relative_change"]) for x in S["baseline_drift"])*100:.2f}%.'],['Scope limits','Fixed run order; one session and device pairing; different model precisions. No power, accuracy-equivalence, SSD, or concurrent-load claims.']],[142,365])
p('The report reads the accepted campaign manifest and evidence paths. It excludes warmups and diagnostic attempts. Main statistics use host in-memory measurements only; separate GPU profiles appear only in Figure 6. The separate full preprocessing-v2 report contains the broader measurement record; previous reports remain available as historical artifacts.')
p('Source: hls4ml/optimize/runs/final_benchmarks_gpu_preprocess_v2_20261021_030038. Every source-manifest hash is checked; selected statistics are recomputed from trial data. All 60 selected implementation/input cells have 200 measured trials. Fresh measurements use the existing FPGA images and the preprocessing-v2 software fix. Later runtime experiments are excluded.',True)
p('Reproduction: run <b>ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/2026-10-21_focused_hls4ml_checker_gpu_preprocess_v2/build_report.py</b> from the repository root. Figures are exported as SVG, PNG, and PDF; data/ contains statistics, ratios, phases, profiles, and representative timelines. The setup paths are also exported individually for presentations.',True)

title('Appendix A1 · Real-bitstream latency')
p('Eight real files, ordered by size. Input identity and size are listed on the final appendix page. This is the same host in-memory timing boundary used in the main figures.')
plot('A1_real_latency',400)
p('Each group compares FPGA_HLS4ML, GPU_HOST, and GPU_P2P for exactly the same file. Labels show medians; black ticks show p95. Different files also have different sizes, so this is not a controlled experiment isolating the effect of bitstream contents.')
p('Keep these measured values distinct from the synthetic-size guide curves. Host/GPU runtime effects can make latency non-monotonic between files; the evidence does not prove that real bitstream contents inherently require more computation.',True)

title('Appendix A2 · Real-bitstream FPGA speedup')
plot('A2_real_speedup_bars',400)
p('For each file, speedup is the GPU path’s median divided by FPGA_HLS4ML’s median. Ratios above 1 favor the hls4ml-checker. All ratios use matching input files, timing scope, and the accepted host in-memory evidence.')
p('There is no speedup scatter plot in this report. The paired bars retain the direct per-file comparison and keep the two GPU baselines explicit.',True)

title('Appendix A3 · Real-bitstream latency by size')
plot('A3_real_latency_scatter',290)
p('Linear size axis; unconnected measured medians. R1–R8 identify the files below. No synthetic interpolation or fitted trend is overlaid.',True)
case_sources={}
for line in (ROOT/'cases.tsv').read_text().splitlines():
    if line and not line.startswith('#'):
        fields=line.split('\t');case_sources[fields[0]]=fields[2]
rr=[['ID','Bytes / MiB','Source identifier']]
for c in REAL:
    sourcepath=case_sources[c]
    short=sourcepath.split('/upload_dataset/')[-1] if '/upload_dataset/' in sourcepath else sourcepath.split('/jobs/')[-1]
    rr.append([RID[c],f'{CASE[c]:,} / {CASE[c]/2**20:.2f}',short])
table(rr,[35,118,354])

# Artifacts and verification metadata, with machine-readable values for every chart.
def writecsv(path,rows):
    with path.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
writecsv(DATA/'latency_statistics.csv',STATS);writecsv(DATA/'speedups.csv',SPEEDUPS);writecsv(DATA/'phase_means.csv',SEGMENTS)
savejson(DATA/'timelines.json',TIMELINES);savejson(DATA/'gpu_profiles.json',PROFILE_EXPORT)
savejson(DATA/'resources.json',{N[i]:S['resources'][i] for i in IDS[:3]})
savejson(DATA/'real_inputs.json',[dict(id=RID[c],case_id=c,input_bytes=CASE[c],source=case_sources[c]) for c in REAL])
savejson(DATA/'validation.json',dict(status='passed',source_hashes=len(VERIFIED),selected_cells=60,measured_trials=12000,excluded_warmups=True,statistics_reconciled=True,additive_intervals_verified=True,figure_count=len(FIGURES),timing_label='host in-memory'))
PDF=OUT/'focused_hls4ml_checker_report.pdf'
def footer(canvas,doc):
    canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#617184'));canvas.drawString(44,24,'hls4ml-checker · host in-memory · campaign 2026-10-21 / preprocessing-v2');canvas.drawRightString(A4[0]-44,24,str(doc.page));canvas.restoreState()
SimpleDocTemplate(str(PDF),pagesize=A4,leftMargin=44,rightMargin=44,topMargin=38,bottomMargin=40,title='Focused hls4ml-checker benchmarks',author='ML Deep Bitstream Inspection').build(STORY,onFirstPage=footer,onLaterPages=footer)
for rel,digest in OLD_HASHES.items():assert sha(OLD/rel)==digest,('Original report changed',rel)
savejson(OUT/'evidence_manifest.json',dict(campaign=str(ROOT),sources=VERIFIED,original_report_hashes=OLD_HASHES,generated={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='evidence_manifest.json' and '__pycache__' not in p.parts},planned_pages=PAGES))
print('PASS PDF generated; original report preserved:',PDF,flush=True)
