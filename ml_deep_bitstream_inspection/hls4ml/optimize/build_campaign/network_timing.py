"""Verify coupled Coyote clocks and target measured Ethernet control fanout."""

import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path


def user_register_source(report):
    """Find the user-clock ARP slice in this configuration's generated RTL."""
    build = report.parent.parent
    job = build if (build / 'config.json').exists() else build.parent
    visited = set()
    while job not in visited:
        visited.add(job)
        paths = list((job / 'build').glob('*_shell/hdl/dynamic_top.sv'))
        if len(paths) == 1:
            path = paths[0]
            matches = [number for number, line in enumerate(path.read_text().splitlines(), 1)
                       if 'meta_reg_array' in line and 'ARP_LUP_REQ_BITS' in line
                       and '.aclk(uclk)' in line]
            if len(matches) != 1:
                raise RuntimeError('Cannot identify generated user-clock ARP slice')
            return path, matches[0]
        config = json.loads((job / 'config.json').read_text())
        if not config.get('recovery_of'):
            break
        job = Path(config['recovery_of'])
    raise RuntimeError('Missing generated RTL for user-clock audit')


def verify_generated_control_clocks(build, application_mhz, user_mhz):
    paths = list(build.glob('**/design_ctrl_clk_wiz_0_0.xci'))
    if len(paths) != 1:
        raise RuntimeError('Expected one Coyote control clock generator')
    path = paths[0]
    parameters = json.loads(path.read_text())['ip_inst']['parameters']['component_parameters']

    def value(name):
        return float(parameters[name][0]['value'])

    vco = value('PRIM_IN_FREQ') * value('MMCM_CLKFBOUT_MULT_F') / value('MMCM_DIVCLK_DIVIDE')
    actual = {}
    for output, divider, expected in [
        (1, 'MMCM_CLKOUT0_DIVIDE_F', application_mhz),
        (2, 'MMCM_CLKOUT1_DIVIDE', 250),
        (3, 'MMCM_CLKOUT2_DIVIDE', user_mhz),
    ]:
        frequency = vco / value(divider)
        requested = value(f'CLKOUT{output}_REQUESTED_OUT_FREQ')
        if abs(frequency - expected) > 0.001 or abs(requested - expected) > 0.001:
            raise RuntimeError(f'Control clock output {output}: actual={frequency}, expected={expected}')
        actual[str(output)] = frequency
    if application_mhz != user_mhz:
        raise RuntimeError('Direct ARP control path requires matched application/user clocks')
    return {'frequencies_mhz': actual, 'xci': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_report_user_clock(report, mhz):
    for line in report.read_text().splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] == 'clk_out3_design_ctrl_clk_wiz_0_0' and fields[1].startswith('{'):
            if abs(float(fields[3]) - 1000 / mhz) <= 0.001 and abs(float(fields[4]) - mhz) <= 0.001:
                return
            raise RuntimeError('Routed user clock differs from configured frequency')
    # Vivado merges equivalent generated clocks. When application and user
    # clocks match, CLKOUT3 can disappear from the clock-summary table. Verify
    # the clock propagated to the user-domain ARP registers in the routed
    # netlist. The boundary port itself can also disappear during optimization.
    checkpoint = report.parent.parent / 'checkpoints/shell_routed.dcp'
    if not checkpoint.is_file():
        raise RuntimeError('Missing routed checkpoint for user-clock audit')
    directory = report.parent / 'user_clock_audit'
    directory.mkdir(exist_ok=True)
    source, line_number = user_register_source(report)
    script = directory / 'verify.tcl'
    script.write_text(
        'set_param general.maxThreads 4\n'
        f'open_checkpoint {{{checkpoint.resolve()}}}\n'
        f'set cells [get_cells -hier -filter {{NAME =~ inst_shell/inst_dynamic/nolabel_line{line_number}/* && REF_NAME =~ FD*}}]\n'
        'if {[llength $cells] == 0} {error "User ARP register slice cells missing"}\n'
        'set pins [get_pins -of_objects $cells -filter {REF_PIN_NAME == C}]\n'
        'if {[llength $pins] == 0} {error "User ARP register clock pins missing"}\n'
        'set clocks [get_clocks -of_objects $pins]\n'
        'if {[llength $clocks] != 1} {error "Expected one propagated user clock"}\n'
        'set period [get_property PERIOD $clocks]\n'
        f'if {{abs($period - {1000 / mhz}) > 0.001}} {{error "User period mismatch"}}\n'
        'puts [list VERIFIED_USER_CLOCK [get_property NAME $clocks] $period]\n'
        'close_design\nexit 0\n'
    )
    with (directory / 'stdout.log').open('w') as log:
        process = subprocess.Popen(
            ['/tools/Xilinx/Vivado/2024.2/bin/vivado', '-mode', 'batch',
             '-source', str(script.resolve()), '-log', 'vivado.log',
             '-journal', 'vivado.jou'],
            cwd=directory, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError('Read-only user-clock audit timed out')
    lines = (directory / 'stdout.log').read_text().splitlines()
    verified = [line for line in lines if line.startswith('VERIFIED_USER_CLOCK ')]
    if code or len(verified) != 1:
        raise RuntimeError('Cannot verify routed user-clock alias')
    evidence = {
        'status': 'passed', 'expected_mhz': mhz, 'routed_clock': verified[0],
        'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
        'generated_rtl': str(source), 'arp_slice_line': line_number,
        'generated_rtl_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    (directory / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')


def install_ethernet_control_replication(job):
    path = job / 'build/pnr_shell.tcl'
    contents = path.read_text()
    marker = 'write_checkpoint -force "$dcp_dir/shell_phys_opted.dcp"'
    if contents.count(marker) != 1:
        raise RuntimeError('Cannot locate pre-route physical optimization boundary')
    # Measured path: Ethernet padding register-slice state -> >500 data bits.
    # Restrict replication to those data-control FFs; leave clock/reset trees alone.
    repair = '''
set padding_cells [get_cells -hier -filter {NAME =~ inst_shell/inst_network_top/inst_network_module/ethernet_frame_padding_inst/* && NAME =~ *FSM_sequential_state_reg* && REF_NAME =~ FD*}]
set padding_nets [get_nets -of_objects [get_pins -of_objects $padding_cells -filter {REF_PIN_NAME == Q}]]
set padding_targets {}
set padding_evidence [open "$rprt_dir/ethernet_padding_replication.txt" w]
foreach net [lsort -unique $padding_nets] {
    set loads [get_pins -leaf -of_objects $net -filter {DIRECTION == IN}]
    if {[llength $loads] >= 64} {
        lappend padding_targets $net
        puts $padding_evidence [list $net fanout [llength $loads]]
    }
}
close $padding_evidence
if {[llength $padding_targets] == 0} { error "Measured Ethernet padding control nets not found" }
phys_opt_design -force_replication_on_nets $padding_targets
'''
    path.write_text(contents.replace(marker, repair + '\n' + marker))
