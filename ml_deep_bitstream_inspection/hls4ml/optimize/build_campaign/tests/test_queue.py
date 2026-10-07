import sys
import unittest
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campaign import ORDER, eligible
from prepare import INITIAL, add_hierarchical_reports, choose_geometry


class QueueTests(unittest.TestCase):
    def test_narrowing_avoids_archived_capacity_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=root/'attempts/H1/attempt_03';old.mkdir(parents=True)
            (old/'job.json').write_text(json.dumps(dict(geometry=[0,0,0,0])))
            (old/'app.log').write_text('ERROR: [DRC UTLZ-1] BRAM capacity')
            state=dict(jobs=[dict(id='H2',status='passed',geometry=[0,0,1,0],
                                 artifacts=dict(partial_bytes=2000))])
            self.assertEqual(choose_geometry('HN',state,root),((0,0,1,0),True,False))

    def jobs(self):
        return [dict(id=ident, status='pending') for ident in ORDER]

    def test_initial_priority_and_diagnostics_fill_slots(self):
        jobs = self.jobs()
        self.assertEqual([j['id'] for j in jobs if eligible(j, jobs)][:5],
                         ['S_I', 'I', 'H16', 'H8', 'H4'])
        for job in jobs:
            if job['id'] in INITIAL or job['id'] in ('S_I','I'):
                job['status'] = 'running'
        self.assertEqual([j['id'] for j in jobs if eligible(j, jobs)], ['U', 'N', 'P', 'C'])

    def test_refinement_waits_for_all_coarse_attempts(self):
        jobs = self.jobs()
        for job in jobs:
            if job['id'] in INITIAL:
                job.update(status='failed')
        byid = {j['id']: j for j in jobs}
        self.assertTrue(eligible(byid['HN'], jobs))
        self.assertFalse(eligible(byid['HE'], jobs))
        with self.assertRaisesRegex(RuntimeError, 'No initial'):
            choose_geometry('HN', dict(jobs=jobs), None)
        byid['H2'].update(status='passed', geometry=list(INITIAL['H2']),
                         artifacts=dict(partial_bytes=2000))
        byid['H4'].update(status='passed', geometry=list(INITIAL['H4']),
                         artifacts=dict(partial_bytes=4000))
        self.assertEqual(choose_geometry('HN', dict(jobs=jobs), None)[0], (0, 0, 0, 0))
        byid['HN'].update(status='failed')
        byid['HR'].update(status='passed', geometry=[0, 1, 1, 1],
                         artifacts=dict(partial_bytes=1500))
        self.assertTrue(eligible(byid['HE'], jobs))
        self.assertEqual(choose_geometry('HE', dict(jobs=jobs), None), ((0, 1, 1, 1), False, True))

    def test_report_injection_preserves_existing_reports(self):
        original = '    report_utilization -file "$rprt_dir/config_$i/util.rpt"\n'
        patched = add_hierarchical_reports(original)
        self.assertIn(original.rstrip(), patched)
        self.assertIn('util_hierarchical.rpt', patched)
        self.assertEqual(add_hierarchical_reports(patched), patched)


if __name__ == '__main__':
    unittest.main()
