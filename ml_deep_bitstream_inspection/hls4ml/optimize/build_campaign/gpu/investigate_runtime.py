#!/usr/bin/env python3
"""Run isolated runtime revisions after the report campaign; preserve every attempt."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,time
from pathlib import Path

def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def main(root,out):
    cfg=json.loads((root/'campaign.json').read_text());python=cfg['python'];repo=Path(cfg['repo']);source=repo/'hls4ml/optimize/build_campaign/gpu/runtime_probe.py'
    status=dict(status='running',pid=os.getpid(),started_at=time.time(),report_eligible=False);save(out/'status.json',status)
    cases=[('R00_preprocess_v2','v2_baseline','64','1',1,'Report-pinned preprocessing-v2 compute reference'),
           ('R01_gpu_local_cpu','gpu_local','0','0',1,'Move host orchestration near GPU; preserve one CPU and one TF thread'),
           ('R02_cpu_pool','cpu_pool','0-7','0',1,'Allow runtime worker threads to use eight GPU-local CPUs'),
           ('R03_tf_threads2','threads2','0-7','0',2,'Increase TensorFlow inter/intra-op thread limits to two'),
           ('R04_combined_graph','combined_graph','0-7','0',1,'Combine preprocessing and model under one TensorFlow graph call'),
           ('R05_xla_combined','xla_combined','0-7','0',1,'Compile the same FP32 preprocessing/model graph; specialize on input length')]
    results=[]
    for ident,mode,cpus,numa,threads,hypothesis in cases:
        experiment=out/'experiments'/ident;experiment.mkdir(exist_ok=False);runtime=experiment/'runtime';shutil.copytree(root/'software/gpu_runtime',runtime,ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(source,experiment/'runtime_probe.py')
        manifest={str(p.relative_to(experiment)):hashlib.sha256(p.read_bytes()).hexdigest() for p in experiment.rglob('*') if p.is_file()}
        meta=dict(id=ident,mode=mode,parent='R00_preprocess_v2' if ident=='R01_gpu_local_cpu' else 'R01_gpu_local_cpu' if ident=='R02_cpu_pool' else 'R02_cpu_pool' if ident in ['R03_tf_threads2','R04_combined_graph'] else 'R04_combined_graph' if ident=='R05_xla_combined' else None,hypothesis=hypothesis,cpu=cpus,numa=numa,threads=threads,source_hashes=manifest,model_reference=json.loads((runtime/'model_reference.json').read_text()),report_eligible=False)
        save(experiment/'experiment.json',meta);status.update(active=ident,heartbeat=time.time());save(out/'status.json',status)
        env=dict(os.environ,LD_LIBRARY_PATH='/opt/rocm/lib',HIP_VISIBLE_DEVICES='0',TF_CPP_MIN_LOG_LEVEL='2',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONPATH=str(root/'software/gpu_build')+':'+str(runtime))
        cmd=['numactl','--physcpubind='+cpus,'--membind='+numa,python,str(experiment/'runtime_probe.py'),str(root),str(experiment/'measurement'),'--mode',mode,'--threads',str(threads)]
        meta['command']=cmd;meta['environment_overrides']={k:env[k] for k in ['LD_LIBRARY_PATH','HIP_VISIBLE_DEVICES','TF_CPP_MIN_LOG_LEVEL','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','PYTHONPATH']};save(experiment/'experiment.json',meta)
        with (experiment/'run.log').open('w') as f:
            try:code=subprocess.call(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
            except subprocess.TimeoutExpired:code=124
        row=dict(**meta,returncode=code,finished_at=time.time())
        if (experiment/'measurement/result.json').exists():row['result']=str(experiment/'measurement/result.json')
        if code:row['failure_log']=str(experiment/'run.log')
        results.append(row);save(out/'index.json',results)
        with (out/'JOURNAL.md').open('a') as f:f.write('\n## '+ident+'\n\n'+hypothesis+'\n\nStatus: '+('passed' if code==0 else 'failed')+'. CPU '+cpus+', NUMA '+numa+', TF threads '+str(threads)+'. See '+str(experiment.relative_to(out))+'/ for exact source, commands, parity, timing samples and trace.\n')
    status.update(status='awaiting_analysis',finished_at=time.time());save(out/'status.json',status)
    subprocess.run(['curl','-fsS','--max-time','15','-d','GPU runtime investigation: TensorFlow candidate measurements complete; evidence analysis and possible alternative runtime remain. Preprocessing-v2 reports remain separate.','https://ntfy.sh/coyote-build-sdeheredia'],stdout=subprocess.DEVNULL)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);a=p.parse_args();main(a.root.resolve(),a.out.resolve())
