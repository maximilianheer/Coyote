import ctypes
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.coyote_accelerator.raw_overlay import RawCoyoteOverlay


class ProductionSessionTests(unittest.TestCase):
    def overlay(self, free=100):
        self.calls = []
        self.result = ctypes.c_float(-0.5)
        def call(name, value=None):
            def fn(*args):
                self.calls.append((name, args))
                return value
            return fn
        lib = SimpleNamespace(
            init_model_inference_raw=call('init', 123),
            set_inference_raw_data=call('prepare'), flush=call('flush'),
            predict=call('predict'),
            get_inference_predictions=call('result', ctypes.pointer(self.result)),
            free_model_inference=call('free'))
        obj = RawCoyoteOverlay.__new__(RawCoyoteOverlay)
        obj.coyote_lib = lib
        obj._free_hugepages_2m = lambda: free
        return obj

    def test_one_context_repeated_calls_and_length_changes(self):
        with self.overlay().open_production_session(65) as session:
            for size in (65, 0, 1, 64):
                session.prepare([3]*size)
                for _ in range(2):
                    result = session.run()
                    self.assertEqual(result['transport_bytes'], 64+size)
                    self.assertEqual(result['logit_bits'], 0xbf000000)
                    self.assertEqual(result['verdict'], 0)
                    stamps = [result[k] for k in ['host_start_ns', 'submit_start_ns',
                              'predict_return_ns', 'host_verdict_seen_ns']]
                    self.assertEqual(stamps, sorted(stamps))
        session.close()
        names = [name for name, _ in self.calls]
        self.assertEqual(names.count('init'), 1)
        self.assertEqual(names.count('free'), 1)
        self.assertEqual(names.count('predict'), 8)
        self.assertEqual(names[2:5], ['flush', 'predict', 'result'])
        self.assertEqual(self.calls[0][1], (1, 65, 1))

    def test_guards_do_not_enter_native_predict(self):
        overlay = self.overlay()
        with overlay.open_production_session(1) as session:
            with self.assertRaisesRegex(RuntimeError, 'prepare'): session.run()
            with self.assertRaises(ValueError): session.prepare([1, 2])
        with self.assertRaisesRegex(RuntimeError, 'closed'): session.run()
        self.assertNotIn('predict', [name for name, _ in self.calls])
        with self.assertRaises(ValueError): overlay.open_production_session(134217665)
        with self.assertRaisesRegex(RuntimeError, 'hugepages'):
            self.overlay(free=0).open_production_session(1)

    def test_optional_read_only_csr_uses_same_context(self):
        overlay = self.overlay()
        with overlay.open_production_session(1) as session:
            with self.assertRaisesRegex(RuntimeError, 'no read-only'):
                session.read_csr(0)
            calls = []
            def read(handle, index):
                calls.append((handle, index))
                return 0x123456789abcdef0
            overlay.coyote_lib.production_read_csr = read
            self.assertEqual(session.read_csr(1), 0x123456789abcdef0)
            self.assertEqual(calls, [(123, 1)])
            self.assertEqual(read.restype, ctypes.c_uint64)
            with self.assertRaises(ValueError): session.read_csr(512)
            self.assertNotIn('predict', [name for name, _ in self.calls])
        with self.assertRaisesRegex(RuntimeError, 'closed'): session.read_csr(0)


if __name__ == '__main__': unittest.main()
