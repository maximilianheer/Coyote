from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production_timestamps import ABI, MASK, read_snapshot


class TimestampTests(unittest.TestCase):
    def registers(self, origin=100):
        regs = {0: ABI, 2: 7, 3: 2, 4: 31, 10: 65536, 11: 65536, 12: 65, 13: 3}
        for index, delta in enumerate((0, 5, 100, 10, 120), 5):
            regs[index] = (origin+delta) & MASK
        return regs

    def test_overlap_and_counter_rollover(self):
        for origin in (100, MASK-20):
            snapshot = read_snapshot(self.registers(origin).__getitem__, 65, 6)
            self.assertEqual(snapshot['interval_ticks'], dict(preprocessing_startup=5,
                preprocessing_elapsed=100, cnn_elapsed=110, cnn_tail=20, fpga_pipeline=120))

    def test_reject_invalid_capture(self):
        for register, value in ((0, 0), (2, 6), (3, 3), (3, 6), (4, 15),
                                (10, 65535), (11, 65537), (12, 64), (13, 2),
                                (6, 99), (8, 104), (9, 199)):
            with self.subTest(register=register, value=value):
                regs = self.registers(); regs[register] = value
                with self.assertRaises(RuntimeError):
                    read_snapshot(regs.__getitem__, 65, 6)

    def test_reject_torn_readout(self):
        regs = self.registers(); reads = 0
        def reader(index):
            nonlocal reads
            if index == 2:
                reads += 1
                return 7 if reads == 1 else 8
            return regs[index]
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            read_snapshot(reader, 65, 6)


if __name__ == '__main__': unittest.main()
