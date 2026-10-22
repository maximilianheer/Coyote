"""Regression checks for simulation-only recovery and strict profile reuse."""
import hashlib,json,sys,tempfile,unittest,subprocess
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iteration_cosim import configure_profile_reuse,patch_project
from iteration_monitor import alive

class RecoveryTests(unittest.TestCase):
    def fixture(self,root):
        (root/'config').mkdir();cache=root/'fifo_profile_cache';cache.mkdir()
        project=root/'generated';(project/'firmware').mkdir(parents=True);(project/'tb_data').mkdir()
        (project/'firmware/model.cpp').write_text('unchanged RTL-generating source')
        for name in ['tb_input_features.dat','tb_output_predictions.dat']:(project/'tb_data'/name).write_text('1\n2\n')
        for name in ['channel.zip','channel_info.csv','rtl_cosim_results.log']:(cache/name).write_text('test profile data')
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        config={'id':'A','model':{'weights_sha256':'weights'},'hls':{'profiling_samples':2}}
        (root/'config/iteration.json').write_text(json.dumps(config))
        manifest={'status':'passed','iteration':'A','model_weights_sha256':'weights','samples':2,
            'firmware':{'model.cpp':sha(project/'firmware/model.cpp')},
            'files':{p.name:sha(p) for p in cache.iterdir()},
            'inputs_sha256':sha(project/'tb_data/tb_input_features.dat'),
            'predictions_sha256':sha(project/'tb_data/tb_output_predictions.dat')}
        (cache/'manifest.json').write_text(json.dumps(manifest))
        backend=SimpleNamespace(build=lambda model,**opts:'native')
        graph=SimpleNamespace(config=SimpleNamespace(get_output_dir=lambda:str(project),get_project_name=lambda:'iteration_model'))
        return backend,graph,project
    def test_exact_profile_reuse_and_nonprofile_delegation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);backend,graph,project=self.fixture(root)
            configure_profile_reuse(backend,root)
            self.assertEqual(backend.build(graph,fifo_opt=False),'native')
            backend.build(graph,fifo_opt=True)
            self.assertTrue((project/'profile_reuse.json').is_file())
    def test_changed_firmware_or_vectors_cannot_reuse(self):
        for name in ['firmware/model.cpp','tb_data/tb_input_features.dat']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);backend,graph,project=self.fixture(root)
                configure_profile_reuse(backend,root);(project/name).write_text('changed')
                with self.assertRaises(RuntimeError):backend.build(graph,fifo_opt=True)
                self.assertFalse((project/'profile_reuse.json').exists())
    def test_simulation_patch_does_not_modify_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,_,project=self.fixture(root)
            (project/'build_prj.tcl').write_text('before\n    remove_recursive_log_wave\nafter\n')
            script=root/'batch.tcl';script.write_text('# simulation adapter')
            before=(project/'firmware/model.cpp').read_bytes();patch_project(project,script)
            self.assertEqual(before,(project/'firmware/model.cpp').read_bytes())
            self.assertIn('iteration_fifo_batch_setup $project_name',(project/'build_prj.tcl').read_text())
    def test_relative_process_path_is_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'relative.py';script.write_text('import time; print("ready",flush=True); time.sleep(5)')
            child=subprocess.Popen([sys.executable,'relative.py'],cwd=root,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                self.assertTrue(alive(child.pid,str(script)))
            finally:
                child.terminate();child.wait();child.stdout.close()

if __name__=='__main__':unittest.main()
