#!/usr/bin/env python3
"""Isolated C-sim/HLS/RTL validation of first-pixel launch; no board or ntfy."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from prepare import HERE, HARDWARE, sha, verify_sources
from worker import save


def run(job, variant, output):
    output.mkdir(parents=True, exist_ok=False)
    source_hash = verify_sources(job)
    state = dict(status='running', started_at=time.time(), pid=os.getpid(),
                 variant=variant, original_source_manifest_sha256=source_hash,
                 hardware_started=False, scope='C-sim, fresh HLS, second-reset RTL; no board changes')
    env = dict(os.environ, OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='1',
               FRAME_START_CHECK=str(output), DRIVER_RESETS='1',
               DIRECT_STARTUP_IDLE='20000', DIRECT_ALWAYS_READY='1')
    env['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:' + env.get('PATH', '')
    top = 'model_wrapper' if variant == 'R_S' else 'cnn_wrapper'
    env['FRAME_START_TOP'] = top

    def command(stage, args, cwd=output):
        state.update(stage=stage, stage_started_at=time.time())
        save(output/'status.json', state)
        with (output/(stage+'.log')).open('w') as log:
            subprocess.run(args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

    try:
        kernel = output/'kernel'
        shutil.copytree(job/'hw/src/hls'/top, kernel)
        shutil.copy2(HARDWARE/'common/frame_start.hpp', kernel/'frame_start.hpp')
        if variant == 'R_S':
            shutil.copy2(HARDWARE/'common/production_inference.hpp', kernel/'production_inference.hpp')
            test = 'production_wrapper_csim.cpp'
        else:
            shutil.copy2(HARDWARE/'variants/cnn_wrapper.cpp', kernel/'cnn_wrapper.cpp')
            test = 'direct_csim.cpp'
        shutil.copy2(HERE/'tests'/test, output/test)
        shutil.copy2(HERE/'tests/frame_start_synth.tcl', output/'frame_start_synth.tcl')
        inputs = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
        save(output/'sources.json', inputs)
        sources = [str(output/test), str(kernel/(top+'.cpp')),
                   str(kernel/'firmware/prod_res256_manualA_coyote_accel.cpp')]
        if variant == 'D_I':
            pp = job/'hw/src/hls/preprocess_wrapper/preprocess_wrapper.cpp'
            shutil.copy2(pp, output/pp.name)
            inputs[pp.name] = sha(output/pp.name)
            sources.append(str(output/pp.name))
        if variant == 'R_S':
            for name in ('cases.tsv', 'boundary_reference.txt'):
                shutil.copy2(job/'tests'/name, output/name)
                inputs[name] = sha(output/name)
        save(output/'sources.json', inputs)
        command('compile', ['g++', '-O1', '-std=c++14', '-Wno-unknown-pragmas',
            '-I/tools/Xilinx/Vitis/2024.2/include', '-I'+str(kernel),
            '-DWEIGHTS_DIR="'+str(kernel/'firmware/weights')+'"', *sources,
            '/usr/lib/x86_64-linux-gnu/libgmp.so.10', '-pthread', '-o', str(output/'parity')])
        args = [str(output/'parity')]
        if variant == 'R_S':
            args += [str(output/'cases.tsv'), str(output/'boundary_reference.txt')]
        command('csim', args)
        if variant == 'D_I' and (output/'direct_expected.txt').read_bytes() != (job/'reference_simulation/direct_expected.txt').read_bytes():
            raise RuntimeError('Changed CNN reference logits')
        command('hls', ['vitis_hls', '-f', str(output/'frame_start_synth.tcl')])
        sim = output/'rtl'; sim.mkdir()
        fresh = output/'hls/solution1/syn/verilog'
        if variant == 'R_S':
            shutil.copytree(fresh, sim/'core')
            names = ('production_wrapper_tb.sv', 'production_wrapper_sim.tcl')
            reference = 'rtl_expected.txt'; marker = 'PASS production wrapper frames=8'
        else:
            shutil.copytree(fresh, sim/'cnn')
            found = list((job/'build').rglob('solution1/syn/verilog/preprocess_wrapper.v'))
            if len(found) != 1:
                raise RuntimeError('Expected one unchanged preprocessing RTL source')
            shutil.copytree(found[0].parent, sim/'pp')
            shutil.copy2(HARDWARE/'direct/elastic_fifo.sv', sim/'elastic_fifo.sv')
            names = ('direct_pipe_tb.sv', 'direct_sim.tcl')
            reference = 'direct_expected.txt'; marker = 'PASS direct synthesized RTL parity: frames=11'
        for name in names:
            shutil.copy2(HERE/'tests'/name, sim/name)
        shutil.copy2(output/reference, sim/reference)
        rtl_inputs = {str(p.relative_to(sim)): sha(p) for p in sim.rglob('*') if p.is_file()}
        save(output/'rtl_sources.json', rtl_inputs)
        command('driver_reset_rtl', ['vivado', '-mode', 'batch', '-source', str(sim/names[1])], sim)
        log = (output/'driver_reset_rtl.log').read_text()
        if marker not in log or 'Fatal:' in log:
            raise RuntimeError('Incomplete second-reset RTL parity')
        if verify_sources(job) != source_hash:
            raise RuntimeError('Original attempt sources changed')
        if any(sha(output/name) != digest for name, digest in inputs.items()):
            raise RuntimeError('Validation inputs changed')
        if any(sha(sim/name) != digest for name, digest in rtl_inputs.items()):
            raise RuntimeError('RTL inputs changed')
        state.update(status='passed', driver_resets=1, startup_idle_cycles=20000,
                     rtl_frames=8 if variant == 'R_S' else 11)
    except Exception as error:
        state.update(status='failed', error=str(error))
    state['finished_at'] = time.time()
    save(output/'status.json', state)
    print(json.dumps(state), flush=True)
    return int(state['status'] != 'passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    parser.add_argument('variant', choices=['R_S', 'D_I'])
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.job.resolve(), args.variant, args.output.resolve()))
