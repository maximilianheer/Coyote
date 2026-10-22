"""Admission, independent candidate scheduling, and attempt integrity regressions."""
import copy, json, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import iterations
from iteration_prepare import ITERATIONS, snapshot
from iteration_worker import Worker

class IterationTests(unittest.TestCase):
    def test_independent_knobs_and_numeric_contract(self):
        configs={p.parent.name:json.loads(p.read_text()) for p in ITERATIONS.glob('*/iteration.json')}
        baseline=configs['OPT_1_STREAMING']
        for ident,c in configs.items():
            self.assertNotIn('extends',c)
            self.assertEqual(c['model'],baseline['model'])
            for layer in ['conv'+str(i) for i in range(7)]+['output_dense']:
                self.assertEqual(c['hls']['LayerName'][layer+'_linear']['Precision']['result'],
                                 c['hls']['LayerName'][layer]['Precision']['result'])
        b2=copy.deepcopy(configs['OPT_2_DSP_RESOURCES_B2']['hls'])
        for layer in ['conv5','conv6']:
            self.assertEqual(b2['LayerName'][layer]['ReuseFactor'],144)
            b2['LayerName'][layer]['ReuseFactor']=32
        self.assertEqual(b2,baseline['hls'])
        a=copy.deepcopy(configs['OPT_3_BRAM_FIFO_A']['hls'])
        self.assertTrue(a.pop('fifo_depth_optimization'))
        ref=copy.deepcopy(baseline['hls']);ref.pop('fifo_depth_optimization')
        self.assertEqual(a,ref)
    def fake_attempt(self, root, ident):
        job=root/ident/'attempt_01';job.mkdir(parents=True);return job
    def test_baseline_failure_prevents_candidate_launch(self):
        with tempfile.TemporaryDirectory() as d, patch.object(iterations,'new_attempt',side_effect=self.fake_attempt), \
                patch.object(iterations,'run',return_value=1) as run,patch.object(iterations,'notify'):
            self.assertEqual(iterations.campaign(Path(d)),1)
            self.assertEqual(run.call_count,1)
            self.assertEqual(json.loads((Path(d)/'campaign.json').read_text())['status'],'blocked')
    def test_candidates_run_concurrently_and_failure_does_not_cancel_sibling(self):
        barrier=threading.Barrier(2,timeout=5)
        def run(job,stage):
            if stage=='validate':return 0
            barrier.wait()
            return int(job.parent.name=='OPT_2_DSP_RESOURCES_B2')
        with tempfile.TemporaryDirectory() as d,patch.object(iterations,'new_attempt',side_effect=self.fake_attempt), \
                patch.object(iterations,'run',side_effect=run),patch.object(iterations,'notify'):
            self.assertEqual(iterations.campaign(Path(d)),1)
            outcomes=json.loads((Path(d)/'campaign.json').read_text())['outcomes']
            self.assertEqual(outcomes,{'OPT_2_DSP_RESOURCES_B2':'failed','OPT_3_BRAM_FIFO_A':'passed'})
    def test_changed_attempt_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            job=Path(d)/'attempt';snapshot(ITERATIONS/'OPT_1_STREAMING/iteration.json',job)
            worker=Worker(job);worker.verify()
            p=job/'config/iteration.json';p.write_text(p.read_text()+'\n')
            with self.assertRaisesRegex(RuntimeError,'Attempt input changed'):worker.verify()

if __name__=='__main__':unittest.main()
