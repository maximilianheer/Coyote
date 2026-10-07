import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import floorplan, configure_refinement, sha


class FloorplanRefinementTests(unittest.TestCase):
    def test_xdc_contains_only_declarative_geometry(self):
        text = floorplan((2, 0, 2, 0))
        self.assertIn('CLOCKREGION_X2Y0:CLOCKREGION_X2Y0', text)
        for command in ['foreach ', 'lsort ', 'lindex ', 'if {']:
            self.assertNotIn(command, text)

    def test_refinement_runs_between_link_and_saved_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'hw').mkdir(); (root/'build').mkdir()
            (root/'hw/floorplan_refine.tcl').write_text('puts TEST\n')
            (root/'source_manifest.json').write_text('{}')
            flow = root/'build/flow_dyn.tcl'
            original = 'eval $cmd\nwrite_checkpoint -force "$dcp_dir/config_0/shell_linked_c0.dcp"\nplace_design\n'
            flow.write_text(original)
            configure_refinement(root)
            result = flow.read_text()
            self.assertIn('set_msg_config -id {Designutils 20-1307} -new_severity ERROR', result)
            self.assertLess(result.index('eval $cmd'), result.index('source {'))
            self.assertLess(result.index('source {'), result.index('write_checkpoint'))
            self.assertEqual((root/'build/flow_dyn_before_refinement.tcl').read_text(), original)
            provenance = json.loads((root/'floorplan_implementation.json').read_text())
            self.assertEqual(provenance['implementation_script_sha256'], sha(flow))

    def test_missing_hook_fails_before_modifying_generated_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'hw').mkdir(); (root/'build').mkdir()
            (root/'hw/floorplan_refine.tcl').write_text('puts TEST\n')
            flow = root/'build/flow_dyn.tcl';flow.write_text('unexpected flow\n')
            with self.assertRaisesRegex(RuntimeError, 'unique config-0'):
                configure_refinement(root)
            self.assertEqual(flow.read_text(), 'unexpected flow\n')


if __name__ == '__main__': unittest.main()
