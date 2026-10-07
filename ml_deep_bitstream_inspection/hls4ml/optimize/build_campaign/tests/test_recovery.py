import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recovery import recover_failed

class RecoveryTests(unittest.TestCase):
    def test_timing_retries_are_bounded_and_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dst=root/'jobs/I'
            (dst/'build/checkpoints').mkdir(parents=True)
            (dst/'build/checkpoints/shell_placed.dcp').touch()
            (root/'recovery_policy.json').write_text('{"enabled":true}')
            job=dict(id='I',status='failed',attempt=4,error='Timing failure: final.rpt')
            state=dict(jobs=[job])
            for expected in [1,2,3,4]:
                recover_failed(root,state)
                self.assertEqual(job['timing_recovery'],expected)
                self.assertEqual(job['status'],'pending')
                job.update(status='failed',error='Timing failure: final.rpt')
            recover_failed(root,state)
            self.assertEqual(job['status'],'failed')
            count=len((root/'recovery_events.jsonl').read_text().splitlines())
            recover_failed(root,state)
            self.assertEqual(len((root/'recovery_events.jsonl').read_text().splitlines()),count)

    def test_capacity_retry_preserves_attempt_and_changes_floorplan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dst=root/'jobs/H1';dst.mkdir(parents=True)
            (dst/'app.log').write_text('ERROR: [DRC UTLZ-1] BRAM capacity')
            (root/'recovery_policy.json').write_text('{"enabled":true}')
            job=dict(id='H1',status='failed',attempt=3,geometry=[0,0,0,0])
            recover_failed(root,dict(jobs=[job]))
            self.assertEqual(job['geometry_override'],[0,0,1,0])
            self.assertEqual(job['attempt'],4)
            self.assertTrue((root/'attempts/H1/attempt_03/app.log').exists())
            self.assertFalse(dst.exists())

if __name__=='__main__':unittest.main()
