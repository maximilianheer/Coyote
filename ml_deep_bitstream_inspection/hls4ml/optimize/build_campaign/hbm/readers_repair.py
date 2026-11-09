#!/usr/bin/env python3
"""Prepare and execute isolated, unchanged-clock reader timing repairs."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from implementation_permits import permit
from hbm_clock import verify_report_application_clock, verify_report_hbm_clock


def sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def prepare(old, new, narrow, resume=False):
    sources = json.loads((old / 'source_hashes.json').read_text())
    for name, expected in sources.items():
        assert sha(old / name) == expected, name
    if not resume:
        shutil.copytree(old, new)
        archive = new / 'repair_ancestor_evidence'
        archive.mkdir()
        for path in list(new.iterdir()):
            if path.is_file() and (path.suffix == '.log' or path.name in
                                   ['status.json', 'validation.json', 'artifacts.json',
                                    'verification.json', 'restart_watch.json']):
                shutil.move(str(path), archive / path.name)
        if (new / 'validation').exists():
            shutil.move(str(new / 'validation'), archive / 'validation')
        # Project administration is relocated; sealed source bytes stay unchanged.
        for path in (new / 'build').rglob('*'):
            if path.is_file() and path.suffix in ['.tcl', '.xpr', '.xci', '.bd', '.xml',
                                                   '.json', '.sh', '.prj', '.txt', '.dep']:
                data = path.read_bytes()
                if b'\0' not in data and str(old).encode() in data:
                    path.write_bytes(data.replace(str(old).encode(), str(new).encode()))
        probe = new / 'recovery_project_probe.tcl'
        probe.write_text(probe.read_text().replace(str(old), str(new)))
    else:
        assert (new / 'repair_ancestor_evidence').is_dir()
        assert not (new / 'repair_identity.json').exists()
        assert not (new / 'status.json').exists()
    if narrow:
        relative = 'hw/src/hdl/reader_window.sv'
        path = new / relative
        text = path.read_text()
        if 'wire [63:0] retired' in text:
            start = text.index('    wire [63:0] retired')
            end = text.index('    wire request_fire', start)
            text = text[:start] + '''    // Each independent retirement stream can lag by at most TRACKING.
        // Low-bit subtraction is exact modulo 2*TRACKING for legal traffic,
        // including counter wrap. Keep full 64-bit telemetry separately.
        wire [INDEX_BITS:0] pending_data = issued[INDEX_BITS:0] - response_requests[INDEX_BITS:0];
        wire [INDEX_BITS:0] pending_cq = issued[INDEX_BITS:0] - completed[INDEX_BITS:0];
        wire [INDEX_BITS:0] outstanding = pending_data > pending_cq ? pending_data : pending_cq;
        logic [INDEX_BITS:0] peak_active;
        assign peak_outstanding = 64'(peak_active);
        wire credit = outstanding < window_limit;
    ''' + text[end:]
            text = text.replace('            peak_outstanding <= 0;', '            peak_active <= 0;')
            text = text.replace("            if (outstanding + 64'(request_fire) > peak_outstanding)\n                peak_outstanding <= outstanding + 64'(request_fire);",
                                "            if (outstanding + (INDEX_BITS+1)'(request_fire) > peak_active)\n                peak_active <= outstanding + (INDEX_BITS+1)'(request_fire);")
            assert 'retired' not in text and 'peak_outstanding <=' not in text
            path.write_text(text)
        generated = list((new / 'build').glob('**/reader_window.sv'))
        assert len(generated) == 1
        generated[0].write_text(text)
        pin = json.loads((new / 'model_clock_pin.json').read_text())
        pin['integration_helpers'][relative] = sha(path)
        save(new / 'model_clock_pin.json', pin)
        # Compare every handshake and telemetry output with the original RTL.
        reference = (old / relative).read_text().replace('module reader_window #',
                                                        'module reader_window_reference #')
        (new / 'tooling/reader_window_reference.sv').write_text(reference)
        tb = new / 'tooling/readers_window_tb.sv'
        outputs = ['descriptor_ready', 'request_valid', 'request_address', 'request_bytes',
                   'response_ready', 'word_valid', 'word_data', 'idle', 'error', 'issued',
                   'received_words', 'completed', 'response_requests', 'requested_bytes',
                   'peak_outstanding', 'request_stalls', 'credit_stalls', 'response_backpressure']
        extra = '\n'.join(f'    wire [$bits({name})-1:0] reference_{name};' for name in outputs)
        extra += '\n    reader_window_reference #(.TRACKING(`TRACKING_VALUE)) reference_reader(\n'
        extra += ',\n'.join(f'        .{name}(reference_{name})' for name in outputs)
        extra += ',\n        .*);\n    always @(negedge clk) begin\n        #1;\n        if (rst_n) begin\n'
        for name in outputs:
            extra += f'            assert({name} === reference_{name}) else $fatal(1, "Reference mismatch: {name}");\n'
        extra += '        end\n    end\n'
        body = (old / 'tooling/readers_window_tb.sv').read_text().replace('        if (`TRACKING_VALUE == 128) begin',
            '        if (`TRACKING_VALUE == 32) begin\n'
            '            frame(32, 0);\n            frame(32, 1);\n        end\n'
            '        if (`TRACKING_VALUE == 128) begin')
        tb.write_text(body.replace('    reader_window #', extra + '\n    reader_window #'))
        validator = new / 'tooling/validate.py'
        code = (old / 'tooling/validate.py').read_text().replace('for tracking in [4, 128]:', 'for tracking in [4, 32, 128]:')
        code = code.replace("str(root / 'hw/src/hdl/reader_window.sv'), str(root / 'tooling/readers_window_tb.sv')",
                            "str(root / 'hw/src/hdl/reader_window.sv'), str(root / 'tooling/reader_window_reference.sv'), str(root / 'tooling/readers_window_tb.sv')")
        validator.write_text(code)
    tooling = Path(__file__).resolve().parents[1]
    shutil.copy2(Path(__file__), new / 'tooling/readers_recovery_worker.py')
    for name in ['implementation_permits.py', 'hbm_clock.py']:
        shutil.copy2(tooling / name, new / 'tooling' / name)
    if not narrow:
        text = (tooling / 'implementation/recover_timing.tcl').read_text()
        (new / 'repair_timing.tcl').write_text(text.replace('general.maxThreads 8', 'general.maxThreads 4'))
    changed = [name for name, digest in sources.items() if sha(new / name) != digest]
    assert changed == (['hw/src/hdl/reader_window.sv'] if narrow else []), changed
    save(new / 'source_hashes.json', {name: sha(new / name) for name in sources})
    save(new / 'repair_identity.json', {
        'ancestor': str(old), 'mode': 'resynthesize_user' if narrow else 'physical',
        'changed_sources': changed, 'clocks_changed': False, 'cnn_changed': False,
        'corrective_hardware_attempt': 1,
        'seed_sha256': sha(old / 'build/checkpoints/shell_routed.dcp'),
        'tool_hashes': {path.name: sha(path) for path in (new / 'tooling').glob('*') if path.is_file()},
    })
    save(new / 'status.json', {'id': json.loads((new / 'config.json').read_text())['id'],
                             'status': 'prepared', 'stage': 'repair_validation_pending'})
    print(new, flush=True)


def run(root):
    config = json.loads((root / 'config.json').read_text())
    repair = json.loads((root / 'repair_identity.json').read_text())
    state = {'id': config['id'], 'pid': os.getpid(), 'status': 'running',
             'stage': 'validation', 'started_at': time.time(),
             'process_marker': 'readers_recovery_worker.py', 'hardware_validated': False}

    def progress(**values):
        state.update(values)
        save(root / 'status.json', state)

    def command(stage, arguments, directory):
        progress(stage=stage, stage_started_at=time.time())
        with (root / (stage + '.log')).open('w') as log:
            child = subprocess.Popen(arguments, cwd=directory, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            progress(child_pid=child.pid)
            try:
                code = child.wait(timeout=86400)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise RuntimeError(f'{stage}: 24-hour timeout')
        if code:
            raise RuntimeError(f'{stage}: exit {code}')

    progress()
    try:
        sources = json.loads((root / 'source_hashes.json').read_text())
        for name, digest in sources.items():
            assert sha(root / name) == digest, name
        command('validate', [sys.executable, str(root / 'tooling/validate.py'), str(root)], root)
        vivado = '/tools/Xilinx/Vivado/2024.2/bin/vivado'
        command('project_probe', [vivado, '-mode', 'batch', '-source',
                                 str(root / 'recovery_project_probe.tcl'), '-notrace'], root)
        with permit(progress):
            progress(implementation_started_at=time.time())
            build = root / 'build'
            if repair['mode'] == 'physical':
                command('timing_recovery', [vivado, '-mode', 'batch', '-source',
                    str(root / 'repair_timing.tcl'), '-tclargs', str(build / 'base.tcl'),
                    str(build), str(Path(repair['ancestor']) / 'build/checkpoints/shell_routed.dcp'), '1'], build)
            else:
                for stage, filename in [('synth_user', 'synth_user.tcl'), ('link', 'link.tcl'),
                                         ('shell', 'pnr_shell.tcl')]:
                    command(stage, [vivado, '-mode', 'batch', '-source', str(build / filename), '-notrace'], build)
            report = build / 'reports/shell_timing_summary.rpt'
            assert 'All user specified timing constraints are met.' in report.read_text()
            verify_report_application_clock(report, 250)
            verify_report_hbm_clock(report, 450)
            command('bitgen', [vivado, '-mode', 'batch', '-source', str(build / 'bitgen.tcl'), '-notrace'], build)
            command('verify', [sys.executable, str(root / 'tooling/verify.py'), str(root)], root)
            assert json.loads((root / 'verification.json').read_text())['status'] == 'passed'
            for name, digest in sources.items():
                assert sha(root / name) == digest, name
            files = [root / name for name in ['verification.json', 'validation.json',
                     'source_hashes.json', 'repair_identity.json', 'model_clock_pin.json']]
            files += list((build / 'bitstreams').glob('*')) + list((build / 'reports').glob('*.rpt'))
            save(root / 'artifacts.json', {'files': {str(path.relative_to(root)): sha(path)
                                                    for path in files if path.is_file()},
                                         'hardware_validated': False})
            progress(status='passed', stage='complete', finished_at=time.time())
    except Exception as error:
        progress(status='failed', error=str(error), finished_at=time.time())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', nargs=2, type=Path)
    parser.add_argument('--narrow-window', action='store_true')
    parser.add_argument('--resume-preparation', action='store_true')
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(*(path.resolve() for path in args.prepare), args.narrow_window, args.resume_preparation)
    else:
        with (args.run.resolve() / 'worker.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run(args.run.resolve())
