"""Pinned discovery boundary adapters; importing performs no work or spawning.

Declared deltas: caller env/private cwd/RLIMIT_FSIZE, acquisition observations,
Redact success cleanup and Trip minimal checkpoint. No app workflows run.
"""
from __future__ import annotations
import ast
import datetime
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import select
import selectors
import shutil
import signal
import stat
import subprocess
import time
import types
import uuid

BASE = Path(__file__).resolve().parent
PINS = {
    'room_hosted': ('vendor/room/scripts/recovery_hosted.py', '529e67bf3b7c3cc4e51c53ad2d969fa36af66cc1958d2271d521cfaa28bd7195'),
    'room_core': ('vendor/room/scripts/run-recovery-journey.py', '640194829f904994aa86332edf0aa8bc1886c70e0ff08f512cddaa7f54a6ee1f'),
    'redact': ('vendor/redact/scripts/check-privacy-ipad.py', '3c840d43a0ce30b57f5d1fe0718db0996841f0d6d7b9f93fde5c29a62fa48ae5'),
    'trip': ('vendor/trip/scripts/recovery_process.py', 'df8c61354b2b7eb3c103fad0a319adb99124fc0d16d97fce269e39cc529ee81a'),
}
ARGV = {'room': ['xcrun', 'simctl', 'list', '--json'],
        'redact': ['xcrun', 'simctl', 'list', 'runtimes', '--json'],
        'trip': ['/usr/bin/xcrun', 'simctl', 'list', 'runtimes', '--json']}
EMPTY = hashlib.sha256(b'').hexdigest()
FILE_CAP = 8 * 1024**2

class SourceIntegrityError(RuntimeError): pass
class IdentityObservationError(RuntimeError): pass
class OutputLimitError(RuntimeError): pass

def libraries():
    """Tests substitute fakes here; no process/signal experiments required."""
    return dict(os=os, time=time, signal=signal, subprocess=subprocess,
                selectors=selectors, select=select, shutil=shutil)

def namespace(lib):
    return dict(lib, Path=Path, datetime=datetime, dt=datetime, errno=errno,
                hashlib=hashlib, json=json, stat=stat, uuid=uuid, GIB=2**30, MIB=2**20)

def extract(key, names, ns):
    relative, expected = PINS[key]
    raw = (BASE / relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SourceIntegrityError('Pinned source differs')
    tree = ast.parse(raw, filename=relative)
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise SourceIntegrityError('Definition closure differs')
    # No original imports, global initializers, main guards or workflows execute.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), ns)

def numeric(v):
    return type(v) in (int, float) and math.isfinite(v)

class Tracker:
    def __init__(self, argv, lib):
        self.argv, self.lib = argv, lib
        self.proc, self.error = None, None
        self.unknown, self.uncertain, self.stopped = False, False, False
        self.observation = {}

    def spawn(self, argv, **kwargs):
        if list(argv) != self.argv or self.proc is not None or self.unknown:
            raise SourceIntegrityError('Unexpected/repeated acquisition')
        start = self.lib['time'].monotonic()
        self.unknown = True
        proc = self.lib['subprocess'].Popen(argv, **kwargs)
        self.proc, self.unknown = proc, False  # Retain before every observation.
        try:
            elapsed = self.lib['time'].monotonic() - start
            if not numeric(elapsed) or elapsed < 0 or type(proc.pid) is not int or proc.pid <= 1:
                raise IdentityObservationError('Invalid acquisition observation')
            self.observation.update(duration_seconds=elapsed, pid=proc.pid)
            pgid, sid = self.lib['os'].getpgid(proc.pid), self.lib['os'].getsid(proc.pid)
            if type(pgid) is not int or type(sid) is not int:
                raise IdentityObservationError('Invalid identity values')
            self.observation.update(pgid=pgid, sid=sid)
            if pgid != proc.pid or sid != proc.pid:
                raise IdentityObservationError('New session identity differs')
        except BaseException as error:
            self.uncertain, self.error = True, error
        return proc

    def facade(self):
        target, owner = self.lib['subprocess'], self
        class Facade:
            Popen = staticmethod(owner.spawn)
            def __getattr__(self, name): return getattr(target, name)
        return Facade()

def room(env, directory, deadline, tracker, lib):
    ns = namespace(lib)
    ns['subprocess'] = tracker.facade()
    extract('room_core', {'RunFailure', 'ConfigurationFailure', 'DeadlineFailure',
                        'require', 'sha', 'write_json', 'tree_size', 'kill_owned'}, ns)
    original = ns['kill_owned']
    def cleanup(*args, **kwargs):
        tracker.stopped = True
        return original(*args, **kwargs)
    controller = types.SimpleNamespace(**{k: ns[k] for k in
        ('require', 'sha', 'write_json', 'tree_size', 'MIB', 'GIB')})
    controller.kill_owned = cleanup
    ns.update(controller=controller, Failure=ns['ConfigurationFailure'],
              Deadline=ns['DeadlineFailure'], POLICY={'abort_free_bytes': 8 * 2**30})
    extract('room_hosted', {'Alarm', 'Discovery'}, ns)
    error, run = None, None
    try:
        with ns['Alarm'](min(deadline, lib['time'].monotonic() + 120)) as alarm:
            run = ns['Discovery'](directory, directory, env, alarm)
            run.command(ARGV['room'], 'probe', 60)
    except BaseException as caught: error = caught
    rec = run.records[-1] if run and run.records else {}
    if run and run.cleanup_errors: rec['diagnostic_boundary_errors'] = run.cleanup_errors
    stop = rec.get('cleanup', {})
    confirmed = bool(stop.get('success') and stop.get('leader_reaped') and
                     stop.get('group_state') == 'absent' and not stop.get('errors'))
    if tracker.proc is None and not tracker.unknown: confirmed = True
    return error, confirmed, (directory/'probe.stdout', directory/'probe.stderr'), rec

def redact(env, directory, deadline, tracker, lib):
    ns = namespace(lib)
    ns.update(subprocess=tracker.facade(), ROOT=directory, OUT=directory, ENV=dict(env),
              TOTAL=780, WORK_END=560, RECOVERY_END=582, SHUTDOWN_END=619,
              DELETE_END=638, CLEANUP_END=660)
    extract('redact', {'now', 'save', 'runtime_context', 'Run', 'stop_group'}, ns)
    original = ns['stop_group']
    def cleanup(*args, **kwargs):
        if tracker.stopped: raise IdentityObservationError('Repeated cleanup withheld')
        tracker.stopped = True
        return original(*args, **kwargs)
    ns['stop_group'] = cleanup
    run = ns['Run']()
    run.end = min(run.end, deadline - run.start)
    error, confirmed = None, False
    previous = lib['signal'].getsignal(lib['signal'].SIGTERM)
    def interrupted(*_): raise InterruptedError('SIGTERM')
    lib['signal'].signal(lib['signal'].SIGTERM, interrupted)
    try:
        try: run.command(ARGV['redact'], 'runtimes.json', 60)
        except BaseException as caught: error = caught
        rec = run.meta['commands'][-1] if run.meta['commands'] else {}
        if tracker.proc is not None and not tracker.stopped:
            # Explicit success cleanup delta. Never re-signal after source cleanup.
            if tracker.uncertain:
                error = error or tracker.error or IdentityObservationError('Cleanup identity uncertain')
            elif deadline - lib['time'].monotonic() < 3:
                error = error or TimeoutError('Cleanup reserve unavailable')
            else:
                try: cleanup(tracker.proc, rec)
                except BaseException as caught: error = error or caught
        obs = rec.get('cleanup_observation', {})
        confirmed = bool(rec.get('owned_group_absent') and
                         obs.get('last_probe', {}).get('leader_reaped') and
                         obs.get('last_probe', {}).get('group') == 'ABSENT' and
                         not any(obs.get('error_counts', {}).values()) and not rec.get('cleanup_errors'))
        if tracker.proc is None and not tracker.unknown: confirmed = True
    finally: lib['signal'].signal(lib['signal'].SIGTERM, previous)
    return error, confirmed, (directory/'runtimes.json', None), rec

def trip(env, directory, deadline, tracker, lib):
    ns = namespace(lib)
    ns.update(subprocess=tracker.facade(), PER_LOG=16*2**20, ALL_LOG=64*2**20)
    extract('trip', {'require', 'observed', 'RealOps', 'Smoke'}, ns)
    original, now, require = ns['Smoke'].stop, lib['time'].monotonic, ns['require']
    class Context:
        command, pump = ns['Smoke'].command, ns['Smoke'].pump
        save, error, signal = ns['Smoke'].save, ns['Smoke'].error, ns['Smoke'].signal
        def stop(self, *args, **kwargs):
            tracker.stopped = True
            return original(self, *args, **kwargs)
        def checkpoint(self, *, force_resources=False):
            # Declared minimal adapter; not original recursive app resource scan.
            require(now() < self.limit, 'Diagnostic absolute deadline reached')
            require(not self.interrupted, 'Interrupted')
            if force_resources or now() >= self.next_scan:
                require(lib['shutil'].disk_usage(directory).free >= 8*2**30, 'Diagnostic free-space floor reached')
                total = 0
                for count, path in enumerate(directory.iterdir(), 1):
                    require(count <= 32 and now() < self.limit, 'Diagnostic scan bound')
                    info = path.lstat()
                    require(stat.S_ISREG(info.st_mode), 'Unexpected diagnostic output type')
                    total += max(info.st_size, info.st_blocks*512)
                    require(total <= 32*2**20, 'Diagnostic output cap exceeded')
                self.next_scan = now() + 1
            require(now() < self.limit, 'Diagnostic absolute deadline reached')
    run = Context()
    run.ops, run.out, run.t0 = ns['RealOps'](dict(env), directory), directory, now()
    run.limit = run.write_deadline = deadline
    run.phase, run.active, run.absent_groups = 'diagnostic', {}, set()
    run.unknown_spawn, run.log_total, run.interrupted, run.cleaning = False, 0, False, False
    run.next_scan, run.report = run.t0, {'commands': [], 'errors': [], 'resources': []}
    error, handlers = None, {}
    try:
        for sig in (lib['signal'].SIGTERM, lib['signal'].SIGINT):
            handlers[sig] = lib['signal'].signal(sig, run.signal)
        try: run.command('profile-runtimes', ARGV['trip'], 60)
        except BaseException as caught: error = caught
    finally:
        for sig, old in handlers.items(): lib['signal'].signal(sig, old)
    rec = run.report['commands'][-1] if run.report['commands'] else {}
    stop = rec.get('stop', {})
    confirmed = bool(stop.get('group_absent') and stop.get('leader_reaped') and
                     not stop.get('error') and not run.active and not run.unknown_spawn)
    if tracker.proc is None and not tracker.unknown and not run.unknown_spawn: confirmed = True
    tracker.unknown |= run.unknown_spawn
    return error, confirmed, (directory/'1-stdout.log', directory/'1-stderr.log'), rec

def hash_output(path):
    if path is None or not path.exists(): return 0, EMPTY
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_CAP:
        raise OutputLimitError('Private output cap exceeded')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > FILE_CAP: raise OutputLimitError('Private output cap exceeded')
            digest.update(chunk)
    return size, digest.hexdigest()

def censored(error, code, record):
    if code == -int(signal.SIGXFSZ): return True
    seen = set()
    pending = [error]
    while pending and len(seen) < 16:
        value = pending.pop()
        if value is None or id(value) in seen: continue
        seen.add(id(value))
        if isinstance(value, OutputLimitError) or getattr(value, 'errno', None) == errno.EFBIG: return True
        pending.extend([getattr(value, '__cause__', None), getattr(value, '__context__', None)])
    pending = [record]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if value.get('errno') == errno.EFBIG: return True
            pending.extend(value.values())
        elif isinstance(value, list): pending.extend(value)
    # Primary timeout must not hide a source-retained secondary cap failure.
    text = json.dumps(record, default=lambda _: 'UNSERIALIZABLE')
    markers = ('Output cap exceeded', 'Discovery stream cap reached',
               'Owned resource byte cap reached', 'Diagnostic output cap exceeded',
               'Resource entry-count cap exceeded', 'Diagnostic scan bound',
               'Hosted disk abort floor reached', 'Diagnostic free-space floor reached',
               '[Errno 27]', 'File too large')
    return any(s in text or (error is not None and s in str(error)) for s in markers)

def run_probe(boundary: str, env: dict[str, str], private_dir: Path,
              absolute_deadline: float) -> dict:
    """Only timeout with confirmed cleanup and identity may advance fixed phases."""
    result = dict(outcome='failure', cleanup_confirmed=True, identity_uncertain=False,
                  elapsed_seconds=0.0, returncode=None, stdout_bytes=0, stderr_bytes=0,
                  stdout_sha256=EMPTY, stderr_sha256=EMPTY, spawn_observation={},
                  exception_type=None, errno=None, streams_merged=boundary == 'redact',
                  output_censored=False)
    lib = libraries()
    start = lib['time'].monotonic()
    tracker, error, record, returned = None, None, {}, False
    try:
        if boundary not in ARGV or not numeric(absolute_deadline):
            raise ValueError('Invalid boundary/deadline')
        if not isinstance(env, dict) or any(type(k) is not str or type(v) is not str for k, v in env.items()):
            raise ValueError('Invalid environment')
        directory = Path(private_dir)
        if not directory.is_absolute() or directory.resolve() != directory:
            raise ValueError('Invalid private directory')
        directory.mkdir(mode=0o700, exist_ok=True)
        if any(directory.iterdir()): raise ValueError('Private directory must be fresh')
        tracker = Tracker(ARGV[boundary], lib)
        error, confirmed, paths, record = {'room': room, 'redact': redact, 'trip': trip}[boundary](
            dict(env), directory, absolute_deadline, tracker, lib)
        result['cleanup_confirmed'], returned = confirmed, True
        for channel, path in zip(('stdout', 'stderr'), paths):
            result[channel+'_bytes'], result[channel+'_sha256'] = hash_output(path)
    except BaseException as caught:
        error = error or caught
        if not returned and tracker is not None and (tracker.proc is not None or tracker.unknown):
            result['cleanup_confirmed'], tracker.uncertain = False, True
        if censored(caught, None, {}): result['output_censored'] = True
    if tracker is not None:
        result['identity_uncertain'] = tracker.uncertain or tracker.unknown
        result['spawn_observation'] = tracker.observation
        if tracker.proc is not None:
            try:
                code = tracker.proc.returncode
                if type(code) is int: result['returncode'] = code
            except BaseException as caught:
                result['identity_uncertain'] = True
                error = error or caught
        if tracker.unknown: result['cleanup_confirmed'] = False
        error = error or tracker.error
    result['output_censored'] |= censored(error, result['returncode'], record)
    if error is not None:
        result['exception_type'] = type(error).__name__
        if type(getattr(error, 'errno', None)) is int: result['errno'] = error.errno
        timeout = (isinstance(error, subprocess.TimeoutExpired) or
                   type(error).__name__ == 'DeadlineFailure' or
                   (type(error) is RuntimeError and str(error) == 'Command timeout') or
                   (boundary == 'trip' and type(error.__cause__) is RuntimeError and
                    str(error.__cause__) == 'Command timeout'))
        secondary_failure = any(record.get(k) for k in (
            'stop_error', 'close_error', 'receipt_error', 'cap_error', 'log_close_errors',
            'secondary_errors', 'cleanup_errors', 'diagnostic_boundary_errors'))
        timeout = timeout and not secondary_failure
        result['outcome'] = 'timeout' if timeout else 'failure'
    elif result['cleanup_confirmed'] and not result['identity_uncertain']:
        result['outcome'] = 'success'
    else: result['exception_type'] = 'IdentityObservationError'
    if result['output_censored']:
        result['outcome'] = 'failure'
        result['exception_type'] = result['exception_type'] or 'OutputLimitError'
    elapsed = lib['time'].monotonic() - start
    if numeric(elapsed) and elapsed >= 0: result['elapsed_seconds'] = elapsed
    else: result.update(outcome='failure', identity_uncertain=True, exception_type='IdentityObservationError')
    return result
