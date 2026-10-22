import ctypes, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from board_benchmark import components,sha
from opt_benchmark_collect import file_trial, derived, image_identity
from test_board_benchmark import BoardBenchmarkTests

class OptBenchmarkTests(unittest.TestCase):
    def test_nonstreaming_full_buffer_accepted_and_early_cnn_rejected(self):
        c,r=BoardBenchmarkTests().row();r.update(csr_29='65536',csr_12='301')
        d=components(r,c,lambda t:(t*4,t*4+20),fifo_depth=65536,pipeline_mode='nonstreaming')
        self.assertEqual(d['overlap_ms'],0)
        with self.assertRaisesRegex(ValueError,'pixel/FIFO'):components(r,c,lambda t:(t*4,t*4+20))
        r['csr_12']='299'
        with self.assertRaisesRegex(ValueError,'non-streaming'):components(r,c,lambda t:(t*4,t*4+20),fifo_depth=65536,pipeline_mode='nonstreaming')
    def test_file_trial_reads_and_prepares_each_time(self):
        from types import SimpleNamespace
        calls=[];ticks=iter([100,200,300,400,500,600])
        session=SimpleNamespace(lib=SimpleNamespace(campaign_now_ns=lambda:next(ticks)),prepare=lambda raw:calls.append('prepare'),run=lambda:{'host_verdict_seen_ns':999})
        with patch('opt_benchmark_collect.np.fromfile',side_effect=lambda *a,**k:calls.append('read')):
            first=file_trial(session,'input');second=file_trial(session,'input')
        self.assertEqual(calls,['read','prepare','read','prepare']);self.assertEqual(first['file_start_ns'],100);self.assertEqual(second['file_start_ns'],400)
    def test_e2e_ends_at_verdict_not_register_readback(self):
        c,r=BoardBenchmarkTests().row();r.update(scope='file',file_start_ns='-1000',file_read_end_ns='-500',prepare_end_ns='-10')
        identity=dict(id='OPT_TEST',fifo_depth=32,pipeline_mode='streaming')
        d=derived(r,c,lambda t:(t*4,t*4+20),4,identity)
        self.assertAlmostEqual(d['file_e2e_ms'],.003);self.assertAlmostEqual(d['file_read_ms'],.0005)
        r['file_read_end_ns']='2500'
        with self.assertRaisesRegex(ValueError,'timestamp ordering'):derived(r,c,lambda t:(t*4,t*4+20),4,identity)
    def test_identity_rejects_alias_and_driver_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bit=root/'image.bit';bit.write_bytes(b'bit');driver=root/'driver.ko';driver.write_bytes(b'driver')
            selected=dict(bitstream=str(bit),bitstream_sha256=sha(bit),source_manifest_sha256='source',artifact_manifest_sha256='manifest',fifo_depth=32,pipeline_mode='streaming')
            cfg=dict(images={'OPT_1_STREAMING':selected},driver=str(driver),driver_sha256=sha(driver),software_files={})
            (root/'campaign.json').write_text(json.dumps(cfg));image=dict(status='ready',id='OPT_1_STREAMING',reset_diagnostic=False,**selected)
            p=root/'installed_image.json';p.write_text(json.dumps(image));self.assertEqual(image_identity(root,'OPT_1_STREAMING')['id'],'OPT_1_STREAMING')
            image['id']='D_I';p.write_text(json.dumps(image))
            with self.assertRaises(ValueError):image_identity(root,'OPT_1_STREAMING')
            image['id']='OPT_1_STREAMING';p.write_text(json.dumps(image));driver.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'driver'):image_identity(root,'OPT_1_STREAMING')

if __name__=='__main__':unittest.main()
