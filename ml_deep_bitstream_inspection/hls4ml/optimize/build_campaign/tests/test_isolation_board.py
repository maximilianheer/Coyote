import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isolation_board import verified_bitstream
from board_benchmark import sha

class BoardGateTests(unittest.TestCase):
    def fixture(self,root):
        bit=root/'cyt_top.bit';bit.write_bytes(b'verified test fixture')
        report=root/'timing.rpt';report.write_text('All user specified timing constraints are met.\n')
        (root/'wrapper_rtl.log').write_text('PASS production wrapper frames=8\n')
        (root/'validation.json').write_text(json.dumps(dict(status='passed',source_manifest_sha256='frozen')))
        progress=dict(status='passed',stage='complete',artifacts=dict(bitstreams=[str(bit)],
            sha256={str(bit):sha(bit)},timing_reports=[str(report)]))
        (root/'progress.json').write_text(json.dumps(progress));return bit,progress

    def test_unfinished_or_changed_bitstream_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch('isolation_board.verify_sources',return_value='frozen'):
            root=Path(tmp);bit,state=self.fixture(root)
            self.assertEqual(verified_bitstream(root),(bit,'frozen'))
            state['status']='running';(root/'progress.json').write_text(json.dumps(state))
            with self.assertRaisesRegex(RuntimeError,'not complete'):verified_bitstream(root)
            state['status']='passed';(root/'progress.json').write_text(json.dumps(state))
            bit.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'hash mismatch'):verified_bitstream(root)

    def test_timing_source_and_rtl_gates(self):
        with tempfile.TemporaryDirectory() as tmp,patch('isolation_board.verify_sources',return_value='changed'):
            root=Path(tmp);self.fixture(root)
            with self.assertRaisesRegex(RuntimeError,'Source validation'):verified_bitstream(root)
        with tempfile.TemporaryDirectory() as tmp,patch('isolation_board.verify_sources',return_value='frozen'):
            root=Path(tmp);self.fixture(root)
            (root/'timing.rpt').write_text('Timing constraints are not met.\n')
            with self.assertRaisesRegex(RuntimeError,'Timing failure'):verified_bitstream(root)
            (root/'timing.rpt').write_text('All user specified timing constraints are met.\n')
            (root/'wrapper_rtl.log').write_text('PASS production wrapper frames=2\n')
            with self.assertRaisesRegex(RuntimeError,'Full wrapper RTL'):verified_bitstream(root)

    def test_launch_fix_requires_driver_reset_coverage(self):
        with tempfile.TemporaryDirectory() as tmp,patch('isolation_board.verify_sources',return_value='frozen'):
            root=Path(tmp);bit,_=self.fixture(root)
            helper=root/'hw/src/hls/model_wrapper/frame_start.hpp'
            helper.parent.mkdir(parents=True);helper.write_text('first-pixel guard')
            with self.assertRaisesRegex(RuntimeError,'second-reset'):verified_bitstream(root)
            (root/'wrapper_rtl.log').write_text('PASS production wrapper frames=8 driver_resets=1\n')
            self.assertEqual(verified_bitstream(root),(bit,'frozen'))

if __name__=='__main__':unittest.main()
