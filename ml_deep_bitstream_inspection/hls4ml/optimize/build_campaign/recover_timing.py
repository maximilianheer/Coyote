#!/usr/bin/env python3
"""Bounded implementation recovery, preserving every input and output attempt."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from prepare import verify_sources, sha
from worker import save, collect_artifacts, final_timing_reports

HERE = Path(__file__).resolve().parent
MAX_STRATEGIES = 4

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
                    started_at=time.time(), timing_recovery=strategy, recovery_output=str(output))
    save(progress_path, progress)
    try:
        manifest = verify_sources(jobdir)
        original = jobdir/'build'
        seed_name = {1:'shell_routed.dcp', 2:'shell_placed.dcp',
                     3:'shell_opted.dcp', 4:'shell_opted.dcp'}[strategy]
        seed = original/'checkpoints'/seed_name
        script = output/'recover_timing.tcl'
        shutil.copy2(HERE/'implementation/recover_timing.tcl', script)
        provenance = dict(source_manifest_sha256=manifest,
            seed=str(seed), seed_sha256=sha(seed), strategy=strategy,
            script_sha256=sha(script), clock_constraints_changed=False)
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
            progress.update(stage=stage, stage_started_at=time.time())
            save(progress_path, progress)
            with (output/(stage+'.log')).open('w') as log:
                result = subprocess.run(['vivado','-mode','batch',*args], cwd=output,
                    env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode: raise RuntimeError(f'{stage} exited {result.returncode}; see {output}/{stage}.log')
        command('timing_recovery', ['-source',str(script),'-tclargs',str(original/'base.tcl'),
            str(output),str(seed),str(strategy),*reference_args])
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
    except Exception as error:
        progress.update(status='failed',error=str(error))
        print(str(error),flush=True)
    progress['finished_at'] = time.time()
    save(progress_path,progress)
    save(output/'outcome.json',progress)
    return 0 if progress['status']=='passed' else 1

if __name__ == '__main__': sys.exit(run(Path(sys.argv[1]).resolve()))
