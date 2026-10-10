import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from board_benchmark import EXACT,clock_model,components,target

class BoardBenchmarkTests(unittest.TestCase):
    def samples(self):
        samples=[]
        for position,base in [('before',1000000),('after',100000000)]:
            for i in range(32):
                tick=base+i*1000;host=4000000000+4*tick
                samples.append(dict(position=position,fpga_tick=str(tick),host_before_ns=str(host-50),host_after_ns=str(host+50)))
        return samples

    def test_bracket_mapping_contains_known_clock(self):
        mapped,details=clock_model(self.samples())
        lo,hi=mapped(50000000)
        self.assertLessEqual(lo,4200000000);self.assertGreaterEqual(hi,4200000000)
        self.assertLess(hi-lo,101)
        self.assertLessEqual(details['ns_per_tick_min'],4)
        self.assertGreaterEqual(details['ns_per_tick_max'],4)

    def test_inconsistent_or_missing_calibration_rejected(self):
        rows=self.samples();rows[10]['host_before_ns']=str(int(rows[10]['host_before_ns'])+100000)
        rows[10]['host_after_ns']=str(int(rows[10]['host_after_ns'])+100000)
        with self.assertRaisesRegex(ValueError,'inconsistent'):clock_model(rows)
        with self.assertRaises(ValueError):clock_model(self.samples()[:-1])

    def row(self):
        c=dict(id='case',sweep='synthetic',bytes=64,sha256='abc',expected_logit_hex='3f800000')
        r=dict(variant='7',input_bytes='64',input_sha256='abc',signature=str(0x4342595400030007),
            status='2',transport_bytes='128',trial='0',warmup='0',host_start_ns='0',submit_start_ns='1',submit_return_ns='2',host_dma_done_ns='1000',host_verdict_seen_ns='2000')
        values={6:10,7:0x1ff,8:20,9:100,10:30,11:300,12:40,13:310,14:400,15:401,16:120,20:2,26:(1<<32)|0x3f800000,27:65536,28:65536,29:10}
        r.update({f'csr_{i}':str(values.get(i,0)) for i in range(6,30)})
        return c,r

    def test_overlapping_intervals_not_added(self):
        c,r=self.row();d=components(r,c,lambda t:(t*4,t*4+20))
        self.assertAlmostEqual(d['inference_ms'],360*4e-6)
        self.assertAlmostEqual(d['overlap_ms'],260*4e-6)
        self.assertAlmostEqual(d['total_ms'],1614/1e6)

    def test_bad_counts_parity_events_and_order_rejected(self):
        for k,v in [('csr_27','65535'),('csr_20','1'),('csr_7','0'),('csr_26','0'),('csr_13','200'),('status','6'),('signature','0')]:
            c,r=self.row();r[k]=v
            with self.subTest(field=k),self.assertRaises(ValueError):components(r,c,lambda t:(t*4,t*4+20))

    def test_stage_durations_use_calibrated_tick_period(self):
        c,r=self.row();d=components(r,c,lambda t:(t*4,t*4+20),4.008)
        self.assertAlmostEqual(d['inference_ms'],360*4.008/1e6)

    def test_dma_ack_may_precede_downstream_last_payload(self):
        c,r=self.row();r['csr_16']='50'
        components(r,c,lambda t:(t*4,t*4+20))
        r['csr_16']='9'
        with self.assertRaisesRegex(ValueError,'DMA acknowledgment'):
            components(r,c,lambda t:(t*4,t*4+20))

    def test_grid_and_reference_target(self):
        self.assertEqual(EXACT,[4194304,16777216,67108864,134217664])
        self.assertEqual(64+((EXACT[-1]+63)//64)*64,128*2**20)
        self.assertAlmostEqual(target(EXACT[0]),.405)
        self.assertLess(target(EXACT[-1]),7.731)

if __name__=='__main__':unittest.main()
