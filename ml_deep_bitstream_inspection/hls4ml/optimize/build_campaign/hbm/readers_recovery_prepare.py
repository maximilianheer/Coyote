#!/usr/bin/env python3
"""Copy interrupted reader work into an isolated, auditable continuation."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(ancestor, destination, validation_cache=None):
    if destination.exists():
        raise RuntimeError(f'Refusing to overwrite {destination}')
    sources = json.loads((ancestor / 'source_hashes.json').read_text())
    for relative, expected in sources.items():
        if sha(ancestor / relative) != expected:
            raise RuntimeError(f'Ancestor source changed: {relative}')
    validation = json.loads((ancestor / 'validation.json').read_text())
    if validation['status'] != 'passed':
        raise RuntimeError('Ancestor validation did not pass')
    shutil.copytree(ancestor, destination, symlinks=False)
    archive = destination / 'ancestor_evidence'
    archive.mkdir()
    # Keep inherited logs/status separate; all continuation logs are new files.
    for path in list(destination.iterdir()):
        if path.is_file() and (path.suffix == '.log' or path.name in (
            'status.json', 'validation.json', 'source_hashes.json',
        )):
            shutil.move(str(path), archive / path.name)
    build = destination / 'build'
    old = str(ancestor).encode()
    new = str(destination).encode()
    rewrites = []
    administrative_suffixes = {
        '.tcl', '.xpr', '.xml', '.json', '.sh', '.bat', '.cmake', '.make', '.txt',
        '.rst', '.xci', '.bd', '.dep', '.d', '.prj', '.f',
    }
    for path in build.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix not in administrative_suffixes and path.name != 'Makefile':
            continue
        data = path.read_bytes()
        if b'\0' in data or old not in data:
            continue
        rewrites.append({'path': str(path.relative_to(destination)),
                         'before_sha256': hashlib.sha256(data).hexdigest()})
        path.write_bytes(data.replace(old, new))
        rewrites[-1]['after_sha256'] = sha(path)
    for relative, expected in sources.items():
        if sha(destination / relative) != expected:
            raise RuntimeError(f'Migration changed sealed source: {relative}')
    save(destination / 'source_hashes.json', sources)

    # Restart only unfinished component runs. Completed OOC synthesis remains
    # available to Vivado; no HLS export or project regeneration is requested.
    recovery_tcl = '''
set recovery_completed 0
set recovery_reset 0
foreach recovery_run [get_runs -filter {IS_SYNTHESIS == 1}] {
    set recovery_name [get_property NAME $recovery_run]
    set recovery_status [get_property STATUS $recovery_run]
    set recovery_progress [get_property PROGRESS $recovery_run]
    puts "RECOVERY_RUN $recovery_name | $recovery_status | $recovery_progress"
    if {$recovery_name eq "synth_1"} { continue }
    if {$recovery_progress eq "100%" && [string match "*Complete*" $recovery_status]} {
        incr recovery_completed
    } else {
        reset_run $recovery_run
        incr recovery_reset
    }
}
puts "RECOVERY_COMPONENTS kept=$recovery_completed reset=$recovery_reset"
'''
    for filename in ['synth_shell.tcl', 'synth_user.tcl']:
        path = build / filename
        contents = path.read_text()
        if contents.count('reset_run synth_1') != 1:
            raise RuntimeError(f'Unexpected synthesis driver: {path}')
        path.write_text(contents.replace('reset_run synth_1', recovery_tcl + '\nreset_run synth_1'))

    projects = sorted(path for path in build.glob('*/*.xpr'))
    projects += sorted(build.glob('*_config_*/user_*/*.xpr'))
    if len(projects) != 2:
        raise RuntimeError(f'Expected shell and user projects, got {projects}')
    probe = [
        'if {[version -short] ne "2024.2"} { error "Wrong Vivado version" }',
        'set_param general.maxThreads 4',
        'set recovery_missing 0',
    ]
    for project in projects:
        probe.append(f'open_project {{{project}}}')
        probe += [
            'puts "RECOVERY_PROJECT [get_property NAME [current_project]]"',
            'foreach source [get_files -all] {',
            '    if {![file exists $source]} {',
            '        set parent [get_property PARENT_COMPOSITE_FILE $source]',
            '        if {[get_property IS_GENERATED $source] && $parent ne "" && [file exists $parent]} {',
            '            puts "RECOVERY_PENDING_OUTPUT $source | generator=$parent"',
            '        } else {',
            '            puts "RECOVERY_MISSING_INPUT $source"',
            '            incr recovery_missing',
            '        }',
            '    }',
            '}',
            'foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {',
            '    puts "RECOVERY_STATE [get_property NAME $run] | [get_property STATUS $run] | [get_property PROGRESS $run]"',
            '}',
            'close_project',
        ]
    probe += [
        'if {$recovery_missing != 0} { error "Missing migrated project dependencies" }',
        'puts "RECOVERY_PROJECT_VALIDATION_PASSED"',
        'exit 0',
    ]
    (destination / 'recovery_project_probe.tcl').write_text('\n'.join(probe) + '\n')
    config = json.loads((destination / 'config.json').read_text())
    manifest = {
        'ancestor': str(ancestor), 'prepared_at': time.time(),
        'ancestor_source_manifest_sha256': sha(ancestor / 'source_hashes.json'),
        'source_files_verified': len(sources), 'source_changes': [],
        'generated_path_rewrites': rewrites,
        'completed_component_markers': len(list(build.glob('**/.vivado.end.rst'))),
        'checkpoint_hashes': {str(path.relative_to(destination)): sha(path)
                              for path in build.rglob('*.dcp')},
        'ip_package_hashes': {str(path.relative_to(destination)): sha(path)
                              for path in (build / 'iprepo').rglob('*') if path.is_file()},
        'configure_or_project_repeated': False,
        'hardware_repair_budget_used': False,
        'application_mhz': 250, 'hbm_mhz': 450,
        'tool_version': '2024.2', 'tool_threads': 4,
    }
    if validation_cache:
        cached_result = json.loads((validation_cache / 'validation.json').read_text())
        if cached_result['status'] != 'passed':
            raise RuntimeError('Validation cache is not passed')
        cached_sources = json.loads((validation_cache / 'source_hashes.json').read_text())
        if cached_sources != sources:
            raise RuntimeError('Validation cache source identity mismatch')
        identities = {}
        for relative in ['config.json', 'model_clock_pin.json', 'tooling/validate.py',
                         'tooling/readers_pixel_test.cpp', 'tooling/readers_control_tb.sv',
                         'tooling/readers_window_tb.sv', 'tooling/wiring.sv']:
            expected = sha(validation_cache / relative)
            if sha(destination / relative) != expected:
                raise RuntimeError(f'Validation cache input changed: {relative}')
            identities[relative] = expected
        manifest['validation_cache'] = {
            'root': str(validation_cache), 'identities': identities,
            'result_sha256': sha(validation_cache / 'validation.json'),
            'reason': 'Only project-probe classification changed; hardware and gate inputs are identical.',
        }
    save(destination / 'recovery_manifest.json', manifest)
    save(destination / 'status.json', {
        'id': config['id'], 'status': 'prepared', 'stage': 'recovery_validation_pending',
        'process_marker': 'readers_recovery_worker.py', 'hardware_validated': False,
    })
    print(json.dumps({'id': config['id'], 'destination': str(destination),
                      'source_files_verified': len(sources), 'path_rewrites': len(rewrites)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('ancestor', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--validation-cache', type=Path)
    args = parser.parse_args()
    cache = args.validation_cache.resolve() if args.validation_cache else None
    prepare(args.ancestor.resolve(), args.destination.resolve(), cache)
