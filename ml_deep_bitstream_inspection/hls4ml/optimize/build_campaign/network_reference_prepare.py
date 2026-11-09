#!/usr/bin/env python3
"""Prepare stock RDMA and minimal receive-to-HBM controls independently."""

import argparse
import json
from pathlib import Path
import shutil

from prepare import COYOTE, HERE, sha
from deployment_prepare import seal_sources
from worker import save


def prepare(root, hbm):
    ident = 'NET_REF_RDMA_HBM' if hbm else 'NET_REF_RDMA_STOCK'
    job = root / ident / 'attempt_01'
    job.mkdir(parents=True, exist_ok=False)
    # Use the existing sealed platform snapshot, including its pinned RoCE IP
    # sources and static checkpoint, so the controls isolate application changes.
    ancestor = root / 'OPT_12_NET_STREAMING/attempt_03'
    for relative, digest in json.loads((ancestor / 'source_hashes.json').read_text()).items():
        if sha(ancestor / relative) != digest:
            raise RuntimeError('Ancestor changed: ' + relative)
    shutil.copytree(ancestor / 'coyote', job / 'coyote')
    stock = COYOTE / 'examples/09_perf_rdma/hw'
    shutil.copytree(stock / 'src', job / 'hw/src')
    cmake = (stock / 'CMakeLists.txt').read_text()
    cmake = cmake.replace('set(CYT_DIR ${CMAKE_SOURCE_DIR}/../../../)',
                          f'set(CYT_DIR "{job / "coyote"}")')
    cmake = cmake.replace('project(example_09_perf_rdma)',
                          f'project({ident.lower()})\nset(FDEV_NAME "u55c")')
    if hbm:
        cmake = cmake.replace('validation_checks_hw()',
                              'set(EN_MEM 1)\nset(N_CARD_AXI 1)\nvalidation_checks_hw()')
        source = job / 'hw/src/vfpga_top.svh'
        text = source.read_text()
        old = 'sq_wr.data.strm = STRM_HOST;        // For RDMA, by definition data is always on the host'
        new = '''// Incoming WRITEs go to the mapped HBM buffer. READ responses
    // retain the stock host path; QP metadata and completion handling are native.
    sq_wr.data.strm = is_opcode_rd_resp(rq_wr.data.opcode) ? STRM_HOST : STRM_CARD;'''
        assert text.count(old) == 1
        text = text.replace(old, new)
        text = text.replace('sq_wr.data.dest = is_opcode_rd_resp(rq_wr.data.opcode) ? 0 : 1;',
                            'sq_wr.data.dest = 0;')
        text = text.replace('`AXISR_ASSIGN(axis_rrsp_recv[0], axis_host_send[1])',
                            '''`AXISR_ASSIGN(axis_rrsp_recv[0], axis_card_send[0])
always_comb axis_card_recv[0].tie_off_s();
always_comb axis_host_send[1].tie_off_m();''')
        source.write_text(text)
    (job / 'hw/CMakeLists.txt').write_text(cmake)
    save(job / 'config.json', {
        'id': ident, 'role': 'diagnostic', 'threads': 4,
        'clock_hz': 250000000, 'user_clock_hz': 250000000,
        'hbm_axi_mhz': 450, 'N_OUTSTANDING': 8, 'N_TLB_ACTV': 16,
        'PMTU_BYTES': 4096, 'application_hbm': hbm,
        'benchmark_eligible': False, 'kernels': [],
        'scope': 'Build control; board validation and benchmark timestamps pending',
    })
    (job / 'tooling').mkdir()
    for name in ['deployment_worker.py', 'network_timing.py', 'hbm_clock.py',
                 'implementation_permits.py', 'prepare.py', 'worker.py',
                 'deployment_ip_cache.py']:
        shutil.copy2(HERE / name, job / 'tooling' / name)
    seal_sources(job)
    save(job / 'reference_identity.json', {
        'stock_example': str(stock), 'platform_ancestor': str(ancestor),
        'stock_wrapper_sha256': sha(stock / 'src/vfpga_top.svh'),
        'prepared_wrapper_sha256': sha(job / 'hw/src/vfpga_top.svh'),
        'stock_wrapper_identical': not hbm,
        'changes': ['Enable one card stream; route incoming WRITE to CARD0'] if hbm else [],
        'platform_changes': 'None; inherited four-thread/reporting build adaptations',
    })
    save(job / 'status.json', {'id': ident, 'status': 'prepared', 'stage': 'preflight_pending'})
    print(job, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    arguments = parser.parse_args()
    for enabled in [False, True]:
        prepare(arguments.root.resolve(), enabled)
