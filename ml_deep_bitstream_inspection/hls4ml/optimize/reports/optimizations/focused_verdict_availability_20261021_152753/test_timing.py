"""Regression cases for the two completion orders and cross-clock uncertainty."""
import unittest
from timing import derive, phase_partition


def sample(result=300, last=500, variant=10):
    done=max(result+1, last)
    row=dict(variant=variant, case_id='test', scope='resident', session='timed', trial=1,
             input_bytes=128, transport_bytes=192, input_sha256='test', host_start_ns=0,
             verdict_seen_ns=10000, csr_0=2, csr_4=0x4342595400040000 | variant,
             csr_6=100, csr_7=0xc3, csr_8=120, csr_9=last, csr_14=result, csr_15=done, csr_20=3,
             submit_ns=100, submitted_ns=200, input_ready_ns=400, relay_start_ns=800, relay_end_ns=1600)
    if variant==11:
        row.update(csr_21=3, csr_18=121, csr_19=last+1, csr_38=last+2,
                   csr_40=result-2, csr_41=result-1, csr_45=0)
    return row


def calculated(row):
    return derive(row, lambda t: (4*t-10, 4*t+10),
                  dict(ns_per_tick_min=4, ns_per_tick_max=4), 'test')


class TimingCases(unittest.TestCase):
    def test_result_before_last_input(self):
        d=calculated(sample())
        self.assertAlmostEqual(d['verdict_available_ms'],.0012)
        self.assertAlmostEqual(d['input_complete_ms'],.002)
        self.assertAlmostEqual(d['remaining_input_after_result_ms'],.0008)
        self.assertEqual(d['after_input_and_result_ms'],0)
        self.assertTrue(d['result_before_input_complete'])

    def test_input_before_result(self):
        d=calculated(sample(result=700))
        self.assertEqual(d['remaining_input_after_result_ms'],0)
        self.assertAlmostEqual(d['result_to_fpga_complete_ms'],.000004)

    def test_coincident_events_keep_control_cycle(self):
        d=calculated(sample(result=500))
        self.assertFalse(d['result_before_input_complete'])
        self.assertAlmostEqual(d['after_input_and_result_ms'],.000004)

    def test_p2p_retrieval_is_included(self):
        d=calculated(sample(result=700,variant=11))
        self.assertAlmostEqual(d['verdict_available_ms'],.0028)

    def test_invalid_p2p_forwarding_rejected(self):
        row=sample(result=700,variant=11);row['csr_19']=900
        with self.assertRaises(AssertionError):calculated(row)

    def test_missing_event_rejected(self):
        row=sample();row['csr_7'] &= ~0x40
        with self.assertRaises(AssertionError):calculated(row)

    def test_invalid_completion_rejected(self):
        row=sample();row['csr_15']=250
        with self.assertRaises(AssertionError):calculated(row)

    def test_phase_clips_return_after_acceptance(self):
        vals=phase_partition(sample(),.0012)
        self.assertAlmostEqual(sum(vals),.0012)
        self.assertAlmostEqual(vals[4],.0004)
        self.assertEqual(vals[5],0)

    def test_uncertain_host_delay_is_not_silently_clamped(self):
        row=sample();row['verdict_seen_ns']=1998
        d=calculated(row)
        self.assertLess(d['host_observation_delay_lower_ms'],0)
        self.assertGreater(d['host_observation_delay_upper_ms'],0)
        self.assertLess(d['host_observation_delay_ms'],0)

    def test_local_cnn_endpoint(self):
        row=sample(result=700);row.update(variant=7,status=2,signature=0x4342595400030007,
                                        host_verdict_seen_ns=10000,csr_15=700)
        d=calculated(row)
        self.assertEqual(d['verdict_available_ms'],d['fpga_complete_ms'])


if __name__=='__main__':unittest.main()
