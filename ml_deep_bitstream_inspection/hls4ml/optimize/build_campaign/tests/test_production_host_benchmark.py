import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import production_host_benchmark as benchmark


class CollectionTest(unittest.TestCase):
    def test_warmup_exclusion_and_failure_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);output=root/'out';output.mkdir();sw=root/'build/prod_res256_manualA_coyote_accel_cyt_sw';(sw/'lib').mkdir(parents=True)
            for p in [sw/'lib/libCoyoteInference.so',sw/'libCoyote.so',root/'bit',root/'driver',root/'production_tolerances.json']:p.write_bytes(b'test')
            image=dict(job='R_O',bitstream=str(root/'bit'),sha256=benchmark.sha(root/'bit'),driver=str(root/'driver'),driver_sha256=benchmark.sha(root/'driver'))
            (root/'installed_image.json').write_text(json.dumps(image));(root/'input').write_bytes(b'\0')
            case=dict(id='case',sweep='synthetic',bytes=1,path=str(root/'input'),sha256=benchmark.sha(root/'input'),expected_logit_hex='00000000')
            class Session:
                def __enter__(self):self.n=0;return self
                def __exit__(self,*args):pass
                def prepare(self,raw):pass
                def run(self):
                    duration=10000000 if self.n<20 else 1000000;self.n+=1
                    return dict(host_start_ns=0,submit_start_ns=10,predict_return_ns=duration-10,host_verdict_seen_ns=duration,raw_bytes=1,transport_bytes=65,logit_bits=0,verdict=1)
            class Overlay:
                def __init__(self,*args):pass
                def open_production_session(self,*args):return Session()
            with patch.object(benchmark,'RawCoyoteOverlay',Overlay),patch.object(benchmark.ctypes,'CDLL'),patch.object(benchmark,'read_cases',return_value=[case]),patch.object(benchmark,'load_tolerances',return_value={case['sha256']:None}),patch.object(benchmark,'record'):
                benchmark.collect(root,'R_O',root,output,'full')
                result=json.loads((output/'full.analysis.json').read_text());self.assertEqual(result['trials'],220)
                row=result['summary'][0];self.assertEqual(row['median_ms'],1);self.assertEqual(row['p95_upper95_ms'],1);self.assertEqual(row['first_call_ms'],10)
                failed=root/'failed';failed.mkdir()
                with patch.object(benchmark,'check_logit',side_effect=ValueError('parity failure')):
                    with self.assertRaisesRegex(ValueError,'parity failure'):benchmark.collect(root,'R_O',root,failed,'full')
                self.assertEqual(json.loads((failed/'full.jsonl').read_text())['validation'],'failed')
                self.assertFalse((failed/'full.analysis.json').exists())
