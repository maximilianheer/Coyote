import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import production_candidate as candidate
from prepare import HARDWARE, PACKAGE, sha


class CandidateTests(unittest.TestCase):
    def test_failed_board_evidence_prevents_preparation(self):
        from production_isolation import prepare_isolation
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(candidate, 'prerequisites', side_effect=RuntimeError('R_S parity failed')):
                with self.assertRaisesRegex(RuntimeError, 'parity failed'):
                    prepare_isolation(root, {'id':'R_SO_T'}, {})
            self.assertFalse((root/'jobs').exists())

    def test_prerequisites_accept_separate_campaigns_and_reject_changed_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec={'board':str(root/'board')}
            for variant in ('R_O','R_S'):
                job=root/variant.lower()/'jobs'/variant
                kernel=job/'hw/src/hls/model_wrapper';kernel.mkdir(parents=True)
                pairs=[('common/conv0_dataflow.hpp','conv0_dataflow.hpp')] if variant=='R_O' else [
                    ('variants/production_streaming.cpp','model_wrapper.cpp'),
                    ('common/production_inference.hpp','production_inference.hpp'),
                    ('common/frame_start.hpp','frame_start.hpp')]
                for source,target in pairs:shutil.copy2(HARDWARE/source,kernel/target)
                spec[variant]={'job':str(job),'evidence':str(root/(variant+'_evidence'))}
            with patch('isolation_evidence.verified_board_parity',return_value={'board_calls':260}) as check:
                self.assertEqual(set(candidate.prerequisites({'production_prerequisites':spec})),{'R_O','R_S'})
                self.assertEqual(check.call_count,2)
                (Path(spec['R_S']['job'])/'hw/src/hls/model_wrapper/frame_start.hpp').write_text('changed')
                with self.assertRaisesRegex(RuntimeError,'differs from board-validated'):
                    candidate.prerequisites({'production_prerequisites':spec})

    def test_configuration_preserves_host_implementation_and_uses_maintained_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp)
            for directory in ('hw/src/hdl','host','tests','coyote/scripts/cr_prjcts'):
                (job/directory).mkdir(parents=True)
            frozen=PACKAGE/'sources/generated_project/src/host_libs.cpp'
            shutil.copy2(frozen,job/'host/host_libs.cpp')
            script=job/'coyote/scripts/cr_prjcts/cr_user.tcl.in'
            script.write_text('source "${CMAKE_BINARY_DIR}/base.tcl"\ncreate_project untouched\n')
            candidate.configure(job,{'R_O':{'board_calls':260},'R_S':{'board_calls':260}})
            self.assertEqual(sha(frozen),sha(job/'host/host_libs.cpp'))
            self.assertEqual(sha(job/'hw/src/vfpga_top.svh'),sha(HARDWARE/'production/vfpga_timed.svh'))
            self.assertIn('source "${CMAKE_SOURCE_DIR}/src/observer/package_campaign.tcl"',script.read_text())
            self.assertTrue(script.read_text().endswith('create_project untouched\n'))

    def test_rtl_gate_handles_echoed_logs_but_rejects_missing_frames_and_changed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);rtl=job/'rtl';rtl.mkdir();source=rtl/'model.v';source.write_text('RTL')
            (rtl/'sources.json').write_text(json.dumps({'model.v':sha(source)}))
            frames=''.join(f'PASS production passive frame={i} bytes={i} exact_pixels=65536\n' for i in range(8))
            final='PASS production wrapper frames=8 driver_resets=1\n'
            log=job/'wrapper_rtl.log';log.write_text(frames+final+frames+final)
            candidate.verify_rtl(job,rtl)
            log.write_text(frames.replace('frame=7','frame=6')+final)
            with self.assertRaisesRegex(RuntimeError,'Incomplete'):candidate.verify_rtl(job,rtl)
            log.write_text(frames+final);source.write_text('changed RTL')
            with self.assertRaisesRegex(RuntimeError,'inputs changed'):candidate.verify_rtl(job,rtl)


if __name__=='__main__':unittest.main()
