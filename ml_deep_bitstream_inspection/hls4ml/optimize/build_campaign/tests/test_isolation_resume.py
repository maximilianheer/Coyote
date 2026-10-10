import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import production_isolation as isolation


class ResumeTest(unittest.TestCase):
    def check_resume(self, valid):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); job=root/'jobs/R_S';job.mkdir(parents=True)
            (job/'progress.json').write_text(json.dumps(dict(status='running',
                stage='waiting_memory_synth',pid=1122,started_at=1,hardware_started=True)))
            (job/'validation.json').write_text(json.dumps(dict(status='passed',source_manifest_sha256='digest')))
            (job/'wrapper_rtl.log').write_text('PASS production wrapper frames=8' if valid else 'partial run')
            calls=[]
            read_text=Path.read_text
            def read(path,*args,**kwargs):
                if path==Path('/proc/meminfo'):return 'MemAvailable: 40000000 kB\n'
                return read_text(path,*args,**kwargs)
            with patch.dict(os.environ,ISOLATION_RESUME_STAGE='synth'), \
                 patch.object(isolation,'verify_sources',return_value='digest'), \
                 patch.object(isolation,'collect_artifacts',return_value={'bitstreams':[]}), \
                 patch.object(isolation,'final_timing_reports'), \
                 patch.object(isolation,'other_build_memory',return_value=(False,0,0)), \
                 patch.object(Path,'read_text',read), \
                 patch.object(isolation.subprocess,'run',side_effect=lambda args,**kwargs:calls.append(args)):
                result=isolation.run_isolation(job,{'id':'R_S','attempt':4})
            state=json.loads((job/'progress.json').read_text())
            return result,state,calls

    def test_resume_runs_only_remaining_hardware_stages(self):
        result,state,calls=self.check_resume(True)
        self.assertEqual(result,0)
        self.assertEqual([call[-1] for call in calls],['synth','link','shell','bitgen'])
        self.assertEqual(state['started_at'],1)
        self.assertEqual(state['resumed_from_pid'],1122)
        self.assertTrue(state['parallel_synthesis'])

    def test_incomplete_rtl_never_launches_hardware(self):
        result,state,calls=self.check_resume(False)
        self.assertEqual(result,1)
        self.assertEqual(calls,[])
        self.assertIn('eight',state['error'])

    def test_admission_reserves_future_growth(self):
        gib=2**30
        self.assertEqual(isolation.parallel_memory_required('synth',False),24*gib)
        self.assertEqual(isolation.parallel_memory_required('synth',True,4*gib),40*gib)
        self.assertEqual(isolation.parallel_memory_required('link',True,16*gib),28*gib)
        self.assertEqual(isolation.parallel_memory_required('synth',True,12*gib,20),28*gib)


if __name__=='__main__':unittest.main()
