import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deployment_abi import decode, identify, SIGNATURE


class DeploymentAbiTest(unittest.TestCase):
    def test_reject_old_and_unknown_signatures(self):
        for signature in [0x434259540004000b, 0, SIGNATURE | 99]:
            with self.assertRaises(ValueError):
                identify(signature)

    def test_valid_ticks_and_counter_mapping(self):
        registers = [0] * 64
        registers[4] = SIGNATURE | 13
        registers[7] = 1 << 2
        registers[18] = 12345
        registers[55] = 4
        result = decode(registers)
        self.assertEqual(result['events']['network_accepted_first'], 12345)
        self.assertIsNone(result['events']['network_accepted_last'])
        self.assertEqual(result['counters']['freed_chunks'], 4)


if __name__ == '__main__':
    unittest.main()
