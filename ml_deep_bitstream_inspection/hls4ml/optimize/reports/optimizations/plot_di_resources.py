#!/usr/bin/env python3
"""Plot routed area and HLS module latency from the report's extracted evidence."""
from pathlib import Path
import json
import os
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir())/'di-report-matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE/'figures/D_I_resources'
OUT.mkdir(parents=True, exist_ok=True)
data = json.loads((HERE/'D_I_resource_evidence.json').read_text())
layers = data['per_layer_resource_latency']
NAVY, TEAL, ORANGE, BLUE = '#17324d', '#087f8c', '#db8735', '#5485ba'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                     'axes.spines.right':False,'axes.labelcolor':NAVY,'text.color':NAVY,
                     'xtick.color':NAVY,'ytick.color':NAVY,'pdf.fonttype':42})

def save(fig, name):
    for extension in ('png','pdf'):
        fig.savefig(OUT/f'{name}.{extension}', dpi=190, facecolor='white')
    plt.close(fig)

stages = []
for i in range(8):
    subset = [r for r in layers if r['stage']==i]
    stages.append({k:sum(r[k] for r in subset) for k in ['dsp','kernel_bram','fifo_bram','uram']})
fig,axes=plt.subplots(1,3,figsize=(8.5,6.23),sharey=True)
y=np.arange(8)
names=[f'Stage {i}' for i in range(7)]+['GAP + dense']
for ax,key,title,limit in zip(axes,['dsp','kernel_bram','uram'],['DSPs','BRAM tiles','URAM blocks'],[360,233,10.4]):
    values=np.array([s[key] for s in stages])
    if key=='kernel_bram':
        fifo=np.array([s['fifo_bram'] for s in stages])
        ax.barh(y,values,color=NAVY,label='Arithmetic / ROM')
        ax.barh(y,fifo,left=values,color=ORANGE,label='Output FIFOs')
        values=values+fifo
    else: ax.barh(y,values,color=TEAL if key=='dsp' else BLUE)
    for i,v in enumerate(values):ax.text(v+limit*.018,i,f'{v:g}',va='center',fontsize=10)
    ax.set_xlim(0,limit);ax.set_title(title,fontweight='bold',pad=13)
    ax.set_axisbelow(True);ax.grid(axis='x',alpha=.18)
axes[0].set_yticks(y,names);axes[0].invert_yaxis()
axes[1].legend(loc='upper center',bbox_to_anchor=(.5,-.075),frameon=False,fontsize=9)
fig.subplots_adjust(left=.17,right=.975,top=.89,bottom=.18,wspace=.28)
fig.suptitle('Routed resources by stage',fontsize=14,fontweight='bold',y=.985)
fig.text(.17,.008,'Stage = padding + convolution + activation + pooling, including producer FIFOs.',fontsize=9)
save(fig,'stage_resources')

fig,axes=plt.subplots(1,3,figsize=(8.5,9.28),sharey=True,gridspec_kw={'width_ratios':[1,1.05,1.55]})
y=np.arange(len(layers))
for ax in axes:
    for i in range(7):
        if i%2==0:ax.axhspan(i*4-.5,i*4+3.5,color='#edf3f7',zorder=0)
    ax.set_axisbelow(True);ax.grid(axis='x',alpha=.17)
    ax.tick_params(axis='y',length=0,labelsize=9)
dsp=np.array([r['dsp'] for r in layers])
bram=np.array([r['kernel_bram'] for r in layers]);fifo=np.array([r['fifo_bram'] for r in layers])
axes[0].barh(y,dsp,color=TEAL,height=.64)
axes[1].barh(y,bram,color=NAVY,height=.64)
axes[1].barh(y,fifo,left=bram,color=ORANGE,height=.64)
for i,r in enumerate(layers):
    if r['dsp']:axes[0].text(r['dsp']+6,i,str(r['dsp']),va='center',fontsize=8.5)
    total=r['kernel_bram']+r['fifo_bram']
    if total:axes[1].text(total+2,i,f'{total:g}',va='center',fontsize=8.5)
    lo,hi=r['latency_min_us'],r['latency_max_us']
    axes[2].plot([lo,hi],[i,i],color=BLUE,lw=3,solid_capstyle='round')
    axes[2].plot(hi,i,'o',color=TEAL,markersize=3.5)
axes[0].set_xlim(0,375);axes[0].set_xticks([0,150,300]);axes[0].set_title('Routed DSPs',fontsize=11,fontweight='bold')
axes[1].set_xlim(0,132);axes[1].set_xticks([0,50,100]);axes[1].set_title('Routed BRAM tiles',fontsize=11,fontweight='bold')
axes[2].set_xscale('log');axes[2].set_xlim(.002,500)
axes[2].set_xticks([.01,1,100],['0.01','1','100'])
axes[2].set_title('HLS latency (µs, log)',fontsize=11,fontweight='bold')
axes[0].set_yticks(y,[r['name'] for r in layers]);axes[0].invert_yaxis()
axes[0].set_ylim(len(layers)-.4,-.8)
fig.subplots_adjust(left=.17,right=.98,top=.945,bottom=.08,wspace=.28)
fig.text(.17,.035,'BRAM: dark = arithmetic / ROM; orange = producer output FIFO.',fontsize=9)
fig.text(.17,.013,'Latency: line = HLS min–max; dot = maximum. Concurrent modules: do not sum.',fontsize=9)
save(fig,'layer_resource_latency')

fig,axes=plt.subplots(2,1,figsize=(8.5,7.405))
conv=[r for r in layers if r['name'].startswith('conv') or r['name']=='output_dense']
memory=[r for r in layers if r['kernel_bram']+r['fifo_bram']>0]
for ax,subset,key,title in [(axes[0],conv,'dsp','DSP sharing: late layers are the clearest starting point'),
                            (axes[1],memory,'bram','BRAM reduction: early producer FIFOs dominate')]:
    ax.set_xscale('log');ax.set_xlim(.01,650);ax.grid(alpha=.19);ax.set_axisbelow(True)
    ax.set_xlabel('HLS module latency (µs, log scale) — not additive',fontsize=9)
    ax.set_title(title,loc='left',fontsize=11,fontweight='bold',pad=12)
    for r in subset:
        val=r['dsp'] if key=='dsp' else r['kernel_bram']+r['fifo_bram']
        lo,hi=r['latency_min_us'],r['latency_max_us']
        color=TEAL if key=='dsp' else ORANGE
        ax.plot([lo,hi],[val,val],color=color,alpha=.45,lw=2)
        ax.scatter([hi],[val],s=42,color=color,zorder=3)
        offset=(5,8)
        if key=='dsp' and r['name']=='conv5':offset=(5,-15)
        if key=='bram':
            # The atlas names every layer; label only the main opportunities here.
            if r['name'] not in {'conv0','pad_conv0','act0','conv2','conv3','conv4','conv5','conv6'}:
                continue
            offset={'conv2':(4,10),'conv3':(4,-15),'conv4':(4,9),
                    'conv5':(4,-15),'conv6':(-12,11),'pad_conv0':(-65,8)}.get(r['name'],offset)
        ax.annotate(r['name'].replace('output_dense','dense'),(hi,val),xytext=offset,textcoords='offset points',fontsize=8.5)
    ax.set_ylabel('Routed DSPs' if key=='dsp' else 'Routed BRAM tiles',fontsize=10)
    ax.set_ylim(-15 if key=='dsp' else -10,340 if key=='dsp' else 125)
axes[0].text(.018,322,'Higher area + shorter module latency → investigate sharing',fontsize=9,color=TEAL)
fig.subplots_adjust(left=.105,right=.985,top=.94,bottom=.08,hspace=.49)
save(fig,'optimization_opportunity')
print(f'Wrote 3 plot pairs to {OUT}')
