#!/usr/bin/env python3
"""Acquire an exact successful-main Release artifact for the ordinary smoke helper.

No build, Simulator mutation, publication or automatic runtime acceptance occurs here.
"""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import zipfile

PREPARE_SECONDS, STOP_RESERVE = 300, 10
DEVELOPER_DIR = '/Applications/Xcode_26.2.app/Contents/Developer'
SOURCE_PATHS = ('scripts/prepare-cloud-smoke.py', 'scripts/release-smoke.py',
                'scripts/prepare-release.py', 'scripts/qualify-release.py',
                'scripts/recovery_process.py', 'scripts/recovery_core.py',
                'scripts/batch_checkpoint.py', '.github/workflows/release-qualification.yml')
ENV_KEYS = ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_REF', 'GITHUB_RUN_ID',
            'GITHUB_RUN_ATTEMPT', 'GITHUB_EVENT_NAME', 'GITHUB_WORKFLOW',
            'GITHUB_JOB', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')


def require(value, message):
    if not value:
        raise ValueError(message)


def load_preparer(repo):
    spec = importlib.util.spec_from_file_location('cloud_release_preparer', repo / 'scripts/prepare-release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Commands:
    """One 300-second preparation envelope, including closing each owned group."""
    def __init__(self, report, seconds=PREPARE_SECONDS):
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.work_deadline = self.deadline - min(STOP_RESERVE, seconds / 2)
        self.report = report

    def check(self):
        require(not self.report.get('interrupted'), 'Preparation interrupted')
        require(time.monotonic() < self.work_deadline, 'Preparation deadline exceeded')

    @staticmethod
    def absent(process):
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        return False

    def close(self, process):
        cleanup_error = None
        def absent():
            nonlocal cleanup_error
            try:
                return self.absent(process)
            except OSError as error:
                cleanup_error = cleanup_error or error
                return False  # Unknown group state still requires a stop attempt.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if absent():
                break
            if cleanup_error is not None and process.poll() is not None:
                break  # An unverified old PGID may have been reused after exit.
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            except OSError as error:
                cleanup_error = cleanup_error or error
                # Group permission failure must not leave our known child live.
                if process.poll() is None:
                    try:
                        process.send_signal(sig)
                    except ProcessLookupError:
                        pass
                    except OSError as error:
                        cleanup_error = cleanup_error or error
            end = min(self.deadline, time.monotonic() + 3)
            while time.monotonic() < end:
                process.poll()
                if absent() or (cleanup_error is not None and process.returncode is not None):
                    break
                time.sleep(.02)
        process.poll()
        group_absent = absent()
        if cleanup_error is not None:
            raise cleanup_error  # Reaped leader is insufficient proof of group closure.
        require(process.returncode is not None and group_absent,
                'Preparation process group cleanup unverified')

    def command(self, argv, cwd=None, maximum=256 * 1024**2, timeout=180):
        self.check()
        row = {'argv': argv, 'start': time.monotonic() - self.started,
               'closed': False, 'stdout_bytes': 0}
        self.report.setdefault('commands', []).append(row)
        process = None
        data = bytearray()
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            self.check()  # Deferred cancellation cannot interrupt spawn bookkeeping.
            end = min(self.work_deadline, time.monotonic() + timeout)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    self.check()
                    require(time.monotonic() < end, 'Preparation command timed out')
                    for key, _ in selector.select(min(.2, max(0, end - time.monotonic()))):
                        chunk = os.read(key.fd, min(1024**2, maximum - len(data) + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        data.extend(chunk)
                        require(len(data) <= maximum, 'Preparation command output exceeded limit')
            row['exit_code'] = process.wait(timeout=max(.001, end - time.monotonic()))
            self.check()
            require(time.monotonic() < end, 'Preparation command completed after deadline')
            require(row['exit_code'] == 0, 'Preparation command failed')
            require(self.absent(process), 'Preparation command left a running process group')
            return bytes(data)
        except BaseException as error:
            row['failure_type'] = type(error).__name__
            raise
        finally:
            try:
                if process is not None:
                    self.close(process)
                    row['closed'] = True
            except BaseException as error:
                row['cleanup_error_type'] = type(error).__name__
                raise
            finally:
                if process is not None:
                    process.stdout.close()
                    row['exit_code'] = process.returncode
                row.update(stdout_bytes=len(data), finish=time.monotonic() - self.started)


def origin(preparer, api, commit, run_id, artifact_id):
    prefix = 'repos/' + preparer.REPOSITORY + '/actions/'
    run = api.api(prefix + 'runs/' + str(run_id))
    require(run.get('event') == 'push', 'Only a successful main push is eligible')
    jobs = api.pages(prefix + 'runs/%d/attempts/%s/jobs' % (run_id, run.get('run_attempt')), 'jobs')
    identity = preparer.validate_run(run, jobs, commit, run_id)
    artifacts = api.pages(prefix + 'runs/%d/artifacts' % run_id, 'artifacts')
    artifact = preparer.select_artifact(artifacts, run, commit)
    require(type(artifact.get('id')) is int and artifact['id'] == artifact_id,
            'Requested artifact ID does not match exact successful-main artifact')
    return run, identity, artifact, jobs


def extract_app(preparer, data, destination, check):
    files = preparer.archive_members(data, strict_modes=True, allowed_roots={'Tripfolio.app', '__MACOSX'})
    directories = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            check()
            name = item.filename.rstrip('/')
            if name != 'Tripfolio.app' and not name.startswith('Tripfolio.app/'):
                continue
            path = destination / name
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                directories.append((path, stat.S_IMODE(item.external_attr >> 16)))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                body, mode = files[name]
                with path.open('xb') as stream:
                    stream.write(body)
                path.chmod(mode)
    for path, mode in sorted(directories, key=lambda value: len(value[0].parts), reverse=True):
        check()
        path.chmod(mode)


def prepare(args, report):
    repo = args.repo.resolve(strict=True)
    preparer = load_preparer(repo)
    commands = Commands(report)
    preparer.command = commands.command  # Preserve the existing API/ZIP validators.
    api = preparer.GitHub()
    env = os.environ
    report['stage'] = 'diagnostic-source-and-context'
    report['runner'] = {key: env[key] for key in ENV_KEYS if key in env}
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == preparer.REPOSITORY
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_REF') == 'refs/heads/diagnostic/release-smoke', 'Unexpected diagnostic context')
    require(env.get('GITHUB_WORKFLOW') == 'Release ZIP ordinary smoke' and env.get('GITHUB_JOB') == 'smoke'
            and re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))
            and all(re.fullmatch(r'[1-9][0-9]*', env.get(key, '')) for key in
                    ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')), 'Incomplete diagnostic run identity')
    require(env.get('RUNNER_OS') == 'macOS' and env.get('RUNNER_ARCH') == 'X64'
            and env.get('ImageOS') == 'macos15' and env.get('DEVELOPER_DIR') == DEVELOPER_DIR,
            'Unexpected hosted toolchain profile')
    require(re.fullmatch(r'[0-9a-f]{40}', args.commit) and args.run_id > 0 and args.artifact_id > 0,
            'Exact candidate SHA, run ID and artifact ID are required')
    git = lambda *argv: commands.command(['git', *argv], cwd=repo, maximum=preparer.MAX_JSON, timeout=30)
    runner_head = git('rev-parse', 'HEAD').decode().strip()
    require(runner_head == env.get('GITHUB_SHA'), 'Diagnostic checkout SHA mismatch')
    require(not git('status', '--porcelain', '--untracked-files=no').strip(), 'Diagnostic tracked source is dirty')
    report['runner_source'] = {'commit': runner_head, 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
                               'files': {path: preparer.digest(preparer.read_regular(repo / path)) for path in SOURCE_PATHS}}
    require(git('cat-file', '-t', args.commit).strip() == b'commit', 'Candidate is not a commit')
    report['stage'] = 'main-history'
    main = api.api('repos/' + preparer.REPOSITORY + '/git/ref/heads/main')['object']['sha']
    require(preparer.valid_hash(main, 40), 'Invalid current main SHA')
    git('merge-base', '--is-ancestor', args.commit, main)
    tree = git('rev-parse', args.commit + '^{tree}').decode().strip()
    parents = git('show', '-s', '--format=%P', args.commit).decode().strip().split()
    versions = re.findall(r'^    MARKETING_VERSION: "([0-9]+\.[0-9]+\.[0-9]+)"$',
                          git('show', args.commit + ':project.yml').decode(), re.MULTILINE)
    require(len(versions) == 1, 'Ambiguous candidate marketing version')
    report['source'] = {'commit': args.commit, 'tree': tree, 'parents': parents, 'observed_main': main,
                        'version': versions[0]}
    report['stage'] = 'successful-main-ci'
    run, identity, artifact, jobs = origin(preparer, api, args.commit, args.run_id, args.artifact_id)
    report.update(ci=identity, jobs=[{key: job.get(key) for key in
                  ('id', 'name', 'run_id', 'run_attempt', 'head_sha', 'status', 'conclusion')} for job in jobs],
                  artifact={key: artifact[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run')})
    report['stage'] = 'download-and-payload'
    data = api.binary('repos/' + preparer.REPOSITORY + '/actions/artifacts/%d/zip' % args.artifact_id,
                      accept='application/vnd.github+json')
    require(len(data) == artifact['size_in_bytes'] and 'sha256:' + preparer.digest(data) == artifact['digest'],
            'Downloaded artifact size or digest mismatch')
    files = {name: value[0] for name, value in preparer.archive_members(data).items()}
    provenance = preparer.validate_payload(files, args.commit, tree, run, versions[0])
    require(provenance['source'].get('parents') == parents, 'Producer parent identity mismatch')
    inputs = args.out / 'inputs'
    inputs.mkdir(mode=0o700)
    for name, body in files.items():
        commands.check()
        (inputs / name).write_bytes(body)  # Original ZIP, provenance and checksum bytes remain unchanged.
    extract_app(preparer, files['TripDocket-Simulator.zip'], inputs, commands.check)
    report['input_files'] = {name: {'bytes': len(body), 'sha256': preparer.digest(body)} for name, body in files.items()}
    report['stage'] = 'host-profile'
    expected = {'architecture': (['uname', '-m'], 'x86_64'),
                'xcode': (['xcodebuild', '-version'], 'Xcode 26.2\nBuild version 17C52'),
                'sdk': (['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], '26.2')}
    report['host'] = {}
    for key, (argv, value) in expected.items():
        actual = commands.command(argv, maximum=preparer.MAX_JSON, timeout=30).decode().strip()
        require(actual == value, 'Unexpected hosted ' + key)
        report['host'][key] = actual
    os_version = commands.command(['sw_vers', '-productVersion'], maximum=1024, timeout=30).decode().strip()
    require(re.fullmatch(r'15\.[0-9]+(?:\.[0-9]+)?', os_version), 'Unexpected macOS version')
    report['host'].update(macos=os_version, developer_dir=DEVELOPER_DIR,
                          required_runtime='com.apple.CoreSimulator.SimRuntime.iOS-26-2', required_runtime_build='23C54')
    report['stage'] = 'final-ci-identity'
    latest = api.api('repos/' + preparer.REPOSITORY + '/actions/runs/' + str(args.run_id))
    require(preparer.validate_run(latest, jobs, args.commit, args.run_id) == identity,
            'CI identity changed during acquisition')
    commands.check()
    report.update(status='prepared_pending_ordinary_smoke', public_receipt_created=False,
                  elapsed_seconds=time.monotonic() - commands.started)
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--artifact-id', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    args.out = args.out.absolute()
    require(args.out.parent.resolve(strict=True) == args.out.parent and not args.out.exists()
            and not args.out.is_relative_to(repo), 'Evidence output must be new, real and outside checkout')
    args.out.mkdir(mode=0o700)
    report = {'schema_version': 1, 'status': 'failed', 'native_launches': 0,
              'prepare_seconds': PREPARE_SECONDS, 'stop_reserve': STOP_RESERVE, 'interrupted': False}
    code, tree = 1, None
    def interrupt(_signal, _frame):
        report['interrupted'] = True
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        tree = prepare(args, report)
        require(not report['interrupted'], 'Preparation interrupted')
        code = 0
    except Exception as error:
        # API bodies, stderr and presigned redirects never enter exception logs.
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
    finally:
        (args.out / 'acquisition.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    if code == 0:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('tree=' + tree + '\n')
    print(json.dumps({'status': report['status'], 'public_receipt_created': False}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
