"""Check additive-only tap edits against an isolated real HLS export.

Run with HLS_EXPORT pointing to the completed R_S IP directory. No live source
is changed. Full IP packaging and RTL behavior are separately validated.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SNIPPETS = Path(__file__).resolve().parents[1]/'hardware/production'
EXPORT = os.environ.get('HLS_EXPORT')


@unittest.skipUnless(EXPORT, 'HLS_EXPORT required for generated-source contract checks')
class ExportTests(unittest.TestCase):
    def test_additive_only_and_reject_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for lang, suffix in [('verilog', 'v'), ('vhdl', 'vhd')]:
                source = Path(EXPORT)/'hdl'/lang/f'model_wrapper.{suffix}'
                target = root/source.name
                shutil.copy2(source, target)
                script = f'source {{{SNIPPETS}/export_fifo_taps.tcl}}\npassive_taps::{lang} {{{target}}} {{{SNIPPETS}}}\n'
                result = subprocess.run(['tclsh'], input=script, text=True, capture_output=True)
                self.assertEqual(result.stderr, '')
                modified = target.read_text()
                if lang == 'verilog':
                    pieces = ['fifo_tap_ports.vh', 'fifo_taps.vh']
                else:
                    pieces = ['fifo_tap_ports.vhd.inc', 'fifo_taps.vhd.inc']
                for piece in pieces:
                    addition = (SNIPPETS/piece).read_text()
                    self.assertEqual(modified.count(addition), 1)
                    modified = modified.replace(addition, '', 1)
                self.assertEqual(modified, source.read_text())
                duplicate = subprocess.run(['tclsh'], input=script, text=True, capture_output=True)
                self.assertIn('Already instrumented', duplicate.stderr)

    def test_reject_changed_fifo_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(EXPORT)/'hdl/verilog/model_wrapper.v'
            target = Path(tmp)/source.name
            original = source.read_text()
            for old, new in [(".if_write_ce(1'b1)", ".if_write_ce(changed_ce)"),
                             ('model_wrapper_fifo_w16_d32_S', 'model_wrapper_fifo_w16_d64_S'),
                             ('.if_full_n(bitstream_input_full_n)', '.if_full_n(other_full_n)')]:
                target.write_text(original.replace(old, new))
                before = target.read_bytes()
                script = f'source {{{SNIPPETS}/export_fifo_taps.tcl}}\npassive_taps::verilog {{{target}}} {{{SNIPPETS}}}\n'
                result = subprocess.run(['tclsh'], input=script, text=True, capture_output=True)
                self.assertNotEqual(result.stderr, '')
                self.assertEqual(target.read_bytes(), before)


if __name__ == '__main__': unittest.main()
