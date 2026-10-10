"""Bind direct-runtime measurements to explicitly selected hardware and driver."""
import json
from pathlib import Path
from board_benchmark import sha
from prepare import verify_sources
from worker import validate_timing_report


def installed_identity(path, variant):
    image = json.loads(Path(path).read_text())
    expected = {7: 'D_I', 8: 'D_N', 'R_SO_T': 'R_SO_T'}[variant]
    if (image.get('job') != expected or image.get('reset_diagnostic', False)
            or image.get('status','installed') not in ('installed','ready')):
        raise ValueError('Wrong installed image or diagnostic reset policy')
    bit = Path(image['bitstream'])
    driver = Path(image['driver'])
    if sha(bit) != image['sha256'] or sha(driver) != image['driver_sha256']:
        raise ValueError('Installed-image artifact/driver identity changed')
    return dict(job=expected, bitstream_sha256=image['sha256'], driver_sha256=image['driver_sha256'],
                source_manifest_sha256=image['source_manifest_sha256'])


def selected_hardware(root, job):
    # Explicit selection allows a rebuilt checker and the original validated sink.
    selected = json.loads((root/'hardware_selection.json').read_text())[job]
    source = Path(selected['jobdir']).resolve()
    manifest_path = source/'artifact_manifest.json'
    if source.name != job or sha(manifest_path) != selected['artifact_manifest_sha256']:
        raise ValueError('Selected hardware manifest changed')
    manifest = json.loads(manifest_path.read_text())
    digest = verify_sources(source)
    if manifest.get('status') != 'passed' or manifest.get('source_manifest_sha256') != digest:
        raise ValueError('Selected hardware source gate failed')
    progress = json.loads((source/'progress.json').read_text())
    if progress.get('status') != 'passed' or progress.get('stage') != 'complete':
        raise ValueError('Selected hardware is incomplete')
    bits = []
    timing = []
    for name, record in manifest['files'].items():
        path = (source/name).resolve()
        if not path.is_relative_to(source) or sha(path) != record['sha256'] or path.stat().st_size != record['bytes']:
            raise ValueError('Selected hardware artifact changed')
        if path.name == 'cyt_top.bit': bits.append(path)
        if path.name == 'shell_timing_summary.rpt': timing.append(path)
    if len(bits) != 1 or not timing:
        raise ValueError('Missing unique bitstream/final timing evidence')
    for report in timing: validate_timing_report(report)
    if job == 'D_I':
        gate = json.loads((source/'direct_rtl/status.json').read_text())
        if (gate.get('status') != 'passed' or gate.get('source_manifest_sha256') != digest
                or gate.get('driver_resets') != 1 or len(gate.get('comparisons', [])) != 11):
            raise ValueError('D_I requires the complete second-reset RTL gate')
    return source, bits[0], dict(job=job, bitstream_sha256=sha(bits[0]), source_manifest_sha256=digest,
                               artifact_manifest_sha256=sha(manifest_path))
