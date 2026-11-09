#!/usr/bin/env python3
"""Prepare independent HBM/network deployment attempts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from prepare import HERE, HARDWARE, copy_coyote, sha
from worker import save
from hbm_clock import configure_hbm_clock

NETWORK_REVISION = '37b59d3828b003d2d6f7dd9748824a0e39d99167'
REPO = HERE.parents[2]
CNN_REFERENCE = REPO / 'hls4ml/optimize/runs/combined_fifo1024_b2_20261013/OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288/attempt_01'
FINAL_VARIANTS = {
    10: ('OPT_10_HBM_GATHER_DSP_B2_RF72_RF288', 'hbm_checker.svh'),
    11: ('OPT_11_HBM_GPU_P2P_R06', 'hbm_gpu.svh'),
    12: ('OPT_12_NET_STREAMING', 'network_checker.svh'),
    13: ('OPT_13_NET_GPU_P2P_R06', 'network_gpu.svh'),
}


def prepare_final(root, network, variant, attempt='attempt_01', clock_mhz=250,
                  hbm_clock_mhz=450):
    ident, wrapper = FINAL_VARIANTS[variant]
    source_template = HARDWARE / 'deployment' / wrapper
    if not source_template.exists():
        raise RuntimeError('Wrapper implementation is not ready: ' + wrapper)
    job = root / ident / attempt
    job.mkdir(parents=True, exist_ok=False)
    network_enabled = variant >= 12
    cnn_enabled = variant in (10, 12)
    config = {
        'id': ident, 'variant': variant, 'abi': 5, 'threads': 4,
        'hbm_enabled': True, 'rdma_enabled': network_enabled,
        'N_OUTSTANDING': 32, 'N_TLB_ACTV': 64, 'PMTU_BYTES': 4096,
        'clock_hz': clock_mhz * 1000000, 'hbm_axi_mhz': hbm_clock_mhz,
        'user_clock_hz': clock_mhz * 1000000,
        'max_raw_bytes': 134217664,
        'hardware_validated': False,
    }
    if cnn_enabled:
        cnn_config = json.loads((CNN_REFERENCE / 'config/iteration.json').read_text())
        config['cnn_configuration'] = cnn_config
        weights = REPO / cnn_config['model']['weights']
        if sha(weights) != cnn_config['model']['weights_sha256']:
            raise RuntimeError('Pinned CNN weights changed')
        # This cache is a generated compiler artifact. Verify it before copying
        # into the new self-contained iteration, including its configuration.
        generated = json.loads((CNN_REFERENCE / 'generated_manifest.json').read_text())
        for name, expected in generated.items():
            if sha(CNN_REFERENCE / name) != expected:
                raise RuntimeError('Invalid validated CNN cache: ' + name)
        config['cnn_cache_fingerprint'] = sha(CNN_REFERENCE / 'generated_manifest.json')
        shutil.copytree(CNN_REFERENCE / 'config', job / 'cnn_config')
        for name in ['generated_manifest.json', 'fifo_profile_inputs.json',
                     'model_parity.json', 'generator_identity.json', 'hls_config.json']:
            shutil.copy2(CNN_REFERENCE / name, job / name)
        config['kernels'] = ['cnn_wrapper', 'hbm_gather' if variant == 10 else 'network_preprocess']
    else:
        config['gpu_configuration'] = json.loads((REPO / 'hls4ml/optimize/iterations/OPT_9_GPU_P2P_DMA32/iteration.json').read_text())
        config['gpu_runtime_selection'] = 'R06_XLA_ConcreteFunction_FP32'
        config['kernels'] = []
    save(job / 'config.json', config)
    copy_coyote(job / 'coyote')
    if network_enabled:
        revision = subprocess.check_output(['git', '-C', str(network), 'rev-parse', 'HEAD'], text=True).strip()
        if revision != NETWORK_REVISION:
            raise RuntimeError('Network dependency differs from pinned revision')
        shutil.copytree(network, job / 'coyote/hw/services/network',
                        ignore=shutil.ignore_patterns('.git'), dirs_exist_ok=True)
    base = job / 'coyote/scripts/base.tcl.in'
    base.write_text(base.read_text().replace('general.maxThreads 8', 'general.maxThreads 4'))
    source = job / 'hw/src'
    (source / 'hdl').mkdir(parents=True)
    shutil.copy2(source_template, source / 'vfpga_top.svh')
    for path in (HARDWARE / 'deployment').glob('*'):
        if path.suffix in ('.sv', '.svh'):
            shutil.copy2(path, source / 'hdl')
    for path in [HARDWARE / 'direct/elastic_fifo.sv', HARDWARE / 'gpu/gpu_poll.sv',
                 HARDWARE / 'debug_probe.svh']:
        shutil.copy2(path, source / 'hdl')
    shutil.copy2(HARDWARE / 'init_ip.tcl', source / 'init_ip.tcl')
    if cnn_enabled:
        for kernel in config['kernels']:
            target = source / 'hls' / kernel
            target.mkdir(parents=True)
            shutil.copytree(CNN_REFERENCE / 'generated/firmware', target / 'firmware')
            # The cached stock model remains unchanged. New integration helpers
            # live beside it, never in nnet_utils or generated convolution code.
            for name in ['model_types.hpp', 'nnet_axi_utils_stream.h']:
                shutil.copy2(HERE / 'iteration_templates' / name, target / name)
            shutil.copy2(HARDWARE / 'common/frame_start.hpp', target)
            shutil.copy2(HARDWARE / 'common/sample_positions.hpp', target)
            for name in ['hbm_samples.hpp', 'preprocess_stream.hpp']:
                shutil.copy2(HARDWARE / 'deployment' / name, target)
            template = HERE / 'iteration_templates/cnn_wrapper.cpp' if kernel == 'cnn_wrapper' else HARDWARE / 'deployment' / (kernel + '.cpp')
            shutil.copy2(template, target / (kernel + '.cpp'))
            shutil.copy2(CNN_REFERENCE / 'hw/src/hls/cnn_wrapper/firmware/zero_in_raw_downsample.hpp', target / 'firmware')
    (job / 'hw/CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.5)
set(CYT_DIR "{job / 'coyote'}")
set(CMAKE_MODULE_PATH "${{CYT_DIR}}/cmake")
find_package(CoyoteHW REQUIRED)
project({ident.lower()})
set(FDEV_NAME "u55c")
set(N_REGIONS 1)
set(N_CONFIG 1)
set(EN_PR 0)
set(EN_MEM 1)
set(EN_STRM 1)
set(EN_RDMA {int(network_enabled)})
set(EN_TCP 0)
set(EN_SNIFFER 0)
set(N_CARD_AXI 1)
set(N_STRM_AXI 2)
set(N_RDMA_AXI 1)
set(EN_NET_0 1)
set(EN_NET_1 0)
set(N_OUTSTANDING 32)
set(N_TLB_ACTV 64)
set(PMTU_BYTES 4096)
set(HBM_SPLIT 0)
set(COMP_CORES 4)
set(BUILD_OPT 1)
set(ACLK_F {clock_mhz})
set(UCLK_F {clock_mhz})
validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
    if hbm_clock_mhz != 450:
        configure_hbm_clock(job, hbm_clock_mhz)
    seal_sources(job)
    save(job / 'status.json', {'id': ident, 'status': 'prepared', 'validation': 'pending'})
    return job


def seal_sources(job):
    save(job / 'source_hashes.json', {
        str(path.relative_to(job)): sha(path)
        for folder in ['hw', 'coyote']
        for path in (job / folder).rglob('*') if path.is_file()
    })


def prepare_diagnostic(root, network, attempt='attempt_01', clock_mhz=250,
                       hbm_clock_mhz=450):
    revision = subprocess.check_output(
        ['git', '-C', str(network), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != NETWORK_REVISION:
        raise RuntimeError('Network dependency differs from pinned revision')
    job = root / 'NET_DIAG_HBM' / attempt
    job.mkdir(parents=True, exist_ok=False)
    config = {
        'id': 'NET_DIAG_HBM', 'role': 'diagnostic', 'abi': 'NETD/1',
        'network_revision': revision, 'threads': 4,
        'hbm_enabled': True, 'rdma_enabled': True, 'qsfp': 0,
        'N_OUTSTANDING': 32, 'N_TLB_ACTV': 64, 'PMTU_BYTES': 4096,
        'benchmark_eligible': False,
        'clock_hz': clock_mhz * 1000000, 'hbm_axi_mhz': hbm_clock_mhz,
        'user_clock_hz': clock_mhz * 1000000,
    }
    save(job / 'config.json', config)
    copy_coyote(job / 'coyote')
    shutil.copytree(network, job / 'coyote/hw/services/network',
                    ignore=shutil.ignore_patterns('.git'), dirs_exist_ok=True)
    base = job / 'coyote/scripts/base.tcl.in'
    base.write_text(base.read_text().replace('general.maxThreads 8', 'general.maxThreads 4'))
    source = job / 'hw/src'
    (source / 'hdl').mkdir(parents=True)
    shutil.copy2(HARDWARE / 'deployment/net_diag.svh', source / 'vfpga_top.svh')
    shutil.copy2(HARDWARE / 'deployment/diagnostic_control.sv', source / 'hdl')
    shutil.copy2(HARDWARE / 'debug_probe.svh', source / 'hdl')
    shutil.copy2(HARDWARE / 'init_ip.tcl', source / 'init_ip.tcl')
    (job / 'hw/CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.5)
set(CYT_DIR "{job / 'coyote'}")
set(CMAKE_MODULE_PATH "${{CYT_DIR}}/cmake")
find_package(CoyoteHW REQUIRED)
project(net_diag_hbm)
set(FDEV_NAME "u55c")
set(N_REGIONS 1)
set(N_CONFIG 1)
set(EN_PR 0)
set(EN_MEM 1)
set(EN_STRM 1)
set(EN_RDMA 1)
set(EN_TCP 0)
set(EN_SNIFFER 0)
set(N_CARD_AXI 1)
set(N_STRM_AXI 2)
set(N_RDMA_AXI 1)
set(EN_NET_0 1)
set(EN_NET_1 0)
set(N_OUTSTANDING 32)
set(N_TLB_ACTV 64)
set(PMTU_BYTES 4096)
set(HBM_SPLIT 0)
set(COMP_CORES 4)
set(BUILD_OPT 1)
set(ACLK_F {clock_mhz})
set(UCLK_F {clock_mhz})
validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
    if hbm_clock_mhz != 450:
        configure_hbm_clock(job, hbm_clock_mhz)
    seal_sources(job)
    save(job / 'status.json', {'id': 'NET_DIAG_HBM', 'status': 'prepared'})
    return job


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--network', required=True, type=Path)
    parser.add_argument('--variant', type=int, choices=FINAL_VARIANTS)
    parser.add_argument('--attempt', default='attempt_01')
    parser.add_argument('--clock-mhz', type=int, choices=[200, 250], default=250)
    parser.add_argument('--hbm-clock-mhz', type=int, choices=[350, 400, 450], default=450)
    arguments = parser.parse_args()
    if arguments.variant:
        print(prepare_final(arguments.root.resolve(), arguments.network.resolve(), arguments.variant,
                            arguments.attempt, arguments.clock_mhz, arguments.hbm_clock_mhz))
    else:
        print(prepare_diagnostic(arguments.root.resolve(), arguments.network.resolve(),
                                 arguments.attempt, arguments.clock_mhz, arguments.hbm_clock_mhz))
