"""Isolated full-CNN passive-tap diagnostic. No board access or build alerts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('source_job', type=Path)
    parser.add_argument('export_check', type=Path)
    args = parser.parse_args()
    root, source, export = (p.resolve() for p in (args.root, args.source_job, args.export_check))
    root.mkdir(exist_ok=False)
    state = dict(status='running', stage='prepare', pid=os.getpid(), started_at=time.time(),
                 hardware_build=False, source_job=str(source), export_check=str(export))
    save(root/'status.json', state)
    try:
        if json.loads((export/'status.json').read_text())['status'] != 'passed':
            raise RuntimeError('Packaged passive export has not passed')
        original = source/'rtl_validation/core'
        original_export = source/'build/iprepo/model_wrapper_hls_ip/hdl/verilog'
        ip = export/'iprepo/model_wrapper_hls_ip'
        manifest = json.loads((export/'source_manifest.json').read_text())
        if digest(original_export/'model_wrapper.v') != manifest['iprepo/model_wrapper_hls_ip/hdl/verilog/model_wrapper.v']:
            raise RuntimeError('Packaged top source changed since tap export validation')
        top = (ip/'hdl/verilog/model_wrapper.v').read_text()
        for name in ['fifo_tap_ports.vh', 'fifo_taps.vh']:
            addition = (export/'maintained'/name).read_text()
            if top.count(addition) != 1:
                raise RuntimeError('Unexpected tap additions')
            top = top.replace(addition, '', 1)
        if top != (original_export/'model_wrapper.v').read_text():
            raise RuntimeError('Taps changed existing generated logic')
        shutil.copytree(original, root/'core')
        # HLS export adds simulation-only deadlock monitors to its top. Include
        # the entire packaged RTL (and headers), retaining synthesis IP Tcl.
        for path in (ip/'hdl/verilog').iterdir():
            if path.is_file():
                shutil.copy2(path, root/'core'/path.name)
        for name in ['production_wrapper_tb.sv', 'production_wrapper_sim.tcl', 'production_passive_observer.svh']:
            shutil.copy2(HERE/'tests'/name, root/name)
        shutil.copy2(HERE/'hardware/production/passive_timestamps.sv', root/'passive_timestamps.sv')
        shutil.copy2(source/'rtl_expected.txt', root/'rtl_expected.txt')
        files = [p for p in root.rglob('*') if p.is_file() and p.name != 'status.json']
        hashes = {str(p.relative_to(root)): digest(p) for p in files}
        save(root/'source_manifest.json', hashes)
        state.update(stage='full_rtl', heartbeat=time.time())
        save(root/'status.json', state)
        env = os.environ.copy()
        env['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
        env['DRIVER_RESETS'] = '1'
        env.pop('PRODUCTION_RTL_FRAMES', None)
        with (root/'simulation.log').open('w') as log:
            child = subprocess.Popen(['vivado', '-mode', 'batch', '-source', str(root/'production_wrapper_sim.tcl')],
                                     cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            state['tool_pid'] = child.pid
            while child.poll() is None:
                state['heartbeat'] = time.time()
                save(root/'status.json', state)
                time.sleep(10)
            if child.returncode:
                raise RuntimeError(f'Vivado simulation returned {child.returncode}')
        output = (root/'simulation.log').read_text()
        frames = set(re.findall(r'PASS production passive frame=(\d+) bytes=(\d+) exact_pixels=65536', output))
        if len(frames) != 8 or 'PASS production wrapper frames=8 driver_resets=1' not in output:
            raise RuntimeError('Incomplete full-CNN timestamp/pixel/logit gate')
        if any(digest(root/name) != value for name, value in hashes.items()):
            raise RuntimeError('Diagnostic source changed during simulation')
        state.update(status='passed', frames=8, stage='complete')
    except Exception as error:
        state.update(status='failed', error=str(error))
    state['finished_at'] = time.time()
    save(root/'status.json', state)
    print(json.dumps(state), flush=True)
    return 0 if state['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
