import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmark import components, percentile, SIZES

class BenchmarkTests(unittest.TestCase):
    def row(self):
        return {k:str(v) for k,v in dict(abi_version=2,event_flags=239,
            produced_tokens=65536,decision_cycles=125,input_starve_cycles=3,
            input_backpressure_cycles=4,pp_start_cycles=5,pp_end_cycles=100,
            cnn_task_start_cycles=10,logit_cycles=120,payload_first_cycles=6,
            payload_last_cycles=90).items()}

    def test_overlap_is_not_added_to_latency(self):
        d=components(self.row())
        self.assertEqual(d['total'],125)
        self.assertEqual(d['overlap'],90)
        self.assertEqual(d['publication'],5)
        self.assertEqual(d['last_byte_to_decision'],35)
        self.assertGreater(d['preprocess']+d['inference'],d['total'])

    def test_empty_payload_missing_events_and_bad_tokens(self):
        r=self.row();r['event_flags']='111'
        self.assertNotIn('reception',components(r))
        for key,value in [('produced_tokens','65535'),('event_flags','63'),('logit_cycles','150')]:
            r=self.row();r[key]=value
            with self.assertRaises(ValueError):components(r)

    def test_legacy_and_percentile(self):
        r=self.row();r['abi_version']='1'
        r.update(preprocess_cycles='10',inference_cycles='20',publish_cycles='2')
        d=components(r)
        self.assertEqual(d['inference'],20);self.assertNotIn('overlap',d)
        self.assertAlmostEqual(percentile(range(1,201),.95),190.05)
        self.assertEqual(len(SIZES),8)

if __name__=='__main__':unittest.main()
