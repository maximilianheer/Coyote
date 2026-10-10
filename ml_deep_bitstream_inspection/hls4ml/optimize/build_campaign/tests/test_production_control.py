"""Exercise the board-validation CLI with fake native calls, never a device."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parents[1]))
from board_benchmark import sha
from production_timestamps import ABI


class FakeSession:
    def __init__(self, stale=False):
        self.calls=0;self.closed=False;self.stale=stale
        self.regs={0:ABI,2:0}

    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def prepare(self,raw):self.size=raw.size
    def read_csr(self,index):return self.regs[index]

    def run(self):
        self.calls+=1;origin=self.calls*1000
        self.regs={0:ABI,2:self.calls-int(self.stale and self.calls==2),3:2,4:31,
                   10:65536,11:65536,12:self.size,13:1+(self.size+63)//64}
        for index,delta in enumerate((0,5,100,10,120),5):self.regs[index]=origin+delta
        return dict(raw_bytes=self.size,transport_bytes=64+self.size,
            host_start_ns=origin*4-20,submit_start_ns=origin*4-16,
            predict_return_ns=(origin+120)*4+4,host_verdict_seen_ns=(origin+120)*4+8,
            logit=-1.0,logit_bits=0xbf800000,verdict=0)


class FakeOverlay:
    def __init__(self,stale=False):
        self.session=FakeSession(stale);self.legacy_calls=0;self.session_calls=0
    def open_production_session(self,capacity):
        self.session_calls+=1;return self.session
    def predict_raw(self,raw,shape,batch_size):
        self.legacy_calls+=1
        return np.full((len(raw),1),-1.0,dtype=np.float32)


class ProductionControlTests(unittest.TestCase):
    def fixture(self,root):
        cases=root/'cases.tsv';rows=[];tolerances={}
        for size in range(26):
            path=root/f'input_{size}';path.write_bytes(bytes([size])*size)
            digest=sha(path)
            rows.append(f'case_{size}\ttest\t{path}\t{size}\t{digest}\tbf800000\n')
            tolerances[digest]=dict(sha256=digest,bytes=size,expected_logit_hex='bf800000',
                production_verdict=0,repetitions=10,max_abs_error=0)
        cases.write_text(''.join(rows))
        tolerance=root/'tolerances.json';tolerance.write_text(json.dumps(dict(status='passed',
            policy='per-input production maximum absolute error; 10 repeats',inputs=tolerances)))
        project=root/'project'
        for relative in ['build/prod_res256_manualA_coyote_accel_cyt_sw/libCoyote.so',
                         'build/prod_res256_manualA_coyote_accel_cyt_sw/lib/libCoyoteInference.so',
                         'build/prod_res256_manualA_coyote_accel_cyt_hw/bitstreams/cyt_top.bit']:
            path=project/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture only')
        output=root/'output';output.mkdir()
        return [str(HERE/'production_control.py'),str(cases),str(output),'--project',str(project),
                '--acceptance-tolerances',str(tolerance)],output

    def execute(self,args,overlay):
        with patch.object(sys,'argv',args),patch('ctypes.CDLL'),redirect_stdout(io.StringIO()),\
             patch('pipeline.coyote_accelerator.raw_overlay.RawCoyoteOverlay',return_value=overlay):
            runpy.run_path(str(HERE/'production_control.py'),run_name='__main__')

    def test_passive_mode_checks_260_captures_in_one_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,output=self.fixture(Path(tmp));overlay=FakeOverlay()
            with self.assertRaises(SystemExit) as ended:
                self.execute(args+['--persistent','--passive-monitor'],overlay)
            self.assertEqual(ended.exception.code,0)
            result=json.loads((output/'isolation_validation.json').read_text())
            self.assertEqual(result['status'],'passed')
            self.assertEqual(len(result['inputs']),26)
            self.assertEqual(result['passive_timestamps']['frames'],260)
            self.assertEqual(overlay.session_calls,1)
            self.assertTrue(overlay.session.closed)
            self.assertEqual(len((output/'host_observed.jsonl').read_text().splitlines()),260)

    def test_stale_monitor_capture_never_admits_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,output=self.fixture(Path(tmp));overlay=FakeOverlay(stale=True)
            with self.assertRaisesRegex(RuntimeError,'stale/skipped'):
                self.execute(args+['--persistent','--passive-monitor'],overlay)
            self.assertFalse((output/'isolation_validation.json').exists())
            trace=[json.loads(line) for line in (output/'host_observed.jsonl').read_text().splitlines()]
            self.assertEqual(len(trace),2)
            self.assertIn('monitor_error',trace[-1])
            self.assertTrue(overlay.session.closed)

    def test_default_preserves_production_predict_raw_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,output=self.fixture(Path(tmp));overlay=FakeOverlay()
            with self.assertRaises(SystemExit) as ended:self.execute(args,overlay)
            self.assertEqual(ended.exception.code,0)
            self.assertEqual(overlay.legacy_calls,26)
            self.assertEqual(overlay.session_calls,0)
            self.assertNotIn('passive_timestamps',json.loads((output/'isolation_validation.json').read_text()))


if __name__=='__main__':unittest.main()
