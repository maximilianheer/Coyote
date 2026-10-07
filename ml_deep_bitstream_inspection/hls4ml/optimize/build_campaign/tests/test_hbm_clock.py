import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hbm_clock import (configure_hbm_clock, verify_hbm_clock_sources, hbm_setup_failure,
                       verify_generated_hbm_clock, verify_report_hbm_clock)
from prepare import COYOTE
from recovery import recover_failed


def report(clock='clk_out1_design_hbm_clk_wiz_0_0', hold=0):
    return f'''Timing constraints are not met.
 WNS(ns) TNS(ns) Failing Total WHS(ns) THS(ns) Failing Total WPWS(ns)
 --------
 -0.049 -4.554 188 5000 {(-0.01 if hold else 0.002)} 0 {hold} 5000 0.001
From Clock: {clock}
  To Clock: {clock}

Setup : 188 Failing Endpoints, Worst Slack -0.049ns
Hold : {hold} Failing Endpoints, Worst Slack 0.002ns
PW : 0 Failing Endpoints, Worst Slack 0.001ns
'''


class HbmClockTests(unittest.TestCase):
    def test_generated_ip_clock_ratios_and_routed_frequency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(ip, parameters):
                data = {'ip_inst': {'parameters': {'component_parameters':
                    {key:[{'value':str(value)}] for key,value in parameters.items()}}}}
                (root/f'design_hbm_{ip}.xci').write_text(json.dumps(data))
            clock=dict(CLKOUT1_REQUESTED_OUT_FREQ=400,PRIM_IN_FREQ=100,
                MMCM_CLKFBOUT_MULT_F=12,MMCM_DIVCLK_DIVIDE=1,MMCM_CLKOUT0_DIVIDE_F=3)
            write('clk_wiz_0_0',clock)
            write('hbm_inst_0',dict(USER_AXI_CLK_FREQ=400,USER_AXI_CLK1_FREQ=400))
            self.assertEqual(len(verify_generated_hbm_clock(root,400)),2)
            clock['MMCM_CLKOUT0_DIVIDE_F']=2.5
            write('clk_wiz_0_0',clock)
            with self.assertRaisesRegex(RuntimeError,'MMCM produces'):
                verify_generated_hbm_clock(root,400)
            timing=root/'timing.rpt'
            timing.write_text('clk_out1_design_hbm_clk_wiz_0_0 {0.000 1.250} 2.500 400.000\n')
            verify_report_hbm_clock(timing,400)
            with self.assertRaisesRegex(RuntimeError,'differs'):
                verify_report_hbm_clock(timing,450)

    def test_real_source_configuration_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'hw').mkdir()
            for relative in ['cmake/FindCoyoteHW.cmake', 'hw/bd/ultrascale_plus/cr_hbm.tcl']:
                target = root/'coyote'/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(COYOTE/relative, target)
            configure_hbm_clock(root, 400)
            verify_hbm_clock_sources(root)
            text = (root/'coyote/cmake/FindCoyoteHW.cmake').read_text()
            self.assertIn('set(HCLK_F 400)', text[text.index('if(FDEV_NAME STREQUAL "u55c")'):][:800])
            bd = root/'coyote/hw/bd/ultrascale_plus/cr_hbm.tcl'
            self.assertNotIn('CONFIG.MMCM_CLKOUT0_DIVIDE_F {2.625}', bd.read_text())
            self.assertIn('CONFIG.USER_AXI_CLK_FREQ {[expr {$cnfg(hclk_f)}]}', bd.read_text())
            self.assertIn('CONFIG.CLKOUT1_REQUESTED_OUT_FREQ [format "%.3f" $cnfg(hclk_f)]', bd.read_text())
            bd.write_text(bd.read_text()+'\n# changed\n')
            with self.assertRaisesRegex(RuntimeError, 'HBM clock source changed'):
                verify_hbm_clock_sources(root)

    def test_only_complete_hbm_setup_failures_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'timing.rpt'
            for text, expected in [(report(),True),(report('checker_clk'),False),
                                   (report(hold=1),False),
                                   (report().replace('188 5000','189 5000'),False),
                                   ('Timing constraints are not met.',False)]:
                path.write_text(text)
                self.assertEqual(hbm_setup_failure(path),expected)

    def test_fallback_preserves_sources_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dst=root/'jobs/I';dst.mkdir(parents=True)
            path=dst/'timing.rpt';path.write_text(report())
            (root/'recovery_policy.json').write_text(json.dumps(dict(enabled=True,
                hbm_clock_fallback=dict(enabled=True,authorized_at=100))))
            job=dict(id='I',status='failed',attempt=4,finished_at=101,
                error='Timing failure: '+str(path))
            recover_failed(root,dict(jobs=[job]))
            self.assertEqual(job['hbm_axi_mhz'],400)
            self.assertEqual(job['attempt'],5)
            self.assertFalse(job['prepared'])
            self.assertTrue((root/'attempts/I/attempt_04/timing.rpt').exists())
            dst.mkdir();path.write_text(report())
            job.update(status='failed',finished_at=102,error='Timing failure: '+str(path))
            recover_failed(root,dict(jobs=[job]))
            self.assertEqual(job['attempt'],5)

    def test_old_failure_does_not_trigger_new_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dst=root/'jobs/U';dst.mkdir(parents=True)
            path=dst/'timing.rpt';path.write_text(report())
            (root/'recovery_policy.json').write_text(json.dumps(dict(enabled=True,
                hbm_clock_fallback=dict(enabled=True,authorized_at=100))))
            job=dict(id='U',status='failed',attempt=3,finished_at=99,
                error='Timing failure: '+str(path))
            recover_failed(root,dict(jobs=[job]))
            self.assertEqual(job['attempt'],3)
            self.assertNotIn('hbm_axi_mhz',job)
