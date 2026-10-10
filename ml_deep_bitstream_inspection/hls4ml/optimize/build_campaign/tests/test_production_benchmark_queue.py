import io
import json
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import production_benchmark_queue as queue
from board_benchmark import sha
from benchmark_identity import installed_identity


class FinishedChild:
    pid=999999
    def __init__(self,code=0):self.returncode=code
    def poll(self):return self.returncode


class ProductionQueueTests(unittest.TestCase):
    def test_candidate_does_not_wait_for_unavailable_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);priority=root/'priority.json';gate=root/'gate.json'
            priority.write_text(json.dumps(dict(status='running',stage='waiting_runtime_admission')))
            self.assertFalse(queue.priority_allows_candidate(priority,gate))
            gate.write_text(json.dumps(dict(status='running',stage='waiting_build',build_status='running')))
            self.assertTrue(queue.priority_allows_candidate(priority,gate))
            gate.write_text(json.dumps(dict(status='running',stage='waiting_board',build_status='passed')))
            self.assertFalse(queue.priority_allows_candidate(priority,gate))
            gate.write_text(json.dumps(dict(status='passed',stage='complete')))
            self.assertFalse(queue.priority_allows_candidate(priority,gate))
            priority.write_text(json.dumps(dict(status='passed',stage='complete')))
            self.assertTrue(queue.priority_allows_candidate(priority,gate))
            priority.write_text(json.dumps(dict(status='running',stage='waiting_runtime_admission')))
            gate.write_text(json.dumps(dict(status='failed',stage='parity')))
            self.assertTrue(queue.priority_allows_candidate(priority,gate))

    def exercise(self,root,*,gate_failed=False,collect_failed=False,program_failed=False):
        board=root/'board';board.mkdir();admission=root/'admission';admission.mkdir()
        job=root/'R_SO_T';job.mkdir();sink=root/'D_N';sink.mkdir()
        bit=job/'cyt_top.bit';bit.write_bytes(b'candidate')
        sink_bit=sink/'cyt_top.bit';sink_bit.write_bytes(b'sink')
        driver=board/'software/driver/build/coyote_driver.ko';driver.parent.mkdir(parents=True);driver.write_bytes(b'standard driver')
        (admission/'status.json').write_text(json.dumps({'driver_sha256':sha(driver)}))
        calls=[]
        def check_output(args,**kwargs):
            return {'hostname':'hacc-u55c-03.inf.ethz.ch\n','uname':'testkernel\n','modinfo':'testkernel SMP\n'}[args[0]]
        def popen(args,**kwargs):
            calls.append(args)
            if args[0]=='bash':
                return FinishedChild(1 if program_failed and str(bit) in args else 0)
            if any(str(arg).endswith('production_collect.py') for arg in args):
                index=next(i for i,arg in enumerate(args) if str(arg).endswith('production_collect.py'))
                output=Path(args[index+2])
                if collect_failed:return FinishedChild(1)
                output.with_suffix('.meta.json').write_text(json.dumps(dict(status='passed',
                    hardware_identity=installed_identity(board/'installed_image.json','R_SO_T'))))
            return FinishedChild()
        original_read=Path.read_text
        def read(path,*args,**kwargs):
            if path==Path('/sys/bus/pci/devices/0000:c4:00.0/current_link_width'):return '16\n'
            if path==Path('/sys/bus/pci/devices/0000:c4:00.0/current_link_speed'):return '8.0 GT/s\n'
            return original_read(path,*args,**kwargs)
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(queue,'verified_board_parity',side_effect=RuntimeError('260 gate failed') if gate_failed else None,return_value={'board_calls':260}))
            stack.enter_context(patch('isolation_board.verified_bitstream',return_value=(bit,'source')))
            stack.enter_context(patch.object(queue,'verified_sink',return_value=(sink_bit,'sink_source')))
            stack.enter_context(patch.object(queue,'prepare',return_value=job/'runtime_project'))
            stack.enter_context(patch.object(queue.subprocess,'check_output',side_effect=check_output))
            stack.enter_context(patch.object(queue.subprocess,'Popen',side_effect=popen))
            stack.enter_context(patch.object(queue.subprocess,'run',return_value=type('Result',(),{'returncode':1})()))
            stack.enter_context(patch.object(queue.signal,'signal'))
            stack.enter_context(patch.object(Path,'read_text',read))
            result=queue.worker(board,job,admission,sink,root/'attempt')
        state=json.loads((root/'attempt/status.json').read_text())
        return result,state,calls,board,bit,sink_bit

    def test_failed_parity_never_programs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,state,calls,*_=self.exercise(Path(tmp),gate_failed=True)
            self.assertEqual(result,1);self.assertEqual(calls,[])
            self.assertIn('260 gate failed',state['error'])

    def test_success_runs_three_modes_and_restores_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,state,calls,board,bit,sink=self.exercise(Path(tmp))
            self.assertEqual(result,0);self.assertTrue(state['sink_restored'])
            programs=[call for call in calls if call[0]=='bash']
            self.assertIn(str(bit),programs[0]);self.assertIn(str(sink),programs[-1])
            self.assertEqual(sum(any(str(arg).endswith('production_collect.py') for arg in call) for call in calls),3)
            self.assertEqual(json.loads((board/'installed_image.json').read_text())['job'],'D_N')

    def test_failed_collection_restores_sink_but_failed_program_does_not_claim_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,state,calls,board,*_=self.exercise(Path(tmp),collect_failed=True)
            self.assertEqual(result,1);self.assertTrue(state['sink_restored'])
            self.assertFalse(state.get('measurements_passed',False))
            self.assertEqual(json.loads((board/'installed_image.json').read_text())['job'],'D_N')
        with tempfile.TemporaryDirectory() as tmp:
            result,state,calls,board,*_=self.exercise(Path(tmp),program_failed=True)
            self.assertEqual(result,1);self.assertFalse(state['sink_restored'])
            self.assertEqual(len(calls),1)
            self.assertEqual(json.loads((board/'installed_image.json').read_text())['status'],'programming')


if __name__=='__main__':unittest.main()
