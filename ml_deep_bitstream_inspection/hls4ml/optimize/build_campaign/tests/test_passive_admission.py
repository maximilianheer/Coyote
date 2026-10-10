import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isolation_evidence import verified_passive_captures
from production_benchmark import collect_session
from production_timestamps import ABI
import test_production_benchmark as fixtures


class PassiveAdmissionTests(unittest.TestCase):
    def fixture(self,root):
        cases,tolerances=fixtures.ProductionBenchmarkTests().cases(root,tuple(range(26)))
        observations,clocks=io.StringIO(),io.StringIO()
        with redirect_stdout(io.StringIO()):
            collect_session(fixtures.FakeProductionSession(),cases,tolerances,observations,clocks,trials=10,warmups=0)
        records=[json.loads(line) for line in observations.getvalue().splitlines()]
        for record in records:record['logit_hex']=f"{record['logit_bits']:08x}"
        rows=[dict(case_id=r['case_id'],trial=str(r['trial']),logit_hex=r['logit_hex'],verdict=str(r['verdict'])) for r in records]
        path=root/'host_observed.jsonl';self.write(path,records)
        result=dict(runtime_lifecycle='one persistent production context',
                    passive_timestamps=dict(status='passed',frames=260,abi=ABI))
        return {c['id']:c for c in cases},rows,result,records,path

    def write(self,path,records):
        path.write_text(''.join(json.dumps(record)+'\n' for record in records))

    def test_valid_captures_and_incorrect_cached_decoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cases,rows,result,records,path=self.fixture(root)
            self.assertEqual(len(verified_passive_captures(root,cases,rows,result)),64)
            records[20]['monitor']['interval_ticks']['cnn_elapsed']+=1;self.write(path,records)
            with self.assertRaisesRegex(RuntimeError,'decoding changed'):
                verified_passive_captures(root,cases,rows,result)

    def test_stale_capture_and_result_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cases,rows,result,records,path=self.fixture(root)
            records[1]['monitor']=records[0]['monitor'];self.write(path,records)
            with self.assertRaisesRegex(RuntimeError,'stale/skipped'):
                verified_passive_captures(root,cases,rows,result)
            records[1]['logit_bits']=0;self.write(path,records)
            with self.assertRaisesRegex(RuntimeError,'result row'):
                verified_passive_captures(root,cases,rows,result)


if __name__=='__main__':unittest.main()
