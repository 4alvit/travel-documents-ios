"""Offline runner contracts: temporary toy files and fake observations only.

No native command, live signal, resource-limit change, or network call is allowed.
Run with: python3 -B -m unittest discover -s <candidate> -p tests_runner.py -v
"""
from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location('diagnostic_runner_under_test', Path(__file__).with_name('runner.py'))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
SHA = 'a' * 40
INFINITY = runner.resource.RLIM_INFINITY
EXPECTED = ['room-first'] + [f'{b}-{a}' for b in ('room', 'redact', 'trip') for a in ('A-before', 'B', 'A-after')]
BOOT = {'XPC_SERVICE_NAME': 'application.test.123', 'XPC_FLAGS': '0x0', '__CF_USER_TEXT_ENCODING': '0x1F5:0x0:0x0'}


def parent_env():
    return dict(PATH='/usr/bin:/bin', HOME='/toy/private-home', TMPDIR='/toy/private-tmp',
                LANG='en_GB.UTF-8', LC_ALL='en_GB.UTF-8', USER='toy-user', LOGNAME='toy-login',
                DEVELOPER_DIR='/Applications/Toy.app/Contents/Developer',
                GITHUB_TOKEN='PRIVATE_SENTINEL_NEVER_FORWARD', ARBITRARY='PRIVATE_OTHER', **BOOT)


def success(**updates):
    return dict(dict(outcome='success', cleanup_confirmed=True, identity_uncertain=False,
                     elapsed_seconds=0.1, returncode=0, stdout_bytes=0, stderr_bytes=0,
                     stdout_sha256=hashlib.sha256(b'').hexdigest(),
                     stderr_sha256=hashlib.sha256(b'').hexdigest(),
                     spawn_observation={'duration_seconds': 0.01, 'pid': 101, 'pgid': 101, 'sid': 101},
                     exception_type=None, errno=None, streams_merged=False, output_censored=False), **updates)


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='runner-offline-')))
        # These are hard tripwires; tests may replace setrlimit only with a fake.
        for name in ('subprocess.Popen', 'subprocess.run', 'subprocess.check_call', 'subprocess.check_output',
                     'os.system', 'os.popen', 'os.kill', 'os.killpg', 'os.fork', 'os.posix_spawn', 'os.posix_spawnp',
                     'resource.setrlimit', 'signal.signal', 'signal.pthread_sigmask', 'signal.siginterrupt',
                     'signal.setitimer', 'signal.alarm', 'signal.raise_signal', 'os._exit', 'threading.Timer'):
            self.stack.enter_context(mock.patch(name, side_effect=AssertionError('FORBIDDEN_LIVE_OPERATION: ' + name)))
        self.stack.enter_context(mock.patch.object(runner, 'limits', return_value={'RLIMIT_FSIZE': [-1, -1]}))

    def schedule(self, observations=None, env=None, deadline=1000, clock=None, persist=None, invoke=None):
        private = self.temp / ('private-' + str(len(list(self.temp.iterdir()))))
        private.mkdir(mode=0o700)
        calls, snapshots = [], []
        pending = iter(observations or [])

        def fake_invoke(boundary, child_env, target, limit):
            calls.append((boundary, dict(child_env), target, limit))
            value = next(pending, success())
            if isinstance(value, BaseException):
                raise value
            return value

        def fake_persist(rows, stopped):
            snapshots.append((copy.deepcopy(rows), stopped))
            if persist:
                persist(rows, stopped)

        result = runner.run_schedule(parent_env() if env is None else env, private, deadline,
                                     invoke or fake_invoke, fake_persist, clock=clock or (lambda: 0.0))
        return result, calls, snapshots, private


class ScheduleContracts(OfflineCase):
    def test_fixed_ten_phases_and_per_boundary_aba_environment_association(self):
        (rows, stopped), calls, snapshots, private = self.schedule()
        self.assertFalse(stopped)
        self.assertEqual([r['phase'] for r in rows], EXPECTED)
        self.assertEqual(len(calls), 10)
        self.assertEqual(len(snapshots), 10)
        self.assertEqual(rows[0]['arm'], 'first-in-job')
        self.assertNotIn('cold', json.dumps(rows).lower())
        for i, boundary in enumerate(('room', 'redact', 'trip')):
            before, variant, after = calls[1 + i * 3:4 + i * 3]
            self.assertEqual([c[0] for c in (before, variant, after)], [boundary] * 3)
            self.assertEqual(before[1], after[1])
            self.assertEqual(set(variant[1]) - set(before[1]), set(BOOT))
            self.assertEqual({k: v for k, v in variant[1].items() if k not in BOOT}, before[1])
        for row, (_, child_env, target, _) in zip(rows, calls):
            actual = private / row['phase'] / 'actual-env.json'
            self.assertEqual(json.loads(actual.read_text()), child_env)
            self.assertEqual(actual.stat().st_mode & 0o777, 0o600)
        public = json.dumps(snapshots)
        for value in list(BOOT.values()) + ['/toy/private-home', '/toy/private-tmp', 'PRIVATE_SENTINEL_NEVER_FORWARD']:
            self.assertNotIn(value, public)

    def test_absent_all_bootstrap_keys_skips_entire_b_and_after_not_before(self):
        env = {k: v for k, v in parent_env().items() if k not in BOOT}
        (rows, stopped), calls, _, _ = self.schedule(env=env)
        self.assertFalse(stopped)
        self.assertEqual(len(calls), 4)
        for row in rows:
            if row['phase'].endswith('-B'):
                self.assertEqual((row['status'], row['reason']), ('SKIPPED', 'NO_ENV_DELTA'))
            elif row['phase'].endswith('A-after'):
                self.assertEqual((row['status'], row['reason']), ('SKIPPED', 'NO_INTERVENTION'))

    def test_one_invalid_selected_key_skips_full_bundle_without_partial_treatment(self):
        env = parent_env()
        env['XPC_FLAGS'] = 'invalid;value'
        (rows, stopped), calls, _, _ = self.schedule(env=env)
        self.assertFalse(stopped)
        self.assertEqual(len(calls), 4)
        self.assertEqual([r['reason'] for r in rows if r['phase'].endswith('-B')], ['INVALID_BUNDLE'] * 3)
        self.assertTrue(all(not set(c[1]).intersection(BOOT) for c in calls))

    def test_valid_partial_presence_is_one_fixed_bundle(self):
        env = {k: v for k, v in parent_env().items() if k not in ('XPC_FLAGS', '__CF_USER_TEXT_ENCODING')}
        (rows, stopped), calls, _, _ = self.schedule(env=env)
        self.assertFalse(stopped)
        for index in (2, 5, 8):
            self.assertEqual(set(calls[index][1]).intersection(BOOT), {'XPC_SERVICE_NAME'})

    def test_clean_expected_timeouts_can_advance(self):
        (rows, stopped), calls, _, _ = self.schedule([success(outcome='timeout')] * 10)
        self.assertFalse(stopped)
        self.assertEqual(len(calls), 10)
        self.assertTrue(all(r['observation']['outcome'] == 'timeout' for r in rows))

    def test_no_new_phase_after_failed_cleanup_uncertain_identity_or_other_error(self):
        bad = [success(cleanup_confirmed=False), success(identity_uncertain=True),
               success(outcome='error'), success(outcome='refused'),
               {'outcome': 'success', 'cleanup_confirmed': True, 'output_censored': False},
               success(cleanup_confirmed=1), success(identity_uncertain=0)]
        for observation in bad:
            with self.subTest(observation=observation):
                (rows, stopped), calls, _, _ = self.schedule([observation])
                self.assertTrue(stopped)
                self.assertEqual(len(calls), 1)
                self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows[1:]))

    def test_no_new_phase_after_output_censor_even_when_other_flags_look_clean(self):
        for outcome in ('success', 'timeout'):
            with self.subTest(outcome=outcome):
                (rows, stopped), calls, _, _ = self.schedule([success(outcome=outcome, output_censored=True)])
                self.assertTrue(stopped)
                self.assertEqual(len(calls), 1)
                self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows[1:]))

    def test_unknown_output_censor_state_does_not_authorize_continuation(self):
        observation = success()
        del observation['output_censored']
        (rows, stopped), calls, _, _ = self.schedule([observation])
        self.assertTrue(stopped)
        self.assertEqual(len(calls), 1)

    def test_adapter_receives_empty_private_directory_not_environment_file(self):
        invoked = []

        def requires_fresh(boundary, env, target, deadline):
            invoked.append(target)
            if list(target.iterdir()):
                raise ValueError('Private directory must be fresh')
            return success()

        (rows, stopped), _, _, _ = self.schedule(invoke=requires_fresh)
        self.assertFalse(stopped)
        self.assertEqual(len(invoked), 10)
        self.assertTrue(all(r['status'] == 'OBSERVED' for r in rows))

    def test_adapter_observation_cannot_publish_unknown_raw_environment_field(self):
        observation = success()
        observation['raw_environment'] = {'PRIVATE_VALUE': 'RAW_ENV_SENTINEL'}
        (rows, stopped), calls, snapshots, _ = self.schedule([observation])
        self.assertTrue(stopped)
        self.assertEqual(len(calls), 1)
        self.assertTrue('RAW_ENV_SENTINEL' not in json.dumps(snapshots), 'raw environment was published')

    def test_typed_schema_rejects_censored_sizes_nonfinite_time_and_nested_raw_fields(self):
        invalid = [success(stdout_bytes=runner.FILE_CAP + 1), success(stderr_bytes=-1),
                   success(stdout_sha256='RAW_SCHEMA_SENTINEL'), success(errno=True),
                   success(elapsed_seconds=float('nan')), success(elapsed_seconds=float('inf')),
                   success(exception_type='RAW_SCHEMA_SENTINEL\nnot-a-class'),
                   success(spawn_observation={'pid': 101, 'environment': 'RAW_SCHEMA_SENTINEL'})]
        for observation in invalid:
            with self.subTest(observation=observation):
                (rows, stopped), calls, snapshots, _ = self.schedule([observation])
                self.assertTrue(stopped)
                self.assertEqual(len(calls), 1)
                self.assertEqual(rows[0]['status'], 'ADAPTER_FAILED')
                self.assertTrue('RAW_SCHEMA_SENTINEL' not in json.dumps(snapshots), 'invalid raw field was published')

    def test_exception_errno_must_not_publish_arbitrary_values(self):
        class InvalidErrno(Exception):
            errno = 'RAW_ERRNO_SENTINEL'

        (rows, stopped), calls, snapshots, _ = self.schedule([InvalidErrno()])
        self.assertTrue(stopped)
        self.assertEqual(len(calls), 1)
        self.assertTrue('RAW_ERRNO_SENTINEL' not in json.dumps(snapshots), 'raw non-numeric errno was published')

    def test_invalid_observation_and_exception_stop_without_public_error_message(self):
        for observation in ([], None, PermissionError(1, 'PRIVATE_EXCEPTION_SENTINEL')):
            with self.subTest(observation=observation):
                (rows, stopped), calls, snapshots, _ = self.schedule([observation])
                self.assertTrue(stopped)
                self.assertEqual(len(calls), 1)
                self.assertEqual(rows[0]['status'], 'ADAPTER_FAILED')
                self.assertNotIn('PRIVATE_EXCEPTION_SENTINEL', json.dumps(snapshots))

    def test_global_budget_reserves_seventy_seconds_before_each_new_phase(self):
        (rows, stopped), calls, _, _ = self.schedule(deadline=69.999)
        self.assertTrue(stopped)
        self.assertEqual(calls, [])
        self.assertEqual(rows[0]['reason'], 'GLOBAL_BUDGET')
        current = [0.0]
        invoked = []

        def advance(*args):
            invoked.append(args)
            current[0] += 70
            return success()

        (rows, stopped), _, _, _ = self.schedule(deadline=200, clock=lambda: current[0], invoke=advance)
        self.assertTrue(stopped)
        self.assertEqual(len(invoked), 2)
        self.assertEqual(rows[2]['reason'], 'GLOBAL_BUDGET')
        self.assertTrue(all(r['status'] == 'NOT_RUN' for r in rows[2:]))

    def test_private_write_failure_cannot_launch_probe(self):
        invoke = mock.Mock()
        with mock.patch.object(runner, 'write_json', side_effect=OSError('PRIVATE_WRITE_FAILURE')):
            with self.assertRaises(OSError):
                self.schedule(invoke=invoke)
        invoke.assert_not_called()

    def test_persist_failure_cannot_launch_a_following_probe(self):
        invoke = mock.Mock(return_value=success())
        with self.assertRaises(OSError):
            self.schedule(invoke=invoke, persist=lambda *_: (_ for _ in ()).throw(OSError('PERSIST_FAILURE')))
        self.assertEqual(invoke.call_count, 1)


class EnvironmentAndFileContracts(OfflineCase):
    def test_selected_developer_is_explicit_for_room_trip_and_redact_preserves_absence(self):
        original = parent_env()
        del original['DEVELOPER_DIR']
        original['_selected_developer'] = '/Applications/Selected.app/Contents/Developer'
        untouched = dict(original)
        phases = runner.planned_phases(original)
        for phase, boundary, _, env, skip in phases:
            self.assertIsNone(skip)
            self.assertNotIn('_selected_developer', env)
            if boundary == 'redact':
                self.assertNotIn('DEVELOPER_DIR', env, phase)
            else:
                self.assertEqual(env['DEVELOPER_DIR'], original['_selected_developer'], phase)
        self.assertEqual(original, untouched)

    def test_redact_preserves_present_developer_value(self):
        original = parent_env()
        original['_selected_developer'] = original['DEVELOPER_DIR']
        self.assertEqual(runner.env_for('redact', original)['DEVELOPER_DIR'], original['DEVELOPER_DIR'])

    def test_environment_boundaries_do_not_forward_arbitrary_values(self):
        expected = {
            'room': {'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'DEVELOPER_DIR'},
            'redact': {'HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'DEVELOPER_DIR', 'LANG'},
            'trip': {'HOME', 'USER', 'TMPDIR', 'DEVELOPER_DIR', 'PATH', 'GIT_OPTIONAL_LOCKS'},
        }
        for boundary, keys in expected.items():
            child = runner.env_for(boundary, parent_env())
            self.assertEqual(set(child), keys)
            self.assertNotIn('PRIVATE_SENTINEL_NEVER_FORWARD', json.dumps(child))
        self.assertEqual(runner.env_for('redact', parent_env())['LANG'], 'en_US.UTF-8')
        self.assertEqual(runner.env_for('trip', parent_env())['PATH'], '/usr/bin:/bin:/usr/sbin:/sbin')
        with self.assertRaises(runner.Refused):
            runner.env_for('other', parent_env())

    def test_environment_evidence_has_only_lengths_and_digests(self):
        source = {'HOME': 'private-non-ascii-秘密'}
        observed = runner.env_evidence(source)
        self.assertEqual(observed, {'HOME': {'bytes': len(source['HOME'].encode()),
                                           'sha256': hashlib.sha256(source['HOME'].encode()).hexdigest()}})
        self.assertNotIn(source['HOME'], json.dumps(observed))

    def test_file_limits_reject_oversized_and_symlink_inputs(self):
        file = self.temp / 'toy'
        file.write_bytes(b'abcd')
        self.assertEqual(runner.regular_bytes(file, 4), b'abcd')
        with self.assertRaises(runner.Refused):
            runner.regular_bytes(file, 3)
        alias = self.temp / 'alias'
        alias.symlink_to(file)
        with self.assertRaises(runner.Refused):
            runner.regular_bytes(alias, 4)

    def test_json_output_limit_precedes_write_and_no_temporary_overwrite(self):
        target = self.temp / 'report.json'
        with self.assertRaises(runner.Refused):
            runner.write_json(target, {'large': 'x' * 100}, 20)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix('.tmp').exists())
        target.with_suffix('.tmp').write_text('do not overwrite')
        with self.assertRaises(FileExistsError):
            runner.write_json(target, {'ok': True})
        self.assertEqual(target.with_suffix('.tmp').read_text(), 'do not overwrite')

    def test_oversized_private_environment_cannot_launch_probe(self):
        env = parent_env()
        env['HOME'] = 'x' * 65536
        invoke = mock.Mock()
        with self.assertRaises(runner.Refused):
            self.schedule(env=env, invoke=invoke)
        invoke.assert_not_called()

    def toy_seal(self):
        root = self.temp / ('sealed-' + str(len(list(self.temp.iterdir()))))
        root.mkdir()
        for name in ('runner.py', 'adapters.py', 'deadline_guard.py', 'plan.json'):
            (root / name).write_text('toy ' + name)
        (root / 'vendor').mkdir()
        (root / 'vendor/toy.py').write_text('never executed')
        vendor_sha = hashlib.sha256((root / 'vendor/toy.py').read_bytes()).hexdigest()
        (root / 'vendor-manifest.json').write_text(json.dumps({'files': [{'path': 'vendor/toy.py', 'sha256': vendor_sha}]}))
        files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        return root, self.save_seal(root, files)

    def save_seal(self, root, files):
        raw = json.dumps({'files': files}).encode()
        (root / 'seal.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_valid_seal_tamper_source_and_tamper_manifest(self):
        root, expected = self.toy_seal()
        self.assertEqual(runner.verify_seal(root, expected), expected)
        (root / 'adapters.py').write_text('tampered')
        with self.assertRaisesRegex(runner.Refused, 'SOURCE_MISMATCH'):
            runner.verify_seal(root, expected)
        root, expected = self.toy_seal()
        (root / 'seal.json').write_text('{}')
        with self.assertRaisesRegex(runner.Refused, 'SEAL_MISMATCH'):
            runner.verify_seal(root, expected)

    def test_seal_rejects_incomplete_traversal_and_symlink_source(self):
        for mode in ('incomplete', 'traversal', 'symlink'):
            with self.subTest(mode=mode):
                root, _ = self.toy_seal()
                files = json.loads((root / 'seal.json').read_text())['files']
                if mode == 'incomplete':
                    del files['plan.json']
                elif mode == 'traversal':
                    files['../escape'] = 'a' * 64
                else:
                    (root / 'adapters.py').unlink()
                    (root / 'adapters.py').symlink_to(root / 'runner.py')
                expected = self.save_seal(root, files)
                with self.assertRaises(runner.Refused):
                    runner.verify_seal(root, expected)


class HostAndMainContracts(OfflineCase):
    def hosted(self):
        workspace = self.temp / 'workspace'
        root = workspace / 'diagnostics/ios-discovery'
        root.mkdir(parents=True, exist_ok=True)
        env = dict(GITHUB_ACTIONS='true', CI='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='macOS',
                   RUNNER_ARCH='ARM64', GITHUB_EVENT_NAME='push', GITHUB_RUN_ATTEMPT='1',
                   GITHUB_REPOSITORY='4alvit/travel-documents-ios', GITHUB_JOB='diagnostic',
                   GITHUB_SERVER_URL='https://github.com', GITHUB_SHA=SHA, GITHUB_WORKFLOW_SHA=SHA,
                   GITHUB_REF=runner.DIAGNOSTIC_REF, GITHUB_RUN_ID='123', ImageOS='macos15',
                   ImageVersion='20261027.1234.1', GITHUB_WORKSPACE=str(workspace),
                   DEVELOPER_DIR=runner.PINNED_DEVELOPER)
        env['GITHUB_WORKFLOW_REF'] = env['GITHUB_REPOSITORY'] + '/.github/workflows/ios-discovery-diagnostic.yml@' + env['GITHUB_REF']
        return root, env

    def test_host_gate_accepts_only_exact_context_without_probing_host(self):
        root, env = self.hosted()
        with mock.patch.object(runner, 'ROOT', root), mock.patch.object(runner.platform, 'system', return_value='Darwin'), \
             mock.patch.object(runner.platform, 'machine', return_value='arm64'), \
             mock.patch.object(runner.platform, 'python_version', return_value=runner.HISTORICAL['python']):
            runner.host_gate(env, SHA)
            for key in env:
                changed = dict(env, **{key: 'mismatch'})
                with self.subTest(key=key), self.assertRaises(runner.Refused):
                    runner.host_gate(changed, SHA)
            for key in ('SIMCTL_CHILD_SECRET', 'DYLD_INSERT_LIBRARIES', 'XCTestConfig', 'TEST_RUNNER_OPTION'):
                with self.subTest(key=key), self.assertRaises(runner.Refused):
                    runner.host_gate(dict(env, **{key: 'value'}), SHA)

    def test_host_gate_rejects_machine_python_or_requested_sha_mismatch(self):
        root, env = self.hosted()
        for system, machine, version, sha in [('Linux', 'arm64', '3.14.7', SHA),
                                               ('Darwin', 'x86_64', '3.14.7', SHA),
                                               ('Darwin', 'arm64', '3.11.9', SHA),
                                               ('Darwin', 'arm64', '3.14.7', 'b' * 40)]:
            with mock.patch.object(runner, 'ROOT', root), mock.patch.object(runner.platform, 'system', return_value=system), \
                 mock.patch.object(runner.platform, 'machine', return_value=machine), \
                 mock.patch.object(runner.platform, 'python_version', return_value=version), self.assertRaises(runner.Refused):
                runner.host_gate(env, sha)

    def test_default_main_is_preparation_only(self):
        with mock.patch.object(runner.sys, 'argv', ['runner.py']), \
             mock.patch.object(runner, 'verify_seal') as seal, mock.patch.object(runner, 'run_schedule') as schedule, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(), 0)
        seal.assert_not_called()
        schedule.assert_not_called()

    def test_current_image_and_supported_python_are_accepted_without_historical_claim(self):
        root, env = self.hosted()
        for version in ('3.12.10', '3.13.9', '3.14.1'):
            with self.subTest(version=version), mock.patch.object(runner, 'ROOT', root), \
                 mock.patch.object(runner.platform, 'system', return_value='Darwin'), \
                 mock.patch.object(runner.platform, 'machine', return_value='arm64'), \
                 mock.patch.object(runner.platform, 'python_version', return_value=version):
                runner.host_gate(env, SHA)
        self.assertNotEqual(env['ImageVersion'], runner.HISTORICAL['image_version'])

    def test_host_gate_refuses_reruns_non_push_events_and_other_branches(self):
        root, env = self.hosted()
        changes = [{'GITHUB_RUN_ATTEMPT': '2'}, {'GITHUB_EVENT_NAME': 'workflow_dispatch'},
                   {'GITHUB_EVENT_NAME': 'pull_request'}, {'GITHUB_REF': 'refs/heads/main'},
                   {'GITHUB_REF': runner.DIAGNOSTIC_REF + '-other'}]
        with mock.patch.object(runner, 'ROOT', root), mock.patch.object(runner.platform, 'system', return_value='Darwin'), \
             mock.patch.object(runner.platform, 'machine', return_value='arm64'), \
             mock.patch.object(runner.platform, 'python_version', return_value='3.13.9'):
            for change in changes:
                with self.subTest(change=change), self.assertRaises(runner.Refused):
                    runner.host_gate(dict(env, **change), SHA)

    def fake_main(self, *, reject_host=False, fail_schedule=False, bad_restore=False, clock_values=(10.0, 10.0),
                  schedule_rows=None, fail_factory=False, fail_arm=False, fail_close=False,
                  fail_seal=False, fail_toolchain=False, fail_final_write=False, fail_event=False):
        root, env = self.hosted()
        temp = self.temp / 'runner-temp'
        temp.mkdir()
        env.update(parent_env(), RUNNER_TEMP=str(temp))
        env['DEVELOPER_DIR'] = runner.PINNED_DEVELOPER
        toy_python = self.temp / 'toy-python-not-executable'
        toy_python.write_bytes(b'TOY_PYTHON_BINARY')
        state = [(INFINITY, INFINITY)]
        set_calls = []
        events = []
        guard = mock.Mock(name='fake_deadline_guard')

        def fake_arm(deadline):
            events.append('arm')
            if fail_arm:
                raise InterruptedError('PRIVATE_ARM_FAILURE')

        def fake_close():
            events.append('close')
            if fail_close:
                raise RuntimeError('PRIVATE_CLOSE_FAILURE')

        guard.arm.side_effect = fake_arm
        guard.close.side_effect = fake_close

        def fake_factory(started, public):
            events.append('factory')
            if fail_factory:
                raise RuntimeError('PRIVATE_FACTORY_FAILURE')
            return guard

        factory = mock.Mock(side_effect=fake_factory)

        def fake_seal(*args):
            events.append('seal')
            if fail_seal:
                raise runner.Refused('SEAL_MISMATCH')
            return 'a' * 64

        def fake_event(*args):
            events.append('event')
            if fail_event:
                raise runner.Refused('NOT_FIRST_BRANCH_PUSH')

        def fake_toolchain(*args):
            events.append('toolchain')
            if fail_toolchain:
                raise runner.Refused('XCODE_VERSION_MISMATCH')
            return {'identity_basis': 'FAKE_OFFLINE'}

        original_write_json = runner.write_json
        public_writes = [0]

        def fake_write_json(path, value, cap=256 * 1024):
            if path == root / 'public/diagnostic.json':
                public_writes[0] += 1
                events.append('receipt')
                if fail_final_write and public_writes[0] == 2:
                    raise OSError('PRIVATE_RECEIPT_FAILURE')
            return original_write_json(path, value, cap)

        def fake_get(which):
            return state[0]

        def fake_set(which, value):
            set_calls.append((which, value))
            if not (bad_restore and value == (INFINITY, INFINITY)):
                state[0] = value

        fake_adapter = types.ModuleType('adapters')
        fake_adapter.run_probe = mock.Mock(return_value=success())

        def fake_schedule(parent, private, deadline, invoke, persist):
            events.append('schedule')
            if fail_schedule:
                raise RuntimeError('PRIVATE_SCHEDULE_ERROR')
            rows = schedule_rows or []
            stopped = any(row['status'] == 'ADAPTER_FAILED' for row in rows)
            persist(rows, stopped)
            return rows, stopped

        def fake_metadata(path, cap):
            if path == Path('/System/Library/CoreServices/SystemVersion.plist'):
                return runner.plistlib.dumps({'ProductVersion': '15.6', 'ProductBuildVersion': '24G84'})
            if path == toy_python.resolve():
                return b'TOY_PYTHON_BINARY'
            raise AssertionError('Unexpected non-toy metadata read: ' + str(path))

        schedule = mock.Mock(side_effect=fake_schedule)
        self.last_guard_records = dict(factory=factory, guard=guard, events=events, schedule=schedule)
        with mock.patch.object(runner, 'ROOT', root), mock.patch.dict(runner.os.environ, env, clear=True), \
             mock.patch.object(runner.sys, 'argv', ['runner.py', '--execute', '--expected-sha', SHA, '--package-sha256', 'a' * 64]), \
             mock.patch.object(runner.sys, 'path', list(sys.path)), mock.patch.dict(sys.modules, {'adapters': fake_adapter}), \
             mock.patch.object(runner.sys, 'executable', str(toy_python)), \
             mock.patch.object(runner, 'regular_bytes', side_effect=fake_metadata), \
             mock.patch.object(runner, 'verify_seal', side_effect=fake_seal), \
             mock.patch.object(runner, 'push_event_gate', side_effect=fake_event), \
             mock.patch.object(runner, 'new_deadline_guard', factory), \
             mock.patch.object(runner, 'write_json', side_effect=fake_write_json), \
             mock.patch.object(runner, 'host_gate', side_effect=runner.Refused('HOST_CONTEXT') if reject_host else None), \
             mock.patch.object(runner, 'toolchain', side_effect=fake_toolchain), \
             mock.patch.object(runner.resource, 'getrlimit', side_effect=fake_get), \
             mock.patch.object(runner.resource, 'setrlimit', side_effect=fake_set), \
             mock.patch.object(runner.time, 'monotonic', side_effect=clock_values), \
             mock.patch.object(runner, 'run_schedule', schedule):
            code = runner.main()
        return code, set_calls, schedule, json.loads((root / 'public/diagnostic.json').read_text())

    def test_main_restores_resource_limit_after_success_and_schedule_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                # Each main call requires a fresh one-shot output/private root.
                with tempfile.TemporaryDirectory(dir=self.temp) as directory:
                    old = self.temp
                    self.temp = Path(directory)
                    try:
                        code, calls, schedule, report = self.fake_main(fail_schedule=fail)
                    finally:
                        self.temp = old
                self.assertEqual(code, int(fail))
                self.assertEqual([v for _, v in calls], [(runner.FILE_CAP, INFINITY), (INFINITY, INFINITY)])
                self.assertEqual(schedule.call_count, 1)
                if not fail:
                    self.assertEqual(report['status'], 'COLLECTION_COMPLETE')
                    self.assertEqual(report['os'], {'ProductVersion': '15.6', 'ProductBuildVersion': '24G84'})
                    self.assertEqual(report['python_executable_sha256'], hashlib.sha256(b'TOY_PYTHON_BINARY').hexdigest())
                self.assertNotIn('PRIVATE_SCHEDULE_ERROR', json.dumps(report))
                self.assertIn('rlimits_after_restore', report)

    def test_main_host_refusal_never_changes_limits_or_schedules(self):
        code, calls, schedule, report = self.fake_main(reject_host=True)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        schedule.assert_not_called()
        self.assertEqual(report['status'], 'REFUSED_OR_FAILED')

    def test_main_failed_restore_is_failure_even_after_successful_schedule(self):
        code, calls, schedule, report = self.fake_main(bad_restore=True)
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'RESTORE_FAILED')
        self.assertEqual(calls[-1][1], (INFINITY, INFINITY))
        self.last_guard_records['guard'].close.assert_called_once_with()

    def test_main_budget_uses_start_plus_750_not_post_preflight_clock(self):
        code, calls, schedule, report = self.fake_main(clock_values=(10.0, 40.0))
        self.assertEqual(code, 0)
        self.assertEqual(runner.TOTAL_SECONDS, 780)
        self.assertEqual(schedule.call_args.args[2], 760.0)
        self.assertEqual(calls[-1][1], (INFINITY, INFINITY))

    def test_main_exhausted_preflight_refuses_schedule_and_restores_limit(self):
        code, calls, schedule, report = self.fake_main(clock_values=(10.0, 55.0001))
        self.assertEqual(code, 1)
        schedule.assert_not_called()
        self.assertEqual(report['reason'], 'PREFLIGHT_BUDGET')
        self.assertEqual(calls[-1][1], (INFINITY, INFINITY))
        self.last_guard_records['guard'].arm.assert_not_called()
        self.last_guard_records['guard'].close.assert_called_once_with()

    def test_main_counters_preserve_unknown_acquisition_after_adapter_exception(self):
        rows = [{'status': 'OBSERVED', 'observation': success()}, {'status': 'ADAPTER_FAILED'}]
        code, calls, schedule, report = self.fake_main(schedule_rows=rows)
        self.assertEqual(code, 1)
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(report['phase_invocation_count'], 2)
        self.assertEqual(report['native_acquisitions_observed'], 1)
        self.assertTrue(report['native_acquisitions_unknown'])
        self.assertNotIn('native_probe_count', report)

    def test_guard_factory_arm_close_order_on_success(self):
        code, _, schedule, report = self.fake_main()
        self.assertEqual(code, 0)
        record = self.last_guard_records
        record['factory'].assert_called_once()
        self.assertEqual(record['factory'].call_args.args[0], 10.0)
        record['guard'].arm.assert_called_once_with(760.0)
        record['guard'].close.assert_called_once_with()
        self.assertLess(record['events'].index('factory'), record['events'].index('seal'))
        self.assertLess(record['events'].index('seal'), record['events'].index('event'))
        self.assertLess(record['events'].index('event'), record['events'].index('toolchain'))
        self.assertLess(record['events'].index('arm'), record['events'].index('schedule'))
        self.assertEqual(record['events'][-2:], ['receipt', 'close'])
        self.assertFalse(report['historical_reproduction_claim'])
        self.assertEqual(report['experiment_environment'], 'current_hosted_image_single_job')

    def test_guard_not_created_on_host_refusal(self):
        self.fake_main(reject_host=True)
        self.last_guard_records['factory'].assert_not_called()
        self.last_guard_records['guard'].arm.assert_not_called()
        self.last_guard_records['guard'].close.assert_not_called()

    def test_guard_closes_after_seal_toolchain_arm_and_schedule_failures(self):
        for failure in ('fail_seal', 'fail_event', 'fail_toolchain', 'fail_arm', 'fail_schedule'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir=self.temp) as directory:
                old = self.temp
                self.temp = Path(directory)
                try:
                    code, _, schedule, report = self.fake_main(**{failure: True})
                finally:
                    self.temp = old
                self.assertEqual(code, 1)
                self.last_guard_records['guard'].close.assert_called_once_with()
                self.assertEqual(self.last_guard_records['events'][-2:], ['receipt', 'close'])
                if failure != 'fail_schedule':
                    schedule.assert_not_called()
                self.assertNotIn('PRIVATE_', json.dumps(report))

    def test_guard_factory_failure_does_not_arm_or_schedule(self):
        code, calls, schedule, report = self.fake_main(fail_factory=True)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        schedule.assert_not_called()
        self.last_guard_records['guard'].arm.assert_not_called()
        self.last_guard_records['guard'].close.assert_not_called()
        self.assertEqual(report['status'], 'REFUSED_OR_FAILED')

    def test_guard_close_failure_is_unknown_and_failure(self):
        code, _, schedule, report = self.fake_main(fail_close=True)
        self.assertEqual(code, 1)
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(report['status'], 'GUARD_FINALIZATION_FAILED')
        self.assertTrue(report['native_acquisitions_unknown'])
        self.assertNotIn('PRIVATE_CLOSE_FAILURE', json.dumps(report))

    def test_guard_closes_even_when_final_receipt_write_fails(self):
        with self.assertRaises(OSError):
            self.fake_main(fail_final_write=True)
        self.last_guard_records['guard'].close.assert_called_once_with()
        self.assertEqual(self.last_guard_records['events'][-2:], ['receipt', 'close'])


class BranchCreationPayloadContracts(OfflineCase):
    def event(self, **updates):
        return dict(dict(created=True, deleted=False, forced=False, before='0' * 40,
                         after=SHA, ref=runner.DIAGNOSTIC_REF,
                         repository={'full_name': '4alvit/travel-documents-ios'}), **updates)

    def check(self, value, expected=SHA):
        path = self.temp / 'toy-event.json'
        path.write_text(json.dumps(value))
        return runner.push_event_gate({'GITHUB_EVENT_PATH': str(path)}, expected)

    def test_exact_branch_creation_at_reviewed_commit_accepted(self):
        self.assertIsNone(self.check(self.event()))

    def test_branch_updates_forced_deleted_and_missing_or_non_boolean_flags_refused(self):
        invalid = [self.event(created=False), self.event(forced=True), self.event(deleted=True),
                   self.event(created=1), self.event(forced=0), self.event(deleted=0),
                   self.event(before='b' * 40)]
        for key in ('created', 'deleted', 'forced'):
            value = self.event()
            del value[key]
            invalid.append(value)
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(runner.Refused):
                self.check(event)

    def test_wrong_commit_ref_repository_and_payload_shape_refused(self):
        invalid = [self.event(after='b' * 40), self.event(ref='refs/heads/main'),
                   self.event(repository={'full_name': 'other/repository'}),
                   self.event(repository=None), self.event(repository=[]), [], None]
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(runner.Refused):
                self.check(event)
        with self.assertRaises(runner.Refused):
            self.check(self.event(), expected='b' * 40)

    def test_event_file_cap_and_invalid_json_are_refused_without_probe(self):
        path = self.temp / 'toy-event.json'
        path.write_bytes(b' ' * (256 * 1024 + 1))
        with self.assertRaises(runner.Refused):
            runner.push_event_gate({'GITHUB_EVENT_PATH': str(path)}, SHA)
        path.write_text('{invalid')
        with self.assertRaises(json.JSONDecodeError):
            runner.push_event_gate({'GITHUB_EVENT_PATH': str(path)}, SHA)

    def test_event_path_must_be_absolute_regular_and_not_symlink(self):
        file = self.temp / 'toy-event.json'
        file.write_text(json.dumps(self.event()))
        alias = self.temp / 'alias.json'
        alias.symlink_to(file)
        for path in ('', 'relative.json', str(alias), str(self.temp), str(self.temp / 'missing.json')):
            with self.subTest(path=path), self.assertRaises((runner.Refused, OSError)):
                runner.push_event_gate({'GITHUB_EVENT_PATH': path}, SHA)


class ToolchainAndHardAbortContracts(OfflineCase):
    def fake_toolchain(self, *, xcode='16.4', build='16F6', sdk='18.5', developer=None):
        selected = Path(runner.PINNED_DEVELOPER)
        parent = dict(parent_env(), DEVELOPER_DIR=developer or runner.PINNED_DEVELOPER)

        def fake_resolve(path, strict=False):
            if path == Path('/var/db/xcode_select_link'):
                return Path('/Applications/Other.app/Contents/Developer')
            return path

        def fake_read(path, cap):
            if path == selected.parent / 'version.plist':
                return runner.plistlib.dumps({'CFBundleShortVersionString': xcode, 'ProductBuildVersion': build})
            if path.name == 'SDKSettings.plist':
                return runner.plistlib.dumps({'Version': sdk})
            if path.name in ('xcrun', 'simctl', 'xcodebuild'):
                return b'TOY_INSTALLED_BINARY'
            raise AssertionError('Unexpected toolchain file read: ' + str(path))

        with mock.patch.object(runner.Path, 'resolve', fake_resolve), \
             mock.patch.object(runner.Path, 'is_dir', lambda path: path == selected), \
             mock.patch.object(runner, 'regular_bytes', side_effect=fake_read), \
             mock.patch.object(runner.shutil, 'which', return_value='/usr/bin/xcrun'):
            return runner.toolchain(parent), parent

    def test_exact_installed_pin_is_used_when_global_default_differs(self):
        observed, parent = self.fake_toolchain()
        self.assertFalse(observed['global_default_matches_pin'])
        self.assertEqual(parent['_selected_developer'], runner.PINNED_DEVELOPER)
        self.assertEqual(observed['xcode_build'], '16F6')
        self.assertEqual(observed['sdk'], '18.5')

    def test_wrong_installed_toolchain_or_developer_refused_offline(self):
        for difference in ({'xcode': '16.5'}, {'build': 'wrong'}, {'sdk': '18.4'}, {'developer': '/wrong/developer'}):
            with self.subTest(difference=difference), self.assertRaises(runner.Refused):
                self.fake_toolchain(**difference)

    def test_deadline_factory_passes_fixed_deadlines_and_callback_to_fake_guard(self):
        module = types.ModuleType('deadline_guard')
        constructor = mock.Mock()
        instance = mock.MagicMock()
        entered = mock.Mock()
        instance.__enter__.return_value = entered
        constructor.return_value = instance
        module.DeadlineGuard = constructor
        public = self.temp / 'public'
        with mock.patch.dict(sys.modules, {'deadline_guard': module}), \
             mock.patch.object(runner.sys, 'path', list(sys.path)), \
             mock.patch.object(runner, 'hard_abort') as abort:
            self.assertIs(runner.new_deadline_guard(10.0, public), entered)
            options = constructor.call_args.kwargs
            self.assertEqual(options['hard_deadline'], 790.0)
            self.assertEqual(options['soft_deadline'], 55.0)
            options['hard_abort']()
            abort.assert_called_once_with(public)
        instance.__enter__.assert_called_once_with()

    def test_hard_abort_exits_124_on_success_open_write_and_close_failure(self):
        for failure in (None, 'open', 'write', 'close'):
            with self.subTest(failure=failure):
                opened = mock.Mock(return_value=101, side_effect=OSError('PRIVATE_OPEN') if failure == 'open' else None)
                wrote = mock.Mock(return_value=170, side_effect=OSError('PRIVATE_WRITE') if failure == 'write' else None)
                closed = mock.Mock(side_effect=OSError('PRIVATE_CLOSE') if failure == 'close' else None)
                exited = mock.Mock(side_effect=SystemExit(124))
                with mock.patch.object(runner.os, 'open', opened), mock.patch.object(runner.os, 'write', wrote), \
                     mock.patch.object(runner.os, 'close', closed), mock.patch.object(runner.os, '_exit', exited), \
                     self.assertRaises(SystemExit) as caught:
                    runner.hard_abort(self.temp / 'public')
                self.assertEqual(caught.exception.code, 124)
                exited.assert_called_once_with(124)
                if failure != 'open':
                    closed.assert_called_once_with(101)
                    payload = json.loads(wrote.call_args.args[1])
                    self.assertEqual(payload['cleanup'], 'UNKNOWN')
                    self.assertTrue(payload['native_acquisitions_unknown'])
                    self.assertFalse(payload['product_acceptance'])
                else:
                    wrote.assert_not_called()
                    closed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
