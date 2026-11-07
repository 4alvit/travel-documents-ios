#!/usr/bin/env python3
"""Offline cloud acquisition/cache guards. No Xcode, Simulator or network calls."""
import argparse
from contextlib import nullcontext
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load('prepare-cloud-smoke.py', 'cloud_smoke')
s = load('release-smoke.py', 'ordinary_smoke')
fixtures = load('test-prepare-release.py', 'release_fixtures')
p = fixtures.m


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.f = fixtures.Fixture(self.root)
        self.out = self.root / 'prepared'
        self.out.mkdir()
        for name in c.SOURCE_PATHS:
            path = self.f.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic script identity\n')
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': p.REPOSITORY,
                    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_WORKFLOW': 'Release ZIP ordinary smoke', 'GITHUB_JOB': 'smoke',
                    'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1',
                    'GITHUB_REF': 'refs/heads/diagnostic/release-smoke', 'RUNNER_OS': 'macOS',
                    'RUNNER_ARCH': 'X64', 'ImageOS': 'macos15', 'DEVELOPER_DIR': c.DEVELOPER_DIR,
                    'GH_TOKEN': 'synthetic-secret-never-retain', 'SMOKE_RUNNER': 'macos-15-intel'}
        self.host_architecture = 'x86_64'
        self.report, self.calls = {}, []
        self.ancestor = True
        outer = self
        class API(fixtures.FakeGitHub):
            def api(self, path):
                if path.endswith('/git/ref/heads/main'):
                    self.calls.append(('GET', path))
                    return {'object': {'sha': outer.f.commit}}
                return super().api(path)
        self.api = API(self.f)

    def prepare(self, artifact_id=30):
        outer = self
        class Commands:
            started = time.monotonic()
            def __init__(self, _report): pass
            def check(self): pass
            def command(self, argv, **_):
                outer.calls.append(argv)
                if argv[0] == 'git':
                    args = argv[1:]
                    if args == ['rev-parse', 'HEAD']: return b'a' * 40
                    if args == ['rev-parse', 'HEAD^{tree}']: return b'b' * 40
                    if args == ['status', '--porcelain', '--untracked-files=no']: return b''
                    if args == ['cat-file', '-t', outer.f.commit]: return b'commit'
                    if args[:2] == ['merge-base', '--is-ancestor']:
                        if not outer.ancestor: raise ValueError('not on main')
                        return b''
                    if args == ['rev-parse', outer.f.commit + '^{tree}']: return outer.f.tree.encode()
                    if args == ['show', '-s', '--format=%P', outer.f.commit]: return b''
                    if args == ['show', outer.f.commit + ':project.yml']: return b'    MARKETING_VERSION: "0.1.0"\n'
                values = {('uname', '-m'): outer.host_architecture.encode(), ('xcodebuild', '-version'): b'Xcode 26.2\nBuild version 17C52',
                          ('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'): b'26.2',
                          ('sw_vers', '-productVersion'): b'15.8.2'}
                if tuple(argv) in values: return values[tuple(argv)]
                raise AssertionError(argv)
        args = argparse.Namespace(repo=self.f.repo, out=self.out, commit=self.f.commit, run_id=10, artifact_id=artifact_id)
        with patch.dict(os.environ, self.env, clear=True), patch.object(c, 'Commands', Commands), \
                patch.object(c, 'load_preparer', return_value=p), patch.object(p, 'command', p.command), \
                patch.object(p, 'GitHub', return_value=self.api):
            return c.prepare(args, self.report)

    def test_exact_main_artifact_preserves_bytes_modes_and_separate_script_identity(self):
        self.assertEqual(self.prepare(), self.f.tree)
        self.assertEqual(self.report['status'], 'prepared_pending_ordinary_smoke')
        self.assertEqual(self.report['runner']['RUNNER_ARCH'], 'X64')
        self.assertEqual(self.report['host']['architecture'], 'x86_64')
        self.assertNotEqual(self.report['source']['commit'], self.report['runner_source']['commit'])
        self.assertEqual(set(self.report['runner_source']['files']), set(c.SOURCE_PATHS))
        for name, body in self.f.files.items():
            self.assertEqual((self.out / 'inputs' / name).read_bytes(), body)
        self.assertEqual(stat.S_IMODE((self.out / 'inputs/Tripfolio.app').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.out / 'inputs/Tripfolio.app/Tripfolio').stat().st_mode), 0o755)
        self.assertFalse(p.decode_json((self.out / 'inputs/provenance.json').read_bytes())['status']['runtime_accepted'])
        self.assertNotIn(self.env['GH_TOKEN'], json.dumps(self.report))
        self.assertNotIn('GH_TOKEN', self.report['runner'])
        self.assertTrue(all(method == 'GET' for method, _ in self.api.calls))

    def test_missing_or_wrong_runner_architecture_stops_before_commands(self):
        for architecture in (None, 'ARM64', 'arm64', 'x86_64', ''):
            with self.subTest(architecture=architecture):
                if architecture is None: self.env.pop('RUNNER_ARCH', None)
                else: self.env['RUNNER_ARCH'] = architecture
                with self.assertRaisesRegex(ValueError, 'hosted toolchain profile'): self.prepare()
                self.assertEqual(self.calls, [])
                self.assertEqual(self.api.calls, [])
                self.assertFalse((self.out / 'inputs').exists())

    def test_intel_runner_metadata_does_not_accept_arm_host(self):
        self.host_architecture = 'arm64'
        with self.assertRaisesRegex(ValueError, 'hosted architecture'): self.prepare()
        self.assertEqual(self.report['stage'], 'host-profile')
        self.assertNotEqual(self.report.get('status'), 'prepared_pending_ordinary_smoke')
        self.assertEqual([argv for argv in self.calls if argv[0] != 'git'], [['uname', '-m']])
        self.assertEqual(self.report['host'], {})

    def test_explicit_arm_profile_preserves_exact_product_and_metadata(self):
        self.env.update(SMOKE_RUNNER='macos-15', RUNNER_ARCH='ARM64')
        self.host_architecture = 'arm64'
        self.assertEqual(self.prepare(), self.f.tree)
        self.assertEqual(self.report['status'], 'prepared_pending_ordinary_smoke')
        self.assertEqual(self.report['runner']['SMOKE_RUNNER'], 'macos-15')
        self.assertEqual(self.report['runner']['RUNNER_ARCH'], 'ARM64')
        self.assertEqual(self.report['host']['architecture'], 'arm64')
        for name, body in self.f.files.items():
            self.assertEqual((self.out / 'inputs' / name).read_bytes(), body)
        self.assertEqual(stat.S_IMODE((self.out / 'inputs/Tripfolio.app/Tripfolio').stat().st_mode), 0o755)
        self.assertFalse(p.decode_json((self.out / 'inputs/provenance.json').read_bytes())['status']['runtime_accepted'])
        self.assertTrue(all(method == 'GET' for method, _ in self.api.calls))
        self.assertNotIn(self.env['GH_TOKEN'], json.dumps(self.report))

    def test_unknown_or_missing_runner_selection_stops_before_commands(self):
        for runner in (None, '', 'macos-14', 'macos-latest', 'ARM64'):
            with self.subTest(runner=runner):
                if runner is None: self.env.pop('SMOKE_RUNNER', None)
                else: self.env['SMOKE_RUNNER'] = runner
                with self.assertRaisesRegex(ValueError, 'hosted toolchain profile'): self.prepare()
                self.assertEqual(self.calls, [])
                self.assertEqual(self.api.calls, [])
                self.assertFalse((self.out / 'inputs').exists())

    def test_arm_selection_rejects_intel_metadata_before_commands(self):
        self.env['SMOKE_RUNNER'] = 'macos-15'
        with self.assertRaisesRegex(ValueError, 'hosted toolchain profile'): self.prepare()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.api.calls, [])

    def test_arm_metadata_rejects_intel_uname(self):
        self.env.update(SMOKE_RUNNER='macos-15', RUNNER_ARCH='ARM64')
        with self.assertRaisesRegex(ValueError, 'hosted architecture'): self.prepare()
        self.assertEqual(self.report['stage'], 'host-profile')
        self.assertNotEqual(self.report.get('status'), 'prepared_pending_ordinary_smoke')
        self.assertEqual([argv for argv in self.calls if argv[0] != 'git'], [['uname', '-m']])
        self.assertEqual(self.report['host'], {})

    def test_candidate_outside_main_history_stops_before_artifact_or_host_tools(self):
        self.ancestor = False
        with self.assertRaisesRegex(ValueError, 'not on main'): self.prepare()
        self.assertFalse(any('/actions/' in path for _, path in self.api.calls))
        self.assertTrue(all(argv[0] == 'git' for argv in self.calls))

    def test_missing_or_wrong_diagnostic_run_identity_stops_before_commands(self):
        original = self.env.copy()
        for key, wrong in [('GITHUB_WORKFLOW', 'CI'), ('GITHUB_JOB', 'validate'),
                           ('GITHUB_SHA', 'a' * 39), ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '-1')]:
            for value in (None, wrong):
                with self.subTest(key=key, value=value):
                    self.env = original.copy()
                    if value is None: self.env.pop(key)
                    else: self.env[key] = value
                    with self.assertRaisesRegex(ValueError, 'run identity'): self.prepare()
                    self.assertEqual(self.calls, [])
                    self.assertEqual(self.api.calls, [])

    def test_exact_requested_id_and_main_push_required(self):
        with self.assertRaisesRegex(ValueError, 'artifact ID'): self.prepare(31)
        self.assertFalse((self.out / 'inputs').exists())
        self.f.run['event'] = 'workflow_dispatch'
        with self.assertRaisesRegex(ValueError, 'main push'): self.prepare()
        self.assertTrue(all(argv[0] == 'git' for argv in self.calls))

    def test_missing_or_wrong_attempt_job_never_reaches_download(self):
        for field, value in [('conclusion', 'failure'), ('run_attempt', 3)]:
            before = copy.deepcopy(self.f.jobs)
            self.f.jobs[0][field] = value
            with self.assertRaises(p.InvalidRelease): self.prepare()
            self.assertFalse(any(path.endswith('/zip') for _, path in self.api.calls))
            self.f.jobs = before

    def partial_attempt(self):
        build = next(job for job in self.f.jobs if job['name'] == p.BUILD_JOB)
        build['run_attempt'] = 1
        self.f.history = copy.deepcopy(self.f.jobs)
        self.f.latest_jobs = [job for job in self.f.jobs if job['run_attempt'] == 2]
        self.f.producer_attempt(1)
        return build

    def test_partial_rerun_preserves_actual_producer_and_original_payload(self):
        build = self.partial_attempt()
        self.assertEqual(self.prepare(), self.f.tree)
        self.assertEqual(self.report['ci']['run_attempt'], 2)
        self.assertEqual(self.report['artifact']['producer_job_id'], build['id'])
        self.assertEqual(self.report['artifact']['producer_run_attempt'], 1)
        for name, body in self.f.files.items():
            self.assertEqual((self.out / 'inputs' / name).read_bytes(), body)
        self.assertEqual(sum(path.endswith('/jobs?filter=latest') for _, path in self.api.calls), 2)
        self.assertEqual(sum(path.endswith('/jobs?filter=all') for _, path in self.api.calls), 2)

    def test_partial_rerun_wrong_producer_payload_cannot_prepare(self):
        self.partial_attempt()
        self.f.producer_attempt(2)
        self.f.artifact['name'] = 'TripDocket-simulator-%s-10-1' % self.f.commit
        with self.assertRaises(p.InvalidRelease):
            self.prepare()
        self.assertFalse((self.out / 'inputs').exists())

    def test_latest_view_missing_current_gate_cannot_download(self):
        self.partial_attempt()
        self.f.latest_jobs = [job for job in self.f.latest_jobs if job['name'] != 'CI gate']
        with self.assertRaises(p.InvalidRelease):
            self.prepare()
        self.assertFalse(any(path.endswith('/zip') for _, path in self.api.calls))

    def test_changed_effective_job_after_download_cannot_prepare(self):
        fixture = self.f
        original = self.api.pages
        latest_reads = 0
        def pages(path, field):
            nonlocal latest_reads
            if path.endswith('/jobs?filter=latest'):
                latest_reads += 1
                if latest_reads == 2:
                    fixture.jobs[0]['id'] += 1000
            return original(path, field)
        with patch.object(self.api, 'pages', side_effect=pages), \
                self.assertRaisesRegex(ValueError, 'CI identity changed'):
            self.prepare()
        self.assertNotEqual(self.report.get('status'), 'prepared_pending_ordinary_smoke')

    def test_change_scope_job_is_required_before_artifact_download(self):
        self.assertIn("Change scope", p.JOBS)
        self.f.jobs = [job for job in self.f.jobs if job["name"] != "Change scope"]
        with self.assertRaises(p.InvalidRelease):
            self.prepare()
        self.assertFalse(any(path.endswith('/zip') for _, path in self.api.calls))
        self.assertFalse((self.out / 'inputs').exists())

    def test_corrupt_download_stops_before_extracting_or_native_tools(self):
        self.f.outer += b'corrupt'
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): self.prepare()
        self.assertFalse((self.out / 'inputs').exists())
        self.assertTrue(all(argv[0] == 'git' for argv in self.calls))

    def test_changed_attempt_after_download_cannot_prepare(self):
        self.api.changed_run = True
        with self.assertRaises(p.InvalidRelease): self.prepare()
        self.assertNotEqual(self.report.get('status'), 'prepared_pending_ordinary_smoke')

    def test_unsafe_zip_is_rejected_before_any_member_is_written(self):
        for name, kind in [('Tripfolio.app/../outside', stat.S_IFREG),
                           ('Tripfolio.app/link', stat.S_IFLNK)]:
            blob = fixtures.zipped([(name, b'unsafe', kind | 0o777)])
            with self.assertRaises(p.InvalidRelease): c.extract_app(p, blob, self.out, lambda: None)
            self.assertEqual(list(self.out.iterdir()), [])

    def test_native_environment_never_inherits_credentials_or_injection_flags(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'secret', 'SIMCTL_CHILD_TEST': 'bad',
                                     'DYLD_INSERT_LIBRARIES': 'bad', 'HOME': str(self.root)}, clear=True):
            self.assertEqual(s.environment(), {'HOME': str(self.root)})


class CommandTests(unittest.TestCase):
    def test_reaped_leader_present_group_never_receives_a_signal(self):
        commands = c.Commands({})
        process = SimpleNamespace(pid=1234, returncode=0, poll=lambda: 0)
        with patch.object(commands, 'absent', return_value=False), \
                patch.object(c.os, 'killpg') as signals, \
                self.assertRaisesRegex(ValueError, 'cleanup unverified'):
            commands.close(process)
        signals.assert_not_called()

    def test_reaped_after_term_present_group_never_receives_kill(self):
        commands = c.Commands({})
        process = SimpleNamespace(pid=1234, returncode=None)
        process.poll = lambda: process.returncode
        def sent(_pid, sig):
            self.assertEqual(sig, signal.SIGTERM)
            process.returncode = -signal.SIGTERM
        with patch.object(commands, 'absent', return_value=False), \
                patch.object(c.os, 'killpg', side_effect=sent) as signals, \
                self.assertRaisesRegex(ValueError, 'cleanup unverified'):
            commands.close(process)
        self.assertEqual([call.args[1] for call in signals.call_args_list], [signal.SIGTERM])

    def test_reaped_leader_closes_only_after_observed_group_absence(self):
        commands = c.Commands({})
        process = SimpleNamespace(pid=1234, returncode=0, poll=lambda: 0)
        with patch.object(commands, 'absent', side_effect=[False, True]), \
                patch.object(c.os, 'killpg') as signals:
            commands.close(process)
        signals.assert_not_called()

    @staticmethod
    def child_absent(process):
        # These synthetic children never fork. The desktop sandbox denies the
        # negative killpg probe; real hosted group validation is left unchanged.
        return process.poll() is not None

    def test_timeout_closes_sigterm_ignoring_owned_group(self):
        report = {}
        commands = c.Commands(report, seconds=4)
        started = time.monotonic()
        with patch.object(commands, 'absent', side_effect=self.child_absent), \
                self.assertRaisesRegex(ValueError, 'timed out'):
            commands.command([sys.executable, '-c',
                              'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'], timeout=.15)
        self.assertLess(time.monotonic() - started, 4.5)
        self.assertTrue(report['commands'][0]['closed'])
        self.assertEqual(report['commands'][0]['exit_code'], -signal.SIGKILL)

    def test_deferred_cancel_finishes_spawn_bookkeeping_and_reaps_child(self):
        report = {}
        commands = c.Commands(report)
        popen = c.subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            report['interrupted'] = True
            return child
        with patch.object(c.subprocess, 'Popen', side_effect=spawn), \
                patch.object(commands, 'absent', side_effect=self.child_absent), \
                self.assertRaisesRegex(ValueError, 'interrupted'):
            commands.command([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(report['commands'][0]['closed'])
        with patch.object(c.subprocess, 'Popen') as untouched, self.assertRaisesRegex(ValueError, 'interrupted'):
            commands.command([sys.executable, '-c', 'pass'])
        untouched.assert_not_called()

    def test_output_cap_closes_child_and_expired_budget_cannot_spawn(self):
        report = {}
        commands = c.Commands(report)
        with patch.object(commands, 'absent', side_effect=self.child_absent), \
                self.assertRaisesRegex(ValueError, 'output exceeded'):
            commands.command([sys.executable, '-c', 'print("x" * 1024)'], maximum=32)
        self.assertTrue(report['commands'][0]['closed'])
        commands.work_deadline = time.monotonic() - 1
        with self.assertRaisesRegex(ValueError, 'deadline exceeded'):
            commands.command([sys.executable, '-c', 'raise AssertionError("must not spawn")'])
        self.assertEqual(len(report['commands']), 1)

    def test_permission_error_never_counts_as_group_absence(self):
        report = {}
        commands = c.Commands(report)
        with patch.object(commands, 'absent', side_effect=PermissionError('synthetic negative probe denied')), \
                patch.object(c.os, 'killpg') as signals:
            with self.assertRaises(PermissionError):
                commands.command([sys.executable, '-c', 'pass'])
            signals.assert_not_called()
        self.assertEqual(report['commands'][0]['exit_code'], 0)
        self.assertFalse(report['commands'][0]['closed'])

    def test_active_child_is_reaped_even_when_every_group_probe_is_denied(self):
        for signal_denied in (False, True):
            with self.subTest(group_signal_denied=signal_denied):
                report = {}
                commands = c.Commands(report, seconds=4)
                signals = patch.object(c.os, 'killpg', side_effect=PermissionError('group signal denied')) if signal_denied else nullcontext()
                with patch.object(commands, 'absent', side_effect=PermissionError('negative probe denied')), \
                        signals, self.assertRaises(PermissionError):
                    commands.command([sys.executable, '-c',
                                      'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'], timeout=.15)
                row = report['commands'][0]
                self.assertEqual(row['exit_code'], -signal.SIGKILL)
                self.assertEqual(row['failure_type'], 'ValueError')
                self.assertEqual(row['cleanup_error_type'], 'PermissionError')
                self.assertFalse(row['closed'])

    def test_no_group_escalation_after_term_reaps_child_with_unknown_group(self):
        report = {}
        commands = c.Commands(report, seconds=4)
        send = c.os.killpg
        with patch.object(commands, 'absent', side_effect=PermissionError('negative probe denied')), \
                patch.object(c.os, 'killpg', wraps=send) as signals, self.assertRaises(PermissionError):
            commands.command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=.15)
        self.assertEqual([call.args[1] for call in signals.call_args_list], [signal.SIGTERM])
        self.assertEqual(report['commands'][0]['exit_code'], -signal.SIGTERM)
        self.assertFalse(report['commands'][0]['closed'])


class CacheTests(unittest.TestCase):
    def run_preparation(self, now=100, cache_seconds=10, cache_failure=False, report=None):
        owner = s.OrdinarySmoke.__new__(s.OrdinarySmoke)
        owner.report = {} if report is None else report
        owner.commands = SimpleNamespace(limit=900)
        clock, calls = [now], []
        def command(label, argv, cap):
            end = min(owner.commands.limit, clock[0] + cap)
            calls.append((label, argv, cap, end, owner.commands.limit))
            if label == 'runtime-cache-ready':
                clock[0] += cache_seconds
                if cache_failure or clock[0] >= end - 8: raise RuntimeError('cache failed')
                return ''
            if label == 'runtimes': raise StopIteration('Reached runtime inventory after cache')
            return {'xcode': 'Xcode 26.2\nBuild version 17C52', 'developer': c.DEVELOPER_DIR,
                    'sdk': '26.2', 'architecture': 'x86_64'}[label]
        owner.commands.command = command
        with patch.object(s.time, 'monotonic', side_effect=lambda: clock[0]):
            try: owner.prepare_device()
            except (RuntimeError, StopIteration) as error: failure = error
            else: self.fail('Test must stop before any Simulator allocation')
        return owner, calls, failure

    def test_cache_once_precedes_inventory_and_shares_original_discovery_clock(self):
        owner, calls, error = self.run_preparation(cache_seconds=150)
        self.assertIsInstance(error, StopIteration)
        self.assertEqual([row[0] for row in calls], ['xcode', 'developer', 'sdk', 'architecture',
                                                  'runtime-cache-ready', 'runtimes'])
        self.assertEqual(calls[-2][1], ['xcrun', 'simctl', 'runtime', 'dyld_shared_cache', 'update', '--all'])
        self.assertEqual(calls[-2][2:], (300, 400, 400))
        self.assertEqual(calls[-1][3:], (400, 400))
        self.assertEqual(owner.commands.limit, 900)
        self.assertEqual((s.WORK_SECONDS, s.CLEANUP_SECONDS), (900, 180))
        _, second, error = self.run_preparation(report=owner.report)
        self.assertIn('only once', str(error))
        self.assertNotIn('runtime-cache-ready', [row[0] for row in second])

    def test_cache_failure_or_global_clipping_prevents_inventory_and_create(self):
        for options in ({'cache_failure': True}, {'now': 880, 'cache_seconds': 13}):
            owner, calls, error = self.run_preparation(**options)
            self.assertIsInstance(error, RuntimeError)
            self.assertEqual(calls[-1][0], 'runtime-cache-ready')
            self.assertEqual(owner.commands.limit, 900)
            self.assertEqual(owner.report['runtime_cache_readiness'], 'attempted')
            if 'now' in options: self.assertEqual(calls[-1][3:], (900, 900))


class SharedInstallBudgetTests(unittest.TestCase):
    def run_phase(self, ready=108., install=100., start=150., cancelled=None,
                  install_code=0, post_install_delay=0.):
        # Execute both real orchestration and process ownership with a fake OS.
        processes = load('recovery_process.py', 'install_budget_processes')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        owner = s.OrdinarySmoke.__new__(s.OrdinarySmoke)
        owner.out = owner.repo = Path(temporary.name).resolve()
        owner.app = owner.out / 'Tripfolio.app'
        owner.started, owner.work_deadline, owner.cleanup_deadline = 0., 900., 1080.
        owner.cleaning = owner.interrupted = False
        owner.owned = '11111111-1111-4111-8111-111111111111'
        owner.report = {}
        clock, calls = [start], []
        class Process:
            def __init__(self, kind):
                self.kind, self.pid, self.returncode = kind, 1000 + len(calls), None
                self.ready = clock[0] + (ready if kind == 'bootstatus' else install)
            def poll(self):
                if self.returncode is None and clock[0] >= self.ready:
                    self.returncode = 0 if self.kind == 'bootstatus' else install_code
                return self.returncode
        class Ops:
            def now(self): return clock[0]
            def sleep(self, seconds): clock[0] += seconds
            def spawn(self, argv):
                calls.append(argv)
                return Process(argv[2])
            def prepare(self, _): pass
            def read(self, process):
                if cancelled == process.kind: owner.interrupted = True
                return []
            def absent(self, process): return process.poll() is not None
            def send(self, process, sig):
                process.returncode = -sig
                return 'syscall_returned'
            def close(self, process):
                if process.kind == 'install': clock[0] += post_install_delay
        ops = Ops()
        api = SimpleNamespace(Smoke=processes.Smoke, RealOps=lambda *_: ops)
        owner.commands = s.make_commands_class(api)(owner)
        failure = None
        with patch.object(s.time, 'monotonic', side_effect=ops.now):
            try: owner.prepare_install()
            except RuntimeError as error: failure = error
        self.assertEqual(owner.commands.limit, 900.)
        return owner, calls, failure

    def test_unused_ready_allocation_allows_one_install_over_sixty_seconds(self):
        owner, calls, error = self.run_phase()
        self.assertIsNone(error)
        self.assertEqual([row[2] for row in calls], ['bootstatus', 'install'])
        phase = owner.report['boot_install_phase']
        self.assertEqual(phase['deadline_seconds'], 406.)
        self.assertTrue(phase['completed'])
        self.assertEqual(phase['install_attempts'], 1)
        self.assertAlmostEqual(phase['install_work_seconds'], 140., places=2)
        records = owner.commands.report['commands']
        self.assertEqual(records[0]['requested_cap_seconds'], 188.)
        self.assertEqual(records[1]['command_deadline'], 406.)
        self.assertTrue(all(row['stop']['group_absent'] and row['stop']['leader_reaped'] for row in records))
        with patch.object(s.time, 'monotonic', return_value=360.):
            with self.assertRaisesRegex(RuntimeError, 'only once'): owner.prepare_install()
        self.assertEqual(len(calls), 2)
        self.assertEqual((s.WORK_SECONDS, s.CLEANUP_SECONDS), (900, 180))

    def test_slow_ready_reduces_install_window_and_timeout_is_not_accepted(self):
        owner, calls, error = self.run_phase(ready=179., install=70.)
        self.assertIsNotNone(error)
        self.assertEqual([row[2] for row in calls], ['bootstatus', 'install'])
        self.assertNotIn('completed', owner.report['boot_install_phase'])
        install = owner.commands.report['commands'][-1]
        self.assertEqual(install['command_deadline'], 406.)
        self.assertEqual(install['work_deadline'], 398.)
        self.assertTrue(install['stop']['group_absent'] and install['stop']['leader_reaped'])

    def test_ready_still_has_original_180_second_work_limit(self):
        owner, calls, error = self.run_phase(ready=181.)
        self.assertIsNotNone(error)
        self.assertEqual([row[2] for row in calls], ['bootstatus'])
        self.assertEqual(owner.report['boot_install_phase']['install_attempts'], 0)

    def test_parent_deadline_clips_shared_phase_without_renewing_it(self):
        owner, calls, error = self.run_phase(start=850., ready=10., install=33.)
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 2)
        self.assertEqual(owner.report['boot_install_phase']['deadline_seconds'], 900.)
        self.assertEqual(owner.commands.report['commands'][-1]['work_deadline'], 892.)
        self.assertNotIn('completed', owner.report['boot_install_phase'])

    def test_cancellation_prevents_install_or_stops_its_only_attempt(self):
        for phase in ('bootstatus', 'install'):
            with self.subTest(phase=phase):
                owner, calls, error = self.run_phase(cancelled=phase)
                self.assertIsNotNone(error)
                self.assertEqual(len(calls), 1 if phase == 'bootstatus' else 2)
                self.assertNotIn('completed', owner.report['boot_install_phase'])

    def test_install_nonzero_and_late_completion_cannot_pass(self):
        for options in ({'install_code': 1}, {'post_install_delay': 100.}):
            with self.subTest(options=options):
                owner, calls, error = self.run_phase(**options)
                self.assertIsNotNone(error)
                self.assertEqual(len(calls), 2)
                self.assertNotIn('completed', owner.report['boot_install_phase'])


class OrdinaryLaunchTests(unittest.TestCase):
    def run_capture(self, delay, start=200., cancelled=False, sample_delay=0.,
                    sample_unresolved=False, observe_failure=False, sigchld=signal.SIG_DFL,
                    thread_count=1, failed_probe=False):
        # Real capture and process-controller code with a synthetic OS boundary.
        # This never spawns native tools or waits on wall-clock launch time.
        processes = load('recovery_process.py', 'launch_budget_processes')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        owner = s.OrdinarySmoke.__new__(s.OrdinarySmoke)
        owner.out = root
        owner.repo = root
        owner.app = root / 'Tripfolio.app'
        owner.started = 0.
        owner.work_deadline = 900.
        owner.cleanup_deadline = 1080.
        owner.cleaning = owner.interrupted = False
        owner.owned = '11111111-1111-4111-8111-111111111111'
        owner.launch_count = 0
        owner.report = {'screenshots': [], 'installed-before': {'fixture': True}}
        owner.baseline = {}
        owner.save = lambda: None
        owner.expected_manifest = {}
        owner.manifest = lambda _: {}
        verified = []
        owner.verify_installed = verified.append
        owner.zip = root / 'TripDocket-Simulator.zip'
        owner.zip.write_bytes(b'synthetic already-verified ZIP')
        owner.zip_sha = s.sha(owner.zip.read_bytes())
        provenance = root / 'provenance.json'
        provenance.write_bytes(b'synthetic already-verified provenance')
        owner.report['producer_provenance_sha256'] = s.sha(provenance.read_bytes())
        owner.before_code = {'synthetic': 'unchanged'}
        owner.preparer = p
        clock, calls, sample_live = [start], [], [False]
        class Process:
            def __init__(self, pid, ready, output, kind):
                self.pid, self.ready, self.output = pid, ready, output
                self.kind = kind
                self.returncode, self.read_done = None, False
            def poll(self):
                if self.kind == 'launch' and sample_live[0]:
                    raise AssertionError('Parent polled before sampler closed')
                if self.returncode is None and clock[0] >= self.ready:
                    self.returncode = 1 if failed_probe and self.kind == 'probe' else 0
                return self.returncode
        class Ops:
            def now(self): return clock[0]
            def sleep(self, seconds): clock[0] += seconds
            def spawn(self, argv):
                calls.append(argv)
                launch, sample = argv[2] == 'launch', argv[0] == '/usr/bin/sample'
                screenshot = not sample and argv[2] == 'io'
                kind = 'launch' if launch else 'sample' if sample else 'screenshot' if screenshot else 'probe'
                if screenshot or sample:
                    Path(argv[-1]).write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
                if sample: sample_live[0] = True
                output = (s.APP_ID + ': 12345\n').encode() if launch else b''
                if kind == 'probe' and argv[-1] == 'list':
                    output = ('12345\t0\tUIKitApplication:' + s.APP_ID + '[fixture]\n').encode()
                return Process(1000 + len(calls), clock[0] + (delay if launch else sample_delay if sample else 0),
                               output, kind)
            def prepare(self, _): pass
            def read(self, process):
                if cancelled: owner.interrupted = True
                if clock[0] >= process.ready and not process.read_done:
                    process.read_done = True
                    return [('stdout', process.output)] if process.output else []
                return []
            def absent(self, process):
                if process.kind == 'sample' and sample_unresolved:
                    raise PermissionError('Synthetic unresolved sampler')
                return process.poll() is not None
            def send(self, process, sig):
                process.returncode = -sig
                return 'syscall_returned'
            def close(self, process):
                if process.kind == 'sample' and not sample_unresolved: sample_live[0] = False
        ops = Ops()
        process_api = SimpleNamespace(Smoke=processes.Smoke, RealOps=lambda *_: ops)
        owner.qualification = SimpleNamespace(processes=process_api)
        owner.commands = s.make_commands_class(process_api)(owner)
        failure = None
        with patch.object(s.time, 'monotonic', side_effect=ops.now), \
                patch.object(s.time, 'sleep', side_effect=ops.sleep), \
                patch.object(s, 'code_identity', return_value=owner.before_code), \
                patch.object(s.signal, 'getsignal', return_value=sigchld), \
                patch.object(s.threading, 'active_count', return_value=thread_count):
            try: owner.capture()
            except RuntimeError as error: failure = error
            if observe_failure and failure:
                owner.observe_launch_failure()
        return owner, calls, verified, failure

    def test_cold_launch_45_seconds_completes_once_then_three_screens_and_integrity(self):
        owner, calls, verified, failure = self.run_capture(45.)
        self.assertIsNone(failure)
        self.assertEqual(calls[0], ['xcrun', 'simctl', 'launch', owner.owned, s.APP_ID])
        self.assertEqual(len(calls), 4)
        self.assertEqual(owner.commands.report['commands'][0]['requested_cap_seconds'], 128)
        self.assertEqual(owner.report['launch']['arguments'], [])
        self.assertEqual(owner.report['launch']['application_pid'], 12345)
        self.assertEqual(owner.report['launch']['count'], 1)
        self.assertFalse(owner.report['launch']['test_or_demo_flags'])
        self.assertEqual([row['requested_seconds'] for row in owner.report['screenshots']], [2, 10, 30])
        self.assertEqual(verified, ['installed-after'])
        self.assertTrue(owner.report['capture_completed'])
        with self.assertRaisesRegex(RuntimeError, 'only once'): owner.capture()
        self.assertEqual(len(calls), 4)

    def test_exact_120_second_boundary_fails_and_cannot_retry(self):
        owner, calls, verified, failure = self.run_capture(120.)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(len(calls), 2)  # One ordinary launch plus its owned-PID sample.
        self.assertEqual(calls[1][:4], ['/usr/bin/sample', '1001', '1', '10'])
        self.assertEqual(verified, [])
        self.assertEqual(owner.report['screenshots'], [])
        self.assertNotIn('launch', owner.report)
        row = owner.commands.report['commands'][0]
        self.assertEqual(row['work_deadline'] - row['start'], 120)
        self.assertEqual(row['error'], "RuntimeError('Command timeout')")
        self.assertEqual(row['stop']['signals'], [])  # Already exited exactly at the rejected boundary.
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        with self.assertRaisesRegex(RuntimeError, 'only once'): owner.capture()
        self.assertEqual(len(calls), 2)

    def test_near_boundary_launch_remains_finite_and_global_deadline_clips(self):
        owner, _, _, failure = self.run_capture(119.8)
        self.assertIsNone(failure)
        self.assertTrue(owner.report['capture_completed'])
        owner, calls, _, failure = self.run_capture(13., start=880.)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(len(calls), 1)
        row = owner.commands.report['commands'][0]
        self.assertEqual(row['command_deadline'], 900)
        self.assertEqual(row['work_deadline'], 892)
        self.assertEqual((owner.work_deadline, owner.cleanup_deadline), (900, 1080))

    def test_cancelled_launch_stops_once_without_screens_or_integrity_acceptance(self):
        owner, calls, verified, failure = self.run_capture(45., cancelled=True)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(verified, [])
        self.assertEqual(owner.report['screenshots'], [])
        self.assertNotIn('capture_completed', owner.report)
        self.assertTrue(owner.commands.report['commands'][0]['stop']['group_absent'])

    def test_sample_keeps_parent_unreaped_when_it_exits_during_synchronous_sample(self):
        owner, calls, _, failure = self.run_capture(91., sample_delay=3.)
        self.assertIsNone(failure)
        self.assertEqual(len([argv for argv in calls if argv[0] == '/usr/bin/sample']), 1)
        sample = owner.commands.report['commands'][0]['sample']
        self.assertIsNone(sample['last_poll_result'])
        self.assertEqual(sample['status'], 'collected')
        self.assertGreaterEqual(sample['finished_seconds'] - sample['started_seconds'], 3.)
        self.assertTrue(owner.report['capture_completed'])

    def test_sampler_timeout_closes_before_parent_and_does_not_reset_launch_deadline(self):
        owner, calls, _, failure = self.run_capture(125., sample_delay=30.)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(len(calls), 2)
        sample = owner.report['launch-sample_commands']['commands'][0]
        self.assertEqual(sample['requested_cap_seconds'], 13)
        self.assertEqual(sample['stop_reserve_seconds'], 8)
        self.assertEqual(sample['stop']['signals'], [signal.SIGTERM])
        self.assertTrue(sample['stop']['group_absent'] and sample['stop']['leader_reaped'])
        launch = owner.commands.report['commands'][0]
        self.assertEqual(launch['work_deadline'] - launch['start'], 120)
        self.assertTrue(launch['stop']['group_absent'])

    def test_sampler_skipped_for_auto_reaper_or_multiple_threads(self):
        for kwargs in ({'sigchld': signal.SIG_IGN}, {'sigchld': lambda *_: None}, {'thread_count': 2}):
            with self.subTest(kwargs=kwargs):
                owner, calls, _, failure = self.run_capture(120., **kwargs)
                self.assertIsInstance(failure, RuntimeError)
                self.assertEqual(len(calls), 1)
                self.assertEqual(owner.commands.report['commands'][0]['sample']['status'], 'skipped')

    def test_unresolved_sampler_withholds_parent_reap_and_failure_probes(self):
        owner, calls, _, failure = self.run_capture(125., sample_unresolved=True, observe_failure=True)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(len(calls), 2)
        self.assertEqual(owner.report['failure_observation']['status'], 'skipped')
        launch = owner.commands.report['commands'][0]
        self.assertIn('Sampler must close', launch['stop_error'])
        self.assertNotIn('stop', launch)
        self.assertTrue(owner.commands.active)

    def test_failure_probes_require_no_launch_pid_and_never_fill_success_fields(self):
        owner, calls, verified, failure = self.run_capture(125., observe_failure=True)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(verified, [])
        self.assertNotIn('launch', owner.report)
        self.assertEqual(owner.report['screenshots'], [])
        self.assertTrue(owner.report['ordinary_launch_failed'])
        rows = owner.report['failure_observation']['observations']
        self.assertEqual([row['status'] for row in rows], ['collected'] * 3)
        self.assertIn('UIKitApplication:' + s.APP_ID, rows[1]['matching_services'][0])
        self.assertEqual(len([argv for argv in calls if argv[2] == 'launch']), 1)
        for argv in calls[-3:]: self.assertIn(owner.owned, argv)
        self.assertIn('process == "Tripfolio" OR eventMessage CONTAINS[c] "com.4alvit.tripfolio"', calls[-1])

    def test_cancelled_or_deadline_clipped_failure_does_not_start_post_probes(self):
        for kwargs in ({'cancelled': True}, {'start': 880.}):
            with self.subTest(kwargs=kwargs):
                owner, calls, _, failure = self.run_capture(125., observe_failure=True, **kwargs)
                self.assertIsInstance(failure, RuntimeError)
                self.assertEqual(len(calls), 1)
                self.assertEqual(owner.report['failure_observation']['status'], 'skipped')

    def test_unavailable_probe_is_recorded_without_turning_failed_launch_into_success(self):
        owner, _, _, failure = self.run_capture(125., failed_probe=True, observe_failure=True)
        self.assertIsInstance(failure, RuntimeError)
        rows = owner.report['failure_observation']['observations']
        self.assertEqual([row['status'] for row in rows], ['collected', 'unavailable', 'unavailable'])
        self.assertNotIn('capture_completed', owner.report)

    def test_diagnostic_tree_rejects_symlinks_and_total_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner = s.OrdinarySmoke.__new__(s.OrdinarySmoke)
            owner.out = Path(temporary).resolve()
            owner.check = lambda: None
            root = owner.diagnostic_root()
            link = root / 'link'
            link.symlink_to(owner.out)
            with self.assertRaisesRegex(RuntimeError, 'Unsafe diagnostic entry'): owner.diagnostic_usage()
            link.unlink()
            with (root / 'large').open('wb') as stream: stream.truncate(8 * s.MIB + 1)
            with self.assertRaisesRegex(RuntimeError, 'output cap'): owner.diagnostic_usage()


if __name__ == '__main__':
    unittest.main()
