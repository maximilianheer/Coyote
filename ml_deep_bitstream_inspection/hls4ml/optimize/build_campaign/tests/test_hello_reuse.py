from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reuse_hello import configuration,try_reuse

class HelloReuseTests(unittest.TestCase):
    def test_floorplan_can_change_but_clocks_and_interfaces_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'H2';b=Path(tmp)/'HN'
            for d in [a,b]:
                (d/'build').mkdir(parents=True)
                (d/'build/base.tcl').write_text(f'set cfg(build_dir) {d}/build\n'
                    f'set cfg(fplan_path) {d}/hw/floorplan.xdc\nset cfg(aclk_p) 4\nset cfg(n_strm) 2\n')
            self.assertEqual(configuration(a),configuration(b))
            p=b/'build/base.tcl';p.write_text(p.read_text().replace('cfg(aclk_p) 4','cfg(aclk_p) 5'))
            self.assertNotEqual(configuration(a),configuration(b))

    def test_diagnostics_and_containment_experiment_never_reuse_hello_shell(self):
        for ident in ['S_I','I','U','N','P','C','HE']:
            self.assertFalse(try_reuse(Path('/nonexistent'),dict(id=ident)))

if __name__=='__main__':unittest.main()
