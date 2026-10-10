"""R_SO_T preparation gates and passive packaging; no automatic board access."""
import json
from pathlib import Path
import re
import shutil

from prepare import HERE, HARDWARE, PACKAGE, sha
from worker import save


def prerequisites(state):
    from isolation_evidence import verified_board_parity
    spec = state['production_prerequisites']
    board = Path(spec['board']).resolve()
    result = {}
    for variant in ('R_O', 'R_S'):
        job = Path(spec[variant]['job']).resolve()
        if job.name != variant:
            raise ValueError('Prerequisite variant mismatch')
        result[variant] = verified_board_parity(job, board, Path(spec[variant]['evidence']).resolve())
        kernel = job/'hw/src/hls/model_wrapper'
        pairs = [('common/conv0_dataflow.hpp', 'conv0_dataflow.hpp')] if variant == 'R_O' else [
            ('variants/production_streaming.cpp', 'model_wrapper.cpp'),
            ('common/production_inference.hpp', 'production_inference.hpp'),
            ('common/frame_start.hpp', 'frame_start.hpp')]
        if any(sha(HARDWARE/source) != sha(kernel/target) for source, target in pairs):
            raise RuntimeError('Maintained candidate differs from board-validated prerequisite: '+variant)
    return result


def configure(dst, evidence):
    src = dst/'hw/src'
    snippets = src/'observer'; snippets.mkdir()
    for name in ['export_fifo_taps.tcl', 'package_campaign.tcl', 'fifo_tap_ports.vh',
                 'fifo_taps.vh', 'fifo_tap_ports.vhd.inc', 'fifo_taps.vhd.inc']:
        shutil.copy2(HARDWARE/'production'/name, snippets/name)
    shutil.copy2(HARDWARE/'production/vfpga_timed.svh', src/'vfpga_top.svh')
    shutil.copy2(HARDWARE/'production/passive_timestamps.sv', src/'hdl/passive_timestamps.sv')
    shutil.copy2(HERE/'tests/production_passive_observer.svh', dst/'tests/production_passive_observer.svh')
    # Keep the existing class layout and host implementation; add only read CSR.
    header = HERE/'runtime/production_host_libs.hpp'
    original = PACKAGE/'sources/generated_project/src/host_libs.hpp'
    if header.read_text().replace('    uint64_t read_csr(unsigned int index);\n', '') != original.read_text():
        raise RuntimeError('Read-only host header changes production class layout')
    shutil.copy2(header, dst/'host/host_libs.hpp')
    shutil.copy2(HERE/'runtime/production_host_csr.cpp', dst/'host/production_host_csr.cpp')
    script = dst/'coyote/scripts/cr_prjcts/cr_user.tcl.in'
    text = script.read_text()
    anchor = 'source "${CMAKE_BINARY_DIR}/base.tcl"'
    if text.count(anchor) != 1:
        raise RuntimeError('Coyote user-project initialization changed')
    script.write_text(text.replace(anchor, anchor+'\nsource "${CMAKE_SOURCE_DIR}/src/observer/package_campaign.tcl"'))
    save(src/'observer/prerequisites.json', evidence)


def rtl_inputs(jobdir, rtl):
    """Validate the exact tapped IP export imported into the Coyote project."""
    package = jobdir/'build/iprepo/model_wrapper_hls_ip/hdl/verilog'
    top = (package/'model_wrapper.v').read_text()
    original = top
    for name in ('fifo_tap_ports.vh', 'fifo_taps.vh'):
        addition = (jobdir/'hw/src/observer'/name).read_text()
        if original.count(addition) != 1:
            raise RuntimeError('Passive additions missing or ambiguous')
        original = original.replace(addition, '', 1)
    exports = list((jobdir/'build').glob('**/solution1/impl/ip/hdl/verilog/model_wrapper.v'))
    if len(exports) != 1 or original != exports[0].read_text():
        raise RuntimeError('Passive packaging changed existing HLS logic')
    for path in package.iterdir():
        if path.is_file(): shutil.copy2(path, rtl/'core'/path.name)
    shutil.copy2(jobdir/'tests/production_passive_observer.svh', rtl/'production_passive_observer.svh')
    shutil.copy2(jobdir/'hw/src/hdl/passive_timestamps.sv', rtl/'passive_timestamps.sv')
    save(rtl/'sources.json', {str(p.relative_to(rtl)):sha(p) for p in rtl.rglob('*') if p.is_file()})


def verify_rtl(jobdir, rtl):
    log = (jobdir/'wrapper_rtl.log').read_text()
    frames = set(re.findall(r'^PASS production passive frame=(\d+) bytes=\d+ exact_pixels=65536$',
                            log, re.M))
    if ('PASS production wrapper frames=8 driver_resets=1' not in log or
            frames != {str(i) for i in range(8)} or 'Fatal:' in log):
        raise RuntimeError('Incomplete combined parity/reset/timestamp RTL gate')
    hashes = json.loads((rtl/'sources.json').read_text())
    if any(sha(rtl/name) != digest for name, digest in hashes.items()):
        raise RuntimeError('Combined RTL validation inputs changed')
