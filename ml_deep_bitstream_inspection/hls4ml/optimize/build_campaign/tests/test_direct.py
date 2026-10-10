import json,sys,tempfile,unittest
from contextlib import nullcontext
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from direct_monitor import hardware_event
from campaign import ORDER,eligible
import recover_timing
class DirectTests(unittest.TestCase):
    def test_validation_outcomes_are_quiet(self):
        for status in ['failed','passed','blocked']:
            self.assertFalse(hardware_event(dict(status=status,hardware_started=False)))
            self.assertTrue(hardware_event(dict(status=status,hardware_started=True)))
        self.assertFalse(hardware_event(dict(status='running',hardware_started=True)))
    def test_direct_priority_and_concurrency(self):
        self.assertEqual(ORDER[:3],['D_I','D_N','D_G'])
        jobs=[dict(id=i,status='pending') for i in ORDER[:3]]
        self.assertTrue(all(eligible(j,jobs) for j in jobs))
        self.assertNotIn('S_I',ORDER)
    def test_routing_failure_persists_outcome_before_requeue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job=root/'jobs/D_G';job.mkdir(parents=True)
            (job/'job.json').write_text(json.dumps(dict(id='D_G',attempt=4,timing_recovery=1)))
            with patch.object(recover_timing,'verify_sources',return_value='manifest'), \
                 patch.object(recover_timing,'implementation_slot',return_value=nullcontext()), \
                 patch.object(recover_timing,'sha',return_value='hash'), \
                 patch.object(recover_timing.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
                self.assertEqual(recover_timing.run(job),1)
            event=json.loads((root/'hardware_outcomes.jsonl').read_text())
            self.assertEqual(event['key'],'D_G:4:1:failed')
            self.assertTrue(json.loads((job/'progress.json').read_text())['hardware_started'])
    def test_routing_preparation_failure_is_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job=root/'jobs/D_G';job.mkdir(parents=True)
            (job/'job.json').write_text(json.dumps(dict(id='D_G',attempt=4,timing_recovery=1)))
            with patch.object(recover_timing,'verify_sources',side_effect=RuntimeError('source mismatch')):
                self.assertEqual(recover_timing.run(job),1)
            self.assertFalse((root/'hardware_outcomes.jsonl').exists())
            self.assertFalse(json.loads((job/'progress.json').read_text())['hardware_started'])
