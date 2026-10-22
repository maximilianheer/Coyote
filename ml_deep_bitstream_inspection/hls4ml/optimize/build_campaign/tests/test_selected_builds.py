import contextlib, json, multiprocessing, os, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from implementation_permits import permit, available_slots
from selected_builds import selected, execute
from iteration_prepare import snapshot, ITERATIONS
from iteration_worker import Worker

def acquire(root,lane,ready,release):
    os.environ.update(HLS4ML_IMPLEMENTATION_PERMITS=root,HLS4ML_IMPLEMENTATION_LANE=lane)
    with permit():ready.set();release.wait(10)

class SelectedTests(unittest.TestCase):
    def test_four_slots_reserved_lane_and_fifth_waits(self):
        with tempfile.TemporaryDirectory() as root:
            processes=[];events=[]
            try:
                for lane in ['primary']*3+['nonstreaming','primary']:
                    ready=multiprocessing.Event();release=multiprocessing.Event()
                    p=multiprocessing.Process(target=acquire,args=(root,lane,ready,release));p.start()
                    processes.append(p);events.append((ready,release))
                    if len(processes)<=4:self.assertTrue(ready.wait(3))
                self.assertFalse(events[4][0].wait(.3))
                events[3][1].set();processes[3].join(2)
                self.assertFalse(events[4][0].wait(.3),'primary cannot borrow dedicated nonstream slot')
                events[0][1].set();processes[0].join(2)
                self.assertTrue(events[4][0].wait(4))
            finally:
                for _,release in events:release.set()
                for p in processes:
                    p.join(3)
                    if p.is_alive():p.terminate();p.join()
    def test_legacy_reserves_one_primary_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'legacy.json').write_text(json.dumps([{'pid':123,'job':'legacy_job'}]))
            with patch('implementation_permits.alive',return_value=True):self.assertEqual(available_slots(root,'primary'),[1,2])
            with patch('implementation_permits.alive',return_value=False):self.assertEqual(available_slots(root,'primary'),[0,1,2])
            self.assertEqual(available_slots(root,'nonstreaming'),[3])
    def test_not_selected_never_dispatched(self):
        config={'jobs':[{'id':'keep','lane':'primary'},{'id':'drop','lane':'primary'},{'id':'other','lane':'nonstreaming'}],'not_selected':['drop']}
        self.assertEqual([r['id'] for r in selected(config,'primary')],['keep'])
    def test_changed_profile_cache_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'jobs').mkdir();job=root/'attempt';(job/'config').mkdir(parents=True);(job/'config/iteration.json').write_text('{}')
            row={'id':'test','job':str(job),'lane':'primary','config_sha256':'same','profile_fingerprint':'expected'}
            with patch('selected_builds.verify_controller'),patch('selected_builds.verify_inputs'),patch('selected_builds.sha',return_value='same'),patch('selected_builds.profile_summary',return_value={'fingerprint':'changed'}),patch('selected_builds.subprocess.Popen') as launch:
                execute(root,row);launch.assert_not_called()
            result=json.loads((root/'jobs/test.json').read_text());self.assertEqual(result['status'],'failed');self.assertIn('Cached profile mismatch',result['error'])
    def test_controller_restart_adopts_worker_without_launching_again(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'jobs').mkdir();job=root/'attempt';(job/'config').mkdir(parents=True)
            (job/'config/iteration.json').write_text('{}')
            record=root/'jobs/test.json';record.write_text(json.dumps({'status':'running','worker_pid':123}))
            (job/'status.json').write_text(json.dumps({'status':'running','stage':'project'}))
            row={'id':'test','job':str(job),'lane':'primary','config_sha256':'same'}
            def worker_finishes(seconds):
                (job/'artifact_manifest.json').write_text('{}')
            with patch('selected_builds.verify_controller'),patch('selected_builds.verify_inputs'),patch('selected_builds.sha',return_value='same'),patch('selected_builds.alive',side_effect=[True,True,False]),patch('selected_builds.time.sleep',side_effect=worker_finishes),patch('selected_builds.artifact_summary'),patch('selected_builds.subprocess.Popen') as launch:
                execute(root,row);launch.assert_not_called()
            self.assertEqual(json.loads(record.read_text())['status'],'passed')

    def test_new_configs_snapshot_and_model_contract(self):
        baseline=json.loads((ITERATIONS/'OPT_1_STREAMING/iteration.json').read_text())
        for ident in ['OPT_0_NONSTREAMING','OPT_5_DSP_B2_RF72_RF288']:
            with tempfile.TemporaryDirectory() as d:
                job=Path(d)/'attempt';snapshot(ITERATIONS/ident/'iteration.json',job);worker=Worker(job);worker.verify()
                self.assertEqual(worker.c['model'],baseline['model']);self.assertFalse(worker.c['hls']['fifo_depth_optimization'])
                self.assertTrue((job/'tooling/implementation_permits.py').exists())
        c=json.loads((ITERATIONS/'OPT_0_NONSTREAMING/iteration.json').read_text());self.assertEqual(c['hls'],baseline['hls'])

if __name__=='__main__':unittest.main()
