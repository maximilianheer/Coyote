#!/usr/bin/env python3
"""Replay the preserved S_I HBM checker; diagnostic results never unlock benchmarks."""
import argparse
import csv
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from prepare import REPO, sha, verify_sources
from worker import save, validate_timing_report
from parity_gate import as_float, check_logit, load_tolerances
from benchmark import components


def run(job, board, output):
    output.mkdir(parents=True, exist_ok=False)
    state = dict(status='running', stage='verify', pid=os.getpid(), started_at=time.time(),
                 diagnostic=True, benchmark_gate_unchanged=True)
    def record(**values):
        state.update(values); save(output/'status.json', state)
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    env['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:'+env.get('PATH', '')
    def command(stage, args, timeout=900):
        record(stage=stage, stage_started_at=time.time())
        with (output/(stage+'.log')).open('w') as log:
            proc = subprocess.Popen(args, cwd=REPO, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, preexec_fn=os.setpgrp)
            record(child_pid=proc.pid)
            try:
                while proc.poll() is None:
                    record(heartbeat=time.time())
                    if time.time()-state['stage_started_at'] > timeout:
                        raise TimeoutError(stage+' timeout')
                    time.sleep(1)
            except BaseException:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                raise
            if proc.returncode: raise RuntimeError(f'{stage} exited {proc.returncode}')
    try:
        if subprocess.check_output(['hostname'], text=True).strip() != 'hacc-u55c-03.inf.ethz.ch':
            raise RuntimeError('Wrong board host')
        progress = json.loads((job/'progress.json').read_text())
        if progress['status'] != 'passed': raise RuntimeError('S_I hardware build incomplete')
        digest = verify_sources(job)
        validation = json.loads((job/'validation.json').read_text())
        if validation['status'] != 'passed' or validation['source_manifest_sha256'] != digest:
            raise RuntimeError('Source validation mismatch')
        for report in progress['artifacts']['timing_reports']: validate_timing_report(Path(report))
        bit = job/'build/bitstreams/cyt_top.bit'
        driver = board/'software/driver/build/coyote_driver.ko'
        kernel = subprocess.check_output(['uname', '-r'], text=True).strip()
        if not subprocess.check_output(['modinfo', '-F', 'vermagic', str(driver)], text=True).startswith(kernel+' '):
            raise RuntimeError('Driver/kernel mismatch')
        tolerances = load_tolerances(board/'production_tolerances.json')
        cases = []
        for line in (board/'diagnostics/runtime_cases.tsv').read_text().splitlines():
            name, kind, path, size, digest_input, expected = line.split('\t')
            if sha(Path(path)) != digest_input or Path(path).stat().st_size != int(size):
                raise RuntimeError('Input identity mismatch')
            cases.append(dict(id=name, path=path, bytes=int(size), sha256=digest_input,
                              expected_logit_hex=expected))
        if len(cases) != 26 or len(tolerances) != 26: raise RuntimeError('Incomplete references')
        host = output/'host'; host.mkdir()
        for name in ['host_bench.cpp', 'CMakeLists.txt']:
            shutil.copy2(job/'host'/name, host/name)
        record(bitstream=str(bit), bitstream_sha256=sha(bit), source_manifest_sha256=digest,
               host_source_sha256=sha(host/'host_bench.cpp'), driver_sha256=sha(driver),
               cases_sha256=sha(board/'diagnostics/runtime_cases.tsv'),
               tolerance_sha256=sha(board/'production_tolerances.json'))
        command('configure', ['cmake', '-S', str(host), '-B', str(output/'build'),
                              '-DCOYOTE_SW='+str(REPO.parent/'sw')])
        command('compile', ['cmake', '--build', str(output/'build'), '--parallel', '2'])
        record(executable_sha256=sha(output/'build/opt_bench'),
               coyote_library_sha256=sha(output/'build/coyote/libcoyote.so'))
        results = []
        with (board/'board_device.lock').open('a') as lock:
            record(stage='waiting_board'); fcntl.flock(lock, fcntl.LOCK_EX)
            devices = list(Path('/dev').glob('coyote*'))
            if devices and subprocess.run(['fuser', *map(str, devices)], capture_output=True).returncode != 1:
                raise RuntimeError('Board ownership check failed')
            command('program', ['bash', str(REPO.parent/'util/program_hacc_local.sh'), str(bit), str(driver), '1'])
            pci = Path('/sys/bus/pci/devices/0000:c4:00.0')
            if (pci/'current_link_width').read_text().strip() != '16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):
                raise RuntimeError('Unexpected PCIe link')
            save(board/'installed_image.json', dict(job='S_I', bitstream=str(bit), sha256=sha(bit),
                 installed_at=time.time(), diagnostic=True))
            for case in cases:
                path = output/(case['id']+'.csv')
                command('parity_'+case['id'], ['numactl', '--physcpubind=2', '--membind=0',
                    str(output/'build/opt_bench'), case['path'], str(path), '10', '0'], timeout=180)
                rows = list(csv.DictReader(path.open()))
                if len(rows) != 10: raise RuntimeError('Incomplete S_I trials')
                for row in rows:
                    if int(row['variant']) != 6 or int(row['abi_version']) != 2:
                        raise RuntimeError('Wrong S_I ABI')
                    if int(row['input_bytes']) != case['bytes'] or int(row['input_beats'])*64 != int(row['transport_bytes']):
                        raise RuntimeError('S_I byte/beat count mismatch')
                    components(row)  # Validate tokens, completion flags and event ordering.
                    bits = int(row['result_bits']); value = as_float(bits)
                    verdict = int(value >= 0)
                    error = None
                    try: check_logit(bits, verdict, case, tolerances[case['sha256']])
                    except ValueError as exc: error = str(exc)
                    results.append(dict(case=case['id'], trial=int(row['trial']),
                        result_hex=f'{bits:08x}', expected_hex=case['expected_logit_hex'],
                        verdict=verdict, verdict_match=math.isfinite(value) and verdict == int(as_float(int(case['expected_logit_hex'],16))>=0),
                        exact=bits == int(case['expected_logit_hex'],16), accepted=error is None, error=error))
                save(output/'results.json', results)
                record(completed_cases=len(results)//10, completed_calls=len(results))
        exact = sum(r['exact'] for r in results); flips = sum(not r['verdict_match'] for r in results)
        result = dict(status='passed' if all(r['accepted'] for r in results) else 'failed',
            calls=len(results), exact_logits=exact, verdict_flips=flips, diagnostic=True,
            scope='Preserved S_I: host LOCAL_OFFLOAD to HBM, FPGA card read, original streaming wrapper, CSR logit',
            repetitions=10, inputs=26, **{k:state[k] for k in ['bitstream_sha256','source_manifest_sha256',
            'host_source_sha256','driver_sha256','cases_sha256','tolerance_sha256','executable_sha256','coyote_library_sha256']})
        save(output/'parity_summary.json', result)
        record(status=result['status'], stage='complete', exact_logits=exact, verdict_flips=flips)
    except Exception as error:
        record(status='failed', error=str(error)); print(str(error), flush=True)
    record(finished_at=time.time())
    return 0 if state['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['job', 'board', 'output']: parser.add_argument(name, type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.job.resolve(), args.board.resolve(), args.output.resolve()))
