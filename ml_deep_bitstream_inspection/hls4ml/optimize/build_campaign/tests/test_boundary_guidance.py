import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recover_timing as recovery


class BoundaryGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = self.root/'build/reports/shell_timing_summary.rpt'
        self.report.parent.mkdir(parents=True)
        self.report_text = (
            'Slack (VIOLATED) : -0.313ns\n'
            f'  Source: {recovery.BOUNDARY_CELL}/C\n'
            '  Destination: inst_static/inst_cnvrt_static/register/D\n'
            '  Path Group: xclk\n  Path Type: Setup (Max at Slow Process Corner)\n')
        self.report.write_text(self.report_text)
        self.baseline = self.root/'baseline.log'
        self.baseline.write_text(
            f'CELL {{{recovery.BOUNDARY_CELL}}} LOC SLICE_X166Y196 BEL SLICEM.AFF\n'
            'Slack (MET) : 0.652ns\n')
        self.config = dict(source_manifest_sha256='current',
            cell=recovery.BOUNDARY_CELL, loc='SLICE_X166Y196',
            baseline_stdout=str(self.baseline),
            evidence=[dict(path=str(self.baseline), sha256=recovery.sha(self.baseline))])
        self.config_path = self.root/'boundary_placement_guidance.json'
        self.config_path.write_text(json.dumps(self.config))
        self.job = dict(id='D_I', timing_recovery=1)

    def test_matching_failure_uses_verified_placement(self):
        result = recovery.boundary_guidance(self.root, self.job, 'current')
        self.assertEqual(result['loc'], 'SLICE_X166Y196')
        self.assertEqual(result['failing_report_sha256'], recovery.sha(self.report))
        self.assertEqual(result['guidance_sha256'], recovery.sha(self.config_path))

    def test_other_variants_attempts_and_sources_do_not_use_guidance(self):
        for job, digest in [(dict(id='D_G', timing_recovery=1), 'current'),
                            (dict(id='D_I', timing_recovery=2), 'current'),
                            (self.job, 'old')]:
            self.assertIsNone(recovery.boundary_guidance(self.root, job, digest))

    def test_unrelated_or_met_or_hold_path_does_not_activate(self):
        for text in [self.report_text.replace('VIOLATED', 'MET'),
                     self.report_text.replace(recovery.BOUNDARY_CELL, 'cnn/arithmetic'),
                     self.report_text.replace('Setup', 'Hold'),
                     self.report_text.replace('Path Group: xclk', 'Path Group: hbm_clk'),
                     self.report_text.replace('inst_static/inst_cnvrt_static/', 'cnn/')]:
            with self.subTest(text=text):
                self.report.write_text(text)
                self.assertIsNone(recovery.boundary_guidance(self.root, self.job, 'current'))

    def test_modified_evidence_is_rejected(self):
        self.baseline.write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            recovery.boundary_guidance(self.root, self.job, 'current')

    def test_unsupported_cell_or_location_is_rejected(self):
        for key, value in [('cell', 'inst_static/register'), ('loc', 'not-a-site')]:
            config = dict(self.config, **{key:value})
            self.config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(RuntimeError, 'Invalid'):
                recovery.boundary_guidance(self.root, self.job, 'current')

    def test_location_must_match_successful_evidence(self):
        self.config['loc'] = 'SLICE_X166Y197'
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(RuntimeError, 'does not demonstrate'):
            recovery.boundary_guidance(self.root, self.job, 'current')


if __name__ == '__main__':
    unittest.main()
