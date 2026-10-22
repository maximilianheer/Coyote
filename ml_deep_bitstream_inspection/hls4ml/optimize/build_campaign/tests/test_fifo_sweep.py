"""Phase safety, native evidence, isolation and scheduling regression tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fifo_sweep as sweep
import fifo_sweep_results as results
from iteration_worker import Worker

class SweepTests(unittest.TestCase):
    def test_profile_never_packages_validates_or_builds(self):
        worker=Worker.__new__(Worker)
        with patch.object(worker,'profile') as profile,patch.object(worker,'prepare') as prepare, \
             patch.object(worker,'validate') as validate,patch.object(worker,'build') as build,patch.object(worker,'progress'):
            self.assertEqual(worker.run('profile'),0)
            profile.assert_called_once();prepare.assert_not_called();validate.assert_not_called();build.assert_not_called()

    def test_profile_failure_cannot_dispatch_build(self):
        worker=Worker.__new__(Worker);worker.state={}
        with patch.object(worker,'profile',side_effect=RuntimeError('native profile failed')), \
             patch.object(worker,'build') as build,patch.object(worker,'progress'):
            self.assertEqual(worker.run('profile'),1);build.assert_not_called()

    def test_native_transactions_are_not_total_runtime_divided_by_frames(self):
        rows=results.transactions('latency interval\ntransaction 0: 544438 69141\ntransaction 1: 475430 x\n')
        self.assertEqual([r['latency_cycles'] for r in rows],[544438,475430])
        self.assertEqual(rows[0]['interval_cycles'],69141);self.assertIsNone(rows[1]['interval_cycles'])

    def test_fingerprint_ignores_iteration_name_but_tracks_firmware(self):
        with tempfile.TemporaryDirectory() as d:
            job=Path(d);(job/'generated/firmware').mkdir(parents=True)
            fw=job/'generated/firmware/model.cpp';fw.write_text('depth=1')
            config={'model':{'weights':'same'},'interface':{'abi':3},'hls':dict(backend='Vitis',part='U55C',clock_period=4,clock_uncertainty='27%')}
            for f in ['generator_identity.json','resolved_layers.json']:(job/f).write_text('{}')
            with patch.object(results,'verify_inputs',return_value=config):
                first=results.fingerprint(job);config['id']='other name'
                self.assertEqual(first,results.fingerprint(job))
                fw.write_text('depth=2');self.assertNotEqual(first,results.fingerprint(job))

    def test_guarded_failure_preserves_other_points(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'points/bad').mkdir(parents=True);(root/'events').mkdir()
            with patch.object(sweep,'profile_point',side_effect=RuntimeError('cosim failed')):
                self.assertIsNone(sweep.guarded(root,{'id':'bad','job':'original'},'profile'))
            self.assertEqual(json.loads((root/'points/bad/state.json').read_text())['status'],'failed')
            self.assertEqual(len(list((root/'events').glob('*.json'))),1)

    def test_existing_a_reserves_an_hls_slot_but_routing_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            job=Path(d);config={'external_jobs':[d]}
            with patch.object(sweep,'alive',return_value=True):
                (job/'status.json').write_text(json.dumps(dict(status='running',pid=1,stage='rtl_validation')))
                self.assertEqual(sweep.external_hls(config),1)
                (job/'status.json').write_text(json.dumps(dict(status='running',pid=1,stage='host_compile')))
                self.assertEqual(sweep.external_hls(config),1)
                (job/'status.json').write_text(json.dumps(dict(status='running',pid=1,stage='shell')))
                self.assertEqual(sweep.external_hls(config),0)

    def test_monitor_ignores_short_handover_but_reports_persistent_absence(self):
        for recovery in [True,False]:
            with self.subTest(recovery=recovery),tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/'events').mkdir();clock=[0];sent=[];original_load=sweep.load
                def load(path,default=None):
                    if path==root/'status.json':return {'status':'passed' if clock[0]>=100 else 'running','pid':777}
                    return original_load(path,default)
                def send(root,event):sent.append((clock[0],event));return True
                with patch.object(sweep,'load',side_effect=load),patch.object(sweep,'inspect'), \
                     patch.object(sweep,'write_results'),patch.object(sweep,'send',side_effect=send), \
                     patch.object(sweep,'alive',side_effect=lambda *args:recovery and clock[0]>=20), \
                     patch.object(sweep.time,'time',side_effect=lambda:clock[0]), \
                     patch.object(sweep.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
                    sweep.monitor(root)
                alarms=[(t,e) for t,e in sent if e['stage'].startswith('supervisor_')]
                if recovery:self.assertEqual(alarms,[])
                else:self.assertEqual(alarms[0][0],60)

    def test_supervisor_restart_adopts_active_worker(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'points/test';folder.mkdir(parents=True)
            job=root/'job';job.mkdir()
            (folder/'state.json').write_text(json.dumps({'stage':'profile','pid':123,'status':'running'}))
            (job/'status.json').write_text(json.dumps({'status':'passed'}))
            with patch.object(sweep,'alive',side_effect=[True,False]),patch.object(sweep.subprocess,'Popen') as launch:
                result=sweep.execute(root,{'id':'test','job':str(job)},'profile')
                self.assertEqual(result['status'],'passed');launch.assert_not_called()

    def test_retired_sweep_cannot_restart_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'status.json').write_text(json.dumps({'status':'superseded','superseded_by':'selected_campaign'}))
            with patch.object(sweep,'dispatch') as dispatch:
                with self.assertRaisesRegex(RuntimeError,'Sweep dispatch retired'):sweep.run(root,'build')
                dispatch.assert_not_called()

    def test_build_uses_cross_campaign_implementation_lock(self):
        import os
        import iteration_worker
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);job=root/'sweep/point/attempt_01';job.mkdir(parents=True)
            for top in ['preprocess_wrapper','cnn_wrapper']:
                directory=job/'build'/top/'solution1/syn/verilog';directory.mkdir(parents=True)
                (directory/(top+'.v')).write_text('// fixture')
            worker=Worker.__new__(Worker);worker.job=job;worker.c={'id':'OPT_TEST'}
            gate=job/'build_rtl_validation';gate.mkdir()
            (gate/'inputs.json').write_text('{}')
            from prepare import sha
            (gate/'result.json').write_text(json.dumps({'status':'passed','input_manifest_sha256':sha(gate/'inputs.json')}))
            shared=root/'existing_campaign.lock'
            with patch.dict(os.environ,{'HLS4ML_IMPLEMENTATION_LOCK':str(shared)}), \
                 patch.object(worker,'command'),patch.object(worker,'rtl'),patch.object(worker,'verify'), \
                 patch.object(worker,'progress'),patch.object(iteration_worker,'final_timing_reports'), \
                 patch.object(iteration_worker,'collect_artifacts',return_value={}),patch.object(iteration_worker,'seal_artifacts'):
                worker.build()
            self.assertTrue(shared.exists())
            self.assertFalse((job.parents[1]/'implementation.lock').exists())

    def test_generated_firmware_tamper_is_rejected_before_packaging(self):
        with tempfile.TemporaryDirectory() as d:
            worker=Worker.__new__(Worker);worker.job=Path(d)
            (worker.job/'file').write_text('before')
            from prepare import sha
            (worker.job/'generated_manifest.json').write_text(json.dumps({'file':sha(worker.job/'file')}))
            (worker.job/'file').write_text('after')
            with patch.object(worker,'verify'),self.assertRaisesRegex(RuntimeError,'Generated evidence changed'):
                worker.profile()

if __name__=='__main__':unittest.main()
