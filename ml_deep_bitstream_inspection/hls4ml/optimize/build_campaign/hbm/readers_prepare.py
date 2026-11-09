#!/usr/bin/env python3
"""Create independent reader templates from the accepted OPT_10 snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
HARDWARE = HERE.parent / 'hardware'
BASE = REPO / 'hls4ml/optimize/runs/hbm_network_20261107/OPT_10_HBM_GATHER_DSP_B2_RF72_RF288/attempt_01'
VARIANTS = {
    14: ('OPT_14_HBM_SCAN', 'hbm_scan', [0]),
    15: ('OPT_15_HBM_COALESCED_GATHER', 'hbm_coalesced', [1, 2, 4, 8]),
    16: ('OPT_16_HBM_GATHER_OUTSTANDING128', 'hbm_gather', [32, 64, 128]),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(root):
    for variant, (ident, _, _) in VARIANTS.items():
        if (REPO / 'hls4ml/optimize/iterations' / ident).exists():
            raise RuntimeError('Iteration identifier is already registered: ' + ident)
        if any(path.name.startswith(f'OPT_{variant}_') for path in (REPO / 'hls4ml/optimize/iterations').iterdir()):
            raise RuntimeError(f'Iteration number {variant} is already registered')
    base_config = json.loads((BASE / 'config.json').read_text())
    weights = REPO / base_config['cnn_configuration']['model']['weights']
    assert sha(weights) == base_config['cnn_configuration']['model']['weights_sha256']
    for variant, (ident, kernel, settings) in VARIANTS.items():
        target = root / 'prepared' / ident
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(BASE / 'coyote', target / 'coyote', symlinks=False,
                        ignore=shutil.ignore_patterns('.Xil', '__pycache__'))
        shutil.copytree(BASE / 'hw', target / 'hw')
        for path in list((target / 'hw/src/hdl').iterdir()):
            path.unlink()
        source = target / 'hw/src'
        for path in (HARDWARE / 'hbm_readers').iterdir():
            if path.suffix in ['.sv', '.svh']:
                shutil.copy2(path, source / 'hdl')
        for path in [HARDWARE / 'deployment/cnn_instance.svh',
                     HARDWARE / 'direct/elastic_fifo.sv', HARDWARE / 'debug_probe.svh']:
            shutil.copy2(path, source / 'hdl')
        (source / 'vfpga_top.svh').write_text(
            f'`define DEPLOY_VARIANT {variant}\n`include "reader_checker.svh"\n`undef DEPLOY_VARIANT\n')
        if variant != 16:
            destination = source / 'hls' / kernel
            (source / 'hls/hbm_gather').rename(destination)
            (destination / 'hbm_gather.cpp').unlink()
            shutil.copy2(HARDWARE / 'hbm_readers' / f'{kernel}.cpp', destination)
            shutil.copy2(HARDWARE / 'hbm_readers/reader_preprocess.hpp', destination)
        config = dict(base_config)
        config.update(id=ident, variant=variant, abi=6, runtime_settings=settings,
                      kernels=['cnn_wrapper', kernel], N_OUTSTANDING=128 if variant == 16 else 32,
                      N_TLB_ACTV=128 if variant == 16 else 64, tracking=128 if variant == 16 else 4 if variant == 14 else 32,
                      source_reference=str(BASE), hbm_clock_mhz=450,
                      translation_cache_capacity_changed=False)
        packages = list((BASE / 'build').glob('*_config_0/user_c0_0/hdl/lynx_pkg.sv'))
        assert len(packages) == 1
        config['reference_package'] = str(packages[0])
        config['cpu_reference_library'] = str(BASE / 'hw/src/hls/cnn_wrapper/firmware/iteration_model-68668784.so')
        save(target / 'config.json', config)
        cmake = (BASE / 'hw/CMakeLists.txt').read_text()
        cmake = cmake.replace(str(BASE / 'coyote'), '${CMAKE_CURRENT_SOURCE_DIR}/../coyote')
        cmake = cmake.replace(base_config['id'].lower(), ident.lower())
        cmake = cmake.replace('set(N_OUTSTANDING 32)', f"set(N_OUTSTANDING {config['N_OUTSTANDING']})")
        cmake = cmake.replace('set(N_TLB_ACTV 64)', f"set(N_TLB_ACTV {config['N_TLB_ACTV']})")
        (target / 'hw/CMakeLists.txt').write_text(cmake)
        pin = dict(weights=str(weights), weights_sha256=sha(weights),
                   cnn_config=base_config['cnn_configuration'], app_clock_hz=250000000,
                   hbm_clock_mhz=450, memory_streams=1,
                   cnn_sources={str(path.relative_to(target)): sha(path)
                                for path in (source / 'hls/cnn_wrapper').rglob('*') if path.is_file()},
                   coyote_configuration={str(path.relative_to(target)): sha(path)
                                         for path in (target / 'coyote/cmake').rglob('*') if path.is_file()})
        pin['integration_helpers'] = {
            str(path.relative_to(target)): sha(path)
            for name in config['kernels']
            for path in (source / 'hls' / name).rglob('*')
            if path.is_file() and path.name in ['frame_start.hpp', 'sample_positions.hpp', 'hbm_samples.hpp']
        }
        pin['cpu_reference_library'] = dict(path=config['cpu_reference_library'],
                                           sha256=sha(Path(config['cpu_reference_library'])))
        if variant == 16:
            entry = source / 'hls/hbm_gather/hbm_gather.cpp'
            pin['integration_helpers'][str(entry.relative_to(target))] = sha(entry)
        save(target / 'model_clock_pin.json', pin)
        tooling = target / 'tooling'
        tooling.mkdir()
        for source_name, destination_name in [('readers_validate.py', 'validate.py'),
                                               ('readers_worker.py', 'worker.py'),
                                               ('readers_verify.py', 'verify.py')]:
            shutil.copy2(HERE / source_name, tooling / destination_name)
        for name in ['readers_pixel_test.cpp', 'readers_window_tb.sv']:
            shutil.copy2(HERE / name, tooling)
        shutil.copy2(HARDWARE / 'hbm_readers/reader_preprocess.hpp', tooling)
        shutil.copy2(HERE / 'readers_control_tb.sv', tooling)
        shutil.copy2(HERE.parent / 'tests/deployment_top_elaboration.sv', tooling / 'wiring.sv')
        with (tooling / 'wiring.sv').open('a') as output:
            for name in ['hbm_scan', 'hbm_coalesced']:
                output.write(f'''\nmodule {name}_hls_ip (
 input logic ap_clk, ap_rst_n,
 input logic [191:0] frame_TDATA, input logic frame_TVALID, output logic frame_TREADY,
 output logic [95:0] requests_TDATA, output logic requests_TVALID, input logic requests_TREADY,
 input logic [511:0] words_TDATA, input logic words_TVALID, output logic words_TREADY,
 output logic [15:0] pixels_TDATA, output logic pixels_TVALID, input logic pixels_TREADY
); endmodule\n''')
        save(target / 'status.json', dict(status='prepared', id=ident))
        registration = REPO / 'hls4ml/optimize/iterations' / ident
        registration.mkdir()
        save(registration / 'iteration.json', config)
        (registration / 'README.md').write_text(
            f'# {ident}\n\nRegistered 2026-11-08. Campaign: `{root}`.\n'
            f'Runtime settings: {settings}. CNN and clocks pinned to accepted OPT_10.\n')
        print('Prepared', target, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    prepare(parser.parse_args().root.resolve())
