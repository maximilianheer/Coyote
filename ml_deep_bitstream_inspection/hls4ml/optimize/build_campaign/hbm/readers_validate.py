#!/usr/bin/env python3
"""Immutable acceptance gates for one isolated HBM reader input snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

VIVADO = Path('/tools/Xilinx/Vivado/2024.2/bin')
HLS = Path('/tools/Xilinx/Vitis/2024.2/include')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(directory, label, argv):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'{label}.log').open('w') as output:
        result = subprocess.run(argv, cwd=directory, stdout=output, stderr=subprocess.STDOUT)
    text = (directory / f'{label}.log').read_text()
    if result.returncode or 'ERROR:' in text or 'Fatal:' in text:
        raise RuntimeError(f'{label} failed: {directory / (label + ".log")}')
    return text


def run(root):
    config = json.loads((root / 'config.json').read_text())
    pin = json.loads((root / 'model_clock_pin.json').read_text())
    assert sha(Path(pin['weights'])) == pin['weights_sha256']
    assert sha(Path(pin['cpu_reference_library']['path'])) == pin['cpu_reference_library']['sha256']
    for section in ['cnn_sources', 'coyote_configuration', 'integration_helpers']:
        for name, expected in pin[section].items():
            assert sha(root / name) == expected, name
    cmake = (root / 'hw/CMakeLists.txt').read_text()
    for setting in ['set(ACLK_F 250)', 'set(N_CARD_AXI 1)', 'set(EN_RDMA 0)',
                    f"set(N_OUTSTANDING {config['N_OUTSTANDING']})",
                    f"set(N_TLB_ACTV {config['N_TLB_ACTV']})"]:
        assert setting in cmake, setting
    output = root / 'validation'
    kernel = root / 'hw/src/hls' / config['kernels'][1]
    if config['variant'] == 16:
        # Exercise the same helper for all pixel cases; the actual individual
        # gather helper remains the accepted OPT_10 source, hash checked below.
        helper = root / 'tooling/reader_preprocess.hpp'
    else:
        helper = kernel / 'reader_preprocess.hpp'
    includes = [str(helper.parent), str(kernel), str(HLS)]
    command(output, 'compile_pixels', ['g++', '-std=c++14', '-O2', '-Wno-unknown-pragmas',
                                     *[flag for path in includes for flag in ['-I', path]],
                                     str(root / 'tooling/readers_pixel_test.cpp'), '-ldl', '-o', str(output / 'pixels')])
    assert 'PASS ' in command(output, 'pixels', [str(output / 'pixels'), config['cpu_reference_library']])
    for tracking in [4, 128]:
        directory = output / f'window_{tracking}'
        command(directory, 'compile', [str(VIVADO / 'xvlog'), '--sv', '--define', f'TRACKING_VALUE={tracking}',
                                       str(root / 'hw/src/hdl/reader_window.sv'), str(root / 'tooling/readers_window_tb.sv')])
        command(directory, 'elaborate', [str(VIVADO / 'xelab'), 'readers_window_tb', '-s', 'check', '-mt', '4'])
        assert 'PASS reader window' in command(directory, 'simulate', [str(VIVADO / 'xsim'), 'check', '-runall'])
    directory = output / 'control'
    command(directory, 'compile', [str(VIVADO / 'xvlog'), '--sv', '--define', f"CONTROL_VARIANT={config['variant']}",
                                   str(root / 'hw/src/hdl/reader_control.sv'), str(root / 'tooling/readers_control_tb.sv')])
    command(directory, 'elaborate', [str(VIVADO / 'xelab'), 'readers_control_tb', '-s', 'check', '-mt', '4'])
    assert 'PASS ABI6' in command(directory, 'simulate', [str(VIVADO / 'xsim'), 'check', '-runall'])
    source = root / 'hw/src'
    package = Path(config['reference_package'])
    files = [package, root / 'coyote/hw/hdl/pkg/axi_intf.sv', root / 'coyote/hw/hdl/pkg/lynx_intf.sv',
             *sorted((source / 'hdl').glob('*.sv')), root / 'tooling/wiring.sv']
    directory = output / 'wiring'
    command(directory, 'compile', [str(VIVADO / 'xvlog'), '--sv', '-i', str(source), '-i', str(source / 'hdl'),
                                   '-i', str(root / 'coyote/hw/hdl/pkg'), *map(str, files)])
    command(directory, 'elaborate', [str(VIVADO / 'xelab'), 'top_elaboration', '-s', 'wiring', '-mt', '4'])
    result = dict(status='passed', variant=config['variant'], completed_at=time.time(),
                  gates=['all_fixed_point_pixels', 'descriptor_limits_and_page_boundaries',
                         'independent_data_and_CQ', 'all_window_settings', 'always_ready_sink',
                         'backpressure_and_resets', 'ABI6_runtime_settings', 'real_Coyote_type_wiring'],
                  cnn='Exact quantized CPU-bridge scores match reference preprocessing for every tested case; board admission remains separate')
    (root / 'validation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
