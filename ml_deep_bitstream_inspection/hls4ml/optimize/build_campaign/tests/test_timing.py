from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker import validate_timing_report, final_timing_reports

class TimingTests(unittest.TestCase):
    def test_pr_final_report_supersedes_intermediate_but_diagnostic_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'reports/config_0').mkdir(parents=True)
            (root/'reports/shell_timing_summary.rpt').write_text('Timing constraints are not met.\n')
            final=root/'reports/config_0/shell_timing_summary_c0.rpt'
            final.write_text('All user specified timing constraints are met.\n')
            self.assertEqual(final_timing_reports(root,'H2'),[final])
            with self.assertRaisesRegex(RuntimeError,'Timing failure'):final_timing_reports(root,'I')
            final.unlink()
            with self.assertRaisesRegex(RuntimeError,'Missing final'):final_timing_reports(root,'H2')

    def test_vivado_success_failure_and_missing_evidence(self):
        cases = [
            ('All user specified timing constraints are met.\n', None),
            ('Timing constraints are met.\n', None),
            ('Timing constraints are not met.\n', 'Timing failure'),
            ('Not all user specified timing constraints are met.\n', 'Timing failure'),
            ('All user specified timing constraints are met.\nTiming constraints are not met.\n', 'Timing failure'),
            ('Report generation interrupted.\n', 'Cannot verify timing'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timing.rpt'
            for text,error in cases:
                with self.subTest(text=text):
                    path.write_text(text)
                    if error:
                        with self.assertRaisesRegex(RuntimeError,error):validate_timing_report(path)
                    else:validate_timing_report(path)

if __name__=='__main__':unittest.main()
