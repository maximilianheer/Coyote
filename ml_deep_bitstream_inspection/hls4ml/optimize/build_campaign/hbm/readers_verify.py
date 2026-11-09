#!/usr/bin/env python3
"""Build acceptance, including unchanged clocks/model and routed resources."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root):
    config = json.loads((root / 'config.json').read_text())
    pin = json.loads((root / 'model_clock_pin.json').read_text())
    assert json.loads((root / 'validation.json').read_text())['status'] == 'passed'
    assert sha(Path(pin['weights'])) == pin['weights_sha256']
    for section in ['cnn_sources', 'coyote_configuration', 'integration_helpers']:
        for path, expected in pin[section].items():
            assert sha(root / path) == expected, path
    report = root / 'build/reports/shell_timing_summary.rpt'
    text = report.read_text()
    assert not re.search(r'timing constraints are not met|not all user specified timing constraints are met', text, re.I)
    assert re.search(r'^\s*(?:All user specified )?Timing constraints are met\.?\s*$', text, re.I | re.M)
    clocks = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[1].startswith('{'):
            if fields[0] in ['clk_out1_design_hbm_clk_wiz_0_0', 'clk_out1_design_user_clk_wiz_0_0']:
                clocks[fields[0]] = float(fields[4])
    assert clocks['clk_out1_design_hbm_clk_wiz_0_0'] == 450
    # The application clock name follows the copied OPT_10 Coyote BD.
    user_lines = [line for line in text.splitlines() if '250.000' in line and line.strip().startswith('clk_')]
    assert user_lines, 'Missing 250 MHz application clock'
    packages = list((root / 'build').glob('*_config_0/user_c0_0/hdl/lynx_pkg.sv'))
    assert len(packages) == 1
    package = packages[0].read_text()
    for name, expected in [('N_OUTSTANDING', config['N_OUTSTANDING']), ('N_TLB_ACTV', config['N_TLB_ACTV']),
                           ('TLB_S_ORDER', 10), ('TLB_L_ORDER', 9), ('N_CARD_AXI', 1)]:
        match = re.search(rf'\b{name}\s*=\s*(\d+)\s*;', package)
        assert match and int(match[1]) == expected, (name, expected)
    xci = list((root / 'build').glob('**/design_hbm_clk_wiz_0_0.xci'))
    assert len(xci) == 1
    parameters = json.loads(xci[0].read_text())['ip_inst']['parameters']['component_parameters']
    assert float(parameters['CLKOUT1_REQUESTED_OUT_FREQ'][0]['value']) == 450
    hierarchy = root / 'build/reports/shell_utilization_hierarchical.rpt'
    areas = {}
    for line in hierarchy.read_text().splitlines():
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        if cells and cells[0] in ['cyt_top', 'inst_user_wrapper_0']:
            areas['full' if cells[0] == 'cyt_top' else 'application'] = dict(
                LUT=int(cells[4]), FF=int(cells[8]), BRAM_tiles=int(cells[9]) + int(cells[10]) / 2,
                URAM=int(cells[11]), DSP=int(cells[12]))
    assert len(areas) == 2
    bits = root / 'build/bitstreams/cyt_top.bit'
    assert bits.stat().st_size > 1000000
    sources = json.loads((root / 'source_hashes.json').read_text())
    # Existing source identities must survive synthesis. Tool-created new files
    # are allowed; source changes require a new registered repair attempt.
    for name, expected in sources.items():
        assert sha(root / name) == expected, 'Build modified sealed source: ' + name
    result = dict(status='passed', board_validated=False, id=config['id'], variant=config['variant'],
                  runtime_settings=config['runtime_settings'], clocks=clocks, resources=areas,
                  image=dict(path=str(bits), sha256=sha(bits), bytes=bits.stat().st_size),
                  timing_report_sha256=sha(report), hierarchy_sha256=sha(hierarchy),
                  validation_sha256=sha(root / 'validation.json'), unchanged_translation_cache_orders=[10, 9])
    (root / 'verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
