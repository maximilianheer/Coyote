#!/usr/bin/env python3
"""Measured OPT comparison PDF, with identical-input latency and routed resources."""
import argparse,csv,json,sys,time,shutil,os
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
import build_current_results_report as base
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(base.TOOLS))
from board_benchmark import sha,save
from iteration_monitor import send
NAMES={'OPT_0_NONSTREAMING':'Nonstream','OPT_1_STREAMING':'Streaming','OPT_3_BRAM_FIFO_A':'A 100k','OPT_FIFO_A_P1024':'FIFO 1024','OPT_FIFO_A_P16384':'FIFO 16384','OPT_2_DSP_RESOURCES_B2':'B2','OPT_4_DSP_B2_CONV34_RF72':'B2+72','OPT_5_DSP_B2_RF72_RF288':'B2+72/288'}
ORDER=['OPT_0_NONSTREAMING','OPT_1_STREAMING','OPT_3_BRAM_FIFO_A','OPT_FIFO_A_P1024','OPT_FIFO_A_P16384','OPT_2_DSP_RESOURCES_B2','OPT_4_DSP_B2_CONV34_RF72','OPT_5_DSP_B2_RF72_RF288']
PDF=OUT/'streaming_optimization_benchmarks_20261013.pdf'

def load(p):return json.loads(p.read_text()) if p.exists() else {}
def collect(root):
    cfg=load(root/'campaign.json');data=dict(schema=2,kind='opt_board_benchmark_report',as_of=datetime.now().astimezone().isoformat(timespec='seconds'),root=str(root),status=load(root/'status.json'),builds=cfg['images'],measurements={})
    for item in cfg['order']:
        attempts=sorted((root/'jobs'/item['label']).glob('attempt_*/status.json'))
        if not attempts:continue
        job=attempts[-1].parent;state=load(attempts[-1]);entry=dict(state=state,path=str(job),id=item['id'])
        for phase in ['admission','pilot','full']:
            path=job/phase/'result.json'
            if not path.exists():continue
            result=load(path)
            if result.get('status')!='passed' or result['identity']['id']!=item['id']:raise ValueError('Invalid benchmark result')
            if result['identity']['bitstream_sha256']!=cfg['images'][item['id']]['bitstream_sha256']:raise ValueError('Benchmark image changed')
            for file,digest in result['files'].items():
                if sha(job/phase/file)!=digest:raise ValueError('Benchmark evidence changed')
            entry[phase]=result;entry[phase+'_sha256']=sha(path)
        data['measurements'][item['label']]=entry
    return data

def render(root):
    data=collect(root);story=[];capacity=data['builds']['OPT_1_STREAMING']['resources']['capacity']
    def p(text,small=False):story.append(Paragraph(text,base.styles['SmallR' if small else 'BodyR']))
    def title(text,new=False):
        if new:story.append(PageBreak())
        story.append(Paragraph(text,base.styles['HeadR']))
    def table(rows,widths=None):
        cells=[[Paragraph(escape(str(c)),base.styles['SmallR']) for c in row] for row in rows]
        t=Table(cells,colWidths=widths or [500/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),base.PALE),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('LINEBELOW',(0,0),(-1,0),.8,base.TEAL)]));story.extend([t,Spacer(1,6)])
    def resource(ident,key):return data['builds'][ident]['resources']['wrapper'][key]
    def fmt(value):return 'pending' if value is None else f'{value:.4f}'
    def metric(ident,n,scope,key,stat='median'):
        rows=data['measurements'].get(ident,{}).get('full',{}).get('summaries',[])
        row=next((r for r in rows if r['input_bytes']==n and r['scope']==scope),None)
        return row['metrics'][key][stat] if row else None
    def plot(ids,series,name,unit,height=220,cap=None):story.append(base.chart([NAMES.get(i,i) for i in ids],series,name,unit,height,cap))
    title('OPT benchmarks: resource and latency impact')
    p('Updated '+escape(data['as_of'])+'. Host: hacc-u55c-02; U55C, PCIe Gen3 x16; 250 MHz. '+('All board runs completed.' if data['status'].get('status')=='passed' else 'Measurements in progress; pending values are not zero.'))
    p('Eight independently built OPT variants use the same model and weights. OPT_1_STREAMING is the comparison baseline. R_S is excluded from these measurements. Nonstream buffers all 65536 pixels and waits for raw-input completion before CNN consumption.')
    table([['Label','Iteration','Board state']]+[[NAMES[i],i,data['measurements'].get(i,{}).get('state',{}).get('status','pending')] for i in ORDER],[95,285,120])
    p('<b>Protocol:</b> exact model logits and verdicts; 520 admission calls across three sessions per image; pilot before timing; 20 warm-ups + 200 measured trials per workload and scope. 15 timed workloads: eight real bitstreams, four synthetic sizes and three preprocessing boundary cases. The streaming baseline is repeated at the end.')
    p('<b>Scope:</b> file e2e starts before file open/read and ends when the host observes the verdict. It includes input copies, submission, transfer, FPGA preprocessing and CNN work. It excludes initial allocation/programming and diagnostic CSR readback. Filesystem cache is warm; this does not measure cold-storage latency. Resident-input latency excludes file reading and preparation.')
    title('A / FIFO variants: BRAM reduction',True)
    ids=['OPT_1_STREAMING','OPT_3_BRAM_FIFO_A','OPT_FIFO_A_P1024','OPT_FIFO_A_P16384'];key='BRAM_tiles';ref=resource(ids[0],key)
    table([['Variant','BRAM tiles','Device %','Reduction vs baseline']]+[[NAMES[i],f'{resource(i,key):g}',f'{resource(i,key)/capacity[key]*100:.2f}%',f'{(ref-resource(i,key))/ref*100:.2f}%'] for i in ids],[150,110,110,130])
    plot(ids,[('Routed wrapper BRAM',[resource(i,key) for i in ids])],'BRAM: native FIFO optimization','Left axis: tiles; right axis and labels: device utilization.',260,capacity[key])
    p('Profiling depths are temporary native profiling capacities; final internal FIFO depths differ by channel. Profiles were reused, not rerun. A 100k, FIFO1024 and FIFO16384 use zero URAM; the streaming baseline uses 11 URAM blocks.')
    title('B2 variants: DSP reduction',True)
    ids=['OPT_1_STREAMING','OPT_2_DSP_RESOURCES_B2','OPT_4_DSP_B2_CONV34_RF72','OPT_5_DSP_B2_RF72_RF288'];key='DSP';ref=resource(ids[0],key)
    table([['Variant','conv3/4/5/6 reuse','DSPs / device %','Reduction vs baseline']]+[[NAMES[i],reuse,f'{resource(i,key):g} / {resource(i,key)/capacity[key]*100:.2f}%',f'{(ref-resource(i,key))/ref*100:.2f}%'] for i,reuse in zip(ids,['36/36/32/32','36/36/144/144','72/72/144/144','72/72/288/288'])],[100,145,125,130])
    plot(ids,[('Routed wrapper DSPs',[resource(i,key) for i in ids])],'DSP: increasing multiplier reuse','Left axis: DSP count; right axis and labels: device utilization.',260,capacity[key])
    p('B variants preserve baseline FIFOs. No A+B combination is included yet. Select the combination after comparing measured latency and both resource costs.')
    title('End-to-end latency across all variants',True)
    n=4194304
    table([['Variant','File e2e median / p95 (ms)','Resident median / p95 (ms)']]+[[NAMES[i],fmt(metric(i,n,'file','file_e2e_ms'))+' / '+fmt(metric(i,n,'file','file_e2e_ms','p95')),fmt(metric(i,n,'resident','host_observed_ms'))+' / '+fmt(metric(i,n,'resident','host_observed_ms','p95'))] for i in ORDER],[110,195,195])
    plot(ORDER,[('File read to verdict',[metric(i,n,'file','file_e2e_ms') for i in ORDER]),('Resident input',[metric(i,n,'resident','host_observed_ms') for i in ORDER])],'4 MiB: measured host latency','Median milliseconds. Each scope has its own measured trials.',240)
    p('Both scopes transmit the entire bitstream for every call. Resident-input results isolate the hardware path more closely; file e2e includes filesystem and copy costs. The same raw input bytes and preparation semantics are used in every variant.')
    title('File e2e: reading, preparation and inference',True)
    table([['Variant','File read','Input preparation','Invocation to verdict','Complete file e2e']]+[[NAMES[i]]+[fmt(metric(i,n,'file',k)) for k in ['file_read_ms','prepare_ms','host_observed_ms','file_e2e_ms']] for i in ORDER],[110,95,100,95,100])
    plot(ORDER,[('File open/read',[metric(i,n,'file','file_read_ms') for i in ORDER]),('Prepare/copy',[metric(i,n,'file','prepare_ms') for i in ORDER]),('Invocation to verdict',[metric(i,n,'file','host_observed_ms') for i in ORDER])],'4 MiB: where file-to-verdict time is spent','Median ms from the file-scope trials. Medians are not strictly additive.',250)
    p('File read includes allocation of the input array and filesystem open/read/close. Input preparation includes framing, copying to the registered buffer and setting raw length. Invocation includes transfer, FPGA preprocessing/CNN and verdict observation. Small gaps between these operations are included in complete file e2e. The file read and copy phases occur before submission; FPGA preprocessing and CNN may then overlap.')
    title('FPGA latency and streaming overlap',True)
    table([['Variant','Arm to verdict','CNN first input to score','Preprocessing','Overlap']]+[[NAMES[i]]+[fmt(metric(i,n,'resident',k)) for k in ['arm_to_verdict_ms','inference_ms','preprocess_ms','overlap_ms']] for i in ORDER],[110,90,115,95,90])
    plot(ORDER,[('Observed CNN interval',[metric(i,n,'resident','inference_ms') for i in ORDER]),('Arm to verdict',[metric(i,n,'resident','arm_to_verdict_ms') for i in ORDER])],'4 MiB: FPGA timestamp intervals','Median ms, calibrated from 32 bracketed clock samples before/after each block.',240)
    p('CNN first-input-to-score is the observed interval, including pixel starvation/backpressure. It is not standalone CNN compute time. Streaming reception, preprocessing and CNN intervals overlap and must not be summed. Nonstream has no preprocessing/CNN overlap; its full frame fill appears in arm-to-verdict.')
    title('Preprocessing boundary and input size',True)
    plot(ORDER,[('4,194,240 bytes',[metric(i,4194240,'resident','host_observed_ms') for i in ORDER]),('4,194,241 bytes',[metric(i,4194241,'resident','host_observed_ms') for i in ORDER])],'One-byte boundary: observed host latency','Median ms, prepared input. The preprocessing implementation changes path here.',245)
    plot(ORDER,[('64 MiB file e2e',[metric(i,67108864,'file','file_e2e_ms') for i in ORDER]),('64 MiB resident input',[metric(i,67108864,'resident','host_observed_ms') for i in ORDER])],'64 MiB: file reading and copies matter','Median ms. Both modes send the complete raw bitstream.',245)
    p('A size-dependent latency discontinuity can arise in preprocessing even with identical CNN weights. File e2e also includes host cache and copy variability; small differences between variants should be interpreted alongside resident-input and FPGA intervals, and the final baseline repeat.',True)
    cases=[]
    for line in (root/'cases.tsv').read_text().splitlines():
        f=line.split('\t');cases.append((f[0],int(f[3])))
    cases.sort(key=lambda x:x[1])
    for scope,key,heading in [('file','file_e2e_ms','File-to-verdict latency: all workloads'),('resident','host_observed_ms','Resident-input latency: all workloads')]:
        title(heading,True)
        p('Median milliseconds; 200 measured trials/case. Boundary cases 4,194,240 / 4,194,241 / 4,194,242 bytes exercise the preprocessing branch transition. Raw CSV and JSON retain p95 and per-trial results.')
        table([['Input bytes']+[NAMES[i] for i in ORDER]]+[[f'{n:,}']+[fmt(metric(i,n,scope,key)) for i in ORDER] for _,n in cases],[76]+[53]*8)
    title('Baseline repeat and admission evidence',True)
    repeat='OPT_1_STREAMING_REPEAT'
    rows=[]
    for n in [4194304,16777216,67108864,134217664]:
        before=metric('OPT_1_STREAMING',n,'file','file_e2e_ms');after=metric(repeat,n,'file','file_e2e_ms')
        rows.append([f'{n:,}',fmt(before),fmt(after),'pending' if before is None or after is None else f'{(after/before-1)*100:+.2f}%'])
    table([['Input bytes','First baseline file e2e','Final baseline file e2e','Change']]+rows,[110,140,140,110])
    rows=[]
    for scope,key,label in [('resident','host_observed_ms','Resident host'),('resident','arm_to_verdict_ms','FPGA arm to verdict'),('resident','inference_ms','CNN input to score')]:
        before=metric('OPT_1_STREAMING',4194304,scope,key);after=metric(repeat,4194304,scope,key)
        rows.append([label,fmt(before),fmt(after),'pending' if before is None or after is None else f'{(after/before-1)*100:+.2f}%'])
    table([['4 MiB interval','First baseline (ms)','Final baseline (ms)','Change']]+rows,[150,120,120,110])
    table([['Variant','Exact admission calls','Full measured calls','Image SHA256 prefix']]+[[NAMES.get(i,'Streaming repeat'),data['measurements'].get(i,{}).get('admission',{}).get('rows','pending'),6000 if 'full' in data['measurements'].get(i,{}) else 'pending',data['builds']['OPT_1_STREAMING' if i==repeat else i]['bitstream_sha256'][:16]] for i in ORDER+[repeat]],[125,110,110,155])
    p('A failed parity/event/clock check prevents admission of that variant. Successful results are tied to exact bitstream, source manifest, driver and software hashes. Standard driver reset is retained. CPU2 / NUMA0 and HPF allocation are used throughout. Any measured baseline drift is reported, not silently normalized away.')
    title('Appendix: all routed resource types',True)
    keys=['LUT','FF','BRAM_tiles','DSP','URAM']
    table([['Variant']+keys]+[[NAMES[i]]+[f'{resource(i,k):g} / {resource(i,k)/capacity[k]*100:.2f}%' for k in keys] for i in ORDER],[105]+[79]*5)
    p('Each cell is count / device utilization. Wrapper scope includes integration and debug logic, excluding the static Coyote shell. BRAM tiles = RAMB36 + RAMB18 / 2. The nonstream full-frame buffer adds 30 BRAM tiles relative to the matching streaming baseline.')
    table([['Full design']+keys]+[[NAMES[i]]+[f"{data['builds'][i]['resources']['full_design'][k]:g} / {data['builds'][i]['resources']['full_design'][k]/capacity[k]*100:.2f}%" for k in keys] for i in ORDER],[105]+[79]*5)
    for group in [['LUT','FF'],['BRAM_tiles','DSP','URAM']]:
        title('Appendix: resource plots',True)
        for key in group:plot(ORDER,[(key,[resource(i,key) for i in ORDER])],key+' across all variants','Left: count. Right: device utilization %. Bar labels show both.',190,capacity[key])
    p('Evidence and paths are recorded in the companion JSON. Production and historical report packages are preserved. No combined A+B build or measurement has been selected automatically.',True)
    def footer(canvas,doc):
        canvas.setFont('Helvetica',7);canvas.drawString(45,24,'OPT resources and board benchmarks | '+data['as_of']);canvas.drawRightString(550,24,str(doc.page))
    temp=PDF.with_suffix('.tmp.pdf');SimpleDocTemplate(str(temp),pagesize=A4,leftMargin=45,rightMargin=45,topMargin=40,bottomMargin=42,title='OPT resource and measured latency comparison').build(story,onFirstPage=footer,onLaterPages=footer);temp.replace(PDF)
    save(PDF.with_suffix('.json'),data)
    if data['status'].get('status')=='passed':
        target=OUT/'streaming_optimization_results_20261012.pdf';backup=OUT/'streaming_optimization_results_20261012_build_only.pdf'
        if not backup.exists():shutil.copy2(target,backup)
        original_json=target.with_suffix('.json');backup_json=backup.with_suffix('.json')
        if original_json.exists() and not backup_json.exists():shutil.copy2(original_json,backup_json)
        shutil.copy2(PDF,target)
        shutil.copy2(PDF.with_suffix('.json'),original_json)
    print(PDF,flush=True)

def watch(root):
    state_path=root/'report_watcher.json';state=load(state_path);last=state.get('last_signature')
    while True:
        status=load(root/'status.json');signature=tuple((str(p),p.stat().st_mtime_ns) for p in sorted((root/'jobs').glob('*/attempt_*/full/result.json')))
        key=str(signature)+str(status.get('status'))
        try:
            if key!=last:
                render(root);last=key
            state.update(status='watching',pid=os.getpid(),heartbeat=time.time(),last_signature=last);save(state_path,state)
            if status.get('status')=='passed':
                if send(root,dict(id='benchmark_pdf',outcome='updated',message='OPT benchmark results PDF completed: '+str(PDF))):
                    state.update(status='complete',finished_at=time.time());save(state_path,state);return
        except Exception as e:
            state.update(status='error',error=str(e),heartbeat=time.time());save(state_path,state)
        time.sleep(30)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--watch',action='store_true');a=p.parse_args();watch(a.root.resolve()) if a.watch else render(a.root.resolve())
