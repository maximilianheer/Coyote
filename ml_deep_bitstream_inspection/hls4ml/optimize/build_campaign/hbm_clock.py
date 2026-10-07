"""Explicit HBM AXI clock fallback for fresh, isolated U55C attempts."""
import hashlib
import json
import re


def verify_generated_hbm_clock(build, mhz):
    records = {}
    for ip, fields in [('clk_wiz_0_0', ['CLKOUT1_REQUESTED_OUT_FREQ']),
                       ('hbm_inst_0', ['USER_AXI_CLK_FREQ', 'USER_AXI_CLK1_FREQ'])]:
        paths = list(build.glob(f'**/design_hbm_{ip}.xci'))
        if len(paths) != 1:
            raise RuntimeError(f'Expected one generated HBM {ip} IP configuration')
        parameters = json.loads(paths[0].read_text())['ip_inst']['parameters']['component_parameters']
        for field in fields:
            if float(parameters[field][0]['value']) != mhz:
                raise RuntimeError('Generated HBM clock mismatch: '+field)
        if ip == 'clk_wiz_0_0':
            def value(name): return float(parameters[name][0]['value'])
            actual = (value('PRIM_IN_FREQ') * value('MMCM_CLKFBOUT_MULT_F') /
                      value('MMCM_DIVCLK_DIVIDE') / value('MMCM_CLKOUT0_DIVIDE_F'))
            if abs(actual-mhz) > 0.001:
                raise RuntimeError(f'Generated MMCM produces {actual} MHz, expected {mhz}')
        records[str(paths[0])] = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    return records


def verify_report_hbm_clock(report, mhz):
    for line in report.read_text().splitlines():
        values = line.split()
        if len(values) == 5 and values[0] == 'clk_out1_design_hbm_clk_wiz_0_0' and values[1].startswith('{'):
            if abs(float(values[3])-1000/mhz) <= 0.001 and abs(float(values[4])-mhz) <= 0.001:
                return
            raise RuntimeError('Final routed HBM clock differs from configured frequency')
    raise RuntimeError('Missing HBM clock in final routed timing report')


def configure_hbm_clock(jobdir, mhz):
    if mhz != 400:
        raise ValueError('Only the 400 MHz fallback is supported')
    coyote = jobdir/'coyote'
    cmake = coyote/'cmake/FindCoyoteHW.cmake'
    text = cmake.read_text()
    start = text.index('if(FDEV_NAME STREQUAL "u55c")')
    position = text.index('set(HCLK_F 450)', start)
    text = text[:position] + text[position:].replace('set(HCLK_F 450)', 'set(HCLK_F 400)', 1)
    cmake.write_text(text)
    bd = coyote/'hw/bd/ultrascale_plus/cr_hbm.tcl'
    text, count = re.subn(
        r'(?m)^ set_property -dict \[list CONFIG\.CLKOUT1_REQUESTED_OUT_FREQ \{450\.000\}[^\n]*\[get_bd_cells clk_wiz_0\][ \t]*$',
        ' set_property -dict [list CONFIG.CLKOUT1_REQUESTED_OUT_FREQ [format "%.3f" $cnfg(hclk_f)] CONFIG.USE_LOCKED {false} CONFIG.USE_RESET {false}] [get_bd_cells clk_wiz_0]',
        bd.read_text())
    if count != 1:
        raise RuntimeError('Expected exactly one hard-coded HBM clock generator')
    bd.write_text(text)
    # The HBM IP USER_AXI_CLK{,1}_FREQ and BD port metadata already consume
    # cnfg(hclk_f). Removing fixed MMCM ratios lets Clocking Wizard derive them.
    evidence = dict(hbm_axi_mhz=mhz, previous_hbm_axi_mhz=450,
        checker_clock_changed=False,
        files={str(p.relative_to(jobdir)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [cmake, bd]})
    (jobdir/'hw/hbm_clock.json').write_text(json.dumps(evidence, indent=2))


def verify_hbm_clock_sources(jobdir):
    evidence = jobdir/'hw/hbm_clock.json'
    if evidence.exists():
        for relative, expected in json.loads(evidence.read_text())['files'].items():
            if hashlib.sha256((jobdir/relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError('HBM clock source changed: '+relative)


def hbm_setup_failure(report):
    """Only classify a complete report whose failures are HBM-domain setup."""
    text = report.read_text(errors='replace')
    if 'Timing constraints are not met.' not in text:
        return False
    groups = re.findall(
        r'From Clock:\s*(\S+)\s+To Clock:\s*(\S+)\s+'
        r'Setup\s*:\s*(\d+)\s+Failing Endpoints[^\n]*\n'
        r'Hold\s*:\s*(\d+)\s+Failing Endpoints[^\n]*\n'
        r'PW\s*:\s*(\d+)\s+Failing Endpoints', text)
    failures = 0
    for source, destination, setup, hold, pulse in groups:
        if int(hold) or int(pulse):
            return False
        if int(setup):
            if source != 'clk_out1_design_hbm_clk_wiz_0_0' or destination != source:
                return False
            failures += int(setup)
    lines = text.splitlines()
    try:
        index = next(i for i, line in enumerate(lines) if line.lstrip().startswith('WNS(ns)'))
        values = lines[index+2].split()
        return failures > 0 and failures == int(values[2]) and float(values[4]) >= 0 and float(values[8]) >= 0
    except (StopIteration, IndexError, ValueError):
        return False
