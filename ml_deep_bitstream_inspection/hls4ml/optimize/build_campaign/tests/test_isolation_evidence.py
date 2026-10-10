"""Prerequisite audit against copies of completed board evidence, never a board."""
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isolation_evidence import verified_board_parity

JOB=os.environ.get('ISOLATION_JOB')
BOARD=os.environ.get('BOARD_ROOT')
EVIDENCE=os.environ.get('BOARD_EVIDENCE')


@unittest.skipUnless(JOB and BOARD and EVIDENCE,'completed board evidence paths required')
class EvidenceTests(unittest.TestCase):
    def copy_evidence(self, root):
        for name in ('status.json','isolation_validation.json','production.csv'):
            shutil.copy2(Path(EVIDENCE)/name,root/name)

    def check(self, evidence):
        return verified_board_parity(Path(JOB),Path(BOARD),evidence)

    def test_live_evidence_passes_without_modification(self):
        self.assertEqual(self.check(Path(EVIDENCE))['board_calls'],260)

    def test_duplicate_trial_rejected_despite_passed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.copy_evidence(root)
            with (root/'production.csv').open() as stream:rows=list(csv.DictReader(stream))
            rows[1]=dict(rows[0])
            with (root/'production.csv').open('w') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(RuntimeError,'Duplicate'):
                self.check(root)

    def test_wrong_library_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.copy_evidence(root)
            path=root/'isolation_validation.json';result=json.loads(path.read_text())
            result['library_sha256']='0'*64;path.write_text(json.dumps(result))
            with self.assertRaisesRegex(RuntimeError,'identity mismatch'):
                self.check(root)

    def test_missing_trial_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.copy_evidence(root);path=root/'production.csv'
            path.write_text('\n'.join(path.read_text().splitlines()[:-1])+'\n')
            with self.assertRaisesRegex(RuntimeError,'260 board result rows'):
                self.check(root)


if __name__=='__main__':unittest.main()
