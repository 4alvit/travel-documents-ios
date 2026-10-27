"""Host-gated supervisor deadlines; no work happens on import/construction.

Use after the host gate, on the main thread. SIGUSR1 interrupts Python execution;
SIGTERM raises InterruptedError. Room's SIGALRM and all signal masks are untouched.
The hard callback must write only its tiny unresolved receipt and never return
(normally os._exit(124)). It never establishes descendant cleanup.

Python timer scheduling and signal delivery are not a real-time/OS-independent
guarantee: uninterruptible native code or code holding the GIL can delay them.
The existing hosted-job teardown remains the independent last backstop.
"""
from __future__ import annotations
import math
import os
import signal
import threading
import time


class DeadlineExpired(TimeoutError):
    """A supervisor deadline expired; no further probe is permitted."""


class GuardConfigurationError(RuntimeError):
    pass


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class DeadlineGuard:
    """Single-use guard. Constructor is inert; __enter__ installs protections.

    dependencies is an optional dictionary with clock, timer_factory, signal, os,
    main_thread and lock_factory entries. Tests must supply fake timers/signals/OS.
    arm() changes only the soft deadline, never the original hard deadline.
    """
    def __init__(self, hard_deadline, hard_abort, soft_deadline=None, dependencies=None):
        if not _finite(hard_deadline) or not callable(hard_abort):
            raise GuardConfigurationError('Invalid hard deadline/callback')
        self._hard_deadline, self._abort = hard_deadline, hard_abort
        self._initial_soft = soft_deadline
        self._validate_soft(soft_deadline, optional=True)
        deps = dict(clock=time.monotonic, timer_factory=threading.Timer,
                    signal=signal, os=os,
                    main_thread=lambda: threading.current_thread() is threading.main_thread(),
                    lock_factory=threading.RLock)
        deps.update(dependencies or {})
        self._deps = deps
        self._clock, self._signals, self._os = deps['clock'], deps['signal'], deps['os']
        self._entered = self._closed = self._active = self._hard_fired = False
        self._generation, self._soft_pending = 0, False
        self._soft_expired = self._interrupted = False
        self._soft_timer = self._hard_timer = self._lock = None
        self._previous = {}
        self._pid = None
        self.terminal_reason = None  # None, hard_deadline or soft_signal_failed.

    @property
    def hard_deadline(self):
        return self._hard_deadline

    def _validate_soft(self, value, optional=False):
        if optional and value is None:
            return
        if not _finite(value) or value > self._hard_deadline:
            raise GuardConfigurationError('Invalid soft deadline')

    def _now(self):
        value = self._clock()
        if not _finite(value):
            raise GuardConfigurationError('Invalid monotonic clock')
        return value

    def _main_thread(self):
        if not self._deps['main_thread']():
            raise GuardConfigurationError('Guard lifecycle requires main thread')

    def __enter__(self):
        self._main_thread()
        if self._entered or self._closed:
            raise GuardConfigurationError('Guard is single-use')
        sig = self._signals
        # SIG_BLOCK with an EMPTY set queries the mask without changing it.
        blocked = sig.pthread_sigmask(sig.SIG_BLOCK, set())
        if sig.SIGUSR1 in blocked or sig.SIGTERM in blocked:
            raise GuardConfigurationError('Required supervisor signal is blocked')
        if sig.getsignal(sig.SIGUSR1) != sig.SIG_DFL:
            raise GuardConfigurationError('SIGUSR1 handler is already owned')
        pid = self._os.getpid()
        if type(pid) is not int or pid <= 1:
            raise GuardConfigurationError('Invalid supervisor PID')
        now = self._now()
        if self._hard_deadline <= now or (self._initial_soft is not None and self._initial_soft <= now):
            raise DeadlineExpired('Supervisor deadline already expired')
        self._lock, self._pid, self._entered = self._deps['lock_factory'](), pid, True
        try:
            for number, handler in ((sig.SIGUSR1, self._soft_handler), (sig.SIGTERM, self._term_handler)):
                self._previous[number] = sig.signal(number, handler)
            self._active = True
            self._hard_timer = self._new_timer(self._hard_deadline, self._hard_fire)
            self._hard_timer.start()
            if self._initial_soft is not None:
                self.arm(self._initial_soft)
            return self
        except BaseException:
            self.close()
            raise

    def _new_timer(self, absolute, callback):
        remaining = absolute - self._now()
        if remaining <= 0:
            raise DeadlineExpired('Supervisor deadline already expired')
        timer = self._deps['timer_factory'](remaining, callback)
        timer.daemon = True
        return timer

    def arm(self, absolute_soft):
        self._main_thread()
        self._validate_soft(absolute_soft)
        if not self._entered:
            raise GuardConfigurationError('Guard must be entered before arm')
        with self._lock:
            if not self._active or self._closed or self._hard_fired:
                raise GuardConfigurationError('Guard is terminal')
            if self._soft_pending or self._soft_expired:
                raise DeadlineExpired('A deadline interruption is pending')
            if self._interrupted:
                raise InterruptedError('Supervisor was interrupted')
            self._generation += 1
            generation = self._generation
            previous_timer = self._soft_timer
            self._soft_timer = None
            try:
                if previous_timer is not None:
                    previous_timer.cancel()
                timer = self._new_timer(absolute_soft, lambda: self._soft_fire(generation))
                self._soft_timer = timer
                timer.start()
            except BaseException:
                self._generation += 1
                self._soft_expired = True
                if self._soft_timer is not None:
                    self._soft_timer.cancel()
                raise

    def _soft_fire(self, generation):
        with self._lock:
            if self._closed or not self._active or self._hard_fired or generation != self._generation:
                return
            self._generation += 1  # A duplicate callback cannot send twice.
            self._soft_pending = self._soft_expired = True
            try:
                self._os.kill(self._pid, self._signals.SIGUSR1)
            except BaseException:
                # Cannot safely continue if the main thread cannot be interrupted.
                # Use the same terminal unresolved fallback, with a fixed reason.
                self._soft_pending = False
                self._hard_fired = True
                self.terminal_reason = 'soft_signal_failed'
                self._abort()

    def _soft_handler(self, *_):
        with self._lock:
            if self._closed:
                return
            self._soft_pending = False
            self._soft_expired = True
        raise DeadlineExpired('Supervisor soft deadline expired')

    def _term_handler(self, *_):
        with self._lock:
            if self._closed:
                return
            self._interrupted = True
        raise InterruptedError('Supervisor SIGTERM')

    def _hard_fire(self):
        with self._lock:
            if self._closed or not self._active or self._hard_fired:
                return
            self._hard_fired = True
            self.terminal_reason = 'hard_deadline'
            self._abort()  # No child/group signalling; callback must not return.

    def close(self):
        self._main_thread()
        if self._closed:
            return
        if not self._entered:
            self._closed = True
            return
        with self._lock:
            if self._soft_pending:
                # A process-directed signal already sent cannot be cancelled.
                # Do not restore SIG_DFL while that signal could still arrive.
                # Keep the hard fallback armed and fail the caller closed.
                raise DeadlineExpired('Deadline delivery is still pending')
            self._closed, self._active = True, False
            self._generation += 1
            first_error = None
            for timer in (self._soft_timer, self._hard_timer):
                if timer is not None:
                    try: timer.cancel()
                    except BaseException as error: first_error = first_error or error
            for number, handler in self._previous.items():
                try: self._signals.signal(number, handler)
                except BaseException as error: first_error = first_error or error
            self._previous.clear()
            if first_error is not None:
                raise first_error
            # A delayed timer callback must not turn over-budget finalization
            # into success. Restore safely first; pending delivery above still
            # keeps its handler and the hard fallback armed.
            if self._now() >= self._hard_deadline:
                raise DeadlineExpired('Supervisor hard deadline reached during finalization')

    def __exit__(self, *_):
        self.close()
        return False
