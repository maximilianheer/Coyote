#!/usr/bin/env python3
"""One independently resumable iteration; correctness and build readiness are separate."""
import argparse, csv, fcntl, json, os, signal, shutil, subprocess, sys, time
from pathlib import Path
from prepare import sha, verify_sources
from implementation_permits import permit
from worker import save, collect_artifacts, seal_artifacts, final_timing_reports

class Worker:
    def __init__(self, job):
        self.job=job; self.meta=json.loads((job/'attempt.json').read_text())
        self.repo=Path(self.meta['repo']);self.c=json.loads((job/'config/iteration.json').read_text())
        self.env=os.environ.copy()
        self.env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:/tools/Xilinx/Vitis/2024.2/bin:'+self.env['PATH']
        self.env.update(OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',TF_USE_LEGACY_KERAS='1',
                        MPLCONFIGDIR=str(job/'tmp/matplotlib'),TMPDIR=str(job/'tmp'))
        (job/'tmp').mkdir(exist_ok=True)
        self.state={'id':self.c['id'],'status':'running','stage':'starting','pid':os.getpid(),
                    'started_at':time.time(),'correctness':'pending','timing':'pending','board_validated':False}
        self.progress()
    def progress(self, **kw):
        self.state.update(kw);save(self.job/'status.json',self.state)
    def verify(self):
        for p,d in self.meta['inputs'].items():
            if sha(self.job/p)!=d:raise RuntimeError('Attempt input changed: '+p)
        if sha(self.repo/self.c['model']['weights'])!=self.meta['model_weights_sha256']:
            raise RuntimeError('Model weights changed')
        if (self.job/'source_manifest.json').exists():
            verify_sources(self.job)
            for p,d in json.loads((self.job/'source_manifest.json').read_text())['build_scripts'].items():
                if sha(self.job/'coyote'/p)!=d:raise RuntimeError('Build script changed: '+p)
    def command(self, stage, args, cwd=None):
        self.progress(stage=stage,stage_started_at=time.time())
        print(stage, flush=True)
        with (self.job/(stage+'.log')).open('w') as log:
            timeout=6*3600 if stage=='generate' and self.c['hls']['fifo_depth_optimization'] else None
            process=subprocess.Popen(args,cwd=cwd or self.job,env=self.env,stdout=log,
                                     stderr=subprocess.STDOUT,start_new_session=True)
            try:
                code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()
                raise RuntimeError('FIFO profiling exceeded the six-hour tool watchdog; subprocess group stopped')
            if code:raise subprocess.CalledProcessError(code,args)
    def prepare(self):
        self.verify()
        if (self.job/'source_manifest.json').exists():return
        self.profile()
        import prepare, iteration_prepare
        prepare.COYOTE = self.repo.parent
        iteration_prepare.package(self.job)
        self.verify()
    def profile(self):
        """Native conversion/profiling only: never package or implement hardware."""
        self.verify()
        sealed=self.job/'generated_manifest.json'
        if sealed.exists():
            for name,digest in json.loads(sealed.read_text()).items():
                if sha(self.job/name)!=digest:raise RuntimeError('Generated evidence changed: '+name)
            return
        if not (self.job/'model_parity.json').exists():
            self.command('generate',[str(self.repo/'ml_baseline/.venv_hls4ml/bin/python'),
                 str(self.job/'tooling/iteration_generate.py'),str(self.job),str(self.repo)])
        if json.loads((self.job/'model_parity.json').read_text())['status']!='passed':
            raise RuntimeError('Regenerated model parity failed')
        files=list((self.job/'generated/firmware').rglob('*'))
        files += [self.job/n for n in ['model_parity.json','generator_identity.json','resolved_layers.json',
                  'hls_config.json','fifo_profile_inputs.json','generated/fifo_depths.json']]
        save(sealed,{str(p.relative_to(self.job)):sha(p) for p in files if p.is_file()})
    def csim(self):
        j=self.job;kr=j/'hw/src/hls/cnn_wrapper';pp=j/'hw/src/hls/preprocess_wrapper'
        flags=['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I/tools/Xilinx/Vitis/2024.2/include',
               '-I'+str(kr),'-I'+str(kr/'firmware'),'-I'+str(pp/'firmware'),
               '-DWEIGHTS_DIR="'+str(kr/'firmware/weights')+'"']
        self.command('csim_compile',flags+[str(j/'tests/direct_csim.cpp'),str(pp/'preprocess_wrapper.cpp'),
            str(kr/'cnn_wrapper.cpp'),str(kr/'firmware/iteration_model.cpp'),
            '/usr/lib/x86_64-linux-gnu/libgmp.so.10','-pthread','-o',str(j/'csim')])
        sim=j/'csim_run';sim.mkdir(exist_ok=True)
        self.command('csim',[str(j/'csim')],sim)
        if (sim/'direct_expected.txt').read_bytes()!=(j/'fixtures/direct_expected.txt').read_bytes():
            raise RuntimeError('Wrapped synthetic logits differ from production reference')
        control=j/'control';control.mkdir(exist_ok=True)
        self.command('control_compile',['xvlog','--sv',str(j/'hw/src/hdl/direct_control.sv'),
             str(j/'hw/src/hdl/elastic_fifo.sv'),str(j/'tests/direct_control_tb.sv')],control)
        self.command('control_elaborate',['xelab','direct_control_tb','-s','checker','-generic_top','VARIANT=7'],control)
        self.command('control_simulate',['xsim','checker','-runall'],control)
        if 'PASS direct control variant=7' not in (j/'control_simulate.log').read_text():
            raise RuntimeError('Control/timestamp simulation failed')
        if self.c['interface'].get('pipeline_mode')=='nonstreaming':
            check=j/'frame_buffer_validation';check.mkdir(exist_ok=True)
            self.command('frame_buffer_compile',['xvlog','--sv',str(j/'hw/src/hdl/frame_buffer.sv'),str(j/'tests/frame_buffer_tb.sv')],check)
            self.command('frame_buffer_elaborate',['xelab','frame_buffer_tb','-s','frame_buffer_check','-mt','4'],check)
            self.command('frame_buffer_simulate',['xsim','frame_buffer_check','-runall'],check)
            if 'PASS frame buffer:' not in (j/'frame_buffer_simulate.log').read_text():raise RuntimeError('Frame buffer simulation failed')
            self.command('frame_buffer_synthesis',['vivado','-mode','batch','-source',str(j/'tests/frame_buffer_synth.tcl'),'-tclargs',str(j/'hw/src/hdl/frame_buffer.sv')],check)
            if 'PASS frame buffer BRAM inference:' not in (j/'frame_buffer_synthesis.log').read_text():raise RuntimeError('Frame buffer BRAM inference failed')
    def synthesize(self):
        roots={}
        for top in ['preprocess_wrapper','cnn_wrapper']:
            j=self.job;kr=j/'hw/src/hls'/top;target=j/(top+'_hls');script=j/(top+'_synth.tcl')
            script.write_text(f'''open_project -reset {{{target}}}
set_top {top}
add_files {{{kr}/{top}.cpp}} -cflags "-std=c++14 -I{kr} -I{kr}/firmware"
add_files {{{kr}/firmware/iteration_model.cpp}} -cflags "-std=c++14 -I{kr} -I{kr}/firmware"
open_solution -reset solution1 -flow_target vivado
set_part {{{self.c['hls']['part']}}}
create_clock -period {self.c['hls']['clock_period']} -name default
set_clock_uncertainty {self.c['hls']['clock_uncertainty']}
csynth_design
exit
''')
            self.command(top+'_synthesis',['vitis_hls','-f',str(script)])
            roots[top]=target/'solution1/syn/verilog'
        return roots
    def rtl(self, roots, name):
        j=self.job;sim=j/name;sim.mkdir(exist_ok=False)
        for label,top in [('pp','preprocess_wrapper'),('cnn','cnn_wrapper')]:shutil.copytree(roots[top],sim/label)
        for filename in ['elastic_fifo.sv','direct_control.sv'] + (['frame_buffer.sv'] if (j/'hw/src/hdl/frame_buffer.sv').exists() else []):
            shutil.copy2(j/'hw/src/hdl'/filename,sim/filename)
        for f in ['direct_pipe_tb.sv','direct_sim.tcl']:shutil.copy2(j/'tests'/f,sim/f)
        shutil.copy2(j/'fixtures/direct_expected.txt',sim/'direct_expected.txt')
        save(sim/'inputs.json',{str(p.relative_to(sim)):sha(p) for p in sim.rglob('*') if p.is_file()})
        self.env.update(DRIVER_RESETS='1',DIRECT_STARTUP_IDLE='20000',DIRECT_ALWAYS_READY='0')
        self.command(name,['vivado','-mode','batch','-source',str(sim/'direct_sim.tcl')],sim)
        if 'PASS direct synthesized RTL parity: frames=11' not in (j/(name+'.log')).read_text():
            raise RuntimeError('Incomplete wrapped RTL parity')
        rows=list(csv.DictReader((sim/'cycles.csv').open()))
        if len(rows)!=11:raise RuntimeError('Missing RTL frames')
        save(sim/'result.json',{'status':'passed','frames':11,'startup_idle_cycles':20000,'driver_resets':1,
             'measurements':rows,'performance_admission':False,'input_manifest_sha256':sha(sim/'inputs.json')})
    def validate(self):
        self.verify();j=self.job;record=j/'validation.json'
        if record.exists():
            data=json.loads(record.read_text())
            if data['status']=='passed' and data['source_manifest_sha256']==sha(j/'source_manifest.json'):
                for p,d in data['evidence'].items():
                    if sha(j/p)!=d:raise RuntimeError('Validation evidence changed: '+p)
                self.progress(correctness='passed');return
            raise RuntimeError('Invalid validation record; create a fresh attempt')
        self.csim();self.rtl(self.synthesize(),'rtl_validation');self.verify()
        evidence={str(p.relative_to(j)):sha(p) for p in [j/'model_parity.json',j/'csim_run/direct_expected.txt',
             j/'control_simulate.log',j/'rtl_validation/result.json',j/'rtl_validation/inputs.json',j/'rtl_validation/cycles.csv']}
        if self.c['interface'].get('pipeline_mode')=='nonstreaming':
            for name in ['frame_buffer_simulate.log','frame_buffer_synthesis.log','frame_buffer_validation/frame_buffer_utilization.rpt']:evidence[name]=sha(j/name)
        save(record,{'status':'passed','source_manifest_sha256':sha(j/'source_manifest.json'),
              'evidence':evidence,'performance_admission':False})
        self.progress(correctness='passed')
    def build(self):
        j=self.job;b=j/'build'
        self.command('host_configure',['cmake','-S',str(j/'host'),'-B',str(j/'host_build'),'-DCOYOTE_SW='+str(j/'coyote/sw')])
        self.command('host_compile',['cmake','--build',str(j/'host_build'),'--parallel','2'])
        self.command('configure',['cmake','-S',str(j/'hw'),'-B',str(b),'-DVITIS_HLS_MODE=vitis_hls','-DCOMP_CORES=4',
             '-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2','-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'])
        self.command('project',['make','-j1','project'],b)
        roots={}
        for top in ['preprocess_wrapper','cnn_wrapper']:
            found=list(b.rglob('solution1/syn/verilog/'+top+'.v'))
            if len(found)!=1:raise RuntimeError('Cannot identify actual build RTL '+top)
            roots[top]=found[0].parent
        self.rtl(roots,'build_rtl_validation');self.verify()
        self.implement()
    def implement(self):
        j=self.job;b=j/'build'
        self.verify()
        result=json.loads((j/'build_rtl_validation/result.json').read_text())
        if result['status']!='passed' or result['input_manifest_sha256']!=sha(j/'build_rtl_validation/inputs.json'):
            raise RuntimeError('Actual build RTL gate is not sealed')
        for name,digest in json.loads((j/'build_rtl_validation/inputs.json').read_text()).items():
            if sha(j/'build_rtl_validation'/name)!=digest:raise RuntimeError('Actual build RTL input changed: '+name)
        os.environ.setdefault('HLS4ML_IMPLEMENTATION_LOCK',str(j.parents[1]/'implementation.lock'))
        with permit(self.progress):
            for stage in ['synth','link','shell','bitgen']:
                self.command(stage,['make','-j1',stage],b)
                if stage=='shell':
                    self.progress(stage='timing_check')
                    final_timing_reports(b,self.c['id'])
                    self.progress(timing='passed')
        self.verify()
        artifacts=collect_artifacts(b,self.c['id']);seal_artifacts(j,artifacts)
        self.progress(timing='passed',artifacts=artifacts)
    def run(self, stage):
        try:
            if stage=='profile':self.profile()
            else:self.prepare()
            if stage in ('validate','build','implement'):self.validate()
            if stage=='implement':self.implement()
            if stage=='build' and self.c['build']['routed']:self.build()
            self.progress(status='passed',stage='complete',finished_at=time.time())
            return 0
        except Exception as error:
            if 'Timing failure:' in str(error):self.state['timing']='failed'
            self.progress(status='failed',error=str(error),finished_at=time.time())
            print(str(error),flush=True);return 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('stage',choices=['profile','prepare','validate','build','implement'])
    a=p.parse_args();job=a.job.resolve()
    with (job/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        raise SystemExit(Worker(job).run(a.stage))
