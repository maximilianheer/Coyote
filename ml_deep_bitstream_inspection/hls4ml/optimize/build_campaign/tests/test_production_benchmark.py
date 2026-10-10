import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from board_benchmark import sha
from production_benchmark import analyze, collect_session, components
from production_timestamps import ABI


class FakeProductionSession:
    def __init__(self, bad_call=None):
        self.frame = 9; self.size = None; self.calls = 0; self.bad_call = bad_call
        self.registers = {0: ABI, 1: 1000, 2: self.frame}

    def read_csr(self, index):
        return self.registers[index]

    def prepare(self, raw):
        self.size = len(raw)

    def run(self):
        self.calls += 1; self.frame += 1
        origin = self.frame*1000
        self.registers = {0: ABI, 1: origin+121, 2: self.frame, 3: 2, 4: 31,
                          10: 65536, 11: 65536, 12: self.size, 13: 1+(self.size+63)//64}
        for index, delta in enumerate((0, 5, 100, 10, 120), 5):
            self.registers[index] = origin+delta
        return dict(raw_bytes=self.size, transport_bytes=64+self.size,
                    host_start_ns=origin*4-20, submit_start_ns=origin*4-16,
                    predict_return_ns=(origin+120)*4+4, host_verdict_seen_ns=(origin+120)*4+8,
                    logit=-1.0, logit_bits=0xbf800000, verdict=int(self.calls==self.bad_call))


class ProductionBenchmarkTests(unittest.TestCase):
    def cases(self, root, sizes=(1,65)):
        cases=[]; tolerances={}
        for size in sizes:
            path=root/f'{size}.bin'; path.write_bytes(bytes(size))
            case=dict(id=f'case_{size}', sweep='test', path=str(path), bytes=size,
                      sha256=sha(path), expected_logit_hex='bf800000')
            cases.append(case)
            tolerances[case['sha256']]=dict(sha256=case['sha256'], bytes=size,
                expected_logit_hex='bf800000', production_verdict=0, repetitions=10, max_abs_error=0)
        return cases,tolerances

    def test_counts_context_and_interval_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases,tolerances=self.cases(Path(tmp))
            observations,calibration=io.StringIO(),io.StringIO()
            session=FakeProductionSession()
            self.assertEqual(collect_session(session,cases,tolerances,observations,calibration,trials=3,warmups=2),10)
            rows=[json.loads(line) for line in observations.getvalue().splitlines()]
            clocks=[json.loads(line) for line in calibration.getvalue().splitlines()]
            self.assertEqual([r['monitor']['frame_id'] for r in rows],list(range(10,20)))
            for case in cases:
                trials=[r for r in rows if r['case_id']==case['id']]
                self.assertEqual([r['warmup'] for r in trials],[1,1,0,0,0])
                for position in ('before','after'):
                    self.assertEqual(sum(r['case_id']==case['id'] and r['position']==position for r in clocks),32)
                derived=components(trials[0],case,lambda tick:(tick*4,tick*4),4,tolerances[case['sha256']])
                self.assertAlmostEqual(derived['total_ms'],0.0005)
                self.assertAlmostEqual(derived['preprocessing_elapsed_ms'],0.0004)
                self.assertAlmostEqual(derived['cnn_elapsed_ms'],0.00044)
                self.assertAlmostEqual(derived['overlap_ms'],0.00036)
                self.assertNotIn('transfer_ms',derived)
                self.assertNotIn('dma_call_ms',derived)

    def test_verdict_failure_preserved_and_stops_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases,tolerances=self.cases(Path(tmp))
            observations,calibration=io.StringIO(),io.StringIO(); session=FakeProductionSession(bad_call=2)
            with self.assertRaisesRegex(ValueError,'verdict parity'):
                collect_session(session,cases,tolerances,observations,calibration,trials=3,warmups=0)
            rows=[json.loads(line) for line in observations.getvalue().splitlines()]
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[-1]['validation'],'failed')
            self.assertEqual(session.calls,2)

    def test_full_analysis_requires_trials_warmups_and_clock_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); attempt=root/'attempt';attempt.mkdir()
            cases,tolerances=self.cases(root,(65536,))
            (root/'inputs.json').write_text(json.dumps(dict(cases=cases)))
            (root/'production_tolerances.json').write_text(json.dumps(dict(status='passed',
                policy='per-input production maximum absolute error; 10 repeats',inputs=tolerances)))
            with (attempt/'full.jsonl').open('w') as rows:
                collect_session(FakeProductionSession(),cases,tolerances,rows,io.StringIO())
            clocks=[]
            for position,origin in [('before',1000),('after',500000)]:
                for i in range(32):
                    tick=origin+i*10
                    clocks.append(dict(case_id=cases[0]['id'],position=position,
                        host_before_ns=tick*4-2,fpga_tick=tick,host_after_ns=tick*4+2))
            clockfile=attempt/'full.clock.jsonl'
            clockfile.write_text(''.join(json.dumps(c)+'\n' for c in clocks))
            result=analyze(root,attempt)
            self.assertEqual(result['trials'],220)
            self.assertEqual(result['summary'][0]['measured'],200)
            self.assertEqual(result['summary'][0]['warmups'],20)
            self.assertLess(result['summary'][0]['p95_upper95_ms'],0.00051)
            clockfile.write_text(''.join(json.dumps(c)+'\n' for c in clocks[:-1]))
            with self.assertRaisesRegex(ValueError,'calibration'):
                analyze(root,attempt)
            clockfile.write_text(''.join(json.dumps(c)+'\n' for c in clocks))
            rows=[json.loads(line) for line in (attempt/'full.jsonl').read_text().splitlines()]
            rows[20]['warmup']=1
            (attempt/'full.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'warmup'):
                analyze(root,attempt)


if __name__=='__main__': unittest.main()
