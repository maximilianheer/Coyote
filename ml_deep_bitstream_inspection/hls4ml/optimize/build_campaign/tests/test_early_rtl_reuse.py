import csv,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_direct_rtl as gate

class EarlyRTLReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.job=Path(self.tmp.name);self.early=self.job/'direct_rtl_early'
        self.sources={}
        for name,root in [('preprocess_wrapper','build/pp'),('cnn_wrapper','build/cnn'),('baseline','reference_hls')]:
            directory=self.job/root/'solution1/syn/verilog';directory.mkdir(parents=True)
            (directory/('preprocess_wrapper.v' if name=='preprocess_wrapper' else 'cnn_wrapper.v')).write_text(name)
            (directory/'weights.dat').write_text('fixed weights')
            self.sources[name]=directory
        common={'elastic_fifo.sv':self.job/'hw/src/hdl/elastic_fifo.sv',
                'direct_pipe_tb.sv':self.job/'tests/direct_pipe_tb.sv',
                'direct_sim.tcl':self.job/'tests/direct_sim.tcl',
                'direct_expected.txt':self.job/'reference_simulation/direct_expected.txt'}
        for name,p in common.items():
            p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name)
        self.sizes=[0,1,63,64,65,65535,65536,65537,4194240,4194241,4194242]
        common['direct_expected.txt'].write_text(''.join(f'{n} 00000000\n' for n in self.sizes))
        for variant,cycles in [('baseline',270000),('candidate',74000)]:
            sim=self.early/variant;sim.mkdir(parents=True)
            inputs={}
            for prefix,root in [('pp',self.sources['preprocess_wrapper']),('cnn',self.sources['baseline' if variant=='baseline' else 'cnn_wrapper'])]:
                for p in root.iterdir():inputs[prefix+'/'+p.name]=p.read_bytes()
            inputs.update({name:p.read_bytes() for name,p in common.items()})
            for name,data in inputs.items():
                p=sim/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            (sim/'sources.json').write_text(json.dumps({name:gate.sha(sim/name) for name in inputs}))
            with (sim/'cycles.csv').open('w') as f:
                writer=csv.writer(f);writer.writerow(['bytes','cnn_cycles'])
                writer.writerows((n,cycles) for n in self.sizes)
            runtime=sim/'sim_project/direct_rtl.sim/sim_1/behav/xsim';runtime.mkdir(parents=True)
            (runtime/'cycles.csv').write_bytes((sim/'cycles.csv').read_bytes())
            for p in [sim/'check.log',runtime/'simulate.log']:
                p.write_text('PASS direct synthesized RTL parity: frames=11 startup_idle=20000 always_ready=0 driver_resets=1\n')
        self.status=dict(status='passed',source_manifest_sha256='manifest',driver_resets=1,comparisons=[
            dict(bytes=n,baseline_cycles=270000,candidate_cycles=74000) for n in self.sizes])
        (self.early/'status.json').write_text(json.dumps(self.status))
        (self.job/'reference_hls_validation.json').write_text('{}')

    def check(self):return gate.verified_early_result(self.job,'manifest',self.sources)

    def test_identical_actual_cores_skip_new_simulation(self):
        with patch.object(gate,'verify_sources',return_value='manifest'), \
             patch.object(gate,'prepare_reference'),patch.object(gate.subprocess,'run') as tool:
            self.assertEqual(gate.run(self.job),0);tool.assert_not_called()
        result=json.loads((self.job/'direct_rtl/status.json').read_text())
        self.assertEqual(result['comparisons'],self.status['comparisons'])
        self.assertEqual(result['reused_from'],'direct_rtl_early')
        self.assertTrue(result['evidence_sha256'])

    def test_changed_inputs_or_evidence_require_fresh_simulation(self):
        paths=[self.sources['cnn_wrapper']/'weights.dat',
               self.sources['preprocess_wrapper']/'preprocess_wrapper.v',
               self.job/'tests/direct_pipe_tb.sv',
               self.early/'candidate/cnn/cnn_wrapper.v',
               self.early/'candidate/cycles.csv',self.early/'baseline/check.log']
        for p in paths:
            with self.subTest(path=str(p)):
                original=p.read_bytes();p.write_text('changed')
                self.assertIsNone(self.check());p.write_bytes(original)
        self.assertIsNotNone(self.check())

    def test_incomplete_failed_or_different_attempt_cannot_be_reused(self):
        for changed in [dict(status='running'),dict(status='failed'),dict(source_manifest_sha256='old attempt'),dict(comparisons=[]),dict(driver_resets=0)]:
            with self.subTest(changed=changed):
                (self.early/'status.json').write_text(json.dumps(dict(self.status,**changed)))
                self.assertIsNone(self.check())

    def test_added_core_input_requires_new_simulation(self):
        (self.sources['cnn_wrapper']/'extra.v').write_text('new RTL input')
        self.assertIsNone(self.check())
