import json
from pathlib import Path
from board_benchmark import sha
def installed_identity(path, variant):
    image = json.loads(Path(path).read_text())
    expected = {7: 'D_I', 8: 'D_N'}[variant]
    if (image.get('job') != expected or image.get('reset_diagnostic', False)
            or image.get('status','installed') not in ('installed','ready')):
        raise ValueError('Wrong installed image or diagnostic reset policy')
    bit = Path(image['bitstream'])
    driver = Path(image['driver'])
    if sha(bit) != image['sha256'] or sha(driver) != image['driver_sha256']:
        raise ValueError('Installed-image artifact/driver identity changed')
    return dict(job=expected, bitstream_sha256=image['sha256'], driver_sha256=image['driver_sha256'],
                source_manifest_sha256=image['source_manifest_sha256'])
