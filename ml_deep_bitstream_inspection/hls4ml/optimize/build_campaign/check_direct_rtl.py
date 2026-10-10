#!/usr/bin/env python3
"""Real HLS RTL parity and paired full-CNN latency gate; no notifications."""
import argparse,csv,fcntl,json,os,shutil,subprocess,time
from pathlib import Path
from prepare import sha,verify_sources
from worker import save

def verified_early_result(jobdir,digest,sources):
    """Reuse only complete evidence for byte-identical actual build cores/tests."""
    early=jobdir/'direct_rtl_early'
    try:
        cached=json.loads((early/'status.json').read_text())
        if (cached.get('status')!='passed' or cached.get('source_manifest_sha256')!=digest
                or cached.get('driver_resets')!=1):
            return None
        expected_sizes=[int(line.split()[0]) for line in
                        (jobdir/'reference_simulation/direct_expected.txt').read_text().splitlines()]
        if len(expected_sizes)!=11:return None
        evidence={'direct_rtl_early/status.json':sha(early/'status.json')}
        rows={}
        for variant in ['baseline','candidate']:
            sim=early/variant
            inputs={}
            for prefix,root in [('pp',sources['preprocess_wrapper']),
                                ('cnn',sources['baseline' if variant=='baseline' else 'cnn_wrapper'])]:
                inputs.update({prefix+'/'+str(p.relative_to(root)):sha(p)
                               for p in root.rglob('*') if p.is_file()})
            for name,p in [('elastic_fifo.sv',jobdir/'hw/src/hdl/elastic_fifo.sv'),
                           ('direct_pipe_tb.sv',jobdir/'tests/direct_pipe_tb.sv'),
                           ('direct_sim.tcl',jobdir/'tests/direct_sim.tcl'),
                           ('direct_expected.txt',jobdir/'reference_simulation/direct_expected.txt')]:
                inputs[name]=sha(p)
            if json.loads((sim/'sources.json').read_text())!=inputs:return None
            if any(not (sim/p).is_file() or sha(sim/p)!=h for p,h in inputs.items()):return None
            runtime=sim/'sim_project/direct_rtl.sim/sim_1/behav/xsim'
            if (sim/'cycles.csv').read_bytes()!=(runtime/'cycles.csv').read_bytes():return None
            for log in [sim/'check.log',runtime/'simulate.log']:
                if 'PASS direct synthesized RTL parity: frames=11' not in log.read_text():
                    return None
            with (sim/'cycles.csv').open() as f:rows[variant]=list(csv.DictReader(f))
            if [int(r['bytes']) for r in rows[variant]]!=expected_sizes:return None
            for p in [sim/'sources.json',sim/'cycles.csv',sim/'check.log',runtime/'simulate.log']:
                evidence[str(p.relative_to(jobdir))]=sha(p)
        comparisons=[dict(bytes=int(a['bytes']),baseline_cycles=int(a['cnn_cycles']),
                          candidate_cycles=int(b['cnn_cycles']))
                     for a,b in zip(rows['baseline'],rows['candidate'])]
        if comparisons!=cached.get('comparisons'):return None
        if any(not 0<r['candidate_cycles']<r['baseline_cycles'] for r in comparisons):return None
        return dict(comparisons=comparisons,evidence_sha256=evidence)
    except (OSError,ValueError,KeyError,TypeError):
        # Missing, partial or changed evidence requires a fresh simulation.
        return None

def prepare_reference(jobdir,digest,env):
    """Overlap fresh reference synthesis with packaging; reuse only this attempt."""
    record=jobdir/'reference_hls_validation.json'
    script=jobdir/'tests/cnn_reference_synth.tcl'
    with (jobdir/'reference_hls.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if record.exists():
            cached=json.loads(record.read_text())
            if (cached.get('status')=='passed' and cached.get('source_manifest_sha256')==digest
                    and cached.get('script_sha256')==sha(script) and cached.get('files')
                    and all((jobdir/p).is_file() and sha(jobdir/p)==h for p,h in cached['files'].items())):
                return
            raise RuntimeError('Reference synthesis cache changed; preserve it before a fresh validation attempt')
        if (jobdir/'reference_hls').exists():
            raise RuntimeError('Unverified reference synthesis directory exists; preserve it before retrying')
        with (jobdir/'reference_hls.log').open('w') as f:
            subprocess.run(['vitis_hls','-f',str(script)],cwd=jobdir,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
        solution=jobdir/'reference_hls/solution1/syn'
        if not (solution/'verilog/cnn_wrapper.v').is_file() or not (solution/'report/cnn_wrapper_csynth.rpt').is_file():
            raise RuntimeError('Reference synthesis did not produce RTL and report')
        if verify_sources(jobdir)!=digest:raise RuntimeError('Reference sources changed during synthesis')
        save(record,dict(status='passed',source_manifest_sha256=digest,script_sha256=sha(script),
            finished_at=time.time(),files={str(p.relative_to(jobdir)):sha(p) for p in solution.rglob('*') if p.is_file()}))

def run(jobdir,reference_only=False,early=False):
    digest=verify_sources(jobdir)
    env=os.environ.copy();env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env['PATH'];env['DIRECT_JOB']=str(jobdir)
    env.update(DRIVER_RESETS='1', DIRECT_STARTUP_IDLE='20000', DIRECT_ALWAYS_READY='0')
    if reference_only:
        prepare_reference(jobdir,digest,env)
        print('PASS pristine reference HLS synthesis; full RTL gate still pending',flush=True)
        return 0
    output=jobdir/('direct_rtl_early' if early else 'direct_rtl');output.mkdir(exist_ok=False)
    status=dict(status='running',started_at=time.time(),source_manifest_sha256=digest,early_validation=early,
                driver_resets=1,startup_idle_cycles=20000)
    save(output/'status.json',status)
    try:
        if early:
            script=Path(__file__).parent/'tests/direct_preprocess_synth.tcl'
            if (jobdir/'preprocess_validation_hls').exists():raise RuntimeError('Preserve existing early preprocessing synthesis before retrying')
            status['preprocess_script_sha256']=sha(script)
            with (output/'preprocess_synthesis.log').open('w') as f:
                subprocess.run(['vitis_hls','-f',str(script)],cwd=jobdir,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
        prepare_reference(jobdir,digest,env)
        shutil.copy2(jobdir/'reference_hls_validation.json',output/'reference_synthesis.json')
        sources={}
        for kernel in ['preprocess_wrapper','cnn_wrapper']:
            root=jobdir/'preprocess_validation_hls' if early and kernel=='preprocess_wrapper' else jobdir/'build'
            found=list(root.rglob('solution1/syn/verilog/'+kernel+'.v'))
            if len(found)!=1:raise RuntimeError('Cannot identify synthesized '+kernel)
            sources[kernel]=found[0].parent
        sources['baseline']=jobdir/'reference_hls/solution1/syn/verilog'
        reuse=verified_early_result(jobdir,digest,sources) if not early else None
        if reuse is not None:
            for variant in ['baseline','candidate']:
                target=output/variant;target.mkdir()
                for name in ['sources.json','cycles.csv','check.log']:
                    shutil.copy2(jobdir/'direct_rtl_early'/variant/name,target/name)
            if verify_sources(jobdir)!=digest:raise RuntimeError('Prepared source changed during RTL reuse checks')
            status.update(status='passed',finished_at=time.time(),reused_from='direct_rtl_early',
                          validation_script_sha256=sha(Path(__file__)),**reuse)
            save(output/'status.json',status)
            print(json.dumps(status),flush=True)
            return 0
        for variant in ['baseline','candidate']:
            sim=output/variant;sim.mkdir()
            shutil.copytree(sources['preprocess_wrapper'],sim/'pp')
            shutil.copytree(sources['baseline' if variant=='baseline' else 'cnn_wrapper'],sim/'cnn')
            shutil.copy2(jobdir/'hw/src/hdl/elastic_fifo.sv',sim/'elastic_fifo.sv')
            for name in ['direct_pipe_tb.sv','direct_sim.tcl']:shutil.copy2(jobdir/'tests'/name,sim/name)
            shutil.copy2(jobdir/'reference_simulation/direct_expected.txt',sim/'direct_expected.txt')
            save(sim/'sources.json',{str(p.relative_to(sim)):sha(p) for p in sim.rglob('*') if p.is_file()})
            with (sim/'check.log').open('w') as f:
                subprocess.run(['vivado','-mode','batch','-source',str(sim/'direct_sim.tcl')],cwd=sim,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
        def rows(tag):
            with (output/tag/'cycles.csv').open() as f:return list(csv.DictReader(f))
        baseline,candidate=rows('baseline'),rows('candidate')
        if len(baseline)!=11 or [r['bytes'] for r in baseline]!=[r['bytes'] for r in candidate]:raise RuntimeError('Missing paired cycle cases')
        comparisons=[]
        for a,b in zip(baseline,candidate):
            old,new=int(a['cnn_cycles']),int(b['cnn_cycles'])
            if new>=old:raise RuntimeError(f"No full-CNN cycle reduction for bytes={a['bytes']}: {old}->{new}")
            comparisons.append(dict(bytes=int(a['bytes']),baseline_cycles=old,candidate_cycles=new))
        if verify_sources(jobdir)!=digest:raise RuntimeError('Prepared source changed during RTL checks')
        status.update(status='passed',comparisons=comparisons)
    except Exception as error:status.update(status='failed',error=str(error))
    status['finished_at']=time.time();save(output/'status.json',status)
    print(json.dumps(status),flush=True)
    return 0 if status['status']=='passed' else 1
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('jobdir',type=Path)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--reference-only',action='store_true');mode.add_argument('--early',action='store_true')
    a=p.parse_args();raise SystemExit(run(a.jobdir.resolve(),a.reference_only,a.early))
