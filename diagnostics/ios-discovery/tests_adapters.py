"""Meaningful original-boundary tests using fake processes, signals and clocks."""
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('diagnostic_adapters', Path(__file__).with_name('adapters.py'))
adapters = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapters)

class Clock:
    value = 100.0
    def monotonic(self): return self.value
    def sleep(self, delay): self.value += max(delay, 0.0001)

class Pipe(io.BytesIO):
    def __init__(self, data, fd): super().__init__(data); self.fd = fd
    def fileno(self): return self.fd

class Process:
    pid = 42042
    def __init__(self, world):
        self.world = world
        self.returncode = None if world.mode == 'timeout' else (-int(signal.SIGXFSZ) if world.mode == 'censor' else 0)
        self.stdout, self.stderr = Pipe(b'{"ok":true}', 10001), Pipe(b'', 10002)
    def poll(self): return self.returncode
    def wait(self, timeout=None):
        if self.returncode is None:
            self.world.clock.sleep(timeout or 0)
            raise subprocess.TimeoutExpired(['fixed'], timeout)
        return self.returncode

class FakeOS:
    def __init__(self, world): self.world = world
    def __getattr__(self, name): return getattr(os, name)
    def getpgid(self, pid):
        if self.world.identity_error: raise PermissionError(errno.EPERM, 'private identity failure')
        return pid
    def getsid(self, pid): return pid
    def killpg(self, pid, sig):
        self.world.calls.append(('killpg', pid, sig))
        if self.world.cleanup_error: raise PermissionError(errno.EPERM, 'private cleanup failure')
        proc = self.world.proc
        if proc.returncode is not None: raise ProcessLookupError(errno.ESRCH, 'gone')
        if sig: proc.returncode = -int(sig)
    def set_blocking(self, *_): pass
    def read(self, fd, n):
        for stream in (self.world.proc.stdout, self.world.proc.stderr):
            if fd == stream.fileno(): return stream.read(n)
        raise AssertionError('unexpected read')

class FakeSignals:
    def __init__(self): self.handlers = {}; self.mask = set()
    def __getattr__(self, name): return getattr(signal, name)
    def getsignal(self, sig): return self.handlers.get(sig, signal.SIG_DFL)
    def signal(self, sig, handler):
        old = self.getsignal(sig); self.handlers[sig] = handler; return old
    def getitimer(self, *_): return (0.0, 0.0)
    def setitimer(self, *_): return (0.0, 0.0)
    def pthread_sigmask(self, how, mask):
        old = self.mask.copy(); self.mask = set(mask) if how == signal.SIG_SETMASK else self.mask | set(mask); return old

class FakeSelector:
    def __init__(self, world): self.world = world; self.mapping = {}
    def register(self, stream, events, data): self.mapping[stream] = types.SimpleNamespace(fileobj=stream, data=data)
    def unregister(self, stream): del self.mapping[stream]
    def get_map(self): return self.mapping
    def select(self, timeout):
        self.world.clock.sleep(timeout)
        return [] if self.world.proc.returncode is None else [(key, 1) for key in list(self.mapping.values())]
    def close(self): self.mapping.clear()

class World:
    def __init__(self, mode='success', identity_error=False, cleanup_error=False):
        self.mode, self.identity_error, self.cleanup_error = mode, identity_error, cleanup_error
        self.clock, self.calls, self.proc = Clock(), [], None
        self.kwargs, self.argv = None, None
    def popen(self, argv, **kwargs):
        self.calls.append(('spawn',)); self.argv, self.kwargs = list(argv), kwargs
        if self.mode == 'spawnfail': raise OSError(errno.EAGAIN, 'private spawn failure')
        self.proc = Process(self)
        sink = kwargs['stdout']
        if hasattr(sink, 'write') and self.mode == 'success': sink.write(b'{"ok":true}'); sink.flush()
        return self.proc
    def lib(self):
        return dict(os=FakeOS(self), time=self.clock, signal=FakeSignals(),
                    subprocess=types.SimpleNamespace(Popen=self.popen, PIPE=subprocess.PIPE,
                        STDOUT=subprocess.STDOUT, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired),
                    selectors=types.SimpleNamespace(DefaultSelector=lambda: FakeSelector(self), EVENT_READ=1),
                    select=types.SimpleNamespace(select=lambda rs, *_: (rs if self.proc.returncode is not None else [], [], [])),
                    shutil=types.SimpleNamespace(disk_usage=lambda _: types.SimpleNamespace(free=40*2**30),
                                                 which=lambda name, **_: '/usr/bin/'+name))

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Any accidental real process or signal/identity experiment fails the test.
        for obj, name in [(subprocess, 'Popen'), (os, 'killpg'), (os, 'getpgid'), (os, 'getsid'),
                          (signal, 'signal'), (signal, 'setitimer')]:
            guard = patch.object(obj, name, side_effect=AssertionError('Real OS process operation forbidden'))
            guard.start(); self.addCleanup(guard.stop)
    def probe(self, boundary, world):
        directory = (Path(self.temp.name)/boundary).resolve()
        with patch.object(adapters, 'libraries', return_value=world.lib()):
            return adapters.run_probe(boundary, {'PATH':'/usr/bin:/bin', 'HOME':'/synthetic', 'PRIVATE_MARKER':'do-not-export'}, directory, 200.0)
    def test_success_all_original_boundaries_and_exact_popen_arguments(self):
        for name in ('room', 'redact', 'trip'):
            with self.subTest(name=name):
                world = World(); result = self.probe(name, world)
                self.assertEqual(result['outcome'], 'success', result)
                self.assertTrue(result['cleanup_confirmed']); self.assertFalse(result['identity_uncertain'])
                self.assertEqual(world.argv, adapters.ARGV[name]); self.assertEqual(len([c for c in world.calls if c[0]=='spawn']), 1)
                self.assertTrue(world.kwargs['start_new_session'])
                self.assertEqual(world.kwargs['env']['PRIVATE_MARKER'], 'do-not-export')
                if name == 'room': self.assertEqual(world.kwargs['stdin'], subprocess.DEVNULL)
                else: self.assertNotIn('stdin', world.kwargs)
                self.assertEqual(result['streams_merged'], name=='redact')
                self.assertEqual(result['stdout_sha256'], hashlib.sha256(b'{"ok":true}').hexdigest())
                public = json.dumps(result)
                for secret in ('/synthetic', 'do-not-export', self.temp.name): self.assertNotIn(secret, public)
                self.assertTrue(all(type(x) in (int,float) for x in result['spawn_observation'].values()))
    def test_timeout_all_boundaries_runs_original_cleanup_once(self):
        for name in ('room','redact','trip'):
            with self.subTest(name=name):
                world = World('timeout'); result = self.probe(name, world)
                self.assertEqual(result['outcome'], 'timeout', result)
                self.assertTrue(result['cleanup_confirmed']); self.assertFalse(result['identity_uncertain'])
                signals = [c for c in world.calls if c[0]=='killpg' and c[2]]
                self.assertEqual(len(signals), 1); self.assertEqual(signals[0][2], signal.SIGTERM)
                self.assertFalse(result['output_censored'])
    def test_identity_observation_failure_keeps_handle_and_cleanup(self):
        world=World('timeout', identity_error=True); result=self.probe('redact',world)
        self.assertTrue(result['identity_uncertain']); self.assertTrue(result['cleanup_confirmed'])
        self.assertEqual(world.proc.returncode, -int(signal.SIGTERM))
    def test_success_identity_uncertain_does_not_add_signaling(self):
        world=World(identity_error=True); result=self.probe('redact',world)
        self.assertTrue(result['identity_uncertain']); self.assertFalse(result['cleanup_confirmed'])
        self.assertFalse(any(c[0]=='killpg' for c in world.calls))
    def test_clock_failure_after_acquisition_does_not_lose_handle(self):
        world=World(); lib=world.lib(); count=0
        def clock():
            nonlocal count
            count+=1
            if count==2: raise RuntimeError('synthetic observation clock failure')
            return 100.0
        lib['time']=types.SimpleNamespace(monotonic=clock)
        tracker=adapters.Tracker(adapters.ARGV['trip'],lib)
        proc=tracker.spawn(adapters.ARGV['trip'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        self.assertIs(proc,tracker.proc); self.assertTrue(tracker.uncertain); self.assertFalse(tracker.unknown)
    def test_original_cleanup_failure_is_never_retried_by_adapter(self):
        world=World('timeout', cleanup_error=True); result=self.probe('redact',world)
        self.assertFalse(result['cleanup_confirmed'])
        signals=[c for c in world.calls if c[0]=='killpg' and c[2]]
        self.assertEqual([c[2] for c in signals],[signal.SIGTERM,signal.SIGKILL])
    def test_unknown_spawn_stops_without_signaling_guessed_pid(self):
        result=self.probe('trip',World('spawnfail'))
        self.assertEqual(result['outcome'],'failure'); self.assertTrue(result['identity_uncertain'])
        self.assertFalse(result['cleanup_confirmed'])
    def test_sigxfsz_is_censored_failure(self):
        result=self.probe('redact',World('censor'))
        self.assertTrue(result['output_censored']); self.assertEqual(result['outcome'],'failure')
    def test_nested_efbig_and_secondary_cap_are_censored(self):
        error=RuntimeError('primary'); error.__cause__=OSError(errno.EFBIG,'private path')
        self.assertTrue(adapters.censored(error,None,{}))
        self.assertTrue(adapters.censored(None,None,{'secondary_errors':{'persist':{'errno':errno.EFBIG}}}))
        self.assertTrue(adapters.censored(subprocess.TimeoutExpired(['x'],60),None,{'cleanup':'Discovery stream cap reached'}))
    def test_tampered_vendor_rejected_before_spawn(self):
        world=World()
        with patch.dict(adapters.PINS, {'redact':(adapters.PINS['redact'][0],'0'*64)}):
            result=self.probe('redact',world)
        self.assertEqual(result['exception_type'],'SourceIntegrityError'); self.assertIsNone(world.proc)
    def test_existing_output_directory_rejected_before_spawn(self):
        (Path(self.temp.name)/'room').mkdir(); (Path(self.temp.name)/'room'/'existing').write_text('owned elsewhere')
        world=World(); result=self.probe('room',world)
        self.assertEqual(result['outcome'],'failure'); self.assertIsNone(world.proc)

if __name__ == '__main__': unittest.main()
