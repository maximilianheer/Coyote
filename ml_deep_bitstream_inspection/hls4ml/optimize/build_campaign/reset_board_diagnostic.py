#!/usr/bin/env python3
"""Diagnostic A/B of driver reset with the same R_S bitstream; never a benchmark gate."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from board_benchmark import REPO, save, sha
from isolation_board import verified_bitstream

HERE = Path(__file__).resolve().parent


def run(job, board, output):
    state = dict(status='running', started_at=time.time(), pid=os.getpid(),
                 scope='Diagnostic only: same bitstream/runtime; suppress driver reset then restore standard driver',
                 benchmark_admitted=False)
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', COYOTE_ALLOC_TYPE='HPF')
    env['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:' + env.get('PATH', '')
    bit, source = verified_bitstream(job)
    standard = board/'software/driver/build/coyote_driver.ko'
    diagnostic = output/'driver_without_second_reset/build/coyote_driver.ko'
    state.update(bitstream_sha256=sha(bit), source_manifest_sha256=source,
                 standard_driver_sha256=sha(standard), diagnostic_driver_sha256=sha(diagnostic))
    save(output/'status.json', state)

    def command(stage, args, allowed=(0,)):
        state.update(stage=stage, stage_started_at=time.time()); save(output/'status.json', state)
        with (output/(stage+'.log')).open('w') as log:
            result = subprocess.run(args, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        if result.returncode not in allowed:
            raise RuntimeError(f'{stage} exited {result.returncode}')

    def program(stage, driver):
        command(stage, ['bash', str(REPO.parent/'util/program_hacc_local.sh'), str(bit), str(driver), '1'])
        save(board/'installed_image.json', dict(job='R_S', bitstream=str(bit), sha256=sha(bit),
             installed_at=time.time(), diagnostic=True, driver_sha256=sha(driver), reset_diagnostic=driver!=standard))

    def parity(label):
        target = output/label; target.mkdir(exist_ok=False)
        command(label, ['numactl', '--physcpubind=2', '--membind=0',
             str(REPO/'ml_baseline/.venv_hls4ml/bin/python'), str(HERE/'production_control.py'),
             str(board/'diagnostics/runtime_cases.tsv'), str(target),
             '--project', str(job/'runtime_project'), '--acceptance-tolerances', str(board/'production_tolerances.json')],
             allowed=(0, 1))
        return json.loads((target/'isolation_validation.json').read_text())

    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        if subprocess.check_output(['hostname'], text=True).strip() != 'hacc-u55c-03.inf.ethz.ch':
            raise RuntimeError('Wrong board host')
        kernel = subprocess.check_output(['uname', '-r'], text=True).strip()
        for driver in (standard, diagnostic):
            if not subprocess.check_output(['modinfo', '-F', 'vermagic', str(driver)], text=True).startswith(kernel+' '):
                raise RuntimeError('Driver/kernel mismatch')
        with (board/'board_device.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            devices = list(Path('/dev').glob('coyote*'))
            if devices and subprocess.run(['fuser', *map(str, devices)], capture_output=True).returncode != 1:
                raise RuntimeError('Board already in use')
            try:
                program('program_without_driver_reset', diagnostic)
                before = parity('without_driver_reset')
                state['without_driver_reset'] = dict(status=before['status'], failures=len(before['failures']), inputs=len(before['inputs']))
            finally:
                program('restore_standard_driver', standard)
                state['standard_driver_restored'] = True; save(output/'status.json', state)
            after = parity('with_standard_driver_reset')
            state['with_standard_driver_reset'] = dict(status=after['status'], failures=len(after['failures']), inputs=len(after['inputs']))
        if state['without_driver_reset'] != dict(status='passed', failures=0, inputs=26):
            raise RuntimeError('Suppressing the second reset did not restore complete parity')
        if state['with_standard_driver_reset'] != dict(status='failed', failures=260, inputs=26):
            raise RuntimeError('Standard-driver negative control did not reproduce all mismatches')
        state['status'] = 'passed'
    except Exception as error:
        state.update(status='failed', error=str(error))
    state['finished_at'] = time.time(); save(output/'status.json', state)
    print(json.dumps(state), flush=True)
    return int(state['status'] != 'passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path); parser.add_argument('board', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.job.resolve(), args.board.resolve(), args.output.resolve()))
