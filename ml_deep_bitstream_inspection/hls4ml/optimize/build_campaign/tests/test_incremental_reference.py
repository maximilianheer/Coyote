import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recover_timing import best_reference


def checkpoint(directory, wns, whs=0.005, manifest='same', complete=True):
    (directory/'checkpoints').mkdir(parents=True)
    (directory/'checkpoints/shell_routed.dcp').write_bytes(b'checkpoint fixture')
    (directory/'reports').mkdir()
    (directory/'reports/shell_timing_summary.rpt').write_text(
        f' WNS(ns) TNS(ns) Endpoints Total WHS(ns)\n -----\n {wns} -1 2 100 {whs}\n'
        'Timing constraints are not met.\n')
    (directory/'provenance.json').write_text(json.dumps(dict(source_manifest_sha256=manifest)))
    if complete:
        (directory/'outcome.json').write_text(json.dumps(dict(status='failed',
            finished_at=1, error='Timing failure: final.rpt')))


class IncrementalReferenceTests(unittest.TestCase):
    def test_uses_best_completed_same_source_result_not_latest_or_unfinished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint(root/'build', -0.101)
            (root/'shell.log').write_text('[100%] Built target shell')
            checkpoint(root/'recovery/route_01', -0.095)
            checkpoint(root/'recovery/route_02', -0.158)
            checkpoint(root/'recovery/route_03', 0.05, complete=False)
            checkpoint(root/'recovery/route_04', 0.10, manifest='different')
            path, details = best_reference(root, 'same')
            self.assertEqual(path, root/'recovery/route_01/checkpoints/shell_routed.dcp')
            self.assertEqual(details['wns_ns'], -0.095)

    def test_hold_violations_are_considered_when_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint(root/'recovery/route_01', -0.05, whs=-0.20)
            checkpoint(root/'recovery/route_02', -0.08)
            path, _ = best_reference(root, 'same')
            self.assertEqual(path.parent.parent.name, 'route_02')

    def test_rejects_missing_completed_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint(root/'recovery/route_01', -0.01, complete=False)
            with self.assertRaisesRegex(RuntimeError, 'No completed same-source'):
                best_reference(root, 'same')


if __name__ == '__main__':
    unittest.main()
