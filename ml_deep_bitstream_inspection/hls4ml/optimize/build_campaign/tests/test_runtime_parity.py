import ctypes
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parents[1]))
from parity_gate import check_logit
from pipeline.coyote_accelerator.direct_session import DirectCoyoteSession,Measurement
from pipeline.coyote_accelerator.raw_overlay import RawCoyoteOverlay


def bits(f):return struct.unpack('<I',struct.pack('<f',f))[0]


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.case=dict(sha256='abc',bytes=64,expected_logit_hex='3f800000')
        self.tolerance=dict(self.case,production_verdict=1,repetitions=10,max_abs_error=.125)

    def test_per_input_boundary_and_no_blanket_allowance(self):
        check_logit(bits(1.125),1,self.case,self.tolerance)
        with self.assertRaisesRegex(ValueError,'tolerance'):check_logit(bits(1.126),1,self.case,self.tolerance)
        with self.assertRaisesRegex(ValueError,'exact-logit'):check_logit(bits(1.001),1,self.case)
        self.tolerance['max_abs_error']=0
        check_logit(bits(1),1,self.case,self.tolerance)
        with self.assertRaises(ValueError):check_logit(bits(1.001),1,self.case,self.tolerance)

    def test_verdict_flip_rejected_even_inside_tolerance(self):
        self.tolerance['max_abs_error']=2
        with self.assertRaisesRegex(ValueError,'verdict'):check_logit(bits(-.1),0,self.case,self.tolerance)

    def test_bad_reference_and_nonfinite_rejected(self):
        for change in [dict(sha256='changed'),dict(bytes=65),dict(repetitions=9),dict(production_verdict=0),dict(max_abs_error=float('nan'))]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                check_logit(bits(1),1,self.case,dict(self.tolerance,**change))
        for x in [float('nan'),float('inf'),float('-inf')]:
            with self.assertRaises(ValueError):check_logit(bits(x),1,self.case,self.tolerance)


class Function:
    def __init__(self,fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)


class SessionTests(unittest.TestCase):
    def library(self):
        class Library:pass
        lib=Library();self.closes=0
        lib.campaign_last_error=Function(lambda:b'FPGA timeout')
        lib.campaign_init=Function(lambda *args:1234)
        lib.campaign_prepare=Function(lambda *args:0)
        def predict(handle,pointer):
            m=ctypes.cast(pointer,ctypes.POINTER(Measurement)).contents
            m.csr[20]=(1<<32)|bits(1.25)
            return 0
        lib.campaign_predict=Function(predict)
        lib.campaign_clock=Function(lambda *args:0)
        def close(handle):self.closes+=1;return 0
        lib.campaign_close=Function(close)
        return lib

    def test_context_and_explicit_sink_result(self):
        with patch('ctypes.CDLL',return_value=self.library()):
            with RawCoyoteOverlay.open_direct_session('/unused','direct_sink',64) as session:
                result=session.run()
                self.assertIsNone(result['logit']);self.assertIsNone(result['verdict'])
            session.close();self.assertEqual(self.closes,1)
            with self.assertRaisesRegex(RuntimeError,'closed'):session.run()

    def test_checker_decode_bounds_and_native_error(self):
        lib=self.library()
        with patch('ctypes.CDLL',return_value=lib):
            with DirectCoyoteSession('/unused','direct_checker',1) as session:
                self.assertEqual(session.run()['logit'],1.25)
                with self.assertRaises(ValueError):session.prepare([1,2])
                lib.campaign_predict=Function(lambda *args:-1)
                with self.assertRaisesRegex(RuntimeError,'FPGA timeout'):session.run()
        self.assertEqual(self.closes,1)

if __name__=='__main__':unittest.main()
