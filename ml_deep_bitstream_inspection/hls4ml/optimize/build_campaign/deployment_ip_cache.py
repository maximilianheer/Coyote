#!/usr/bin/env python3
"""Copy verified HLS IP into an independent RTL integration retry."""

import argparse
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from prepare import sha
from worker import save


def source_files(job, kernel):
    directory = job / 'hw/src/hls' / kernel
    return {
        str(path.relative_to(job)): sha(path)
        for path in directory.rglob('*') if path.is_file()
    }


def check_package(directory):
    component = ET.parse(directory / 'component.xml')
    for element in component.findall('.//{*}file/{*}name'):
        path = (directory / element.text).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise RuntimeError('IP package has a missing or external file: ' + element.text)


def prepare_cache(original, job):
    config = json.loads((job / 'config.json').read_text())
    sealed = json.loads((original / 'source_hashes.json').read_text())
    metadata = {'source_attempt': str(original), 'kernels': {}}
    for kernel in config['kernels']:
        if not re.fullmatch(r'[A-Za-z0-9_]+', kernel):
            raise RuntimeError('Invalid kernel name')
        inputs = source_files(job, kernel)
        if not inputs or inputs != source_files(original, kernel):
            raise RuntimeError('HLS inputs differ from cache: ' + kernel)
        if any(sealed.get(name) != digest for name, digest in inputs.items()):
            raise RuntimeError('Original HLS inputs differ from their sealed manifest')
        reports = list((original / 'build').glob(f'**/syn/report/{kernel}_csynth.xml'))
        if len(reports) != 1:
            raise RuntimeError('Expected one HLS synthesis report for ' + kernel)
        report = ET.parse(reports[0]).getroot()
        if report.findtext('ReportVersion/Version') != '2024.2':
            raise RuntimeError('HLS tool version mismatch')
        assignments = report.find('UserAssignments')
        period = float(assignments.findtext('TargetClockPeriod'))
        if assignments.findtext('Part') != 'xcu55c-fsvh2892-2L-e':
            raise RuntimeError('Cached IP targets a different FPGA')
        # A core compiled for a tighter period can run at a slower clock.
        # Preserve its RTL schedule; final integration timing remains mandatory.
        if period - 1e9 / config['clock_hz'] > 0.001:
            raise RuntimeError('Cached IP was compiled for a slower application clock')
        target = job / 'hls_ip_cache' / (kernel + '_hls_ip')
        shutil.copytree(original / 'build/iprepo' / target.name, target)
        check_package(target)
        report_target = job / 'hls_ip_cache' / (kernel + '_csynth.xml')
        shutil.copy2(reports[0], report_target)
        metadata['kernels'][kernel] = {
            'inputs': inputs, 'clock_period_ns': period,
            'tool_version': '2024.2', 'part': assignments.findtext('Part'),
        }
    metadata['files'] = {
        str(path.relative_to(job)): sha(path)
        for path in (job / 'hls_ip_cache').rglob('*') if path.is_file()
    }
    save(job / 'hls_ip_cache_manifest.json', metadata)
    config['hls_ip_cache_manifest_sha256'] = sha(job / 'hls_ip_cache_manifest.json')
    save(job / 'config.json', config)


def install_cache(job, config):
    manifest = job / 'hls_ip_cache_manifest.json'
    if sha(manifest) != config['hls_ip_cache_manifest_sha256']:
        raise RuntimeError('Changed HLS IP cache manifest')
    metadata = json.loads(manifest.read_text())
    if set(metadata['kernels']) != set(config['kernels']):
        raise RuntimeError('HLS cache kernel list mismatch')
    for relative, expected in metadata['files'].items():
        if sha(job / relative) != expected:
            raise RuntimeError('Changed cached IP file: ' + relative)
    for kernel, record in metadata['kernels'].items():
        if source_files(job, kernel) != record['inputs']:
            raise RuntimeError('HLS source no longer matches cached IP: ' + kernel)
        if record['clock_period_ns'] - 1e9 / config['clock_hz'] > 0.001:
            raise RuntimeError('HLS cache was compiled for a slower application clock')
        source = job / 'hls_ip_cache' / (kernel + '_hls_ip')
        check_package(source)
        shutil.copytree(source, job / 'build/iprepo' / source.name)
    script = job / 'build/comp_hls.tcl'
    text = script.read_text()
    anchor = 'foreach krnl $krnls {'
    if text.count(anchor) != 1:
        raise RuntimeError('Cannot identify the generated HLS kernel loop')
    # The kernels and all transitive RTL files are copied into this attempt.
    # Only compilation is skipped; this attempt still synthesizes and routes
    # its own changed integration RTL and independently checks final timing.
    names = ' '.join(sorted(metadata['kernels']))
    skip = f'\n                        if {{$krnl in {{{names}}}}} {{continue}}'
    script.write_text(text.replace(anchor, anchor + skip))
    save(job / 'hls_ip_cache_installed.json', {
        'status': 'verified_and_installed', 'kernels': sorted(metadata['kernels']),
        'manifest_sha256': sha(manifest), 'comp_hls_sha256': sha(script),
        'application_clock_hz': config['clock_hz'],
        'cached_synthesis_period_ns': {
            kernel: record['clock_period_ns']
            for kernel, record in metadata['kernels'].items()
        },
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('job', type=Path)
    arguments = parser.parse_args()
    prepare_cache(arguments.original.resolve(), arguments.job.resolve())
