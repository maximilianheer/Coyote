"""Native FIFO evidence and build summaries. Never measures board latency."""
import csv
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from prepare import REPO, sha, verify_sources
from worker import validate_timing_report


def read(path):
    return json.loads(Path(path).read_text())


def verify_inputs(job):
    meta=read(job/'attempt.json')
    for name,digest in meta['inputs'].items():
        if sha(job/name)!=digest:raise ValueError('Changed attempt input: '+name)
    config=read(job/'config/iteration.json')
    if sha(Path(meta['repo'])/config['model']['weights'])!=config['model']['weights_sha256']:
        raise ValueError('Changed model weights')
    if (job/'source_manifest.json').exists():verify_sources(job)
    return config


def fingerprint(job):
    """Identical generated firmware + model/tool/interface identities, not point names."""
    config=verify_inputs(job)
    fw=job/'generated/firmware'
    if not fw.is_dir():raise ValueError('Missing generated firmware')
    firmware={str(p.relative_to(fw)):sha(p) for p in fw.rglob('*') if p.is_file()}
    identity={'firmware':firmware,'model':config['model'],'interface':config['interface'],
              'toolchain':'Xilinx 2024.2','generator':read(job/'generator_identity.json'),
              'resolved_layers':read(job/'resolved_layers.json'),
              'clock':{k:config['hls'][k] for k in ['backend','part','clock_period','clock_uncertainty']}}
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()


def transactions(text):
    rows=[]
    for n,latency,interval in re.findall(r'transaction\s+(\d+):\s+(\d+)\s+(\d+|x)',text):
        rows.append({'transaction':int(n),'latency_cycles':int(latency),
                     'interval_cycles':None if interval=='x' else int(interval)})
    return rows


def profile_summary(job):
    c=verify_inputs(job)
    parity=read(job/'model_parity.json')
    if parity['status']!='passed' or parity['exact_mismatches']!=0 or parity['samples']!=146:
        raise ValueError('Incomplete model parity')
    fifo=c['hls']['fifo_depth_optimization']
    capacity=c['hls']['profiling_depth'] if fifo else None
    report={'status':'passed','job':str(job),'fingerprint':fingerprint(job),
            'profiling_depth':capacity,'clock_period_ns':c['hls']['clock_period'],
            'latency_scope':'CNN-only native profiling RTL; excludes streaming preprocessing and host transfer',
            'board_measured':False,'fifos':{},'transactions':[]}
    if fifo:
        samples=read(job/'fifo_profile_inputs.json')
        if samples['samples']!=2:raise ValueError('Expected the pinned two-frame experiment')
        for name,digest in samples['files'].items():
            if sha(job/name)!=digest:raise ValueError('Changed profiling input/output evidence')
        report['sample_ids']=samples['sample_ids']
        report['fifos']=read(job/'generated/fifo_depths.json')
        if len(report['fifos'])!=29:raise ValueError('Incomplete native FIFO map')
        if any(v['optimized']<1 or v['optimized']>capacity for v in report['fifos'].values()):
            raise ValueError('Invalid native selected depth')
        report['saturated_fifos']=[k for k,v in report['fifos'].items() if v['optimized']==capacity]
        report['interpretation']='capacity-constrained' if report['saturated_fifos'] else 'no capacity hit observed'
        candidates=list((job/'generated').glob('**/iteration_model.performance.result.transaction.xml'))
        # Recovered profiles may lack a copied native transaction table. Never infer
        # latency by dividing aggregate simulation time by the number of frames.
        if candidates:
            data=transactions(candidates[0].read_text())
            if len(data)!=2:raise ValueError('Incomplete native transaction latency table')
            report['transactions']=data
            report['transaction_evidence']={'path':str(candidates[0]),'sha256':sha(candidates[0])}
        else:report['latency_unavailable']='Native transaction table not preserved in recovered profile'
        defs=(job/'generated/firmware/defines.h').read_text()
        widths={f'layer{n}_out':int(bits)*int(ch) for bits,ch,n in re.findall(
            r'typedef nnet::array<ap_u?fixed<(\d+),[^\n]+>, (\d+)\*1> layer(\d+)_t;',defs)}
        for name,v in report['fifos'].items():
            v.update(width_bits=widths[name],saturated=v['optimized']==capacity)
        report['initial_fifo_bits']=sum(v['initial']*v['width_bits'] for v in report['fifos'].values())
        report['selected_fifo_bits']=sum(v['optimized']*v['width_bits'] for v in report['fifos'].values())
    return report


def artifact_summary(job):
    verify_inputs(job)
    manifest=read(job/'artifact_manifest.json')
    source=verify_sources(job)
    if manifest['status']!='passed' or source!=manifest['source_manifest_sha256']:
        raise ValueError('Invalid artifact/source identity')
    for evidence in ['validation.json','build_rtl_validation/result.json']:
        if read(job/evidence)['status']!='passed':raise ValueError('Incomplete RTL gate')
    validation=read(job/'validation.json')
    if validation['source_manifest_sha256']!=source:raise ValueError('Validation source mismatch')
    for name,digest in validation['evidence'].items():
        if sha(job/name)!=digest:raise ValueError('Changed validation evidence')
    bits=[];timing=[];reports={}
    for name,r in manifest['files'].items():
        p=(job/name).resolve()
        if not p.is_relative_to(job.resolve()) or p.stat().st_size!=r['bytes'] or sha(p)!=r['sha256']:
            raise ValueError('Changed hardware artifact: '+name)
        if p.name=='cyt_top.bit':bits.append(str(p))
        if p.name=='shell_timing_summary.rpt':validate_timing_report(p);timing.append(str(p))
        if p.name in ['shell_utilization_hierarchical.rpt','shell_utilization.rpt']:reports[p.name]=p
    if len(bits)!=1 or not timing:raise ValueError('Missing unique bitstream/timing')
    result={'status':'passed','bitstream':bits[0],'timing_reports':timing,
            'artifact_manifest_sha256':sha(job/'artifact_manifest.json'),'source_manifest_sha256':source}
    if len(reports)==2:
        from resource_attribution import attribute
        result['resources']=attribute(reports['shell_utilization_hierarchical.rpt'].read_text(),
                                      reports['shell_utilization.rpt'].read_text(),'D_I')
    return result


def hls_estimates(job):
    out={}
    for top in ['preprocess_wrapper','cnn_wrapper']:
        path=job/(top+'_hls/solution1/syn/report/'+top+'_csynth.xml')
        if not path.exists():continue
        tree=ET.parse(path)
        out[top]={'scope':'HLS estimate, not routed utilization',
                  'resources':{node.tag:node.text for node in tree.findall('.//AreaEstimates/Resources/*')},
                  'latency':{node.tag:node.text for node in tree.findall('.//SummaryOfOverallLatency/*')}}
    return out


def write_csv(path,rows):
    with path.open('w') as f:
        fields=list(dict.fromkeys(k for row in rows for k in row))
        if fields:
            w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)


def report_output(config):
    """Resolve moved report folders without modifying archived sweep configs."""
    output = Path(config['results'])
    migration_path = REPO / 'hls4ml/optimize/reports/report_path_migration_2026-10-22.json'
    if migration_path.exists() and output.is_relative_to(REPO):
        relative = str(output.relative_to(REPO))
        destination = read(migration_path)['paths'].get(relative)
        if destination is not None:
            output = REPO / destination
    return output


def summarize(root):
    config = read(root / 'sweep.json')
    output = report_output(config)
    output.mkdir(parents=True, exist_ok=True)
    rows=[];fifos=[];latencies=[];integrated=[]
    for item in config['points']:
        record=root/'points'/item['id'];state=read(record/'state.json') if (record/'state.json').exists() else {}
        row={'id':item['id'],'profiling_depth':item.get('depth'),'status':state.get('status','pending'),
             'stage':state.get('stage','pending'),'alias_of':state.get('alias_of',''),'error':state.get('error','')}
        if (record/'profile.json').exists():
            p=read(record/'profile.json')
            row.update(selected_fifo_bits=p.get('selected_fifo_bits'),saturated_fifos=','.join(p.get('saturated_fifos',[])),
                       fingerprint=p['fingerprint'])
            for name,v in p['fifos'].items():fifos.append({'id':item['id'],'fifo':name,**v})
            for transaction in p['transactions']:
                latencies.append({'id':item['id'],'profiling_depth':p['profiling_depth'],**transaction,
                    'latency_ms':transaction['latency_cycles']*p['clock_period_ns']/1e6,
                    'scope':p['latency_scope']})
            rtl=Path(item['job'])/'rtl_validation/result.json'
            if rtl.exists():
                validation=read(rtl)
                if validation.get('status')=='passed':
                    for measurement in validation['measurements']:
                        integrated.append({'id':item['id'],**measurement,
                            'cnn_elapsed_ms':int(measurement['cnn_cycles'])*p['clock_period_ns']/1e6,
                            'scope':'Integrated synthetic RTL input; not a board measurement'})
        if (record/'artifacts.json').exists():
            r=read(record/'artifacts.json').get('resources',{})
            row.update({'routed_wrapper_'+k:v for k,v in r.get('wrapper',{}).items()})
        rows.append(row)
    write_csv(output/'summary.csv',rows);write_csv(output/'fifo_depths.csv',fifos)
    write_csv(output/'native_profile_latency.csv',latencies);write_csv(output/'integrated_rtl_latency.csv',integrated)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if fifos:
        groups={}
        for row in fifos:groups.setdefault(row['id'],[]).append(row)
        fig,ax=plt.subplots(figsize=(13,6))
        for ident,values in groups.items():
            ax.plot([r['fifo'] for r in values],[r['optimized'] for r in values],marker='.',label=ident)
        ax.set_yscale('log');ax.set_ylabel('Native selected depth (entries, log scale)')
        ax.tick_params(axis='x',rotation=90);ax.legend(fontsize=7);fig.tight_layout();fig.savefig(output/'fifo_depths.png',dpi=160);plt.close(fig)
    if latencies:
        fig,ax=plt.subplots(figsize=(9,5))
        for transaction in sorted({r['transaction'] for r in latencies}):
            values=sorted([r for r in latencies if r['transaction']==transaction],key=lambda r:r['profiling_depth'])
            ax.plot([r['profiling_depth'] for r in values],[r['latency_ms'] for r in values],marker='o',label=f'Frame {transaction}')
        ax.set_xscale('log');ax.set_xlabel('Temporary profiling capacity (entries)')
        ax.set_ylabel('CNN-only native RTL latency (ms at 250 MHz)');ax.legend()
        fig.tight_layout();fig.savefig(output/'native_profile_latency.png',dpi=160);plt.close(fig)
    built=[r for r in rows if 'routed_wrapper_BRAM_tiles' in r]
    if built:
        fig,axes=plt.subplots(1,2,figsize=(12,5))
        for ax,key in zip(axes,['BRAM_tiles','DSP']):
            ax.bar([r['id'] for r in built],[r['routed_wrapper_'+key] for r in built]);ax.set_ylabel('Routed wrapper '+key);ax.tick_params(axis='x',rotation=90)
        fig.tight_layout();fig.savefig(output/'routed_resources.png',dpi=160);plt.close(fig)
    return rows
