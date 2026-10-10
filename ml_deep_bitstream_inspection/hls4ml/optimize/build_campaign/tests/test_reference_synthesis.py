import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_direct_rtl as gate

class ReferenceSynthesisTests(unittest.TestCase):
    def test_reuses_only_intact_current_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);(job/'tests').mkdir()
            (job/'tests/cnn_reference_synth.tcl').write_text('synthesis configuration')
            rtl=job/'reference_hls/solution1/syn/verilog/cnn_wrapper.v'
            def synthesize(*args,**kwargs):
                rtl.parent.mkdir(parents=True);rtl.write_text('reference RTL')
                report=rtl.parent.parent/'report/cnn_wrapper_csynth.rpt'
                report.parent.mkdir();report.write_text('reference report')
            with patch.object(gate,'verify_sources',return_value='sources'), \
                 patch.object(gate.subprocess,'run',side_effect=synthesize) as run:
                gate.prepare_reference(job,'sources',{})
                gate.prepare_reference(job,'sources',{})
                self.assertEqual(run.call_count,1)
                rtl.write_text('modified RTL')
                with self.assertRaisesRegex(RuntimeError,'cache changed'):
                    gate.prepare_reference(job,'sources',{})
                self.assertEqual(run.call_count,1)
                self.assertEqual(rtl.read_text(),'modified RTL')

    def test_unfinished_reference_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);old=job/'reference_hls';old.mkdir()
            (old/'partial.log').write_text('unfinished synthesis')
            with patch.object(gate.subprocess,'run') as run:
                with self.assertRaisesRegex(RuntimeError,'Unverified reference'):
                    gate.prepare_reference(job,'sources',{})
                run.assert_not_called()
            self.assertEqual((old/'partial.log').read_text(),'unfinished synthesis')
