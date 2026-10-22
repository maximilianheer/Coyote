#!/usr/bin/env python3
"""Read-only evidence report; optionally refresh when both build campaigns terminate."""
from pathlib import Path
import argparse, csv, json, re, sys, time, subprocess, os
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.graphics.shapes import Drawing, Rect, String, Line

OUT=Path(__file__).resolve().parent
REPO=OUT.parents[3]
TOOLS=REPO/'hls4ml/optimize/build_campaign'
sys.path.insert(0,str(TOOLS))
from fifo_sweep_results import artifact_summary, read
from resource_attribution import parse_hierarchy, attribute
from prepare import sha
RUNS=REPO/'hls4ml/optimize/runs'
SWEEP=RUNS/'native_fifo_sweep_20261011'
EXTRA=RUNS/'b2_conv34_rf72_20261012'
SELECTED=RUNS/'selected_builds_20261012'
PDF=OUT/'streaming_optimization_results_20261012.pdf'
NAVY=colors.HexColor('#17324d');TEAL=colors.HexColor('#087f8c');ORANGE=colors.HexColor('#d57d24');PALE=colors.HexColor('#edf3f7')

def load(p):return read(p) if p.exists() else {}
def short(ident):
    return {'OPT_3_BRAM_FIFO_A':'A / 100000','OPT_FIFO_A_P100000':'A / 100000','OPT_2_DSP_RESOURCES_B2':'B2','OPT_4_DSP_B2_CONV34_RF72':'B2 + conv3/4 RF72','OPT_1_STREAMING':'Streaming baseline','OPT_0_NONSTREAMING':'Non-streaming baseline','OPT_5_DSP_B2_RF72_RF288':'B2 + RF72/288'}.get(ident,ident.replace('OPT_FIFO_A_P','FIFO '))
def collect():
    queue=load(SWEEP/'status.json')
    config=read(SWEEP/'sweep.json');points=config['points']+[{'id':'OPT_4_DSP_B2_CONV34_RF72','job':str(EXTRA/'OPT_4_DSP_B2_CONV34_RF72/attempt_01')}]
    if (SELECTED/'campaign.json').exists():points=read(SELECTED/'campaign.json')['jobs']
    data={'as_of':datetime.now().astimezone().isoformat(timespec='seconds'),'builds':[],'profiles':[],'sources':[]}
    for point in points:
        job=Path(point['job']);ident=point['id'];state=load(job/'status.json');pstate=load(SWEEP/'points'/ident/'state.json')
        focused=load(SELECTED/'jobs'/(ident+'.json'))
        row={'id':ident,'label':short(ident),'job':str(job),'status':pstate.get('status',state.get('status','pending')),'stage':state.get('stage','pending')}
        if focused:row.update(status=focused.get('status','pending'),stage=focused.get('stage','pending'))
        if (job/'artifact_manifest.json').exists():
            artifact=artifact_summary(job);row.update(status='passed',stage='complete',artifact=artifact)
            data['sources'].append({'path':str(job/'artifact_manifest.json'),'sha256':sha(job/'artifact_manifest.json')})
        elif row['stage']=='complete':row['stage']='profile complete; build queued'
        elif not focused and pstate.get('status')=='profiled':row['stage']='profile complete; build queued'
        if ident in queue.get('queued',[]):row.update(status='queued',stage='profile complete; build queued')
        if row['status'] in {'failed','blocked'}:row['stage']=row['status'].upper()+' at '+row['stage']
        if (job/'validation.json').exists():row['validation']=load(job/'validation.json')['status']
        rtl=job/'rtl_validation/result.json'
        if rtl.exists():row['rtl']=read(rtl)
        if ident=='OPT_1_STREAMING' and 'rtl' not in row:
            prior=RUNS/'configurable_streaming_20261010/OPT_1_STREAMING/attempt_02'
            current=read(job/'config/iteration.json'); previous=read(prior/'config/iteration.json')
            assert all(current[k]==previous[k] for k in ['model','hls','interface','validation'])
            assert (prior/'tests/direct_pipe_tb.sv').read_bytes()==(job/'tooling/iteration_templates/direct_pipe_tb.sv').read_bytes()
            assert (prior/'tests/direct_sim.tcl').read_bytes()==(job/'tooling/iteration_templates/direct_sim.tcl').read_bytes()
            validation=read(prior/'validation.json')
            assert validation['status']=='passed' and validation['source_manifest_sha256']==sha(prior/'source_manifest.json')
            for name,digest in validation['evidence'].items():assert sha(prior/name)==digest
            row['rtl']=read(prior/'rtl_validation/result.json')
            row['rtl_source_note']='Matching earlier baseline validation (attempt_02); routed build still separate.'
            data['sources'].append({'path':str(prior/'rtl_validation/result.json'),'sha256':sha(prior/'rtl_validation/result.json')})
        buffer_report=job/'frame_buffer_validation/frame_buffer_utilization.rpt'
        if ident=='OPT_0_NONSTREAMING' and buffer_report.exists():
            match=re.search(r'\|\s*Block RAM Tile\s*\|\s*([\d.]+)',buffer_report.read_text())
            if match and 'PASS frame buffer BRAM inference:' in (job/'frame_buffer_synthesis.log').read_text():
                row['frame_buffer_bram_estimate']=float(match[1])
                data['sources'].append({'path':str(buffer_report),'sha256':sha(buffer_report)})
        data['builds'].append(row)
        profile=SWEEP/'points'/('OPT_FIFO_A_P100000' if ident=='OPT_3_BRAM_FIFO_A' else ident)/'profile.json'
        if profile.exists():
            p=read(profile)
            if p.get('profiling_depth'):data['profiles'].append({'id':ident,**p})
            data['sources'].append({'path':str(profile),'sha256':sha(profile)})
    # Historical measured reference: verify archived evidence and original routed reports.
    historical=REPO/'hls4ml/optimize/reports/2026-10-09_u55c02'
    sealed=read(historical/'file_manifest.json')
    for name in ['data/R_S/routed_resources.json','data/R_S/full.summary.csv','data/R_S/hardware/artifact_manifest.json']:
        source=historical/name
        assert sha(source)==sealed[name]['sha256'],name
        data['sources'].append({'path':str(source),'sha256':sha(source)})
    original=RUNS/'parallel_resume_20261009_1550/jobs/R_S'
    manifest=read(historical/'data/R_S/hardware/artifact_manifest.json');reports={}
    for name,item in manifest['files'].items():
        if name.endswith('.rpt'):
            source=original/name;assert sha(source)==item['sha256'],name
            reports[source.name]=source
            data['sources'].append({'path':str(source),'sha256':sha(source)})
    from worker import validate_timing_report
    validate_timing_report(reports['shell_timing_summary.rpt'])
    resources=attribute(reports['shell_utilization_hierarchical.rpt'].read_text(),reports['shell_utilization.rpt'].read_text(),'R_S')
    recorded=read(historical/'data/R_S/routed_resources.json')
    assert resources['wrapper']==recorded['wrapper'] and resources['full_design']==recorded['full_design']
    with (historical/'data/R_S/full.summary.csv').open() as f:host=list(csv.DictReader(f))
    data['builds'].append({'id':'R_S','label':'R_S (measured reference)','job':str(original),
        'status':'passed','stage':'Historical routed and board-tested reference',
        'artifact':{'resources':resources},'historical_reference':True,'host_measurements':host})
    data['terminal']=all(load(p).get('status') in {'passed','failed','blocked'} for p in [SELECTED/'primary.json',SELECTED/'nonstreaming.json'])
    return data

def layer_data(build,data):
    job=Path(build['job']);manifest=read(job/'artifact_manifest.json')
    path=next(job/p for p in manifest['files'] if p.endswith('shell_utilization_hierarchical.rpt'))
    rows=parse_hierarchy(path.read_text());kernel=next(p for p in rows if p.rsplit('/',1)[-1].startswith('conv_2d_cl_'))
    parent=kernel.rsplit('/',1)[0];groups=[{'DSP':0,'BRAM_tiles':0,'URAM':0} for _ in range(8)]
    for path,values in rows.items():
        if path.rsplit('/',1)[0]!=parent:continue
        name=path.rsplit('/',1)[-1]
        if name.startswith('start_for_'):continue
        match=re.search(r'(?:config|layer)(\d+)(?:_U0|_out_U)$',name)
        if not match:continue
        stage=min(7,max(0,(int(match[1])-2)//5))
        for k in groups[stage]:groups[stage][k]+=values[k]
    cnn=build['artifact']['resources']['components']['inference_and_publication']['resources']
    for k in groups[0]:assert sum(g[k] for g in groups)==cnn[k],(build['label'],k)
    latency=[]
    for i in range(7):
        paths=list((job/'cnn_wrapper_hls/solution1/syn/report').glob(f'conv_2d_cl*config{3+5*i}_s_csynth.xml'))
        assert len(paths)==1
        tree=ET.parse(paths[0]);v=tree.findtext('.//SummaryOfOverallLatency/Worst-caseLatency')
        latency.append(float(v)*4/1000 if v and v.isdigit() else None)
        data['sources'].append({'path':str(paths[0]),'sha256':sha(paths[0])})
    return groups,latency

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyR',fontName='Helvetica',fontSize=9,leading=13,spaceAfter=8))
styles.add(ParagraphStyle(name='SmallR',fontName='Helvetica',fontSize=7.5,leading=10,spaceAfter=6,wordWrap='CJK'))
styles.add(ParagraphStyle(name='HeadR',fontName='Helvetica-Bold',fontSize=19,leading=24,textColor=NAVY,spaceAfter=13))

def chart(labels,series,title,unit,height=215,capacity=None):
    d=Drawing(500,height);d.add(String(0,height-12,title,fontName='Helvetica-Bold',fontSize=10,fillColor=NAVY))
    left=42;bottom=38;top=height-60;plotw=410 if capacity else 442
    maximum=max([v for _,values in series for v in values if v is not None]+[1])*1.22
    d.add(String(left,top+12,'Count' if capacity else 'Latency (ms)',fontSize=7,fillColor=NAVY))
    if capacity:d.add(String(left+plotw,top+12,'Device utilization (%)',fontSize=7,textAnchor='end',fillColor=NAVY))
    for tick in range(5):
        val=maximum*tick/4;y=bottom+(top-bottom)*tick/4
        d.add(Line(left,y,left+plotw,y,strokeColor=colors.HexColor('#dce3e9'),strokeWidth=.4))
        d.add(String(left-5,y-2,f'{val:,.0f}' if maximum>10 else f'{val:.2f}',textAnchor='end',fontSize=6.5))
        if capacity:d.add(String(left+plotw+5,y-2,f'{100*val/capacity:.1f}%',fontSize=6.5))
    step=plotw/len(labels);width=min(33,step*.75/len(series));palette=[TEAL,ORANGE,colors.HexColor('#6a67a3')]
    for si,(name,values) in enumerate(series):
        color=palette[si%len(palette)]
        d.add(Rect(44+si*155,height-31,7,7,fillColor=color,strokeColor=None));d.add(String(55+si*155,height-30,name,fontSize=6.5))
        for i,value in enumerate(values):
            x=left+step*(i+.5)+(si-len(series)/2)*width
            if value is None:
                d.add(String(x+width*.45,bottom+5,'pending',fontSize=5.5,textAnchor='middle',fillColor=colors.grey));continue
            h=(top-bottom)*value/maximum
            d.add(Rect(x,bottom,width*.9,h,fillColor=color,strokeColor=None))
            label=(f'{value:,.0f}' if value==int(value) else f'{value:,.2f}') if capacity else f'{value:.5f}'
            d.add(String(x+width*.45,bottom+h+4,label,fontSize=6,textAnchor='middle'))
            if capacity:d.add(String(x+width*.45,bottom+h+12,f'{100*value/capacity:.2f}%',fontSize=6,textAnchor='middle'))
    for i,label in enumerate(labels):d.add(String(left+step*(i+.5),bottom-12,str(label),fontSize=6.5,textAnchor='middle'))
    d.add(String(0,5,unit,fontSize=6.5,fillColor=colors.HexColor('#52606d')))
    return d

def render():
    data=collect();story=[]
    baseline=next(b for b in data['builds'] if b['id']=='OPT_1_STREAMING')
    fifos=sorted([b for b in data['builds'] if b['id'].startswith('OPT_FIFO') or b['id']=='OPT_3_BRAM_FIFO_A'],key=lambda b:100000 if b['id']=='OPT_3_BRAM_FIFO_A' else int(b['id'].split('P')[-1]))
    bs=[b for b in data['builds'] if b['id'] in ['OPT_2_DSP_RESOURCES_B2','OPT_4_DSP_B2_CONV34_RF72','OPT_5_DSP_B2_RF72_RF288']]
    rs=next(b for b in data['builds'] if b['id']=='R_S')
    nonstream=next((b for b in data['builds'] if b['id']=='OPT_0_NONSTREAMING'),None)
    current=([nonstream] if nonstream else [])+[baseline]+fifos+bs
    ordered=[rs]+current
    built=[b for b in ordered if 'artifact' in b]
    capacity=built[0]['artifact']['resources']['capacity']
    assert all(b['artifact']['resources']['capacity']==capacity for b in built)
    def label(b):return b['label'].replace('R_S (measured reference)','R_S').replace('Streaming baseline','Baseline').replace('FIFO ','').replace('A / 100000','A 100k').replace('B2 + conv3/4 RF72','B2+72').replace('Non-streaming baseline','Nonstream').replace('B2 + RF72/288','B2+72/288')
    def value(b,key,scope='wrapper'):return b.get('artifact',{}).get('resources',{}).get(scope,{}).get(key)
    def fmt(v):return 'pending' if v is None else f'{v:,.0f}' if int(v)==v else f'{v:,.1f}'
    def percent(v,key):return 'pending' if v is None else f'{100*v/capacity[key]:.2f}%'
    def saving(b,key,reference=None):
        ref=value(baseline if reference is None else reference,key);v=value(b,key)
        return ('pending','pending') if ref is None or v is None else (fmt(ref-v),f'{100*(ref-v)/ref:.2f}%')
    def p(t,small=False):story.append(Paragraph(t,styles['SmallR' if small else 'BodyR']))
    def heading(t,new=False):
        if new:story.append(PageBreak())
        story.append(Paragraph(t,styles['HeadR']))
    def table(rows,widths):
        cells=[[Paragraph(escape(str(c)),styles['SmallR']) for c in row] for row in rows]
        t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT');t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('LINEBELOW',(0,0),(-1,0),1,TEAL)]));story.extend([t,Spacer(1,8)])
    heading('Optimization impact vs streaming baseline')
    p('Updated '+escape(data['as_of'])+'. '+('Campaigns terminated.' if data['terminal'] else 'Builds in progress; missing results are marked pending.'))
    p('<b>Two references:</b> R_S is the existing routed, board-tested streaming design. OPT_1_STREAMING regenerates the same intended model and preprocessing with the D_I interface and timestamps, matching the new candidates. Its routed result remains separate. No custom conv0 kernel is used.')
    p('<b>Interpretation:</b> reductions versus R_S are whole-variant comparisons, including integration differences. Reductions versus OPT_1_STREAMING isolate the configured optimization with matching instrumentation. Savings % uses the reference count; device utilization % uses U55C capacity.')
    heading('1. A and FIFO sweeps: BRAM savings')
    group=[baseline]+fifos;key='BRAM_tiles'
    table([['Variant','BRAM tiles','Device %','Saved tiles vs OPT_1','Saved % vs OPT_1']]+[[b['label'],fmt(value(b,key)),percent(value(b,key),key),*saving(b,key)] for b in group],[140,75,75,105,105])
    story.append(chart([label(b) for b in group],[('Routed wrapper BRAM',[value(b,key) for b in group])],'BRAM usage: matching baseline and FIFO variants','Left: BRAM tiles. Right: % of device BRAM. Bar labels show both.',200,capacity[key]))
    p('A is the 100000-depth sweep point. Profiling depth is the temporary profiling capacity, not the depth of every final FIFO. Logical FIFO storage is not substituted for routed BRAM usage.',True)
    if value(baseline,key) is None:p('<b>Measured against R_S:</b> A uses 152 versus 345 BRAM tiles: 193 fewer tiles, a 55.94% reduction. The comparison against OPT_1_STREAMING is pending routing; R_S is not substituted for that result.',True)
    heading('2. B series: DSP savings',True)
    group=[baseline]+bs;key='DSP'
    table([['Variant','DSPs','Device %','Saved DSPs vs OPT_1','Saved % vs OPT_1']]+[[b['label'],fmt(value(b,key)),percent(value(b,key),key),*saving(b,key)] for b in group],[140,75,75,105,105])
    p('Reuse factors for conv3 / conv4 / conv5 / conv6: baseline and R_S = 36 / 36 / 32 / 32; B2 = 36 / 36 / 144 / 144; B2+72 = 72 / 72 / 144 / 144; aggressive B2+72/288 = 72 / 72 / 288 / 288.',True)
    story.append(chart([label(b) for b in group],[('Routed wrapper DSPs',[value(b,key) for b in group])],'DSP usage: matching baseline and B variants','Left: DSP count. Right: % of 9024 device DSPs. Bar labels show both.',270,capacity[key]))
    p('B2 shares more multipliers in conv5/6. B2+72 also increases reuse in conv3/4. All B variants retain the baseline FIFO configuration; no B variant includes FIFO optimization A.')
    if value(baseline,key) is None:p('<b>Measured against R_S:</b> B2 uses 879 versus 1328 DSPs: 449 fewer DSPs, a 33.81% reduction. Its routed reduction against OPT_1_STREAMING remains pending.')
    p('Higher reuse can increase latency or reduce throughput. Resource savings and latency must be judged together. B3 is a separate proposal and is not included as a measured variant.')
    if nonstream:
        heading('Streaming vs non-streaming baseline',True)
        p('OPT_0_NONSTREAMING uses the same stock hls4ml CNN, weights, quantizers, reuse settings and ABI v3 timestamps as OPT_1_STREAMING. Its synchronous 65536 x 16-bit buffer waits for both the complete preprocessed image and the last raw input beat before the CNN consumes a pixel. No cross-frame overlap is enabled.')
        p('The sequencing mirrors the original production preprocessing-then-CNN design. The split wrappers and timestamps match this campaign, so this is a matched baseline rather than a bit-identical replay of the original production package.')
        table([['Variant','BRAM tiles','Device %','DSPs','Device %']]+[[b['label'],fmt(value(b,'BRAM_tiles')),percent(value(b,'BRAM_tiles'),'BRAM_tiles'),fmt(value(b,'DSP')),percent(value(b,'DSP'),'DSP')] for b in [nonstream,baseline]],[170,85,80,85,80])
        buffer_tiles=nonstream.get('frame_buffer_bram_estimate')
        p(('Standalone buffer synthesis inferred '+fmt(buffer_tiles)+' BRAM tiles ('+percent(buffer_tiles,'BRAM_tiles')+' of U55C BRAM). ' if buffer_tiles is not None else 'Standalone buffer synthesis pending. ')+'This is a component estimate, not the complete routed baseline cost. The full build remains pending until all parity, actual-build RTL and timing gates pass.')
        p('Timestamp scopes for later benchmarking: raw first-to-last measures input arrival; first-to-last preprocessing output measures preprocessing delivery; first CNN input-to-score measures the observed CNN interval; arm-to-verdict includes the full frame fill. Host file reading remains outside FPGA timestamps and requires host-side measurement.')
        rows=[]
        for b in [nonstream,baseline]:
            row=next((m for m in b.get('rtl',{}).get('measurements',[]) if int(m['bytes'])==4194241),{})
            fpga=(int(row['decision_tick'])-int(row['origin_tick']))*4/1e6 if 'decision_tick' in row else None
            rows.append([b['label'],'pending' if fpga is None else f'{fpga:.6f}','not measured'])
        table([['Variant','RTL arm-to-verdict (ms)','Production e2e']]+rows,[190,160,150])
        p('FIFO depths 4096, 65536 and 262144 are no longer selected for routing. Their completed native profiles remain archived. No profiling is repeated, and no board benchmarks are launched.')
    heading('3a. R_S: measured host latency',True)
    p('R_S has existing U55C board measurements. These are retained as a historical reference, separate from the RTL simulations of the current optimization variants.')
    host=sorted(rs['host_measurements'],key=lambda row:int(row['input_bytes']))
    table([['R_S input','Bytes','Median (ms)','p95 (ms)']]+[[row['sweep'],f"{int(row['input_bytes']):,}",f"{float(row['median_ms']):.6f}",f"{float(row['p95_ms']):.6f}"] for row in host],[110,140,125,125])
    p('<b>Recorded scope:</b> host start to host-observed result. Includes submission/flush, transfer of the complete input, FPGA streaming preprocessing and inference, result DMA and readback. Each case has 20 warm-ups and 200 measured calls.')
    p('<b>Excluded:</b> file reading, input copies, allocation, registration and FPGA programming. Thus even this historical result is not full file-read-to-verdict latency. R_S has no internal FPGA timestamp breakdown.')
    p('At 4 MiB the median is 1.1058465 ms. This is not directly comparable to the approximately 1.1 ms first-CNN-input-to-result RTL interval below: endpoints, workload sizes, transport and execution environments differ. No speedup is computed between these scopes.')
    p('OPT_1_STREAMING and the A/FIFO/B variants have no board latency measurements in this campaign. Their host/e2e comparison remains unmeasured; the current request does not launch benchmarks.')
    heading('3b. Latency across current variants',True)
    p('<b>Production end-to-end latency is unavailable for the eight selected campaign variants.</b> No new board benchmarks were run; historical R_S timings are listed separately on the preceding page. Host bitstream reading, host preprocessing if applicable, DMA, FPGA preprocessing, inference and result return have not been timed together.')
    p('The available comparison below is <b>integrated RTL: first CNN input to accepted result</b>. It includes waiting for later pixels from the streaming preprocessor, but excludes host I/O and the interval before the first CNN input. For non-streaming this interval excludes the entire frame fill. It must not be labelled production e2e latency.')
    def latency(b,n):
        result=b.get('rtl',{})
        if result.get('status')!='passed':return None
        row=next((m for m in result['measurements'] if int(m['bytes'])==n),None)
        return int(row['cnn_cycles'])*4/1e6 if row else None
    n=4194241;ref=latency(baseline,n)
    def ms(v):return 'pending' if v is None else f'{v:.6f}'
    def delta(b):
        v=latency(b,n)
        return 'pending' if ref is None or v is None else f'{100*(v-ref)/ref:+.3f}%'
    table([['Variant','Production e2e','RTL 4,194,241 B (ms)','RTL 4,194,240 B (ms)','RTL change vs base']]+[[b['label'],'not measured',ms(latency(b,n)),ms(latency(b,n-1)),delta(b)] for b in current],[125,85,100,100,90])
    story.append(chart([label(b) for b in current],[('Integrated RTL, 4194241 bytes',[latency(b,n) for b in current])],'Available latency comparison (not production e2e)','Milliseconds; same input size, testbench stalls, and output backpressure.',190))
    p('The 4,194,240-byte case uses a slower bytewise preprocessing path; 4,194,241 bytes uses the fast path. Keep these cases separate. All comparisons use 4 ns clocks and identical synthetic inputs. The earlier baseline validation is reused only after checking matching model, HLS, interface and validation configuration, testbench, and sealed validation evidence.',True)
    heading('Appendix A. All resource types',True)
    keys=['LUT','FF','BRAM_tiles','DSP','URAM'];names=['LUT','FF','BRAM tiles','DSP','URAM']
    p('The eight selected configurations plus the historical R_S reference. Routed user-wrapper counts include checker integration and debug overhead; full-shell overhead is excluded. A is listed once as the 100000-depth point. Pending is not zero.')
    table([['Variant']+names]+[[b['label']]+[fmt(value(b,k)) for k in keys] for b in ordered],[135,73,73,73,73,73])
    p('<b>Device utilization percentages, same wrapper scope</b>')
    table([['Variant']+names]+[[b['label']]+[percent(value(b,k),k) for k in keys] for b in ordered],[135,73,73,73,73,73])
    table([['Device capacity']+names,['U55C']+[fmt(capacity[k]) for k in keys]],[135,73,73,73,73,73])
    p('BRAM tiles = RAMB36 + RAMB18 / 2. Percentages use the full device capacity, not a placement region or an optimization budget.',True)
    heading('Appendix B. Resource plots',True)
    for key,title in [('LUT','LUT usage'),('FF','Flip-flop usage'),('URAM','URAM usage')]:
        story.append(chart([label(b) for b in ordered],[(title,[value(b,key) for b in ordered])],title+' across all variants','Left: count. Right: device utilization %. Bar labels show both.',195,capacity[key]))
    p('BRAM and DSP plots for their optimization families appear in sections 1 and 2. Appendix A supplies all resource counts and percentages across both families.',True)
    heading('Appendix C. Full design and evidence',True)
    p('Full routed design, including the Coyote shell: each cell gives count / device utilization. Use the user-wrapper tables to attribute optimization impact; shell overhead can mask it.')
    table([['Variant']+names]+[[b['label']]+[('pending' if value(b,k,'full_design') is None else fmt(value(b,k,'full_design'))+' / '+percent(value(b,k,'full_design'),k)) for k in keys] for b in ordered],[135,73,73,73,73,73])
    p('<b>Build state</b>')
    table([['Variant','Stage']]+[[b['label'],'Historical routed build; board-tested; different interface' if b is rs else 'Complete; correctness and timing passed' if 'artifact' in b else b['stage']] for b in ordered],[165,335])
    p('Source paths and hashes are recorded in streaming_optimization_results_20261012.json. R_S uses the archived u55c02_20261009 report, verified against its file manifest and original routed reports. Its interface is a single HLS wrapper with production DMA, not the split timestamped integration of OPT_1_STREAMING. Routed results are checked against sealed artifacts, source identity, correctness and timing gates. Integrated RTL measurements come from rtl_validation/result.json. OPT_1_STREAMING latency currently uses the matching earlier attempt_02 when the fresh baseline has not yet validated.',True)
    p('The build-host reboot at 07:00 CEST on 12 October interrupted builds and local monitors. They were restarted at 15:58 after verification. The report watcher refreshes this PDF independently when the primary queue and the non-streaming queue terminate. No board benchmarking is scheduled.',True)
    def footer(canvas,doc):
        canvas.setFont('Helvetica',7);canvas.setFillColor(NAVY);canvas.drawString(45,24,'Optimization impact | R_S reference and OPT_1_STREAMING | '+data['as_of'][:10]);canvas.drawRightString(550,24,str(doc.page))
    temporary=PDF.with_suffix('.tmp.pdf')
    SimpleDocTemplate(str(temporary),pagesize=A4,rightMargin=45,leftMargin=45,topMargin=40,bottomMargin=42,title='Optimization impact: R_S reference and OPT_1_STREAMING',author='ML Deep Bitstream Inspection').build(story,onFirstPage=footer,onLaterPages=footer)
    temporary.replace(PDF);PDF.with_suffix('.json').write_text(json.dumps(data,indent=2)+'\n')
    print(PDF,flush=True)

def watch():
    from iteration_monitor import send
    import fcntl
    state=OUT/'results_report_watcher.json'
    with (OUT/'results_report_watcher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        completed=set(load(state).get('completed_lanes',[]))
        while True:
            for lane in ['primary','nonstreaming']:
                terminal=load(SELECTED/(lane+'.json')).get('status') in {'passed','failed','blocked'}
                if terminal and lane not in completed:
                    render()
                    event={'id':'results_pdf_'+lane,'outcome':'updated','message':'Optimization results PDF updated after '+lane+' queue terminated: '+str(PDF)}
                    if send(OUT,event):completed.add(lane)
            done=len(completed)==2
            state.write_text(json.dumps({'status':'complete' if done else 'waiting','pid':os.getpid(),'heartbeat':time.time(),'pdf':str(PDF),'completed_lanes':sorted(completed)})+'\n')
            if done:return
            time.sleep(30)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    watch() if args.watch else render()
