import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import HARDWARE, MODEL, VARIANTS, VARIANT_FILES, prepare, sha, verify_sources
from campaign import run


class PreparationTests(unittest.TestCase):
    def test_all_variants_are_copied_with_unchanged_firmware_and_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for ident in VARIANTS:
                job = dict(id=ident, attempt=3)
                with patch('prepare.copy_coyote', side_effect=lambda dst: dst.mkdir()):
                    dst = prepare(root, job, {})
                kernel = dst/'hw/src/hls/model_wrapper'
                self.assertEqual(sha(kernel/'model_wrapper.cpp'),
                                 sha(HARDWARE/'variants'/(VARIANT_FILES[ident]+'.cpp')))
                self.assertEqual(sha(dst/'hw/src/vfpga_top.svh'), sha(HARDWARE/'vfpga_top.svh'))
                self.assertEqual(sha(dst/'hw/src/hdl/benchmark_control.sv'), sha(HARDWARE/'benchmark_control.sv'))
                self.assertEqual(sha(dst/'hw/src/hdl/debug_probe.svh'), sha(HARDWARE/'debug_probe.svh'))
                self.assertEqual(sha(dst/'hw/src/init_ip.tcl'), sha(HARDWARE/'init_ip.tcl'))
                self.assertIn(str(VARIANTS[ident]), (dst/'hw/src/hdl/benchmark_variant.svh').read_text())
                for path in (MODEL/'firmware').rglob('*'):
                    if path.is_file():
                        self.assertEqual(sha(path), sha(kernel/path.relative_to(MODEL)))
                self.assertFalse((dst/'build').exists())
                verify_sources(dst)
                with self.assertRaises(FileExistsError):
                    prepare(root, job, {})
                (kernel/'model_wrapper.cpp').write_text('// changed after preparation\n')
                with self.assertRaisesRegex(RuntimeError, 'Source hashes changed'):
                    verify_sources(dst)

    def test_hello_world_uses_the_same_ila_without_modifying_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('prepare.copy_coyote',side_effect=lambda dst:dst.mkdir()):
                dst=prepare(Path(tmp),dict(id='H16',attempt=2),{})
            self.assertEqual(sha(dst/'hw/src/init_ip.tcl'),sha(HARDWARE/'init_ip.tcl'))
            self.assertEqual(sha(dst/'hw/src/hdl/debug_probe.svh'),sha(HARDWARE/'debug_probe.svh'))
            self.assertEqual(sha(dst/'hw/src/vfpga_top.svh'),sha(HARDWARE/'hello_world/vfpga_top.svh'))
            self.assertEqual(sha(dst/'hw/src/hdl/perf_local.sv'),sha(HARDWARE/'hello_world/hdl/perf_local.sv'))
            self.assertFalse((dst/'hw/src/hdl/ring_oscillator.sv').exists())
            self.assertNotIn('ring_oscillator', (dst/'hw/src/hdl/perf_local.sv').read_text())
            verify_sources(dst)

    def test_pause_tracks_workers_without_dispatch_and_retry_archives_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=root/'jobs/I';old.mkdir(parents=True)
            (old/'old_checkpoint.dcp').write_text('old checkpoint')
            (root/'dispatch_paused').touch()
            (root/'retry_requests.json').write_text('["I"]')
            (root/'status.json').write_text(json.dumps(dict(tmux_session='test',
                jobs=[dict(id='I',status='failed',attempt=1,prepared=True)])))
            with patch('campaign.prepare') as prepare_mock, patch('campaign.time.sleep',side_effect=InterruptedError):
                with self.assertRaises(InterruptedError):run(root)
                prepare_mock.assert_not_called()
            state=json.loads((root/'status.json').read_text())
            self.assertEqual(state['phase'],'paused')
            self.assertEqual(state['jobs'][0]['status'],'pending')
            self.assertEqual(state['jobs'][0]['attempt'],2)
            self.assertFalse(state['jobs'][0]['prepared'])
            self.assertFalse(old.exists())
            self.assertTrue((root/'attempts/I/attempt_01/old_checkpoint.dcp').exists())


if __name__ == '__main__':unittest.main()
