#!/usr/bin/env python3
"""Bounded implementation recovery, preserving every input and output attempt."""
import json
import fcntl
from contextlib import contextmanager
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from prepare import verify_sources, sha
from worker import save, collect_artifacts, final_timing_reports, seal_artifacts

HERE = Path(__file__).resolve().parent
MAX_STRATEGIES = 4
BOUNDARY_CELL = ('inst_shell/inst_shell_data_cc/genblk1[1].inst_s0_axis_dyn_in/'
    'genblk1[2].inst_reg/inst_reg_slice/inst/axisc_register_slice_0/state_reg[0]')

@contextmanager
def implementation_slot(jobdir, job, progress, progress_path):
    """Share the board-host memory permit with initial isolation builds."""
    if job['id'] not in ('R_O','R_S','R_SO_T','D_I','D_N','D_G'):
        yield
        return
    capacity = jobdir.parents[1]/'parallel_implementation.json'
    if capacity.exists():
        policy = json.loads(capacity.read_text())
        if (policy.get('host') != socket.gethostname() or
                job['id'] not in policy.get('jobs', []) or
                policy.get('max_jobs') != 2):
            raise RuntimeError('Parallel implementation policy does not match this host/job')
        while True:
            fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
            if int(fields['MemAvailable'].split()[0])*1024 >= 64*2**30:
                break
            progress.update(stage='waiting_memory_recovery');save(progress_path,progress)
            time.sleep(30)
        yield
        return
    progress.update(stage='waiting_memory_recovery');save(progress_path,progress)
    with (jobdir.parents[1]/'implementation.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        while True:
            fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
            available=int(fields['MemAvailable'].split()[0])*1024
            if available>=18*2**30:break
            progress.update(available_memory_bytes=available);save(progress_path,progress)
            time.sleep(30)
        yield

def boundary_guidance(jobdir, job, manifest):
    """Use measured placement guidance only for this exact failing setup path."""
    config = jobdir/'boundary_placement_guidance.json'
    if job['id'] != 'D_I' or job['timing_recovery'] != 1 or not config.exists():
        return None
    guidance = json.loads(config.read_text())
    if guidance.get('source_manifest_sha256') != manifest:
        return None
    if (guidance.get('cell') != BOUNDARY_CELL or
            not re.fullmatch(r'SLICE_X[0-9]+Y[0-9]+', guidance.get('loc', ''))):
        raise RuntimeError('Invalid boundary placement guidance')
    report = jobdir/'build/reports/shell_timing_summary.rpt'
    text = report.read_text()
    matched = False
    for block in re.split(r'(?=Slack \()', text):
        source = re.search(r'(?m)^\s*Source:\s*(\S+)', block)
        destination = re.search(r'(?m)^\s*Destination:\s*(\S+)', block)
        if (block.startswith('Slack (VIOLATED)') and source and destination
                and source.group(1) in (BOUNDARY_CELL+'/C', BOUNDARY_CELL+'/Q')
                and destination.group(1).startswith('inst_static/inst_cnvrt_static/')
                and re.search(r'Path Type:\s*Setup', block)
                and re.search(r'Path Group:\s*xclk\s*\n', block)):
            matched = True
            break
    if not matched:
        return None
    evidence = guidance.get('evidence', [])
    if not evidence:
        raise RuntimeError('Missing boundary placement evidence')
    for item in evidence:
        if sha(Path(item['path'])) != item['sha256']:
            raise RuntimeError('Boundary placement evidence changed')
    baseline = Path(guidance['baseline_stdout'])
    if str(baseline) not in {item['path'] for item in evidence}:
        raise RuntimeError('Unhashed boundary placement evidence')
    baseline_text = baseline.read_text()
    record = f"CELL {{{BOUNDARY_CELL}}} LOC {guidance['loc']} "
    margins = re.findall(r'Slack \(MET\)\s*:\s*([0-9.]+)ns', baseline_text)
    if (not any(line.startswith(record) for line in baseline_text.splitlines())
            or not margins or min(map(float, margins)) <= 0):
        raise RuntimeError('Baseline does not demonstrate the proposed placement')
    return dict(cell=BOUNDARY_CELL, loc=guidance['loc'],
        guidance_sha256=sha(config), failing_report_sha256=sha(report),
        evidence=evidence, baseline_stdout=str(baseline))

def best_reference(jobdir, manifest):
    """Choose completed physical data from this source attempt, never another variant."""
    candidates = []
    original = jobdir/'build'
    shell_log = jobdir/'shell.log'
    if shell_log.exists() and '[100%] Built target shell' in shell_log.read_text(errors='replace'):
        candidates.append(original)
    for directory in sorted((jobdir/'recovery').glob('route_*')):
        try:
            outcome = json.loads((directory/'outcome.json').read_text())
            provenance = json.loads((directory/'provenance.json').read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if (provenance.get('source_manifest_sha256') == manifest and
                outcome.get('finished_at') and
                (outcome.get('status') == 'passed' or
                 outcome.get('error', '').startswith('Timing failure:'))):
            candidates.append(directory)
    ranked = []
    for directory in candidates:
        checkpoint = directory/'checkpoints/shell_routed.dcp'
        report = directory/'reports/shell_timing_summary.rpt'
        if not checkpoint.is_file() or not checkpoint.stat().st_size or not report.is_file():
            continue
        text = report.read_text()
        if not any(marker in text for marker in
                   ['Timing constraints are not met.', 'All user specified timing constraints are met.']):
            continue
        lines = text.splitlines()
        try:
            index = next(i for i, line in enumerate(lines) if line.lstrip().startswith('WNS(ns)'))
            values = lines[index+2].split()
            wns, whs = float(values[0]), float(values[4])
        except (StopIteration, IndexError, ValueError):
            continue
        if math.isfinite(wns) and math.isfinite(whs):
            ranked.append((min(wns, whs), checkpoint,
                           dict(wns_ns=wns, whs_ns=whs, report=str(report),
                                report_sha256=sha(report))))
    if not ranked:
        raise RuntimeError('No completed same-source checkpoint available for incremental recovery')
    _, checkpoint, details = max(ranked, key=lambda item:item[0])
    return checkpoint, details

def run(jobdir):
    job = json.loads((jobdir/'job.json').read_text())
    strategy = job['timing_recovery']
    output = jobdir/'recovery'/f'route_{strategy:02d}'
    output.mkdir(parents=True, exist_ok=False)
    progress_path = jobdir/'progress.json'
    if progress_path.exists(): shutil.copy2(progress_path, output/'previous_progress.json')
    progress = dict(status='running', stage='timing_recovery', pid=os.getpid(),
                    started_at=time.time(), timing_recovery=strategy, recovery_output=str(output),
                    hardware_started=False)
    save(progress_path, progress)
    try:
        manifest = verify_sources(jobdir)
        original = jobdir/'build'
        guidance = boundary_guidance(jobdir, job, manifest)
        seed_name = {1:'shell_routed.dcp', 2:'shell_placed.dcp',
                     3:'shell_opted.dcp', 4:'shell_opted.dcp'}[strategy]
        if guidance:
            seed_name = 'shell_opted.dcp'
        seed = original/'checkpoints'/seed_name
        script = output/'recover_timing.tcl'
        shutil.copy2(HERE/'implementation/recover_timing.tcl', script)
        provenance = dict(source_manifest_sha256=manifest,
            seed=str(seed), seed_sha256=sha(seed), strategy=strategy,
            script_sha256=sha(script), clock_constraints_changed=False)
        if guidance:
            provenance['boundary_placement_guidance'] = guidance
        reference_args = []
        if strategy == 4:
            reference, details = best_reference(jobdir, manifest)
            provenance['incremental_reference'] = dict(path=str(reference),
                sha256=sha(reference), **details)
            reference_args = [str(reference)]
        save(output/'provenance.json', provenance)
        env = os.environ.copy()
        env['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
        def command(stage, args):
            with implementation_slot(jobdir,job,progress,progress_path):
                progress.update(stage=stage, stage_started_at=time.time(), hardware_started=True)
                save(progress_path, progress)
                with (output/(stage+'.log')).open('w') as log:
                    result = subprocess.run(['vivado','-mode','batch',*args], cwd=output,
                        env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode: raise RuntimeError(f'{stage} exited {result.returncode}; see {output}/{stage}.log')
        mode = 'boundary_relocation' if guidance else str(strategy)
        extra_args = ['', guidance['cell'], guidance['loc']] if guidance else reference_args
        command('timing_recovery', ['-source',str(script),'-tclargs',str(original/'base.tcl'),
            str(output),str(seed),mode,*extra_args])
        final_timing_reports(output, job['id'])
        if job.get('hbm_axi_mhz'):
            from hbm_clock import verify_report_hbm_clock
            verify_report_hbm_clock(output/'reports/shell_timing_summary.rpt', job['hbm_axi_mhz'])
        # Bitgen reopens the new routed checkpoint and exercises the real ILA.
        for name in ['bitstreams','logs']: (output/name).mkdir()
        base = output/'base.tcl'
        base.write_text(f'source {{{original / "base.tcl"}}}\n'
            f'set dcp_dir {{{output / "checkpoints"}}}\n'
            f'set rprt_dir {{{output / "reports"}}}\n'
            f'set bit_dir {{{output / "bitstreams"}}}\n'
            f'set log_dir {{{output / "logs"}}}\n')
        source = (original/'bitgen.tcl').read_text()
        source, count = re.subn(r'(?m)^source "[^"\n]+/base\.tcl"$',
                               'source {'+str(base)+'}',source)
        if count != 1: raise RuntimeError('Cannot isolate bitgen base.tcl')
        (output/'bitgen.tcl').write_text(source)
        command('bitgen', ['-source',str(output/'bitgen.tcl')])
        if verify_sources(jobdir) != manifest: raise RuntimeError('Source hashes changed')
        progress.update(status='passed',stage='complete',
            artifacts=collect_artifacts(output,job['id']),hardware_validated=False)
        progress['artifacts']['sha256']={p:sha(Path(p)) for p in progress['artifacts']['bitstreams']}
        seal_artifacts(jobdir,progress['artifacts'])
    except Exception as error:
        progress.update(status='failed',error=str(error))
        print(str(error),flush=True)
    progress['finished_at'] = time.time()
    save(progress_path,progress)
    save(output/'outcome.json',progress)
    # Persist actual build outcomes even when the scheduler immediately retries.
    if job['id'] in ('D_I','D_N','D_G','R_O','R_S','R_SO_T') and progress['hardware_started']:
        entry=dict(key=f"{job['id']}:{job.get('attempt',1)}:{strategy}:{progress['status']}",
            message=f"Hardware build {job['id']} attempt {job.get('attempt',1)}, routing strategy {strategy} {progress['status']}: {progress.get('error','bitstreams and routed timing passed')}. Logs: {output}")
        with (jobdir.parents[1]/'hardware_outcomes.jsonl').open('a') as f:
            f.write(json.dumps(entry)+'\n')
    return 0 if progress['status']=='passed' else 1

if __name__ == '__main__': sys.exit(run(Path(sys.argv[1]).resolve()))
