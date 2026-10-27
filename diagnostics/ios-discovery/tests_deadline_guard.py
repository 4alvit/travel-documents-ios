"""Fake clocks/timers/signals/OS only: no real threads or signal experiments."""
import importlib.util
import os
from pathlib import Path
import signal
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('guard_test', Path(__file__).with_name('deadline_guard.py'))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

class FakeLock:
    def __enter__(self): return self
    def __exit__(self, *_): return False

class FakeSignals:
    SIGUSR1, SIGTERM, SIGALRM = 30, 15, 14
    SIG_DFL, SIG_IGN, SIG_BLOCK = 0, 1, 1
    def __init__(self):
        self.alarm_prior, self.term_prior = object(), object()
        self.handlers = {30: 0, 15: self.term_prior, 14: self.alarm_prior}
        self.blocked, self.mask_calls, self.handler_calls = set(), [], []
    def pthread_sigmask(self, how, mask):
        self.mask_calls.append((how, set(mask)))
        if how != self.SIG_BLOCK or mask: raise AssertionError('Mask modification forbidden')
        return set(self.blocked)
    def getsignal(self, number): return self.handlers[number]
    def signal(self, number, handler):
        if number == 14: raise AssertionError('SIGALRM must remain untouched')
        old = self.handlers[number]; self.handlers[number] = handler
        self.handler_calls.append((number, handler)); return old
    def deliver(self, number): self.handlers[number](number, None)

class FakeTimer:
    def __init__(self, delay, callback, world):
        self.delay, self.callback, self.world = delay, callback, world
        self.started, self.cancelled, self.daemon = False, False, False
    def start(self):
        if self.world.fail_start == self.world.timers.index(self): raise RuntimeError('Timer startup failure')
        self.started = True
    def cancel(self): self.cancelled = True
    def fire(self): self.callback()  # Deliberately allow stale callbacks in tests.

class World:
    def __init__(self):
        self.now, self.pid = 100.0, 4242
        self.signals, self.timers, self.sent, self.aborts = FakeSignals(), [], [], []
        self.fail_start, self.kill_error, self.main = None, False, True
    def timer(self, delay, callback):
        timer = FakeTimer(delay, callback, self); self.timers.append(timer); return timer
    def getpid(self): return self.pid
    def kill(self, pid, number):
        self.sent.append((pid, number))
        if self.kill_error: raise PermissionError('Synthetic sender failure')
        # Queue only; handler delivery occurs separately on fake main thread.
    def abort(self): self.aborts.append(self.now)
    def dependencies(self):
        return dict(clock=lambda: self.now, timer_factory=self.timer, signal=self.signals,
                    os=self, main_thread=lambda: self.main, lock_factory=FakeLock)
    def guard(self):
        return module.DeadlineGuard(880.0, self.abort, soft_deadline=145.0, dependencies=self.dependencies())

class DeadlineGuardTests(unittest.TestCase):
    def setUp(self):
        for owner, name in ((threading, 'Timer'), (signal, 'signal'), (signal, 'pthread_sigmask'),
                            (os, 'kill'), (os, 'getpid')):
            guard = patch.object(owner, name, side_effect=AssertionError('Real OS operation forbidden'))
            guard.start(); self.addCleanup(guard.stop)
    def test_constructor_is_inert(self):
        world = World(); guard = world.guard()
        self.assertEqual(world.timers, []); self.assertEqual(world.signals.handler_calls, [])
        self.assertEqual(guard.hard_deadline, 880.0)
    def test_enter_arm_preserve_hard_timer_and_sigalrm(self):
        world = World()
        with world.guard() as guard:
            hard, old = world.timers
            self.assertEqual((hard.delay, old.delay), (780.0, 45.0))
            self.assertTrue(hard.daemon and old.daemon)
            world.now = 110.0; guard.arm(860.0)
            self.assertIs(world.timers[0], hard); self.assertEqual(world.timers[-1].delay, 750.0)
            self.assertTrue(old.cancelled); self.assertFalse(hard.cancelled)
            self.assertIs(world.signals.handlers[14], world.signals.alarm_prior)
            old.fire(); self.assertEqual(world.sent, [])
        self.assertTrue(all(t.cancelled for t in world.timers))
        self.assertEqual(world.signals.handlers[30], 0)
        self.assertIs(world.signals.handlers[15], world.signals.term_prior)
        self.assertEqual(world.signals.mask_calls, [(1, set())])
    def test_hard_abort_once_no_descendant_signals(self):
        world = World()
        with self.assertRaises(module.DeadlineExpired):
            with world.guard() as guard:
                world.now = 880.0; world.timers[0].fire(); world.timers[0].fire()
                self.assertEqual(world.aborts, [880.0]); self.assertEqual(world.sent, [])
                self.assertEqual(guard.terminal_reason, 'hard_deadline')
                with self.assertRaises(module.GuardConfigurationError): guard.arm(880.0)

    def test_close_at_or_after_hard_deadline_restores_then_fails(self):
        for now in (880.0, 880.001, 900.0):
            with self.subTest(now=now):
                world = World(); guard = world.guard(); guard.__enter__()
                world.now = now  # No timer callback has run.
                with self.assertRaises(module.DeadlineExpired): guard.close()
                self.assertTrue(all(t.cancelled for t in world.timers))
                self.assertEqual(world.signals.handlers[30], 0)
                self.assertIs(world.signals.handlers[15], world.signals.term_prior)
                self.assertIs(world.signals.handlers[14], world.signals.alarm_prior)
                for timer in world.timers: timer.fire()
                self.assertEqual(world.sent, []); self.assertEqual(world.aborts, [])
                self.assertEqual(world.signals.mask_calls, [(1, set())])

    def test_overdue_close_preserves_pending_delivery_safety(self):
        world = World(); guard = world.guard(); guard.__enter__()
        world.now = 145.0; world.timers[1].fire(); world.now = 881.0
        with self.assertRaises(module.DeadlineExpired): guard.close()
        self.assertNotEqual(world.signals.handlers[30], 0)
        self.assertFalse(world.timers[0].cancelled)
        with self.assertRaises(module.DeadlineExpired): world.signals.deliver(30)
        with self.assertRaises(module.DeadlineExpired): guard.close()
        self.assertTrue(all(t.cancelled for t in world.timers))
        self.assertEqual(world.signals.handlers[30], 0)
        self.assertIs(world.signals.handlers[15], world.signals.term_prior)
    def test_stale_callbacks_after_close_are_inert(self):
        world = World(); guard = world.guard(); guard.__enter__(); guard.close(); guard.close()
        for timer in world.timers: timer.fire()
        self.assertEqual(world.sent, []); self.assertEqual(world.aborts, [])
    def test_pending_delivery_prevents_unsafe_default_restore(self):
        world = World(); guard = world.guard(); guard.__enter__()
        world.now = 145.0; world.timers[1].fire()
        with self.assertRaises(module.DeadlineExpired): guard.close()
        self.assertNotEqual(world.signals.handlers[30], 0)
        self.assertFalse(world.timers[0].cancelled)
        with self.assertRaises(module.DeadlineExpired): world.signals.deliver(30)
        guard.close(); self.assertEqual(world.signals.handlers[30], 0)
    def test_soft_sender_failure_is_terminal_no_retries(self):
        world = World(); world.kill_error = True
        with world.guard() as guard:
            world.now = 145.0; world.timers[1].fire(); world.timers[1].fire(); world.timers[0].fire()
            self.assertEqual(world.aborts, [145.0]); self.assertEqual(len(world.sent), 1)
            self.assertEqual(guard.terminal_reason, 'soft_signal_failed')
    def test_invalid_deadlines_rejected(self):
        for value in (float('nan'), float('inf'), True, '880'):
            with self.assertRaises(module.GuardConfigurationError): module.DeadlineGuard(value, lambda: None)
        world = World()
        with self.assertRaises(module.GuardConfigurationError):
            module.DeadlineGuard(880.0, world.abort, 881.0, world.dependencies())
        self.assertEqual(world.timers, [])
        with world.guard() as guard:
            for value in (float('nan'), float('inf'), True, 881.0):
                with self.assertRaises(module.GuardConfigurationError): guard.arm(value)
    def test_blocked_signal_and_existing_handler_fail_before_probes(self):
        for blocked in (30, 15):
            world = World(); world.signals.blocked.add(blocked)
            with self.assertRaises(module.GuardConfigurationError): world.guard().__enter__()
            self.assertEqual(world.timers, []); self.assertEqual(world.signals.handler_calls, [])
        world = World(); world.signals.handlers[30] = 1
        with self.assertRaises(module.GuardConfigurationError): world.guard().__enter__()
        self.assertEqual(world.timers, [])
    def test_non_main_or_expired_entry_has_no_context_side_effect(self):
        world = World(); world.main = False
        with self.assertRaises(module.GuardConfigurationError): world.guard().__enter__()
        self.assertEqual(world.signals.mask_calls, [])
        world = World(); world.now = 150.0
        with self.assertRaises(module.DeadlineExpired): world.guard().__enter__()
        self.assertEqual(world.timers, []); self.assertEqual(world.signals.handler_calls, [])
    def test_timer_start_failure_restores_and_cancels(self):
        for failure in (0, 1):
            world = World(); world.fail_start = failure
            with self.assertRaises(RuntimeError): world.guard().__enter__()
            self.assertTrue(all(timer.cancelled for timer in world.timers))
            self.assertEqual(world.signals.handlers[30], 0)
            self.assertIs(world.signals.handlers[15], world.signals.term_prior)
    def test_guard_single_use_and_hard_deadline_read_only(self):
        world = World(); guard = world.guard()
        with guard:
            with self.assertRaises(AttributeError): guard.hard_deadline = 1000.0
        with self.assertRaises(module.GuardConfigurationError): guard.__enter__()

    def test_soft_interrupts_blocked_acquisition_and_latches_stop(self):
        world = World(); following = []; unknown_spawn = False
        with world.guard() as guard:
            try:
                unknown_spawn = True
                world.now = 145.0; world.timers[1].fire(); world.signals.deliver(30)
                following.append('next phase')
            except module.DeadlineExpired: self.assertTrue(unknown_spawn)
            self.assertEqual(following, []); self.assertEqual(world.sent, [(4242, 30)])
            with self.assertRaises(module.DeadlineExpired): guard.arm(800.0)
            world.timers[1].fire(); self.assertEqual(len(world.sent), 1)
    def test_sigterm_reaches_existing_finally_and_restores(self):
        world = World(); cleanup = []
        with self.assertRaises(InterruptedError):
            with world.guard():
                try: world.signals.deliver(15)
                finally: cleanup.append('owned cleanup')
        self.assertEqual(cleanup, ['owned cleanup']); self.assertEqual(world.sent, [])
        self.assertIs(world.signals.handlers[15], world.signals.term_prior)

if __name__ == '__main__': unittest.main()
