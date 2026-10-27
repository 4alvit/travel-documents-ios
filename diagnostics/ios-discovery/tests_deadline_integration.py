"""Guard -> pinned native boundary -> scheduler seams, with fake OS only.

The extracted original command/cleanup bodies run unchanged. Test spies count
entry into the original cleanup helpers; every process, timer and signal is fake.
These tests establish control flow, not actual macOS signal/Popen behavior.
"""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import types
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


adapter_fakes = load('seam_adapter_fakes', 'tests_adapters.py')
guard_fakes = load('seam_guard_fakes', 'tests_deadline_guard.py')
adapters, guard_module = adapter_fakes.adapters, guard_fakes.module
runner = load('seam_runner', 'runner.py')


class SharedSignals(adapter_fakes.FakeSignals):
    def __init__(self):
        super().__init__()
        self.mask_calls = []

    def pthread_sigmask(self, how, mask):
        self.mask_calls.append((how, set(mask)))
        return super().pthread_sigmask(how, mask)

    def deliver(self, number):
        self.handlers[number](number, None)


class Seam:
    def __init__(self, target, event, point):
        self.target, self.event, self.point = target, event, point
        self.world = adapter_fakes.World('timeout' if point == 'owned_wait' else 'success')
        self.signals = SharedSignals()
        self.outer_term, self.outer_alarm = lambda *_: None, lambda *_: None
        self.initial_mask = {signal.SIGWINCH}
        self.signals.mask = self.initial_mask.copy()
        self.signals.handlers.update({signal.SIGTERM: self.outer_term,
                                     signal.SIGALRM: self.outer_alarm,
                                     signal.SIGUSR1: signal.SIG_DFL})
        self.timers = guard_fakes.World()
        self.cleanup_entries, self.invocations, self.persisted = [], [], []
        self.fired, self.calls_at_interrupt = False, None
        self.lib = self.world.lib()
        self.lib['signal'] = self.signals
        original_popen = self.lib['subprocess'].Popen

        def popen(argv, **kwargs):
            if list(argv) == adapters.ARGV[target] and point == 'blocked_acquisition':
                # Popen has not returned a handle: do not invent a PID/identity.
                self.world.calls.append(('spawn',))
                self.interrupt()
                raise AssertionError('Interrupted acquisition unexpectedly resumed')
            return original_popen(argv, **kwargs)

        self.lib['subprocess'].Popen = popen
        owner = self

        class Selector(adapter_fakes.FakeSelector):
            def select(self, timeout):
                if point == 'owned_wait' and not owner.fired:
                    owner.interrupt()
                return super().select(timeout)

        self.lib['selectors'] = types.SimpleNamespace(
            DefaultSelector=lambda: Selector(self.world), EVENT_READ=1)

    def interrupt(self):
        self.fired = True
        self.calls_at_interrupt = len(self.world.calls)
        if self.event == 'soft':
            self.world.clock.value = 145.0
            self.timers.timers[1].fire()  # Real guard callback, fake Timer/kill.
            self.signals.deliver(signal.SIGUSR1)
        else:
            self.signals.deliver(signal.SIGTERM)

    def run(self, directory):
        original_extract = adapters.extract

        def extract(key, names, namespace):
            original_extract(key, names, namespace)
            helper = {'room_core': 'kill_owned', 'redact': 'stop_group'}.get(key)
            if helper:
                original = namespace[helper]

                def spy(*args, **kwargs):
                    self.cleanup_entries.append((key, args[0]))
                    return original(*args, **kwargs)

                namespace[helper] = spy

        def invoke(boundary, env, private, deadline):
            self.invocations.append(boundary)
            return adapters.run_probe(boundary, env, private, deadline)

        def persist(rows, stopped):
            self.persisted.append((len(rows), stopped))

        dependencies = dict(clock=self.world.clock.monotonic,
                            timer_factory=self.timers.timer, signal=self.signals,
                            os=self.timers, main_thread=lambda: True,
                            lock_factory=guard_fakes.FakeLock)
        self.guard = guard_module.DeadlineGuard(
            880.0, self.timers.abort, soft_deadline=145.0, dependencies=dependencies)
        parent = {'PATH': '/usr/bin:/bin', 'HOME': '/synthetic', 'USER': 'synthetic'}
        with patch.object(adapters, 'libraries', return_value=self.lib), \
                patch.object(adapters, 'extract', side_effect=extract), \
                patch.object(runner, 'limits', return_value={'RLIMIT_FSIZE': [8388608, 8388608]}):
            with self.guard:
                return runner.run_schedule(parent, directory, 850.0, invoke, persist,
                                           clock=self.world.clock.monotonic)


class DeadlineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.private = Path(self.temporary.name).resolve()
        for owner, name in ((threading, 'Timer'), (subprocess, 'Popen'),
                            (os, 'kill'), (os, 'killpg'), (os, 'getpid'),
                            (os, 'getpgid'), (os, 'getsid'), (signal, 'signal'),
                            (signal, 'pthread_sigmask'), (signal, 'setitimer')):
            forbid = patch.object(owner, name, side_effect=AssertionError('Real OS operation forbidden'))
            forbid.start(); self.addCleanup(forbid.stop)

    def assert_restored(self, seam):
        self.assertIs(seam.signals.getsignal(signal.SIGTERM), seam.outer_term)
        self.assertIs(seam.signals.getsignal(signal.SIGALRM), seam.outer_alarm)
        self.assertEqual(seam.signals.getsignal(signal.SIGUSR1), signal.SIG_DFL)
        self.assertEqual(seam.signals.mask, seam.initial_mask)
        self.assertFalse(any(signal.SIGUSR1 in mask for _, mask in seam.signals.mask_calls))
        self.assertTrue(all(timer.cancelled for timer in seam.timers.timers))
        old_sent = list(seam.timers.sent)
        for timer in seam.timers.timers:
            timer.fire()  # Cancelled callbacks cannot send or abort later.
        self.assertEqual(seam.timers.sent, old_sent)
        self.assertEqual(seam.timers.aborts, [])

    def assert_schedule_stopped(self, seam, rows, stopped):
        self.assertTrue(stopped)
        self.assertTrue(seam.fired)
        failed = next(i for i, row in enumerate(rows)
                      if row.get('observation', {}).get('outcome') == 'failure')
        self.assertTrue(rows[failed + 1:])
        self.assertTrue(all(row['status'] == 'NOT_RUN' and row['reason'] == 'COHORT_STOPPED'
                            for row in rows[failed + 1:]))
        self.assertEqual(len(seam.invocations), sum(row['status'] == 'OBSERVED' for row in rows))
        self.assertEqual(seam.persisted[-1], (len(rows), True))
        self.assert_restored(seam)
        return rows[failed]['observation']

    def test_room_sigterm_owned_pump_uses_original_cleanup_once(self):
        seam = Seam('room', 'term', 'owned_wait')
        result = self.assert_schedule_stopped(seam, *seam.run(self.private))
        self.assertEqual(seam.invocations, ['room'])
        self.assertEqual(result['exception_type'], 'InterruptedError')
        self.assertTrue(result['cleanup_confirmed']); self.assertFalse(result['identity_uncertain'])
        self.assertEqual(seam.cleanup_entries, [('room_core', seam.world.proc)])
        self.assertEqual([x for x in seam.world.calls if x[0] == 'killpg' and x[2]],
                         [('killpg', seam.world.proc.pid, signal.SIGTERM)])
        self.assertIn((signal.SIG_BLOCK, {signal.SIGALRM}), seam.signals.mask_calls)
        self.assertEqual(seam.timers.sent, [])

    def test_room_soft_deadline_owned_pump_uses_original_cleanup_once(self):
        seam = Seam('room', 'soft', 'owned_wait')
        result = self.assert_schedule_stopped(seam, *seam.run(self.private))
        self.assertEqual(seam.invocations, ['room'])
        self.assertEqual(result['exception_type'], 'DeadlineExpired')
        self.assertTrue(result['cleanup_confirmed']); self.assertFalse(result['identity_uncertain'])
        self.assertEqual(seam.cleanup_entries, [('room_core', seam.world.proc)])
        self.assertEqual([x for x in seam.world.calls if x[0] == 'killpg' and x[2]],
                         [('killpg', seam.world.proc.pid, signal.SIGTERM)])
        self.assertEqual(seam.timers.sent, [(seam.timers.pid, signal.SIGUSR1)])

    def test_redact_soft_deadline_during_popen_is_unknown_no_guessed_cleanup(self):
        seam = Seam('redact', 'soft', 'blocked_acquisition')
        result = self.assert_schedule_stopped(seam, *seam.run(self.private))
        self.assertEqual(seam.invocations, ['room', 'room', 'redact'])
        self.assertEqual(result['exception_type'], 'DeadlineExpired')
        self.assertFalse(result['cleanup_confirmed']); self.assertTrue(result['identity_uncertain'])
        self.assertIsNone(result['returncode']); self.assertEqual(result['spawn_observation'], {})
        self.assertFalse(any(key == 'redact' for key, _ in seam.cleanup_entries))
        self.assertFalse(any(x[0] == 'killpg' for x in seam.world.calls[seam.calls_at_interrupt:]))
        self.assertEqual(seam.timers.sent, [(seam.timers.pid, signal.SIGUSR1)])

    def test_room_sigterm_during_popen_restores_alarm_mask_without_guessing(self):
        seam = Seam('room', 'term', 'blocked_acquisition')
        result = self.assert_schedule_stopped(seam, *seam.run(self.private))
        self.assertEqual(result['exception_type'], 'InterruptedError')
        self.assertFalse(result['cleanup_confirmed']); self.assertTrue(result['identity_uncertain'])
        self.assertEqual(result['spawn_observation'], {}); self.assertIsNone(result['returncode'])
        self.assertEqual(seam.cleanup_entries, [])
        self.assertFalse(any(x[0] == 'killpg' for x in seam.world.calls))
        self.assertIn((signal.SIG_BLOCK, {signal.SIGALRM}), seam.signals.mask_calls)


if __name__ == '__main__':
    unittest.main()
