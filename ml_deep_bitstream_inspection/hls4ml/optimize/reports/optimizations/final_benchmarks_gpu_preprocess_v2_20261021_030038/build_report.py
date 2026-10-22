#!/usr/bin/env python3
"""Generate an offline, evidence-verified FPGA/GPU comparison. No hardware access.
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
CASES=sorted({r['case_id']:r['input_bytes'] for r in S['rows']}.items(),key=lambda x:(x[1],x[0]))
CASE=dict(CASES); REPS=[SYN[0],SYN[-1]]
ROWS={(r['iteration'],r['case_id'],r['scope']):r for r in S['rows']}
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':11,'axes.labelsize':9,'legend.fontsize':8,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':120,'savefig.dpi':210})
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

def curves(ax,ids,scope,key=None):
    for i in ids:
        xs=np.array([x/2**20 for x in SIZES]);ys=[med(i,c,scope,key) for c in SYN]
        ax.plot(xs,ys,'o-',color=C[i],label=N[i],lw=1.5,ms=4)
        ps=[pct(values(i,c,scope,key or ('file_e2e_ms' if scope=='file' else 'host_observed_ms')),95) for c in SYN]
        ax.plot(xs,ps,':',color=C[i],alpha=.8,lw=1)
        real=[c for c,n in CASES if c.startswith('real')]
        ax.scatter([CASE[c]/2**20 for c in real],[med(i,c,scope,key) for c in real],marker='x',s=22,color=C[i],alpha=.8)
        boundary=[c for c,n in CASES if c.startswith('smoke')]
        ax.scatter([CASE[c]/2**20 for c in boundary],[med(i,c,scope,key) for c in boundary],marker='v',s=35,facecolors='none',edgecolors=C[i],zorder=5)
    ax.set(xlabel='Raw input size (MiB)',ylabel='Latency (ms)');ax.set_xscale('log',base=2);ax.set_xticks([4,16,64,128],['4','16','64','128*'])

# Verify original evidence and every accepted summary cell before rendering.
assert S['status']=='passed'
manifest=json.loads((ROOT/'measurement_manifest.json').read_text())
for rel,digest in manifest['files'].items():
    assert sha(ROOT/rel)==digest,rel
    VERIFIED[rel]=digest
assert len(S['rows'])==180
for r in S['rows']:
    a,b=trials(r['iteration'],r['case_id'],r['scope'])
    for k,v in r.items():
        if isinstance(v,dict):STATS.append(dict(iteration=r['iteration'],label=N.get(r['iteration'],'Streaming closing repeat'),case_id=r['case_id'],scope=r['scope'],metric=k,cohort=r['cohort'],evidence=r['evidence'],**stat([float(x[k]) for x in b])))
print('PASS evidence:',len(VERIFIED),'hashes;',len(S['rows']),'accepted cells; medians/p95 reconciled',flush=True)

PHASE_COLORS={'File open/read':'#b7c7d4','Prepare/copy':'#8cc4c3','Handoff gap':'#d5d9df',
    'Setup/submission':'#8dabc0','Input-ready wait':'#557da5',
    'Framework work before publication':'#dda64c','Synchronization/publication':'#b483b5',
    'Completion wait':'#596476','Invocation to verdict':'#467e6c'}
def host_segments(i,c,scope,detailed=True):
    raw,_=trials(i,c,scope); result=[]
    for r in raw:
        r={k:int(v) if k.endswith('_ns') else v for k,v in r.items()}
        end=r['verdict_seen_ns'] if 'GPU' in i else r['host_verdict_seen_ns']
        h=r['host_start_ns'];pairs=[]
        if scope=='file':
            a=r['file_start_ns'];b=r['file_end_ns'] if 'GPU' in i else r['file_read_end_ns'];d=r['pack_end_ns'] if 'GPU' in i else r['prepare_end_ns']
            pairs=[('File open/read',a,b),('Prepare/copy',b,d),('Handoff gap',d,h)]
        if detailed and 'GPU' in i:
            pairs += [('Setup/submission',h,r['submit_ns']),('Input-ready wait',r['submit_ns'],r['input_ready_ns']),('Framework work before publication',r['input_ready_ns'],r['relay_start_ns']),('Synchronization/publication',r['relay_start_ns'],r['relay_end_ns']),('Completion wait',r['relay_end_ns'],end)]
        else:pairs += [('Invocation to verdict',h,end)]
        vals={k:(b-a)/1e6 for k,a,b in pairs};assert min(vals.values())>=0
        total=(end-(r['file_start_ns'] if scope=='file' else h))/1e6
        assert abs(sum(vals.values())-total)<1e-7
        result.append(vals)
    keys=list(result[0]);avg=[float(np.mean([x[k] for x in result])) for k in keys]
    for k,v in zip(keys,avg):SEGMENTS.append(dict(iteration=i,label=N[i],case_id=c,scope=scope,phase=k,mean_ms=v))
    return keys,avg

def stack(ax,ids,c,scope,detailed):
    left=np.zeros(len(ids));keys=None
    for j,i in enumerate(ids):
        kk,v=host_segments(i,c,scope,detailed)
        if keys is None:keys=kk;matrix=[]
        assert kk==keys;matrix.append(v)
    matrix=np.array(matrix)
    for k,key in enumerate(keys):
        ax.barh(range(len(ids)),matrix[:,k],left=left,label=key,color=PHASE_COLORS[key],height=.55);left+=matrix[:,k]
    for j,total in enumerate(left):ax.text(total,j,f' {total:.2f}',va='center',fontsize=8)
    ax.set_yticks(range(len(ids)),[SHORT[i] for i in ids]);ax.invert_yaxis();ax.set_xlabel('Mean elapsed time (ms)');ax.set_xlim(0,max(left)*1.16);ax.set_title(case_label(c));return keys

# 01: latency overview.
f,ax=axes_grid(2,1,size=(9,7))
for a,scope in zip(ax.flat,['resident','file']):curves(a,IDS,scope);a.set_title('Host in-memory input' if scope=='resident' else 'Warm-cache file-inclusive');a.legend(loc='upper left',ncol=2)
figure('01_latency_overview',f)
# 02: GPU breakdowns, host in-memory and file separately.
for scope in ['resident','file']:
    f,ax=axes_grid(2,2,size=(10,6.2))
    for a,c in zip(ax.flat,SYN):stack(a,IDS[3:],c,scope,True)
    handles,labels=ax.flat[0].get_legend_handles_labels();f.legend(handles,labels,loc='outside lower center',ncol=2,fontsize=8)
    figure('02_gpu_'+scope+'_breakdown',f)

# GPU timelines: host and FPGA tracks, mapped from the same trial calibration block.
@lru_cache(None)
def gpu_calibration(path):return [json.loads(x) for x in (Path(path).parent/'calibration.jsonl').read_text().splitlines()]
def gpu_timeline(ax,i,c):
    raw,ds=trials(i,c,'resident');target=med(i,c,'resident');r=min(raw,key=lambda r:abs((r['verdict_seen_ns']-r['host_start_ns'])/1e6-target))
    block=next(b for b in gpu_calibration(ROWS[i,c,'resident']['evidence']) if b['case_id']==c and b['scope']=='resident' and b['first_trial']<=r['trial']<=b['last_trial'])
    mapped,_=clock_model(block['samples']);h=r['host_start_ns'];intervals=[]
    def host(k):return (r[k]-h)/1e6
    def fp(k):return (sum(mapped(r['csr_'+str(k)]))/2-h)/1e6
    for label,a,b,y,col in [('Setup','host_start_ns','submit_ns',0,'#8dabc0'),('Input ready','submit_ns','input_ready_ns',1,'#557da5'),('Framework','input_ready_ns','relay_start_ns',2,'#dda64c'),('Sync/publication','relay_start_ns','relay_end_ns',3,'#b483b5'),('Host completion','relay_end_ns','verdict_seen_ns',4,'#596476')]:intervals.append((label,host(a),host(b),y,col,'host'))
    intervals.append(('FPGA reception',fp(8),fp(9),5,'#087e8b','fpga'))
    if i==IDS[4]:
        intervals += [('P2P forwarding',fp(18),fp(19),6,'#7752a5','fpga'),('Autonomous polling',fp(38),fp(41),7,'#c28350','fpga')]
    for label,a,b,y,col,clock in intervals:
        ax.barh(y,b-a,left=a,height=.62,color=col)
        if clock=='fpga':
            keys=[(8,9)] if y==5 else [(18,19)] if y==6 else [(38,41)]
            for k in keys[0]:
                lo,hi=mapped(r['csr_'+str(k)]);ax.plot([(lo-h)/1e6,(hi-h)/1e6],[y,y],color='black',lw=2)
        TIMELINES.append(dict(iteration=i,case_id=c,trial=r['trial'],label=label,start_ms=a,end_ms=b,clock=clock,evidence=ROWS[i,c,'resident']['evidence']))
    ax.set_yticks(range(len(intervals)),[x[0] for x in intervals],fontsize=8);ax.invert_yaxis();ax.set_xlabel('Time from host invocation (ms)')
    ax.set_title(N[i]+' · '+case_label(c)+f'\nTrial {r["trial"]}; E2E {host("verdict_seen_ns"):.3f} ms',fontsize=10)
    ax.set_xlim(left=0)
f,ax=axes_grid(2,2,size=(10,7))
for a,(i,c) in zip(ax.flat,[(i,c) for c in REPS for i in IDS[3:]]):gpu_timeline(a,i,c)
figure('03_gpu_timelines',f)
# Device profiles.
f,ax=axes_grid(2,2,size=(9,6.5))
for row,phase in enumerate(['gpu_preprocessing','gpu_inference']):
    for col,metric in enumerate(['kernel_sum_ms','device_span_ms']):
        a=ax[row,col]
        for i in IDS[3:]:
            rows=[next(x for x in S['gpu_device_profiles'][i] if x['case_id']==c and x['phase']==phase) for c in SYN]
            a.plot(np.array(SIZES)/2**20,[x[metric]['median'] for x in rows],'o-',color=C[i],label=N[i])
            a.plot(np.array(SIZES)/2**20,[x[metric]['p95'] for x in rows],':',color=C[i])
            if metric=='device_span_ms':a.plot(np.array(SIZES)/2**20,[x['host_synchronized_phase_ms']['median'] for x in rows],'--',color=C[i],alpha=.65)
        a.set(title=phase.replace('gpu_','').title()+' · '+('kernel sum' if col==0 else 'elapsed spans'),xlabel='Raw input (MiB)',ylabel='Profiled duration (ms)');a.set_ylim(bottom=0);a.legend()
figure('04_gpu_profiles',f)
# P2P metrics.
f,ax=axes_grid(2,2,size=(9,6))
for i,key,label in [(IDS[3],'host_to_gpu_ms','Host → GPU copy'),(IDS[4],'forwarding_ms','FPGA → GPU forwarding')]:
    vals=[med(i,c,'resident',key) for c in SYN];xx=np.array(SIZES)/2**20
    ax[0,0].plot(xx,vals,'o-',color=C[i],label=label)
    ax[0,1].plot(xx,np.array(SIZES)/np.array(vals)/1e6,'o-',color=C[i],label=label)
for a,key,title in [(ax[1,0],'poll_window_ms','Autonomous polling window'),(ax[1,1],'poll_requests','Polling requests')]:
    a.plot(xx,[med(IDS[4],c,'resident',key) for c in SYN],'o-',color=C[IDS[4]])
    a.plot(xx,[pct(values(IDS[4],c,'resident',key),95) for c in SYN],':',color=C[IDS[4]]);a.set_title(title)
for a in ax.flat:a.set_xlabel('Raw input (MiB)')
ax[0,0].set(title='Measured transfer intervals',ylabel='Median duration (ms)');ax[0,1].set(title='Effective raw-payload throughput',ylabel='GB/s (decimal)');ax[1,0].set_ylabel('Duration (ms)');ax[1,1].set_ylabel('64-byte reads per trial');ax[0,0].legend();ax[0,1].legend()
figure('05_p2p_transport_polling',f)
# FPGA comparison and speedups.
f,ax=axes_grid(2,2,size=(9,6))
for col,scope in enumerate(['resident','file']):
    curves(ax[0,col],IDS[:3],scope);ax[0,col].set_title(('Host in-memory' if scope=='resident' else 'File-inclusive')+' latency')
    for i in IDS[:3]:ax[1,col].plot(np.array(SIZES)/2**20,[med(IDS[1],c,scope)/med(i,c,scope) for c in SYN],'o-',color=C[i],label=N[i])
    ax[1,col].axhline(1,color='black',lw=.8);ax[1,col].set(xlabel='Raw input (MiB)',ylabel='Speedup vs Streaming',title=('Host in-memory' if scope=='resident' else 'File-inclusive')+' speedup')
ax[0,0].legend(fontsize=7);figure('06_fpga_comparison',f)
# FPGA native timeline; avoids cross-clock alignment.
f,ax=axes_grid(2,1,size=(9,7))
for a,c in zip(ax.flat,REPS):
    ticks=[];labs=[]
    for j,i in enumerate(IDS[:3]):
        raw,ds=trials(i,c,'resident');d=min(ds,key=lambda d:abs(float(d['host_observed_ms'])-med(i,c,'resident')))
        ints=[('Reception',float(d['raw_first_ms']),float(d['raw_last_ms']),'#557da5'),('Pixel production',float(d['pp_first_ms']),float(d['pp_last_ms']),'#8cc4c3'),('CNN interval',float(d['cnn_first_ms']),float(d['logit_ms']),'#dda64c')]
        for k,(lab,start,end,col) in enumerate(ints):
            y=j*4+k;a.barh(y,end-start,left=start,color=col,height=.65);ticks.append(y);labs.append(SHORT[i].replace('\n',' ')+' · '+lab)
            TIMELINES.append(dict(iteration=i,case_id=c,trial=d['trial'],label=lab,start_ms=start,end_ms=end,clock='fpga_relative_arm',evidence=ROWS[i,c,'resident']['evidence']))
    a.set_yticks(ticks,labs,fontsize=8);a.invert_yaxis();a.set(xlabel='Time from FPGA arm (ms)',title=case_label(c));a.set_xlim(left=0)
figure('07_fpga_timelines',f)
f,ax=axes_grid(2,2,size=(9,6))
for a,key,title in zip(ax.flat,['preprocess_ms','inference_ms','overlap_ms','inference_tail_ms'],['Reception/preprocessing interval','CNN first-input-to-score interval','Pixel-production/CNN overlap','Tail after last preprocessed pixel']):
    for i in IDS[:3]:a.plot(np.array(SIZES)/2**20,[med(i,c,'resident',key) for c in SYN],'o-',color=C[i],label=N[i])
    a.set(title=title,xlabel='Raw input (MiB)',ylabel='Median duration (ms)')
ax[0,0].legend(fontsize=7);figure('08_fpga_intervals',f)
# Dedicated OPT6 / GPU_HOST comparison.
f,ax=axes_grid(2,2,size=(9,6))
f.get_layout_engine().set(wspace=.12)
for col,scope in enumerate(['resident','file']):
    curves(ax[0,col],[IDS[2],IDS[3]],scope);ax[0,col].set_title(('Host in-memory' if scope=='resident' else 'File-inclusive')+' latency');ax[0,col].legend(fontsize=7)
    for typ,marker in [('synthetic','o'),('real','x'),('smoke','v')]:
        cases=[c for c,n in CASES if c.startswith(typ)]
        ax[1,col].plot([CASE[c]/2**20 for c in cases],[med(IDS[3],c,scope)/med(IDS[2],c,scope) for c in cases],marker+('-' if typ=='synthetic' else ''),color=C[IDS[2]],label='Boundary' if typ=='smoke' else typ.title(),fillstyle='none' if typ=='smoke' else 'full')
    ax[1,col].axhline(1,color='black',lw=.8);ax[1,col].set(xlabel='Raw input (MiB)',ylabel='GPU_HOST / FPGA latency',title='Resource-optimized streaming speedup');ax[1,col].legend()
figure('09_optimized_vs_gpu_host',f)
f,ax=axes_grid(2,2,size=(10,6))
for a,c in zip(ax.flat,SYN):stack(a,[IDS[2],IDS[3]],c,'file',False)
h,l=ax.flat[0].get_legend_handles_labels();f.legend(h,l,loc='outside lower center',ncol=2)
figure('10_optimized_vs_gpu_file_breakdown',f)
# Resources, fixed denominator secondary axes.
f,ax=axes_grid(3,2,size=(9,8))
for a,key,title in zip(ax.flat,['BRAM_tiles','DSP','LUT','FF','URAM'],['BRAM tiles','DSPs','LUTs','Flip-flops','URAM blocks']):
    cap=S['resources'][IDS[0]]['capacity'][key];vals=[S['resources'][i]['wrapper'][key] for i in IDS]
    a.bar(range(5),vals,color=[C[i] for i in IDS]);a.set_xticks(range(5),['Buffering','Streaming','Resource-opt.\nstreaming','GPU_HOST','GPU_P2P'],rotation=18,fontsize=7);a.set(title=title,ylabel='Routed wrapper count')
    a.set_ylim(0,max(vals)*1.28 if max(vals)>0 else 1)
    sec=a.secondary_yaxis('right',functions=(lambda x,cap=cap:x/cap*100,lambda x,cap=cap:x*cap/100));sec.set_ylabel('Device utilization (%)',fontsize=8)
    for k,v in enumerate(vals):a.text(k,v,f'{v:g}\n{v/cap*100:.2f}%',ha='center',va='bottom',fontsize=7)
ax.flat[-1].axis('off');ax.flat[-1].text(0,1,'Scope: routed user wrapper\nIncludes wrapper interfaces and ILA.\n\nGPU variants also require an MI210;\nits resources are not included here.\n\nResource-opt. = Resource-optimized\nstreaming (abbreviation on this page).',va='top',fontsize=10)
figure('11_resources',f)
# Drift and boundary.
f,ax=axes_grid(2,1,size=(9,6.7))
for scope,col in [('resident','#087e8b'),('file','#cf6a19')]:
    rr=[x for x in S['baseline_drift'] if x['scope']==scope];ax[0,0].scatter([CASE[x['case_id']]/2**20 for x in rr],[x['relative_change']*100 for x in rr],label='Host in-memory' if scope=='resident' else 'File-inclusive',color=col,s=25)
ax[0,0].axhline(5,color='red',ls='--');ax[0,0].axhline(-5,color='red',ls='--');ax[0,0].set(xlabel='Raw input (MiB)',ylabel='Closing/opening change (%)',title='Accepted baseline drift');ax[0,0].legend()
bound=[c for c,n in CASES if c.startswith('smoke')]
for j,i in enumerate(IDS):ax[1,0].plot(range(3),[med(i,c,'resident') for c in bound],'o-',color=C[i],label=N[i])
ax[1,0].set_xticks(range(3),[f'{CASE[c]:,} B' for c in bound]);ax[1,0].set(ylabel='Host in-memory median (ms)',title='Preprocessing boundary: all three workloads');ax[1,0].legend(ncol=2,fontsize=7)
figure('12_validation_boundary',f)
print('PASS figures rendered',flush=True)
# PDF: fixed page structure with explicit interpretations and provenance.
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='ReportTitle',fontName='Helvetica-Bold',fontSize=20,leading=24,textColor=colors.HexColor('#17324d'),spaceAfter=14))
styles.add(ParagraphStyle(name='BodyR',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=8))
styles.add(ParagraphStyle(name='SmallR',fontName='Helvetica',fontSize=8,leading=10,spaceAfter=5))
styles.add(ParagraphStyle(name='TableR',fontName='Helvetica',fontSize=7.4,leading=9))
STORY=[];PAGES=[]
def p(text,small=False):STORY.append(Paragraph(text,styles['SmallR' if small else 'BodyR']))
def title(text):
    if PAGES:STORY.append(PageBreak())
    PAGES.append(text);STORY.append(Paragraph(text,styles['ReportTitle']))
def table(rows,widths=None):
    cells=[[Paragraph(escape(str(x)),styles['TableR']) for x in row] for row in rows]
    t=Table(cells,colWidths=widths or [507/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8eff5')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#17324d')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f7f9')]),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]));STORY.extend([t,Spacer(1,10)])
def plot(name,maxh=405):
    from PIL import Image as PILImage
    path=FIG/(name+'.png');w,h=PILImage.open(path).size;scale=min(507/w,maxh/h)
    STORY.append(Image(str(path),width=w*scale,height=h*scale));STORY.append(Spacer(1,9))
def num(v):return f'{v:.3f}'
def ratio(a,b,c,scope='resident'):return med(a,c,scope)/med(b,c,scope)
small=SYN[0];large=SYN[-1]
boundary=next(c for c,n in CASES if n==4194240)
res0=S['resources'][IDS[1]]['wrapper'];res6=S['resources'][IDS[2]]['wrapper']
reduction=lambda k:(1-res6[k]/res0[k])*100

title('FPGA/GPU inspection benchmarks')
p('<b>Final campaign: 21 October 2026 · Report: 21 October 2026</b>')
p('This report compares five implemented inspection paths on the same host: Buffering, Streaming, Resource-optimized streaming, GPU_HOST, and GPU_P2P. The GPU paths use the original FP32 model; FPGA paths use the quantized W8A8 model. These are system comparisons, not equal-precision kernel comparisons.')
p(f'<b>Main result.</b> Resource-optimized streaming reduces routed wrapper BRAM by {reduction("BRAM_tiles"):.2f}% and DSPs by {reduction("DSP"):.2f}% versus Streaming. Its host in-memory latency at 4 MiB is {num(med(IDS[2],small,"resident"))} ms, {(ratio(IDS[2],IDS[1],small)-1)*100:.2f}% above Streaming. GPU_HOST / checker latency ratios are {ratio(IDS[3],IDS[2],small):.2f}× at 4 MiB and {ratio(IDS[3],IDS[2],large):.2f}× at the largest frame; ratios above one favor the checker.')
p(f'<b>Boundary workload.</b> At 4,194,240 bytes, Resource-optimized streaming takes {med(IDS[2],boundary,"resident"):.3f} ms and GPU_HOST takes {med(IDS[3],boundary,"resident"):.3f} ms. Adjacent sizes exercise a different FPGA preprocessing path. This workload is retained in the full report and excluded from the focused report.')
table([['Variant','4 MiB host in-memory\nmedian / p95 (ms)','4 MiB file-inclusive\nmedian / p95 (ms)']]+[[N[i]]+[f'{med(i,small,scope):.3f} / {pct(values(i,small,scope,"file_e2e_ms" if scope=="file" else "host_observed_ms"),95):.3f}' for scope in ['resident','file']] for i in IDS],[175,166,166])
p(f'<b>P2P outcome.</b> GPU_P2P is slower than GPU_HOST in this setup. At the largest frame, its host in-memory median is {med(IDS[4],large,"resident"):.3f} ms versus {med(IDS[3],large,"resident"):.3f} ms for GPU_HOST. The measured P2P forwarding interval is {med(IDS[4],large,"resident","forwarding_ms"):.3f} ms. Autonomous polling passed board admission; that establishes correctness, not a latency advantage.')
p(f'<b>Evidence:</b> {S["accepted_primary_measured_calls"]:,} primary measured calls, 6,000 closing-baseline calls, and {S["gpu_profile_calls"]} separate GPU profiling calls. Maximum accepted baseline drift: {max(abs(x["relative_change"]) for x in S["baseline_drift"])*100:.2f}%. Runtime revision: preprocessing-v2 only; exploratory later revisions are excluded.')
p('Reading guide: pages 3–7 explain GPU timing; pages 8–10 compare FPGA variants; pages 11–12 compare Resource-optimized streaming with GPU_HOST. Resources, validation, and complete tables follow.',True)

title('Measurement protocol and interpretation')
table([['Report label','Iteration / implementation'],['Buffering',IDS[0]+'; buffers all 65,536 pixels before CNN consumption'],['Streaming',IDS[1]+'; original CNN with streaming preprocessing'],['Resource-optimized streaming',IDS[2]+'; native FIFO profiling capacity 1024; conv3/4/5/6 reuse 72/72/288/288'],['GPU_HOST',IDS[3]+'; host sends input to GPU and FPGA; host relays GPU result'],['GPU_P2P',IDS[4]+'; FPGA forwards input to GPU and autonomously polls result mailbox']],[170,337])
p('<b>Machine:</b> hacc-gpu-u55c-01; U55C device2, PCIe 0000:81:00.0, serial XFL13BA4HVZYA; MI210 GPU0, PCIe 0000:03:00.0. Host thread pinned to CPU64/NUMA1; GPU is on NUMA0. FPGA link: PCIe Gen3 ×16. All comparisons use the same devices and 128 MiB frame allocation.')
p('<b>Workloads:</b> eight real bitstreams, four synthetic sizes, and three preprocessing boundary inputs. Each variant has 20 warmups and 200 measured trials per workload per scope. Each image passes 520 board-admission calls and a pilot. The sequence is Streaming → Buffering → Resource-optimized streaming → GPU_HOST → GPU_P2P → Streaming repeat.')
p('<b>Host in-memory:</b> prepared input invocation to host-observed verdict; excludes file reading, preparation, initial allocation, programming, and diagnostic CSR readback. <b>File-inclusive:</b> file open/read through preparation/copy to host-observed verdict, with a warm filesystem cache. Every call transfers the entire raw input.')
p('<b>Statistics:</b> solid lines show medians; dotted lines show p95 unless stated otherwise. Synthetic points are connected; real inputs use crosses and boundary cases use hollow triangles. The final synthetic point is 134,217,664 bytes (128 MiB minus a 64-byte header). Breakdown stacks show means of consecutive intervals, not sums of medians.')
p('<b>Interpretation limits:</b> streaming intervals overlap. FPGA CNN first-input-to-score includes input stalls. GPU diagnostic traces add profiling and explicit synchronization; they are not interchangeable with unprofiled E2E. Samples quantify within-run variation; no independent-day confidence interval or deployment-level accuracy equivalence is claimed.')

title('Latency across the complete workload range')
plot('01_latency_overview',470)
p('The curves compare the five measured implementations for matching inputs and timing scopes. Streaming overlaps input arrival and CNN work; Buffering exposes compute after preprocessing. The corrected GPU runtime can change which implementation leads at a given size. Read individual comparisons rather than extrapolating a universal winner.')
p('Real inputs are separate workloads, not interpolation checkpoints for the synthetic curve. The three nearly coincident boundary sizes are expanded on page 14; their p95 values are in the full tables. Dotted p95 curves apply to synthetic inputs and describe tail latency, not confidence bands.',True)

title('GPU paths: additive elapsed-time breakdowns')
plot('02_gpu_resident_breakdown',265)
plot('02_gpu_file_breakdown',265)
p('Top: host in-memory; bottom: warm-cache file-inclusive. Each stack sums exactly to its mean total. Setup includes mailbox initialization and control preparation. Input-ready wait includes transfer submission/waiting. Framework work ends when result publication begins. Synchronization/publication can include outstanding model work, score conversion, and transport; it is not a pure result-DMA measurement.',True)
p('Tiny setup, handoff, and completion segments are retained even when visually narrow. Phase means and source references are exported in data/phase_means.csv.',True)

title('GPU execution timelines and overlap')
plot('03_gpu_timelines',465)
p('Each panel uses one actual host in-memory trial nearest its workload’s median E2E. Host phases and calibrated FPGA intervals share the host-invocation origin. Black endpoint marks show feasible clock-mapping bounds; these are usually smaller than the plotted line width. Exact trial IDs and intervals are exported.')
p('GPU_HOST submits its host-to-GPU copy and FPGA input transfer from the same host call; input-ready means the GPU copy completed, not necessarily that the FPGA accepted its final byte. In P2P, forwarding and reception overlap. FPGA polling overlaps GPU/framework work and publication; adding the polling window to these phases would double-count elapsed time.')
p('The host-to-GPU HIP copy duration is reported separately on page 7: its host-aligned start was not recorded, so no artificial start time is drawn here.',True)

title('GPU preprocessing and inference diagnostics')
plot('04_gpu_profiles',450)
p('Left: sum of attributed GPU kernel durations. Right: first-to-last-kernel span, with synchronized host-phase median dashed. Twenty diagnostic calls per workload/path are separate from primary measurements. Kernel counts come from the new trace tables; preprocessing uses FP32 gather on GPU.')
p('Kernel sums exclude copies and gaps; the device span can contain both. This revision removes the confirmed CPU uint8-gather fallback by casting bytes to FP32 before sampling. Trace checks reject input/index copies to CPU GatherV2. Diagnostic output materialization remains outside the main measurement protocol.')
p('These profiles cannot partition an unprofiled E2E bar into exact preprocessing and inference fractions. Profiling phases were explicitly synchronized; first-use effects and profiling overhead can affect their p95 values. No profiled call is included in headline E2E statistics.',True)

title('P2P transport and autonomous polling')
plot('05_p2p_transport_polling',440)
p(f'At the largest input, GPU_P2P forwards data in {med(IDS[4],large,"resident","forwarding_ms"):.3f} ms; the GPU_HOST HIP copy interval is {med(IDS[3],large,"resident","host_to_gpu_ms"):.3f} ms. Effective bandwidth divides raw payload bytes by the median interval. These are different transport boundaries: P2P includes the FPGA forwarding path; the host-copy interval is measured by HIP events.')
p('The autonomous polling window starts with FPGA polling and ends when the result payload arrives. It includes waiting for the GPU verdict; it is not isolated polling overhead. Each request reads 64 bytes. Request counts and durations describe observed traffic, not GPU compute utilization.')
p('Correctness evidence includes 26 deliberately delayed publications during 520-call P2P admission, repeated autonomous polls, and a quiescent polling engine at completion. No poll-engine error was accepted. Cross-root/NUMA topology is documented, but these measurements do not isolate which hardware mechanism causes the transfer penalty.',True)

title('Buffering, Streaming, and resource optimization')
plot('06_fpga_comparison',440)
p('Speedup is Streaming latency divided by the compared variant’s latency. Above 1 means faster than Streaming; below 1 means slower. Median speedups are ratios of medians from independent runs, not paired per-trial ratios.')
p(f'At 4 MiB, Streaming is {ratio(IDS[0],IDS[1],small):.2f}× faster than Buffering for host in-memory input. At the largest frame it is {ratio(IDS[0],IDS[1],large):.2f}× faster. Resource-optimized streaming adds {(med(IDS[2],small,"resident")-med(IDS[1],small,"resident"))*1000:.1f} µs at 4 MiB and {(med(IDS[2],large,"resident")-med(IDS[1],large,"resident"))*1000:.1f} µs at the largest frame.')
p('Small file-inclusive differences should not be interpreted as hardware wins: file read/copy variability can be larger than the FPGA invocation difference. The baseline repeat and rechecks constrain drift but do not remove all host variability.',True)

title('How streaming hides the CNN interval')
plot('07_fpga_timelines',470)
p('Timelines use actual host in-memory trials nearest the median total. All lanes on this page use the FPGA clock, relative to arm; no host/FPGA alignment is needed. Pixel production starts at the first output pixel. Reception/preprocessing can begin earlier.')
p('Buffering waits for the complete input and pixel frame before CNN consumption. Streaming begins consumption early, hiding much of the CNN interval behind input arrival. Resource-optimized streaming preserves that overlap. These are observed timelines: the CNN lane includes periods waiting for incoming pixels.')

title('FPGA pipeline intervals across input sizes')
plot('08_fpga_intervals',455)
p('The reception/preprocessing interval runs from first raw input acceptance to last produced pixel. The CNN interval runs from first consumed pixel to score. The overlap metric covers the intersection of pixel production and CNN execution. The tail runs from last produced pixel to FPGA verdict; it is not standalone CNN compute.')
p('At large inputs, a long streaming CNN interval mainly reflects its duration along the arriving stream. The exposed tail is much shorter than the full interval. Buffering retains an approximately fixed post-preprocessing CNN cost. FIFO pressure and input stalls can change observed phase lengths without causing failure.')
p('These four quantities have different boundaries and overlap. They are plotted as separate curves rather than summed into a misleading total.',True)

title('Resource-optimized streaming versus GPU_HOST')
plot('09_optimized_vs_gpu_host',450)
p(f'At 4 MiB, Resource-optimized streaming achieves {ratio(IDS[3],IDS[2],small):.2f}× host in-memory speedup and {ratio(IDS[3],IDS[2],small,"file"):.2f}× file-inclusive speedup versus GPU_HOST. At the largest frame, the speedups are {ratio(IDS[3],IDS[2],large):.2f}× and {ratio(IDS[3],IDS[2],large,"file"):.2f}×, respectively.')
p(f'At the slow boundary, the GPU_HOST / FPGA latency ratio is {ratio(IDS[3],IDS[2],boundary):.3f}. Adjacent sizes must be interpreted separately; do not interpolate across the FPGA preprocessing discontinuity.')
p('The GPU_HOST/FPGA latency ratio uses matching input bytes and timing scope. A value above 1 favors Resource-optimized streaming. Solid synthetic curves and real-input crosses show how the advantage changes with workload size; p95 latency remains visible in the upper panels.')
p('The comparison includes the implemented TensorFlow runtime, transfers, and completion path. It does not predict an ideal fused GPU implementation, and it does not establish equal classification accuracy for FP32 and W8A8.',True)

title('Where the FPGA/GPU_HOST difference is spent')
plot('10_optimized_vs_gpu_file_breakdown',410)
p('The same additive file-time boundaries are used for both systems: file open/read, host preparation/copy, handoff gap, and invocation to host-observed verdict. Means are plotted so all segments sum exactly. Initial allocation and diagnostic readback remain outside the measured endpoint.')
p('At large sizes, file read and preparation costs dilute the system-level effect of faster inference. At small sizes, the invocation segment contributes more strongly to the FPGA advantage. Apparent differences in file segments are measured host effects; they are not attributable to the FPGA optimization itself.')
p('For the GPU invocation subphases, refer to page 4. For FPGA overlap inside invocation, refer to pages 9–10. Combining their overlapping internal intervals with this outer stack would double-count time.',True)

title('Resource savings and device utilization')
plot('11_resources',475)
p(f'Resource-optimized streaming changes wrapper BRAM from {res0["BRAM_tiles"]:g} to {res6["BRAM_tiles"]:g} tiles (−{reduction("BRAM_tiles"):.2f}%), DSPs from {res0["DSP"]:g} to {res6["DSP"]:g} (−{reduction("DSP"):.2f}%), and URAM from 11 to 0. BRAM device utilization falls from {res0["BRAM_tiles"]/2016*100:.2f}% to {res6["BRAM_tiles"]/2016*100:.2f}%; DSP utilization falls from {res0["DSP"]/9024*100:.2f}% to {res6["DSP"]/9024*100:.2f}%.')
p('Bars and right axes describe the routed user wrapper, including interfaces and ILA. Full-design counts include shell overhead and appear on page 18. GPU-side FPGA resource savings do not account for the MI210’s compute, memory, power, or cost.',True)

title('Validation, drift, and boundary workloads')
plot('12_validation_boundary',420)
p(f'Maximum accepted closing-baseline drift is {max(abs(x["relative_change"]) for x in S["baseline_drift"])*100:.2f}%. Any flagged workloads are remeasured across all variants at the original allocation capacity; evidence and cohorts identify every accepted comparison. Rejected measurements are preserved.')
p('The boundary panel shows a repeatable latency discontinuity, not a correctness failure: at 4,194,240 bytes, Streaming and Resource-optimized streaming spend about 16.777 ms in preprocessing; at 4,194,241 bytes they return to approximately 1.1 ms host in-memory E2E. GPU paths do not show the same discontinuity. Isolating the implementation cause requires separate investigation.')
p('Accepted rows explicitly identify their source attempt and cohort. No warmup, rejected attempt, or diagnostic profiling call enters headline latency distributions. The new campaign does not reuse old latency samples.')
p('FPGA board scores match quantized references exactly. GPU scores match CPU FP32 references within 1e-4 absolute/relative tolerance, with exact verdicts. The 520-call per-image admission, timestamp gates, and file hashes passed; these are execution checks, not a new held-out classification accuracy study.',True)

for scope,titletext in [('resident','Complete host in-memory latency table'),('file','Complete file-inclusive latency table')]:
    title(titletext)
    p('Each cell: median / p95 in milliseconds; 200 measured trials after 20 warmups. B = boundary, R = real, S = synthetic. Labels are abbreviated only in this dense table: Resource-opt. streaming = Resource-optimized streaming.',True)
    head=['Input bytes / type','Buffering','Streaming','Resource-opt. streaming','GPU_HOST','GPU_P2P']
    rr=[head]
    for c,n in CASES:
        vals=[]
        for i in IDS:
            key='host_observed_ms' if scope=='resident' else 'file_e2e_ms';a=values(i,c,scope,key)
            vals.append(f'{np.median(a):.3f} / {pct(a,95):.3f}')
        rr.append([f'{n:,} / '+('B' if c.startswith('smoke') else 'R' if c.startswith('real') else 'S')]+vals)
    table(rr,[97,82,82,82,82,82])
    p('Host in-memory input starts at the host invocation. File-inclusive timing includes warm-cache open/read and preparation. Results are selected by case ID, scope, and accepted evidence path, not by taking the newest attempt blindly.')
    if scope=='file':p('All rows identify their accepted cohort in the exported statistics. This campaign passed the closing-baseline drift gate without requiring a recheck.' if not S.get('recheck') else 'Flagged workloads were rechecked across all variants; source cohorts are recorded explicitly.')

title('GPU profiling detail and timestamp definitions')
p('Profile table: 4 MiB and largest frame, median / p95 (ms), 20 synchronized diagnostic trials per row. Full all-workload profile statistics are exported in data/gpu_profiles.json.',True)
rr=[['Path / size / phase','Kernel sum','Device span','Host synchronized']]
for i in IDS[3:]:
    for c in REPS:
        for phase in ['gpu_preprocessing','gpu_inference']:
            q=next(x for x in S['gpu_device_profiles'][i] if x['case_id']==c and x['phase']==phase)
            rr.append([N[i]+' / '+case_label(c)+' / '+phase.replace('gpu_','')]+[f'{q[k]["median"]:.3f} / {q[k]["p95"]:.3f}' for k in ['kernel_sum_ms','device_span_ms','host_synchronized_phase_ms']])
table(rr,[225,94,94,94])
table([['Quantity','Boundary / meaning'],['File E2E','File open/read start → host-observed verdict'],['Host in-memory E2E','Host invocation start → host-observed verdict'],['Host→GPU copy','HIP copy_begin → copy_end; device event duration, no aligned host start'],['P2P forwarding','FPGA CSR18 → CSR19; first/last forwarded payload timing'],['Polling window','CSR38 → CSR41; polling begins → result payload arrival'],['Ready→payload','CSR40 → CSR41; readiness response → payload arrival'],['FPGA preprocessing','First raw acceptance (CSR8) → last pixel produced (CSR11)'],['FPGA CNN interval','First CNN input (CSR12) → score (CSR14); includes stalls'],['GPU device span','First attributed kernel start → last attributed kernel end'],['Kernel sum','Sum of attributed kernel durations; excludes gaps'],['Publication host phase','Before score conversion/DLPack → completion of publication call']],[150,357])
p('FPGA timestamps are calibrated against 32 MMIO brackets before and after each block. GPU collectors use at most 20 trials per calibration block. GPU XPlane events are correlated with Trace markers and step_num in the trace time domain, not Python wall-clock timestamps.',True)

title('Resources, evidence, and reproduction')
p('Full-design routed utilization, including shell overhead. Each cell shows count / percentage of U55C capacity. GPU variants still require the external MI210.',True)
keys=['BRAM_tiles','DSP','LUT','FF','URAM'];rr=[['Variant','BRAM','DSP','LUT','FF','URAM']]
for i in IDS:
    d=S['resources'][i];rr.append([N[i]]+[f'{d["full_design"][k]:g} / {d["full_design"][k]/d["capacity"][k]*100:.2f}%' for k in keys])
table(rr,[137,74,74,74,74,74])
p('<b>Campaign:</b> hls4ml/optimize/runs/final_benchmarks_gpu_preprocess_v2_20261021_030038. Primary sources: summary.json, measurement_manifest.json, campaign.json, environment_manifest.json, and per-attempt observations/derived/calibration files. Bitstreams and runtimes remain pinned to the campaign identities.')
p(f'<b>Verification:</b> all {len(VERIFIED)} manifest hashes checked; {len(S["rows"])} accepted case/scope/iteration cells with 200 measured calls each. Every stored median/p95 is recomputed. Additive intervals match elapsed time. Timestamp and parity gates were enforced during collection.')
p('<b>Report exports:</b> figures/ contains SVG, PNG, and PDF plots. data/statistics.csv contains means, medians, p95, cohort, and evidence pointers. data/phase_means.csv contains additive breakdown values; data/timelines.json records selected trials and boundaries. data/gpu_profiles.json preserves all diagnostic profile summaries. evidence_manifest.json records source and generated-file hashes.')
p('<b>Reproduce:</b> from the repository root, run ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/final_benchmarks_gpu_preprocess_v2_20261021_030038/build_report.py. Uses the existing NumPy/Matplotlib environment and system ReportLab. Reads campaign data and writes only this report directory; no hardware access, rebuild, training, or benchmark replay.')
p('<b>Limits:</b> fixed variant order, one host session, one GPU and FPGA pairing, warm filesystem cache, and different inference precision. File rechecks address observed drift without proving complete stationarity. Resource totals are synthesis/route evidence; latency values are board measurements. No power, energy, cold-storage, concurrent-load, or accuracy-equivalence claims are made.')
p('Resource-optimized streaming retains reduced wrapper BRAM and DSP usage. Latency conclusions use the newly measured preprocessing-v2 runtime only. Subsequent GPU runtime experiments are archived separately and are not selected into this report.')

# Preserve the preprocessing-only runtime explanation and paired diagnostic evidence.
title('Preprocessing-v2: corrected device execution')
p('The earlier uint8 gather copied the entire raw input from GPU memory to CPU, sampled on CPU, then copied selected bytes back to GPU. This revision casts bytes to FP32 on GPU before gathering. Pixel semantics and model weights are unchanged. The largest input requires an approximately 512 MiB temporary tensor.')
v2=json.loads((ROOT/'diagnostics/preprocessing_validation/result.json').read_text())
comparisons=v2['comparisons']; caseids=sorted({x['case_id'] for x in comparisons},key=lambda c:int(c.split('_')[-1]))
f,a=plt.subplots(figsize=(9,3.5),layout='constrained');xx=np.arange(len(caseids))
for j,(rev,col) in enumerate([('previous','#89939f'),('gpu_preprocess_v2','#087e8b')]):
 vals=[next(x['median_ms'] for x in comparisons if x['case_id']==c and x['revision']==rev) for c in caseids]
 bars=a.bar(xx+(j-.5)*.35,vals,.35,label='Previous CPU fallback' if j==0 else 'GPU FP32 gather',color=col)
 a.bar_label(bars,fmt='%.2f',padding=3,fontsize=9)
a.set_xticks(xx,[case_label(c) for c in caseids]);a.set_ylabel('Preprocessing median (ms)');a.legend();a.grid(axis='y',alpha=.2)
figure('13_preprocessing_fix',f);plot('13_preprocessing_fix',260)
p('Paired software diagnostics: same GPU, inputs, and affinity; 20 warmups and 200 calls per size/revision. Timing includes synchronization and image output materialization. These values are not components to add to unprofiled end-to-end latency.')
p('GPU_BASELINE.pdf reports 0.165 ms preprocessing plus inference, but exact original samples/runtime and timing endpoints are not established. A separate investigation compares explicit scopes and records further runtime revisions. Those later results are deliberately excluded here.')
savejson(DATA/'preprocessing_fix_validation.json',v2)

# Export auditable source/statistic bundles.
def writecsv(path,rows):
    with path.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
writecsv(DATA/'statistics.csv',STATS);writecsv(DATA/'phase_means.csv',SEGMENTS)
savejson(DATA/'timelines.json',TIMELINES);savejson(DATA/'gpu_profiles.json',S['gpu_device_profiles'])
savejson(DATA/'accepted_summary.json',S)
savejson(DATA/'validation.json',dict(status='passed',verified_measurement_files=len(VERIFIED),accepted_cells=180,trials_per_cell=200,warmups_excluded=True,statistics_reconciled=True,additive_intervals_verified=True,scope='offline report validation; existing campaign board admission retained'))
PDF=OUT/'final_fpga_gpu_benchmark_report.pdf'
def footer(canvas,doc):
    canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#617184'));canvas.drawString(44,24,'FPGA/GPU inspection · accepted campaign 2026-10-21 / preprocessing-v2');canvas.drawRightString(A4[0]-44,24,str(doc.page));canvas.restoreState()
doc=SimpleDocTemplate(str(PDF),pagesize=A4,leftMargin=44,rightMargin=44,topMargin=38,bottomMargin=40,title='FPGA/GPU inspection benchmarks',author='ML Deep Bitstream Inspection',pageCompression=1)
doc.build(STORY,onFirstPage=footer,onLaterPages=footer)
savejson(OUT/'evidence_manifest.json',dict(campaign=str(ROOT),sources=VERIFIED,generated={str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='evidence_manifest.json' and '__pycache__' not in p.parts and 'review' not in p.parts},planned_pages=PAGES))
print('PASS PDF:',PDF,flush=True)
