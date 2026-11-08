"""Check campaign capacity without changing legacy lane allocation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from implementation_permits import available_slots


class SharedPermitsTest(unittest.TestCase):
    def test_opt_in_five_shared_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(available_slots(root, 'primary'), [0, 1, 2])
            self.assertEqual(available_slots(root, 'nonstreaming'), [3])
            (root / 'capacity.json').write_text(json.dumps({
                'policy': 'shared', 'slots': 5,
            }))
            self.assertEqual(available_slots(root, 'primary'), list(range(5)))
            self.assertEqual(available_slots(root, 'nonstreaming'), list(range(5)))

    def test_reject_invalid_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in [0, 6, True, '5']:
                (root / 'capacity.json').write_text(json.dumps({
                    'policy': 'shared', 'slots': value,
                }))
                with self.assertRaises(ValueError):
                    available_slots(root, 'primary')


if __name__ == '__main__':
    unittest.main()
