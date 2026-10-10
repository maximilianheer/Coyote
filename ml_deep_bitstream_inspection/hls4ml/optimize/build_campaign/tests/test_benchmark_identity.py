import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark_identity import installed_identity, selected_hardware
from board_benchmark import sha


class HardwareIdentityTests(unittest.TestCase):
    def test_installed_image_rejects_wrong_variant_reset_policy_and_changed_driver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bit=root/'image.bit';driver=root/'driver.ko'
            bit.write_bytes(b'bitstream');driver.write_bytes(b'standard driver')
            image=dict(job='D_I',bitstream=str(bit),sha256=sha(bit),driver=str(driver),
                       driver_sha256=sha(driver),source_manifest_sha256='source',reset_diagnostic=False)
            path=root/'installed.json';path.write_text(json.dumps(image))
            self.assertEqual(installed_identity(path,7)['bitstream_sha256'],sha(bit))
            with self.assertRaises(ValueError):installed_identity(path,8)
            path.write_text(json.dumps(dict(image,status='programming')))
            with self.assertRaises(ValueError):installed_identity(path,7)
            path.write_text(json.dumps(dict(image,reset_diagnostic=True)))
            with self.assertRaises(ValueError):installed_identity(path,7)
            path.write_text(json.dumps(image));driver.write_bytes(b'different driver')
            with self.assertRaises(ValueError):installed_identity(path,7)

    def test_selected_checker_requires_complete_second_reset_gate(self):
        with tempfile.TemporaryDirectory() as temporary,patch('benchmark_identity.verify_sources',return_value='source'):
            root=Path(temporary);job=root/'jobs/D_I';job.mkdir(parents=True)
            bit=job/'cyt_top.bit';bit.write_bytes(b'new bitstream')
            timing=job/'shell_timing_summary.rpt';timing.write_text('All user specified timing constraints are met.\n')
            manifest=dict(status='passed',source_manifest_sha256='source',files={
                p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in (bit,timing)})
            path=job/'artifact_manifest.json';path.write_text(json.dumps(manifest))
            (root/'hardware_selection.json').write_text(json.dumps({'D_I':dict(jobdir=str(job),artifact_manifest_sha256=sha(path))}))
            (job/'progress.json').write_text(json.dumps(dict(status='passed',stage='complete')))
            gate=job/'direct_rtl/status.json';gate.parent.mkdir()
            result=dict(status='passed',source_manifest_sha256='source',comparisons=[{}]*11)
            gate.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'second-reset'):selected_hardware(root,'D_I')
            gate.write_text(json.dumps(dict(result,driver_resets=1)))
            self.assertEqual(selected_hardware(root,'D_I')[1],bit)
            bit.write_bytes(b'other bitstream')
            with self.assertRaisesRegex(ValueError,'artifact changed'):selected_hardware(root,'D_I')

    def test_no_implicit_fallback_to_previous_campaign(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):selected_hardware(Path(temporary),'D_I')


if __name__=='__main__':unittest.main()
