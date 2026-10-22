#!/usr/bin/env python3
"""Isolated GPU builds and independent outcome monitors. No board operations."""
import argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from prepare import copy_coyote,source_manifest,verify_sources,sha
from worker import save,collect_artifacts,seal_artifacts,final_timing_reports
REPO=HERE.parents[3]
MODEL=REPO/'hls4ml/artifacts_layer7_ext/cnn_small_hls_opt_img256/notebook_float/res256_layers7_WfloatAfloat_P0_RFbase_929720764c5b/fold_0/final_weights.weights.h5'
VARIANTS={'OPT_7_GPU_HOST':10,'OPT_8_GPU_P2P':11}
def prepare(root):
 root.mkdir(parents=True,exist_ok=True)
 for name,variant in VARIANTS.items():
  job=root/'jobs'/name;job.mkdir(parents=True,exist_ok=False)
  copy_coyote(job/'coyote')
  base=job/'coyote/scripts/base.tcl.in';base.write_text(base.read_text().replace('general.maxThreads 8','general.maxThreads 4'))
  src=job/'hw/src';(src/'hdl').mkdir(parents=True)
  for f in (HERE.parent/'hardware/gpu').glob('*.sv'):shutil.copy2(f,src/'hdl'/f.name)
  shutil.copy2(HERE.parent/'hardware/gpu/vfpga_top.svh',src/'vfpga_top.svh')
  for name2 in ['elastic_fifo.sv']:shutil.copy2(HERE.parent/'hardware/direct'/name2,src/'hdl'/name2)
  shutil.copy2(HERE.parent/'hardware/debug_probe.svh',src/'hdl/debug_probe.svh')
  shutil.copy2(HERE.parent/'hardware/init_ip.tcl',src/'init_ip.tcl')
  (src/'hdl/direct_variant.svh').write_text(f'localparam integer DIRECT_VARIANT={variant};\n')
  (job/'tests').mkdir()
  for filename in ['direct_top_elaboration.sv','gpu_variants_tb.sv']:shutil.copy2(HERE.parent/'tests'/filename,job/'tests'/filename)
  (job/'tooling').mkdir()
  shutil.copy2(HERE/'check_rtl.py',job/'tooling/check_rtl.py')
  project=name.lower()
  (job/'hw/CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.5)
set(CYT_DIR "{job/'coyote'}")
set(CMAKE_MODULE_PATH "${{CYT_DIR}}/cmake")
find_package(CoyoteHW REQUIRED)
project({project})
set(FDEV_NAME "u55c")
set(N_REGIONS 1)
set(N_CONFIG 1)
set(EN_PR 0)
set(EN_STRM 1)
set(N_STRM_AXI 2)
set(EN_MEM 0)
set(COMP_CORES 4)
set(BUILD_OPT 1)
validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
  config={'id':name,'abi':4,'variant':variant,'model':str(MODEL.relative_to(REPO)),'weights_sha256':sha(MODEL),'dtype':'float32','batch_size':1,'threshold_logit':0,'gpu':0,'hdev_device':1,'coyote_device':0,'transport':'host' if variant==10 else 'p2p','autonomous_polling':variant==11,'poll_gap_cycles':250,'timeout_ticks':7500000000,'clock_hz':250000000,'max_raw_bytes':134217664,'implementation_threads':4}
  save(job/'job.json',config)
  iteration=REPO/'hls4ml/optimize/iterations'/name;iteration.mkdir(exist_ok=False)
  save(iteration/'iteration.json',config)
  save(job/'source_manifest.json',{'files':source_manifest(job),'variant':name,'model_sha256':sha(MODEL),'build_scripts':{str(p.relative_to(job/'coyote')):sha(p) for folder in ['scripts','cmake'] for p in (job/'coyote'/folder).rglob('*') if p.is_file()}})
  save(job/'status.json',{'id':name,'status':'prepared','stage':'validation_pending'})
 save(root/'campaign.json',{'jobs':list(VARIANTS),'max_concurrent_builds':4,'gpu':0,'hdev_device':1,'coyote_device':0,'benchmark_policy':{'warmups':20,'trials':200,'diagnostic_trials':20,'workloads':15},'created_at':time.time()})
def build(job):
 lock=(job/'worker.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 state={'id':job.name,'status':'running','stage':'init','started_at':time.time(),'pid':os.getpid()}
 status=job/'status.json'
 env=dict(os.environ);env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env['PATH']
 (job/'tmp').mkdir(exist_ok=True);env.update(TMPDIR=str(job/'tmp'),OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1')
 def cmd(stage,args,cwd):
  state.update(stage=stage,stage_started_at=time.time());save(status,state)
  with (job/(stage+'.log')).open('w') as f:
   p=subprocess.Popen(args,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
   state['child_pid']=p.pid
   while p.poll() is None:
    state['heartbeat']=time.time();save(status,state);time.sleep(10)
   if p.returncode:raise RuntimeError(f'{stage} exited {p.returncode}; see {stage}.log')
 try:
  digest=verify_sources(job)
  validation=json.loads((job/'rtl_validation/validation.json').read_text())
  if validation['status']!='passed':raise RuntimeError('RTL gate missing')
  for p,h in validation['files'].items():
   if sha(p)!=h:raise RuntimeError('RTL gate source changed: '+p)
  if job.name=='OPT_8_GPU_P2P':
   gate=json.loads((job.parents[1]/'preflight/p2p_gate.json').read_text())
   if gate['status']!='passed':raise RuntimeError('P2P preflight gate missing')
   for p,h in gate['evidence'].items():
    if sha(p)!=h:raise RuntimeError('P2P evidence changed')
  build=job/'build';build.mkdir(exist_ok=True)
  cmd('configure',['cmake','-S',str(job/'hw'),'-B',str(build),'-DCOMP_CORES=4','-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2','-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'],job)
  for stage in ['project','synth','link','shell','bitgen']:
   cmd(stage,['make','-j1',stage],build)
   if stage=='project':
    pkg=build/(job.name.lower()+'_shell')/'hdl/lynx_pkg.sv'
    cmd('actual_package_rtl',[sys.executable,str(HERE/'check_rtl.py'),str(job),'--package',str(pkg)],job)
   if stage=='shell':final_timing_reports(build,job.name)
  if verify_sources(job)!=digest:raise RuntimeError('Sources changed during implementation')
  artifacts=collect_artifacts(build,job.name);seal_artifacts(job,artifacts)
  state.update(status='passed',stage='complete',artifacts=artifacts,hardware_validated=False)
 except Exception as e:state.update(status='failed',error=str(e))
 state['finished_at']=time.time();save(status,state)
 return 0 if state['status']=='passed' else 1

def monitor(job):
 lock=(job/'monitor.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 last_error=None
 while True:
  state=json.loads((job/'status.json').read_text())
  if state['status']=='running':
   try:os.kill(state['pid'],0)
   except ProcessLookupError:
    state=dict(state,status='interrupted',error='Build supervisor exited unexpectedly; inspect child process before restart')
  if state['status'] in ('passed','failed','interrupted'):
   key=state['status']+str(state.get('started_at'))
   sent=job/'notification.json'
   if sent.exists() and json.loads(sent.read_text()).get('key')==key:return
   msg=f"{job.name}: {state['status'].upper()}. Stage: {state['stage']}. {state.get('error','Routed timing and sealed bitstream passed; board admission still pending.')} Logs: {job}"
   result=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','20','-H','Title: GPU FPGA build','--data-binary',msg,'https://ntfy.sh/coyote-build-sdeheredia'],capture_output=True,text=True)
   save(job/'monitor_status.json',{'status':'sent' if result.returncode==0 else 'retrying','time':time.time(),'error':result.stderr})
   if result.returncode==0:save(sent,{'key':key,'message':msg,'response':result.stdout,'sent_at':time.time()});return
  else:save(job/'monitor_status.json',{'status':'watching','time':time.time(),'build_status':state['status'],'stage':state['stage']})
  time.sleep(20)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','build','monitor']);p.add_argument('path',type=Path);a=p.parse_args();path=a.path.resolve()
 if a.action=='prepare':prepare(path)
 elif a.action=='build':sys.exit(build(path))
 else:monitor(path)
