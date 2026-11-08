"""Exercise real process locks, the sixth-job wait and crash recovery."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from implementation_permits import permit


def acquire(directory, identifier):
    os.environ['HLS4ML_IMPLEMENTATION_PERMITS'] = directory
    os.environ['HLS4ML_IMPLEMENTATION_LANE'] = 'primary'
    with permit():
        root = Path(directory)
        (root / f'entered_{identifier}').touch()
        # A killed process must not strand a multiprocessing Event/Queue lock.
        while not (root / 'release').exists():
            time.sleep(0.05)


class SharedPermitProcessesTest(unittest.TestCase):
    def test_sixth_waits_and_crash_releases_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'capacity.json').write_text(json.dumps({'policy': 'shared', 'slots': 5}))
            children = []
            def wait_until(predicate):
                deadline = time.monotonic() + 6
                while not predicate():
                    if time.monotonic() > deadline:
                        self.fail('Timed out waiting for process lock transition')
                    time.sleep(0.05)
            try:
                for identifier in range(5):
                    child = multiprocessing.Process(target=acquire,
                        args=(directory, identifier))
                    child.start()
                    children.append(child)
                wait_until(lambda: len(list(root.glob('entered_*'))) == 5)
                sixth = multiprocessing.Process(target=acquire,
                    args=(directory, 5))
                sixth.start()
                children.append(sixth)
                time.sleep(0.3)
                self.assertFalse((root / 'entered_5').exists())
                children[0].terminate()
                children[0].join(timeout=3)
                wait_until(lambda: (root / 'entered_5').exists())
            finally:
                (root / 'release').touch()
                for child in children:
                    child.join(timeout=3)
                    if child.is_alive():
                        child.terminate()
                        child.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
