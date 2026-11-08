"""Offline tests: temporary toy builds, fake agent, no FPGA tools or network."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import buildctl as ctl
from runner import alive, identity, save


FAKE_AGENT = '''#!/usr/bin/env python3
import json
from pathlib import Path
import sys

prompt = sys.argv[-1]
output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
candidate = Path(sys.argv[sys.argv.index('--cd') + 1])
decision = dict(action='continue', explanation='Toy progress checked', hypothesis='')
if 'Task: repair.' in prompt:
    options = json.loads((candidate / 'tuning.json').read_text())
    if options.get('malformed_agent') and not (candidate / 'agent_recovered').exists():
        (candidate / 'agent_recovered').write_text('yes')
        output.write_text('not json')
        sys.exit(0)
    options['level'] += 1
    (candidate / 'tuning.json').write_text(json.dumps(options))
    if options.get('change_invariant'):
        (candidate / 'hardware.json').write_text('changed')
    decision = dict(action='retry', explanation='Applied a plausible correction',
                    hypothesis='Uncertain root cause; test tuning level ' + str(options['level']))
elif 'Task: terminal.' in prompt:
    decision['action'] = 'accept'
    decision['explanation'] = 'Toy artifacts and gates reviewed'
output.write_text(json.dumps(decision))
print(json.dumps(dict(type='fake_agent_completed', decision=decision)))
'''

TOY_BUILD = '''import json
from pathlib import Path
import time

options = json.loads(Path('tuning.json').read_text())
time.sleep(options.get('delay', 0))
assert options['level'] >= options['required'], 'Toy tool failed; root cause uncertain'
if not options.get('missing_artifact'):
    Path('image.bit').write_bytes(b'toy image, not a real FPGA bitstream')
'''


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='buildctl-test-')
        self.base = Path(self.temporary.name)
        self.root = self.base / 'campaign'
        self.template = self.base / 'prepared'
        self.template.mkdir()
        (self.template / 'build.py').write_text(TOY_BUILD)
        (self.template / 'validate.py').write_text(
            "from pathlib import Path\nassert Path('hardware.json').read_text() == 'frozen'\n")
        (self.template / 'verify.py').write_text("print('Toy verification passed')\n")
        (self.template / 'hardware.json').write_text('frozen')
        self.options()
        agent = self.base / 'fake_codex'
        agent.write_text(FAKE_AGENT)
        agent.chmod(0o755)
        plan = self.base / 'plan.md'
        plan.write_text('Toy builds only. Try three plausible fixes. Never run real tools.\n')
        self.cli('init', '--plan', str(plan), '--codex', str(agent))

    def tearDown(self):
        # On assertion failures, clean up only the test supervisors we created.
        for path in self.root.glob('commands/*/identity.json'):
            process = ctl.read(path)
            if alive(process):
                os.kill(process['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            processes = [ctl.read(path) for path in self.root.glob('commands/*/identity.json')]
            if not any(alive(process) for process in processes):
                break
            time.sleep(0.05)
        self.reap()
        self.temporary.cleanup()

    @staticmethod
    def reap():
        ctl.reap_runners()

    def options(self, **overrides):
        values = dict(level=0, required=0)
        values.update(overrides)
        save(self.template / 'tuning.json', values)

    def cli(self, action, *args, success=True):
        result = subprocess.run(
            [sys.executable, str(ctl.HERE / 'buildctl.py'), action, str(self.root), *args],
            capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def add(self, name='toy', depends=None):
        extra = ['--depends', depends] if depends else []
        self.cli('add', '--id', name, '--template', str(self.template),
                 '--validate', f'{sys.executable} validate.py',
                 '--build', f'{sys.executable} build.py',
                 '--verify', f'{sys.executable} verify.py',
                 '--artifact', 'image.bit', '--invariant', 'hardware.json', *extra)

    def advance(self, until=lambda state: state['status'] == 'complete', timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Reload every tick, exercising restart reconciliation continuously.
            state = ctl.read(self.root / 'monitor_state.json')
            ctl.tick(self.root, state, time.time())
            self.reap()
            if until(state):
                return state
            time.sleep(0.03)
        self.fail('Toy campaign timed out: ' + json.dumps(state))

    def test_success_and_sealed_handoff(self):
        self.add()
        state = self.advance()
        self.assertEqual(state['jobs']['toy']['phase'], 'passed')
        manifest = ctl.read(self.root / 'artifact_manifest.json')['toy']
        self.assertFalse(manifest['board_validated'])
        artifact = manifest['files']['image.bit']
        self.assertEqual(artifact['sha256'], ctl.digest(Path(artifact['path'])))
        self.assertIn('passed', (self.root / 'BUILD_SUMMARY.md').read_text())

    def test_three_plausible_fixes_then_success(self):
        self.options(required=3)
        self.add()
        state = self.advance()
        job = state['jobs']['toy']
        self.assertEqual(job['phase'], 'passed')
        self.assertEqual(job['repairs'], 3)
        self.assertEqual(len(job['attempts']), 4)
        self.assertEqual(len(list(self.root.glob('commands/*_toy_build'))), 4)
        for attempt in job['attempts'][1:]:
            self.assertIn('Uncertain root cause', attempt['hypothesis'])
        original = Path(job['attempts'][0]['path']) / 'input' / 'tuning.json'
        self.assertEqual(ctl.read(original)['level'], 0)

    def test_budget_exhaustion_blocks_dependent_only(self):
        self.options(required=4)
        self.add('fails')
        self.add('dependent', depends='fails')
        self.options()
        self.add('independent')
        state = self.advance()
        self.assertEqual(state['jobs']['fails']['phase'], 'needs_attention')
        self.assertEqual(state['jobs']['fails']['repairs'], 3)
        self.assertEqual(state['jobs']['dependent']['phase'], 'blocked')
        self.assertEqual(state['jobs']['independent']['phase'], 'passed')

    def test_five_jobs_maximum(self):
        self.options(delay=0.5)
        for number in range(6):
            self.add(f'job{number}')
        state = ctl.read(self.root / 'monitor_state.json')
        ctl.tick(self.root, state, time.time())
        self.assertEqual(sum(job['phase'] == 'validate' for job in state['jobs'].values()), 5)
        self.assertEqual(state['jobs']['job5']['phase'], 'queued')

        def assert_slots(state):
            active = sum(job['phase'] in ('validate', 'build', 'verify') for job in state['jobs'].values())
            self.assertLessEqual(active, 5)
            return state['status'] == 'complete'

        state = self.advance(assert_slots)
        self.assertTrue(all(job['phase'] == 'passed' for job in state['jobs'].values()))

    def test_invariant_violation_never_reaches_synthesis(self):
        self.options(required=1, change_invariant=True)
        self.add()
        state = self.advance()
        self.assertEqual(state['jobs']['toy']['phase'], 'needs_attention')
        self.assertEqual(len(list(self.root.glob('commands/*_toy_build'))), 1)
        self.assertEqual(state['jobs']['toy']['repairs'], 3)

    def test_agent_transport_failure_does_not_consume_repair_budget(self):
        self.options(required=1, malformed_agent=True)
        self.add()
        state = self.advance()
        self.assertEqual(state['jobs']['toy']['phase'], 'passed')
        self.assertEqual(state['jobs']['toy']['repairs'], 1)
        self.assertEqual(len(state['jobs']['toy']['attempts']), 2)

    def test_missing_artifact_cannot_be_accepted(self):
        self.options(missing_artifact=True)
        self.add()
        state = self.advance()
        self.assertEqual(state['jobs']['toy']['phase'], 'needs_attention')
        self.assertEqual(ctl.read(self.root / 'artifact_manifest.json'), {})

    def test_early_then_hourly_observations(self):
        self.add()
        state = ctl.read(self.root / 'monitor_state.json')
        job = state['jobs']['toy']
        ctl.new_attempt(self.root, job, self.root / 'templates' / 'toy', 1000)
        job['command'] = {'directory': str(self.base)}
        for elapsed in range(0, 301, 30):
            self.assertTrue(ctl.observe(self.root, job, 1000 + elapsed))
            self.assertFalse(ctl.observe(self.root, job, 1000 + elapsed + 1))
        self.assertFalse(ctl.observe(self.root, job, 4899))
        self.assertTrue(ctl.observe(self.root, job, 4900))

    def test_notifications_retry_without_rebuild(self):
        state = ctl.read(self.root / 'monitor_state.json')
        ctl.event(self.root, state, 'sample', 'Synthetic notification')
        ctl.event(self.root, state, 'sample', 'Duplicate must not be enqueued')
        ctl.notify_due(self.root, state, 0, sender=lambda event: False)
        ctl.notify_due(self.root, state, 9, sender=lambda event: self.fail('Retry too soon'))
        state = ctl.read(self.root / 'monitor_state.json')
        ctl.notify_due(self.root, state, 10, sender=lambda event: True)
        self.assertEqual(len(state['notifications']), 1)
        self.assertEqual(state['notifications']['sample']['tries'], 2)
        self.assertTrue(state['notifications']['sample']['delivered'])

    def test_pause_and_resume(self):
        self.add()
        self.cli('pause')
        state = ctl.read(self.root / 'monitor_state.json')
        ctl.tick(self.root, state, time.time())
        self.assertEqual(state['jobs']['toy']['phase'], 'queued')
        self.assertFalse(state.get('agent'))
        self.cli('resume')
        self.assertEqual(self.advance()['jobs']['toy']['phase'], 'passed')

    def test_cancel_only_owned_processes(self):
        self.options(delay=15)
        self.add()
        self.advance(lambda state: state['jobs']['toy']['phase'] == 'build')
        # A process with no relationship to this campaign must survive cancel.
        outsider = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                    start_new_session=True)
        try:
            self.cli('cancel')
            state = self.advance()
            self.assertEqual(state['jobs']['toy']['phase'], 'cancelled')
            self.assertIsNone(outsider.poll())
        finally:
            outsider.terminate()
            outsider.wait(timeout=5)

    def test_ambiguous_launch_stops_without_duplicate(self):
        self.add()
        state = ctl.read(self.root / 'monitor_state.json')
        state['launch_intent'] = {'directory': str(self.base / 'unknown')}
        with mock.patch.object(ctl, 'launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'Interrupted launch'):
                ctl.tick(self.root, state, time.time())
            launch.assert_not_called()

    def test_reconciles_journaled_live_launch(self):
        self.options(delay=0.5)
        self.add()
        state = self.advance(lambda state: state['jobs']['toy']['phase'] == 'build')
        record = state['jobs']['toy']['command']
        deadline = time.monotonic() + 5
        while not (Path(record['directory']) / 'identity.json').exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        state['launch_intent'] = record
        save(self.root / 'monitor_state.json', state)
        self.assertEqual(self.advance()['jobs']['toy']['phase'], 'passed')
        self.assertEqual(len(list(self.root.glob('commands/*_toy_build'))), 1)

    def test_registration_refuses_unsafe_templates(self):
        (self.template / 'external').symlink_to(self.base / 'secret')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            ctl.copy_inputs(self.template, self.base / 'unsafe-copy')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            ctl.contained(self.template, '../secret')
        current = identity(os.getpid())
        current['start_ticks'] = '-1'
        self.assertFalse(alive(current))


    def test_timeout_drains_owned_command(self):
        state = ctl.read(self.root / 'monitor_state.json')
        owner = {}
        ctl.launch(self.root, state,
                   [sys.executable, '-c', 'import time; time.sleep(30)'],
                   self.base, 0.1, 'timeout_test', owner)
        deadline = time.monotonic() + 10
        result = None
        while time.monotonic() < deadline:
            result = ctl.outcome(owner['command'], time.time())
            if result is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(result)
        self.assertNotEqual(result['returncode'], 0)
        self.assertIn('stopped owned group', result['error'])

    def test_abandoned_children_are_stopped(self):
        state = ctl.read(self.root / 'monitor_state.json')
        owner = {}
        script = (
            'import subprocess\nimport sys\n'
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"
        )
        ctl.launch(self.root, state, [sys.executable, '-c', script],
                   self.base, 10, 'child_test', owner)
        deadline = time.monotonic() + 10
        result = None
        while time.monotonic() < deadline:
            result = ctl.outcome(owner['command'], time.time())
            if result is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(result)
        self.assertIn('background children', result['error'])
        self.assertFalse(ctl.group_alive(owner['command']['identity']['pid']))

    def test_host_and_plan_guards(self):
        self.add()
        state = ctl.read(self.root / 'monitor_state.json')
        state['host'] = 'not-this-host'
        save(self.root / 'monitor_state.json', state)
        with self.assertRaisesRegex(RuntimeError, 'Wrong host'):
            ctl.run(self.root)
        state['host'] = ctl.socket.gethostname()
        save(self.root / 'monitor_state.json', state)
        (self.root / 'PLAN.md').write_text('Unapproved change')
        with self.assertRaisesRegex(RuntimeError, 'Approved plan changed'):
            ctl.run(self.root)
        self.assertFalse((self.root / 'commands').exists())

    def test_acceptance_scripts_are_invariants(self):
        self.add()
        state = ctl.read(self.root / 'monitor_state.json')
        self.assertIn('validate.py', state['jobs']['toy']['invariants'])
        self.assertIn('verify.py', state['jobs']['toy']['invariants'])
        self.assertNotIn('build.py', state['jobs']['toy']['invariants'])


    def test_final_artifact_loss_requests_a_build_repair(self):
        self.add()
        state = ctl.read(self.root / 'monitor_state.json')
        job = state['jobs']['toy']
        ctl.new_attempt(self.root, job, self.root / 'templates' / 'toy', time.time())
        decision = self.base / 'decision.json'
        save(decision, dict(action='accept', explanation='Checked', hypothesis=''))
        state['agent'] = dict(job='toy', purpose='terminal', decision=str(decision))
        with mock.patch.object(ctl, 'sealed_artifacts', side_effect=ValueError('Artifact lost')):
            ctl.complete_agent(self.root, state, {'returncode': 0})
        self.assertEqual(job['phase'], 'repair_pending')
        self.assertEqual(job.get('agent_failures', 0), 0)


if __name__ == '__main__':
    unittest.main()
