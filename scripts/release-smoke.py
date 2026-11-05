#!/usr/bin/env python3
"""One ordinary launch of an already-built Release Simulator ZIP; no automatic acceptance.

Default invocation and --self-check never call native tools. --run is explicit.
Raw output is diagnostic evidence; a reviewer creates the release receipt later.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import stat
import sys
import time
import uuid
import zipfile

DEFAULT_REPO = Path(__file__).resolve().parent.parent
APP_ID = 'com.4alvit.tripfolio'
WORK_SECONDS, CLEANUP_SECONDS = 900, 180
SAMPLES = (2, 10, 30)
MIB = 1024 * 1024


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_support(repo):
    qualification = load(repo / 'scripts/qualify-release.py', 'ordinary_smoke_qualification')
    preparer = load(repo / 'scripts/prepare-release.py', 'ordinary_smoke_preparer')
    return qualification, preparer


def code_identity(repo):
    paths = [Path(__file__).resolve(), repo / 'scripts/qualify-release.py',
             repo / 'scripts/recovery_process.py', repo / 'scripts/prepare-release.py']
    return {str(path): sha(path.read_bytes()) for path in paths}


def environment():
    # No SIMCTL_CHILD, DYLD, XCTest or test-driver variables reach native tools.
    allowed = {'HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'SHELL', 'DEVELOPER_DIR',
               'LANG', 'LC_ALL', '__CF_USER_TEXT_ENCODING'}
    return {key: value for key, value in os.environ.items() if key in allowed}


def select_runtime(qualification, data, sdk, architecture, identifier=None, build=None):
    require(bool(identifier) == bool(build), 'Explicit runtime requires identifier and build')
    candidates, version = data, sdk
    if identifier:
        selected = [item for item in data.get('runtimes', [])
                    if item.get('identifier') == identifier]
        require(len(selected) == 1 and selected[0].get('buildversion') == build
                and selected[0].get('platform') == 'iOS',
                'Explicit runtime identity unavailable')
        candidates, version = {'runtimes': selected}, selected[0]['version']
    runtime, device_type = qualification.choose_runtime(candidates, version, architecture)
    selected = [item for item in candidates['runtimes'] if item.get('identifier') == runtime]
    require(len(selected) == 1, 'Ambiguous selected runtime')
    return runtime, device_type, selected[0]


def make_commands_class(processes):
    class Commands(processes.Smoke):
        def __init__(self, owner):
            self.owner = owner
            self.out = owner.out / 'commands'
            self.out.mkdir()
            self.ops = processes.RealOps(environment(), str(owner.repo))
            self.t0 = owner.started
            self.limit = owner.work_deadline
            self.write_deadline = owner.cleanup_deadline + 10
            self.active, self.absent_groups = {}, set()
            self.unknown_spawn, self.log_total = False, 0
            self.report = {'commands': [], 'errors': []}
            owner.report['native_commands'] = self.report

        def checkpoint(self, **_):
            self.owner.check()
            require(time.monotonic() < self.limit, 'Command phase expired')
    return Commands


class OrdinarySmoke:
    def __init__(self, args):
        self.args = args
        self.repo = args.repo.resolve(strict=True)
        self.qualification, self.preparer = load_support(self.repo)
        require(re.fullmatch(r'[0-9a-f]{40}', args.commit or '') and
                re.fullmatch(r'[0-9a-f]{40}', args.tree or ''), 'Exact commit and tree required')
        require(bool(args.runtime) == bool(args.runtime_build), 'Explicit runtime requires identifier and build')
        self.zip = args.zip.absolute()
        self.app = args.app_dir.absolute()
        require(self.app.name == 'Tripfolio.app' and self.app.resolve(strict=True) == self.app,
                'Expected a non-symlink extracted Tripfolio.app')
        require(args.out.is_absolute() and args.out.parent.resolve(strict=True) == args.out.parent,
                'Output must have a real absolute parent without symbolic links')
        self.out = args.out
        require(not self.out.is_relative_to(self.repo) and not os.path.lexists(self.out),
                'Output must be new and outside the source checkout')
        self.out.mkdir(mode=0o700)
        self.started = time.monotonic()
        self.work_deadline = self.started + WORK_SECONDS
        self.cleanup_deadline = self.work_deadline + CLEANUP_SECONDS
        self.cleaning = self.interrupted = False
        self.owned = self.intent = self.baseline = None
        self.launch_count = 0
        self.before_code = code_identity(self.repo)
        self.report = {
            'schema_version': 1, 'status': 'running', 'scope': 'ordinary Release Simulator launch capture',
            'started_at_utc': datetime.now(timezone.utc).isoformat(),
            'source': {'commit': args.commit, 'tree': args.tree},
            'inputs': {'app_dir': str(self.app), 'zip': str(self.zip)},
            'runner_identity': self.before_code,
            'limits': {'work_seconds': WORK_SECONDS, 'cleanup_seconds': CLEANUP_SECONDS,
                       'samples_seconds': list(SAMPLES), 'timing_semantics': 'targets; actual times retained without a timing SLO'},
            'screenshots': [], 'errors': [], 'cleanup_verified': False,
            'public_receipt_created': False, 'visual_review': 'pending',
            'warning_observation': {
                'collected': ['bounded command stdout/stderr', 'three launch screenshots'],
                'application_console_collected': False, 'system_console_collected': False,
                'review_status': 'pending',
            },
        }
        self.commands = make_commands_class(self.qualification.processes)(self)
        self.save()

    def check(self):
        require(self.cleaning or not self.interrupted, 'Smoke interrupted')
        require(time.monotonic() < (self.cleanup_deadline if self.cleaning else self.work_deadline),
                'Smoke phase deadline expired')

    def save(self):
        require(time.monotonic() < self.cleanup_deadline + 10, 'Receipt deadline expired')
        self.report['elapsed_seconds'] = time.monotonic() - self.started
        temporary = self.out / 'receipt.tmp'
        temporary.write_text(json.dumps(self.report, indent=2) + '\n')
        temporary.replace(self.out / 'receipt.json')

    def write_record(self, name, value):
        self.check()
        encoded = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
        require(len(encoded) <= 16 * MIB, 'Record exceeds size limit')
        (self.out / name).write_bytes(encoded)
        return {'file': name, 'bytes': len(encoded), 'sha256': sha(encoded)}

    def command(self, label, argv, seconds=30):
        return self.commands.command(label, [str(arg) for arg in argv], seconds + 8)

    def inventory(self, label):
        data = json.loads(self.command(label, ['xcrun', 'simctl', 'list', 'devices', '--json'],
                                       30 if self.cleaning else 120))
        return self.qualification.device_map(data)

    def manifest(self, root):
        value = self.qualification.tree_manifest(root, self.check)
        require(all(row['kind'] in {'file', 'directory'} for row in value.values()),
                'Product contains links or special entries')
        return value

    def input_verification(self):
        self.check()
        zip_data = self.preparer.read_regular(self.zip, self.preparer.MAX_DOWNLOAD)
        files = self.preparer.archive_members(zip_data, strict_modes=True,
                                             allowed_roots={'Tripfolio.app', '__MACOSX'})
        expected, modes = {}, {}
        with zipfile.ZipFile(io.BytesIO(zip_data)) as archive:
            for entry in archive.infolist():
                self.check()
                name = entry.filename.rstrip('/')
                if name == 'Tripfolio.app':
                    relative = '.'
                elif name.startswith('Tripfolio.app/'):
                    relative = './' + name[len('Tripfolio.app/'):]
                else:
                    continue
                require(relative not in expected, 'Duplicate app ZIP member')
                if entry.is_dir():
                    expected[relative] = {'kind': 'directory'}
                else:
                    data, mode = files[name]
                    expected[relative] = {'kind': 'file', 'bytes': len(data), 'sha256': sha(data)}
                modes[relative] = stat.S_IMODE(entry.external_attr >> 16)
        require(expected.get('.') == {'kind': 'directory'}, 'ZIP lacks the app root directory')
        actual = self.manifest(self.app)
        require(actual == expected, 'Extracted app bytes differ from the exact ZIP')
        for relative, mode in modes.items():
            path = self.app if relative == '.' else self.app / relative[2:]
            require(stat.S_IMODE(path.lstat().st_mode) == mode, 'Extracted app mode differs from ZIP')
        info = plistlib.loads(self.qualification.bounded_read(self.app, 'Info.plist', MIB, self.check))
        require(info.get('CFBundleIdentifier') == APP_ID and info.get('CFBundleExecutable') == 'Tripfolio',
                'Unexpected app identity')
        require(info.get('DTPlatformName') == 'iphonesimulator' and info.get('CFBundleSupportedPlatforms') == ['iPhoneSimulator'],
                'App is not a Simulator build')
        binary = self.qualification.bounded_read(self.app, 'Tripfolio', 128 * MIB, self.check)
        require(b'--ui-testing-' not in binary and b'--demo' not in binary, 'Development launch markers in executable')
        require(modes['./Tripfolio'] & 0o111, 'App executable has no execute permission')
        provenance_data = self.preparer.read_regular(self.zip.parent / 'provenance.json')
        provenance = self.preparer.decode_json(provenance_data)
        require(provenance.get('source', {}).get('commit') == self.args.commit and
                provenance['source'].get('tree') == self.args.tree and
                provenance['source'].get('clean_checkout') is True, 'ZIP provenance source mismatch')
        require(provenance.get('artifact', {}).get('sha256') == sha(zip_data) and
                provenance['artifact'].get('executable_sha256') == sha(binary), 'ZIP provenance artifact mismatch')
        build = provenance.get('build', {})
        require(build.get('configuration') == 'Release' and build.get('sdk') == 'iphonesimulator'
                and build.get('code_signing_allowed') is False and
                build.get('successful_verify_receipt_commit') == self.args.commit, 'ZIP provenance is not the expected Release build')
        self.report['producer_provenance_sha256'] = sha(provenance_data)
        self.expected_manifest, self.zip_sha = expected, sha(zip_data)
        self.report['release_artifact_sha256'] = self.zip_sha
        self.report['zip_bytes'] = len(zip_data)
        self.report['bundle'] = {key: info.get(key) for key in ('CFBundleIdentifier', 'CFBundleShortVersionString',
                                   'CFBundleVersion', 'MinimumOSVersion', 'DTXcode', 'DTXcodeBuild', 'DTSDKName', 'DTSDKBuild')}
        self.report['zip_app_manifest'] = self.write_record('zip-app-manifest.json', expected)
        require(self.command('candidate-type', ['git', 'cat-file', '-t', self.args.commit]).strip() == 'commit',
                'Candidate object is not a commit')
        require(self.command('candidate-tree', ['git', 'rev-parse', self.args.commit + '^{tree}']).strip() == self.args.tree,
                'Candidate commit/tree mismatch')
        self.save()

    def verify_owned(self, devices):
        require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline,
                'No exclusive device ownership')
        require(self.owned in devices and all(devices[self.owned][key] == self.intent[key]
                for key in ('runtime', 'name', 'type')), 'Owned device identity changed')

    def prepare_device(self):
        toolchain = {}
        for name, argv in (('xcode', ['xcodebuild', '-version']),
                           ('developer', ['xcode-select', '-p']),
                           ('sdk', ['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']),
                           ('architecture', ['uname', '-m'])):
            toolchain[name] = self.command(name, argv).strip()
        self.report['toolchain'] = toolchain
        original = self.commands.limit
        self.commands.limit = min(original, time.monotonic() + 300)
        try:
            # Complete host-managed runtime caches before first boot. This shares
            # the original discovery clock; 292 work seconds plus 8 for stopping.
            require('runtime_cache_readiness' not in self.report, 'Cache readiness may run only once')
            self.report['runtime_cache_readiness'] = 'attempted'
            self.command('runtime-cache-ready', ['xcrun', 'simctl', 'runtime',
                         'dyld_shared_cache', 'update', '--all'], 292)
            self.report['runtime_cache_readiness'] = 'completed'
            runtimes = json.loads(self.command('runtimes', ['xcrun', 'simctl', 'list', 'runtimes', '--json'], 150))
            runtime, device_type, selected = select_runtime(self.qualification, runtimes,
                toolchain['sdk'], toolchain['architecture'], self.args.runtime, self.args.runtime_build)
            self.report['runtime'] = {key: selected.get(key) for key in
                                      ('identifier', 'version', 'buildversion', 'supportedArchitectures')}
            self.report['runtime_selection'] = {'explicit_override': bool(self.args.runtime),
                'sdk_version': toolchain['sdk'], 'sdk_version_equal': selected.get('version') == toolchain['sdk']}
            self.baseline = self.inventory('baseline')
            self.intent = {'name': 'TripDocket-Ordinary-Release-' + str(uuid.uuid4()),
                           'runtime': runtime, 'type': device_type}
            require(all(item['name'] != self.intent['name'] for item in self.baseline.values()), 'Device name collision')
            self.report.update(baseline=self.baseline, create_intent=self.intent)
            self.save()
            created = self.command('create', ['xcrun', 'simctl', 'create', self.intent['name'], device_type, runtime], 60).strip()
            candidate = str(uuid.UUID(created)).upper()
            require(candidate not in self.baseline, 'Create returned an existing device')
            self.owned = candidate
            self.report['owned_uuid'] = self.owned
            self.save()
            self.verify_owned(self.inventory('created'))
        finally:
            self.commands.limit = original
        self.command('boot', ['xcrun', 'simctl', 'boot', self.owned], 60)
        self.command('boot-ready', ['xcrun', 'simctl', 'bootstatus', self.owned, '-b'], 180)
        self.command('install', ['xcrun', 'simctl', 'install', self.owned, self.app], 60)
        self.installed = self.installed_path()
        self.verify_installed('installed-before')
        self.save()

    def installed_path(self):
        value = self.command('installed-container', ['xcrun', 'simctl', 'get_app_container', self.owned, APP_ID, 'app'], 60).strip()
        path = Path(value)
        prefix = Path.home() / 'Library/Developer/CoreSimulator/Devices' / self.owned / 'data/Containers/Bundle/Application'
        require(path.is_absolute() and path.resolve(strict=True) == path and path.is_dir(), 'Invalid installed container')
        relative = path.relative_to(prefix)
        require(len(relative.parts) == 2 and str(uuid.UUID(relative.parts[0])).upper() == relative.parts[0]
                and relative.parts[1] == 'Tripfolio.app', 'Unexpected installed container identity')
        return path

    def verify_installed(self, name):
        actual = self.manifest(self.installed)
        require(actual == self.expected_manifest, 'Installed app bytes differ from ZIP')
        require((self.installed / 'Tripfolio').stat().st_mode & 0o111, 'Installed executable permission missing')
        self.report[name] = self.write_record(name + '-manifest.json', actual)

    def capture(self):
        require(self.launch_count == 0, 'Ordinary launch may run only once')
        self.launch_count += 1
        # One cold ordinary launch gets a finite 120-second command window.
        # This consumes the existing work envelope; there is no retry or reset.
        output = self.command('ordinary-launch', ['xcrun', 'simctl', 'launch', self.owned, APP_ID], 120).strip()
        match = re.fullmatch(re.escape(APP_ID) + r': ([1-9][0-9]*)', output)
        require(match is not None, 'Unexpected launch result')
        launched = time.monotonic()
        self.report['launch'] = {'count': self.launch_count, 'application_pid': int(match.group(1)),
                                 'returned_seconds': launched - self.started, 'arguments': [],
                                 'sample_origin': 'successful simctl launch command return',
                                 'authentication_inputs': 0, 'test_or_demo_flags': False}
        self.save()
        for second in SAMPLES:
            while time.monotonic() < launched + second:
                self.check()
                time.sleep(min(0.1, max(0, launched + second - time.monotonic())))
            capture_start = time.monotonic() - launched
            capture_start_utc = datetime.now(timezone.utc).isoformat()
            path = self.out / ('launch-%02ds.png' % second)
            require(not os.path.lexists(path), 'Screenshot destination already exists')
            self.command('screenshot-%02d' % second,
                         ['xcrun', 'simctl', 'io', self.owned, 'screenshot', '--type=png', path], 30)
            capture_end = time.monotonic() - launched
            capture_end_utc = datetime.now(timezone.utc).isoformat()
            image = self.preparer.read_regular(path, 32 * MIB)
            require(image.startswith(b'\x89PNG\r\n\x1a\n'), 'Screenshot is not a PNG')
            self.report['screenshots'].append({'file': path.name, 'requested_seconds': second,
                'started_seconds_after_launch_return': capture_start, 'finished_seconds_after_launch_return': capture_end,
                'started_at_utc': capture_start_utc, 'finished_at_utc': capture_end_utc,
                'start_lateness_seconds': max(0, capture_start - second),
                'bytes': len(image), 'sha256': sha(image)})
            self.save()
        self.verify_installed('installed-after')
        require(self.manifest(self.app) == self.expected_manifest, 'Input app changed during smoke')
        require(sha(self.preparer.read_regular(self.zip, self.preparer.MAX_DOWNLOAD)) == self.zip_sha,
                'Input ZIP changed during smoke')
        require(sha(self.preparer.read_regular(self.zip.parent / 'provenance.json')) ==
                self.report['producer_provenance_sha256'], 'Input provenance changed during smoke')
        require(code_identity(self.repo) == self.before_code, 'Runner/helper code changed during smoke')
        self.report['capture_completed'] = True

    def cleanup(self):
        self.cleaning = True
        self.commands.limit = self.cleanup_deadline
        require(not self.commands.active and not self.commands.unknown_spawn,
                'Unresolved owned process; further native cleanup withheld')
        if self.baseline is None:
            self.report['cleanup_verified'] = True  # No create was attempted.
            return
        current = self.inventory('before-cleanup')
        if self.owned is None and self.intent:
            matches = [identifier for identifier, item in current.items() if identifier not in self.baseline
                       and all(item[key] == self.intent[key] for key in ('name', 'runtime', 'type'))]
            require(len(matches) <= 1, 'Ambiguous interrupted device acquisition')
            if matches:
                self.owned = matches[0]
                self.report.update(owned_uuid=self.owned, recovered_create_ownership=True)
        if self.owned:
            self.verify_owned(current)
            if current[self.owned]['state'] != 'Shutdown':
                self.command('shutdown', ['xcrun', 'simctl', 'shutdown', self.owned], 60)
            self.command('delete', ['xcrun', 'simctl', 'delete', self.owned], 60)
        final = self.inventory('after-cleanup')
        self.report['final_inventory'] = final
        require(final == self.baseline, 'Baseline/final device inventory differs')
        self.report['cleanup_verified'] = True

    def execute(self):
        try:
            self.input_verification()
            self.prepare_device()
            self.capture()
        except BaseException as error:
            self.report['errors'].append(repr(error))
        finally:
            try:
                self.cleanup()
            except BaseException as error:
                self.report['errors'].append('Cleanup: ' + repr(error))
            completed = self.report.get('capture_completed') and self.report['cleanup_verified'] and not self.report['errors']
            self.report['status'] = 'captured_pending_review' if completed else 'failed'
            self.save()
        print(json.dumps({'status': self.report['status'], 'output': str(self.out),
                          'visual_review': 'pending', 'public_receipt_created': False}))
        return 0 if self.report['status'] == 'captured_pending_review' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=DEFAULT_REPO)
    parser.add_argument('--app-dir', type=Path)
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--commit')
    parser.add_argument('--tree')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--runtime', help='Explicit available iOS runtime identifier; no fallback')
    parser.add_argument('--runtime-build', help='Exact runtime build required with --runtime')
    parser.add_argument('--run', action='store_true', help='Explicitly enable the one native smoke attempt')
    parser.add_argument('--self-check', action='store_true', help='Import helpers only; no native tools')
    args = parser.parse_args()
    if args.self_check:
        qualification, preparer = load_support(args.repo.resolve(strict=True))
        require(callable(qualification.choose_runtime) and callable(qualification.tree_manifest)
                and callable(preparer.archive_members), 'Helper interface unavailable')
        print(json.dumps({'status': 'IMPORTS_OK', 'native_calls': 0, 'runner_identity': code_identity(args.repo)}))
        return 0
    if not args.run:
        print(json.dumps({'status': 'NOT_RUN', 'native_calls': 0}))
        return 0
    if not all((args.app_dir, args.zip, args.commit, args.tree, args.out)):
        parser.error('--run requires --app-dir --zip --commit --tree --out')
    run = OrdinarySmoke(args)
    def interrupt(_signal, _frame):
        run.interrupted = True  # Acquisition bookkeeping completes before the next checkpoint.
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    return run.execute()


if __name__ == '__main__':
    sys.exit(main())
