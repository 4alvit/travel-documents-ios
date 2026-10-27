#!/usr/bin/env python3
"""Sealed manual hosted diagnostic. Default invocation never runs probes."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import plistlib
import re
import resource
import shutil
import stat
import sys
import time

ROOT = Path(__file__).resolve().parent
BOOT_KEYS = ('XPC_SERVICE_NAME', 'XPC_FLAGS', '__CF_USER_TEXT_ENCODING')
FILE_CAP, TOTAL_SECONDS = 8 * 1024**2, 780
HISTORICAL = dict(image_version='20260907.0337.1', xcode='16.4',
                  xcode_build='16F6', sdk='18.5', python='3.14.7')
PINNED_DEVELOPER = '/Applications/Xcode_16.4.app/Contents/Developer'
DIAGNOSTIC_REF = 'refs/heads/diagnostics/ios-discovery-20261027-a1'


class Refused(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular_bytes(path, cap):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= cap, 'FILE_SHAPE')
    with path.open('rb') as f:
        raw = f.read(cap + 1)
    require(len(raw) <= cap, 'FILE_CAP')
    return raw


def write_json(path, value, cap=256 * 1024):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= cap and not path.is_symlink(), 'REPORT_SHAPE')
    temporary = path.with_suffix('.tmp')
    with temporary.open('xb') as f:
        os.chmod(temporary, 0o600)
        f.write(raw)
    temporary.replace(path)


def verify_seal(root, expected):
    require(re.fullmatch(r'[0-9a-f]{64}', expected or ''), 'SEAL_DIGEST_REQUIRED')
    raw = regular_bytes(root / 'seal.json', 65536)
    require(digest(raw) == expected, 'SEAL_MISMATCH')
    seal = json.loads(raw)
    require(set(seal) == {'files'} and 1 <= len(seal['files']) <= 32, 'SEAL_SCHEMA')
    for name, sha in seal['files'].items():
        p = Path(name)
        require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == name, 'SEAL_PATH')
        require((root / p).resolve().is_relative_to(root.resolve()), 'SEAL_ESCAPE')
        require(digest(regular_bytes(root / p, 1024**2)) == sha, 'SOURCE_MISMATCH')
    require({'runner.py', 'adapters.py', 'deadline_guard.py', 'vendor-manifest.json', 'plan.json'} <= set(seal['files']), 'SEAL_INCOMPLETE')
    manifest = json.loads(regular_bytes(root / 'vendor-manifest.json', 65536))
    for row in manifest['files']:
        require(seal['files'].get(row['path']) == row['sha256'], 'VENDOR_NOT_SEALED')
    return expected


def host_gate(env, expected_sha):
    constants = dict(GITHUB_ACTIONS='true', CI='true', RUNNER_ENVIRONMENT='github-hosted',
                     RUNNER_OS='macOS', RUNNER_ARCH='ARM64', GITHUB_EVENT_NAME='push',
                     GITHUB_RUN_ATTEMPT='1', GITHUB_REPOSITORY='4alvit/travel-documents-ios',
                     GITHUB_JOB='diagnostic', GITHUB_SERVER_URL='https://github.com')
    require(all(env.get(k) == v for k, v in constants.items()), 'HOST_CONTEXT')
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'HOST_MACHINE')
    require(re.fullmatch(r'[0-9a-f]{40}', expected_sha or '') and env.get('GITHUB_SHA') == expected_sha
            and env.get('GITHUB_WORKFLOW_SHA') == expected_sha, 'SOURCE_IDENTITY')
    ref = env.get('GITHUB_REF', '')
    require(ref == DIAGNOSTIC_REF, 'REF')
    require(env.get('GITHUB_WORKFLOW_REF') ==
            '4alvit/travel-documents-ios/.github/workflows/ios-discovery-diagnostic.yml@' + ref,
            'WORKFLOW_IDENTITY')
    require(re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')), 'RUN_ID')
    require(env.get('ImageOS') == 'macos15', 'IMAGE_OS')
    require(re.fullmatch(r'[0-9]{8}\.[0-9]{1,8}\.[0-9]{1,4}', env.get('ImageVersion', '')), 'IMAGE_VERSION_SHAPE')
    require(re.fullmatch(r'3\.(?:12|13|14)\.[0-9]{1,4}', platform.python_version()), 'PYTHON_UNSUPPORTED')
    require(env.get('DEVELOPER_DIR') == PINNED_DEVELOPER, 'PINNED_DEVELOPER_REQUIRED')
    require(not any(k.startswith(('SIMCTL_CHILD_', 'DYLD_', 'XCTest', 'TEST_RUNNER_')) for k in env), 'INJECTED_ENV')
    workspace = Path(env.get('GITHUB_WORKSPACE', ''))
    require(workspace.is_absolute() and ROOT == workspace / 'diagnostics/ios-discovery', 'PACKAGE_LOCATION')


def push_event_gate(env, expected_sha):
    path = Path(env.get('GITHUB_EVENT_PATH', ''))
    require(path.is_absolute(), 'EVENT_PATH')
    event = json.loads(regular_bytes(path, 256 * 1024))
    require(type(event) is dict, 'EVENT_SCHEMA')
    require(event.get('created') is True and event.get('deleted') is False
            and event.get('forced') is False, 'NOT_FIRST_BRANCH_PUSH')
    require(event.get('before') == '0' * 40 and event.get('after') == expected_sha
            and event.get('ref') == DIAGNOSTIC_REF, 'EVENT_COMMIT')
    repository = event.get('repository')
    require(type(repository) is dict and repository.get('full_name') == '4alvit/travel-documents-ios',
            'EVENT_REPOSITORY')


def env_for(boundary, parent):
    if boundary == 'room':
        out = {k: parent[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'DEVELOPER_DIR') if k in parent}
        if '_selected_developer' in parent:
            out['DEVELOPER_DIR'] = parent['_selected_developer']
        return out
    if boundary == 'redact':
        out = {k: parent[k] for k in ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'DEVELOPER_DIR') if k in parent}
        out['LANG'] = 'en_US.UTF-8'
        return out
    require(boundary == 'trip', 'BOUNDARY')
    out = {k: parent[k] for k in ('HOME', 'USER', 'TMPDIR', 'DEVELOPER_DIR') if k in parent}
    if '_selected_developer' in parent:
        out['DEVELOPER_DIR'] = parent['_selected_developer']
    out.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', GIT_OPTIONAL_LOCKS='0')
    return out


def bundle_variant(original, frozen):
    patterns = {'XPC_SERVICE_NAME': r'[A-Za-z0-9_.:/+-]{1,128}',
                'XPC_FLAGS': r'(?:0x[0-9A-Fa-f]{1,16}|[0-9]{1,20})',
                '__CF_USER_TEXT_ENCODING': r'0x[0-9A-Fa-f]{1,16}:0x[0-9A-Fa-f]{1,16}:0x[0-9A-Fa-f]{1,16}'}
    if any(not re.fullmatch(patterns[k], v) for k, v in frozen.items()):
        return None, 'INVALID_BUNDLE'
    changed = {k: v for k, v in frozen.items() if original.get(k) != v}
    if not changed:
        return None, 'NO_ENV_DELTA'
    return dict(original, **changed), None


def env_evidence(env):
    return {k: {'bytes': len(v.encode()), 'sha256': digest(v.encode())} for k, v in sorted(env.items())}


def limits():
    names = ('RLIMIT_AS', 'RLIMIT_CORE', 'RLIMIT_CPU', 'RLIMIT_DATA', 'RLIMIT_FSIZE',
             'RLIMIT_NOFILE', 'RLIMIT_NPROC', 'RLIMIT_RSS', 'RLIMIT_STACK')
    return {name: list(resource.getrlimit(getattr(resource, name))) for name in names if hasattr(resource, name)}


def public_errno(value):
    return value if type(value) is int and -(2**31) <= value < 2**31 else None


def validated_observation(value):
    fields = {'outcome', 'cleanup_confirmed', 'identity_uncertain', 'elapsed_seconds',
              'returncode', 'stdout_bytes', 'stderr_bytes', 'stdout_sha256',
              'stderr_sha256', 'spawn_observation', 'exception_type', 'errno',
              'streams_merged', 'output_censored'}
    require(type(value) is dict and set(value) == fields, 'OBSERVATION_SCHEMA')
    require(value['outcome'] in ('success', 'timeout', 'failure'), 'OBSERVATION_OUTCOME')
    for key in ('cleanup_confirmed', 'identity_uncertain', 'streams_merged', 'output_censored'):
        require(type(value[key]) is bool, 'OBSERVATION_BOOL')
    require(type(value['elapsed_seconds']) in (int, float)
            and math.isfinite(value['elapsed_seconds']) and value['elapsed_seconds'] >= 0, 'OBSERVATION_TIME')
    for key in ('returncode', 'errno'):
        require(value[key] is None or (type(value[key]) is int and public_errno(value[key]) == value[key]), 'OBSERVATION_INT')
    for channel in ('stdout', 'stderr'):
        require(type(value[channel + '_bytes']) is int and 0 <= value[channel + '_bytes'] <= FILE_CAP, 'OBSERVATION_BYTES')
        require(isinstance(value[channel + '_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', value[channel + '_sha256']), 'OBSERVATION_DIGEST')
    name = value['exception_type']
    require(name is None or (isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name)), 'OBSERVATION_ERROR')
    identity = value['spawn_observation']
    require(type(identity) is dict and set(identity) <= {'duration_seconds', 'pid', 'pgid', 'sid'}, 'OBSERVATION_IDENTITY')
    for key, item in identity.items():
        require(type(item) in (int, float) and math.isfinite(item) and item >= 0, 'OBSERVATION_IDENTITY_VALUE')
        if key != 'duration_seconds':
            require(type(item) is int and item > 1, 'OBSERVATION_PID')
    return value


def toolchain(parent):
    # Filesystem/plist reads only: do not warm xcrun or CoreSimulator here.
    require(parent.get('DEVELOPER_DIR') == PINNED_DEVELOPER, 'PINNED_DEVELOPER_REQUIRED')
    selected = Path(PINNED_DEVELOPER).resolve(strict=True)
    require(selected.is_dir() and selected.parts[-2:] == ('Contents', 'Developer'), 'SELECTED_XCODE')
    require(selected.parent.parent.parent == Path('/Applications'), 'XCODE_LOCATION')
    global_default = Path('/var/db/xcode_select_link').resolve(strict=True)
    version = plistlib.loads(regular_bytes(selected.parent / 'version.plist', 65536))
    sdk = (selected / 'Platforms/iPhoneSimulator.platform/Developer/SDKs/iPhoneSimulator.sdk').resolve(strict=True)
    require(sdk.is_relative_to(selected), 'SDK_LOCATION')
    settings = plistlib.loads(regular_bytes(sdk / 'SDKSettings.plist', 1024**2))
    require(version.get('CFBundleShortVersionString') == HISTORICAL['xcode']
            and version.get('ProductBuildVersion') == HISTORICAL['xcode_build'], 'XCODE_VERSION_MISMATCH')
    require(settings.get('Version') == HISTORICAL['sdk'], 'SDK_VERSION_MISMATCH')
    # Explicit workflow pin is inherited by Redact; Room/Trip canonicalize as upstream.
    parent['_selected_developer'] = str(selected)
    binaries = [Path('/usr/bin/xcrun'), selected / 'usr/bin/simctl', selected / 'usr/bin/xcodebuild']
    hashes = {p.name: digest(regular_bytes(p.resolve(strict=True), 64 * 1024**2)) for p in binaries}
    for boundary in ('room', 'redact', 'trip'):
        found = shutil.which('xcrun', path=env_for(boundary, parent).get('PATH', os.defpath))
        require(found and Path(found).resolve() == Path('/usr/bin/xcrun').resolve(), 'XCRUN_LOOKUP_MISMATCH')
    return dict(xcode=HISTORICAL['xcode'], xcode_build=HISTORICAL['xcode_build'], sdk=HISTORICAL['sdk'],
                tool_sha256=hashes, global_default_matches_pin=global_default == selected,
                global_default_path_sha256=digest(str(global_default).encode()),
                identity_basis='explicit installed Xcode pin, installed plists and binaries; no native version invocation')


def planned_phases(parent):
    frozen = {k: parent[k] for k in BOOT_KEYS if k in parent}
    phases = [('room-first', 'room', 'first-in-job', env_for('room', parent), None)]
    for boundary in ('room', 'redact', 'trip'):
        original = env_for(boundary, parent)
        variant, skip = bundle_variant(original, frozen)
        phases += [(boundary + '-A-before', boundary, 'original', original, None),
                   (boundary + '-B', boundary, 'bootstrap-env-bundle', variant, skip),
                   (boundary + '-A-after', boundary, 'original', original, 'NO_INTERVENTION' if skip else None)]
    return phases


def run_schedule(parent, private, deadline, invoke, persist, clock=time.monotonic):
    rows, stopped = [], False
    for phase, boundary, arm, child_env, skip in planned_phases(parent):
        row = dict(phase=phase, boundary=boundary, arm=arm)
        if stopped:
            row.update(status='NOT_RUN', reason='COHORT_STOPPED')
        elif skip:
            row.update(status='SKIPPED', reason=skip)
        elif deadline - clock() < 70:
            row.update(status='NOT_RUN', reason='GLOBAL_BUDGET')
            stopped = True
        else:
            target = private / phase
            target.mkdir(mode=0o700)
            write_json(target / 'actual-env.json', child_env, 65536)
            row.update(child_env=env_evidence(child_env), rlimits=limits())
            before = clock()
            try:
                probe = target / 'probe'
                probe.mkdir(mode=0o700)
                observation = validated_observation(invoke(boundary, child_env, probe, deadline))
                row.update(status='OBSERVED', observation=observation)
                stopped = not (observation.get('outcome') in ('success', 'timeout')
                               and observation.get('cleanup_confirmed') is True
                               and observation.get('identity_uncertain') is False
                               and observation.get('output_censored') is False)
            except BaseException as error:
                row.update(status='ADAPTER_FAILED', error_type=type(error).__name__, errno=public_errno(getattr(error, 'errno', None)))
                stopped = True
            row['wall_seconds'] = clock() - before
        rows.append(row)
        persist(rows, stopped)
    return rows, stopped


def hard_abort(public):
    # A timed-out supervisor does not prove its independent native sessions died.
    # This fixed receipt contains no mutable report, private paths, env or logs.
    raw = b'{"schema":1,"status":"HARD_ABORT","reason":"DEADLINE_OR_SIGNAL_DELIVERY_FAILURE","cleanup":"UNKNOWN","native_acquisitions_unknown":true,"product_acceptance":false}\n'
    descriptor = None
    try:
        descriptor = os.open(public / 'hard-deadline.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.write(descriptor, raw)
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
        finally:
            os._exit(124)


def new_deadline_guard(started, public):
    sys.path.insert(0, str(ROOT))
    from deadline_guard import DeadlineGuard
    return DeadlineGuard(hard_deadline=started + TOTAL_SECONDS,
                         soft_deadline=started + 45,
                         hard_abort=lambda: hard_abort(public)).__enter__()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--expected-sha')
    parser.add_argument('--package-sha256')
    args = parser.parse_args()
    if not args.execute:
        print('Preparation only; no native commands. Execution requires reviewed hosted dispatch.')
        return 0
    started = time.monotonic()
    parent, original_fsize, guard = dict(os.environ), None, None
    public = ROOT / 'public'
    require(not public.exists(), 'PUBLIC_ALREADY_EXISTS')
    public.mkdir(mode=0o700)
    report = dict(schema=1, kind='diagnostic_only', product_acceptance=False,
                  historical_reference_environment=HISTORICAL,
                  experiment_environment='current_hosted_image_single_job', historical_reproduction_claim=False,
                  historical_python=dict(room='3.12.10', redact='NOT_RETAINED', trip='3.14.7'),
                  phases=[], phase_invocation_count=0,
                  native_acquisitions_observed=0, native_acquisitions_unknown=False)
    code = 1
    try:
        host = {k: parent.get(k) for k in ('ImageOS', 'ImageVersion', 'RUNNER_ARCH')}
        require(all(v is None or (isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_.+-]{1,128}', v)) for v in host.values()), 'HOST_FACTS_SHAPE')
        report['observed_host'] = host
        host_gate(parent, args.expected_sha)
        guard = new_deadline_guard(started, public)
        report['seal'] = verify_seal(ROOT, args.package_sha256)
        push_event_gate(parent, args.expected_sha)
        report.update(run_id=parent['GITHUB_RUN_ID'], source_sha=args.expected_sha,
                      python=platform.python_version(), machine=platform.machine())
        report['historical_comparison'] = dict(image_version_matches=parent['ImageVersion'] == HISTORICAL['image_version'],
                                                trip_python_matches=platform.python_version() == HISTORICAL['python'],
                                                room_python_matches=platform.python_version() == '3.12.10',
                                                redact_python='UNKNOWN')
        system = plistlib.loads(regular_bytes(Path('/System/Library/CoreServices/SystemVersion.plist'), 65536))
        os_facts = {k: system.get(k) for k in ('ProductVersion', 'ProductBuildVersion')}
        require(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9.]{1,32}', v)
                    for v in os_facts.values()), 'OS_FACTS')
        report['os'] = os_facts
        report['python_executable_sha256'] = digest(regular_bytes(Path(sys.executable).resolve(strict=True), 64 * 1024**2))
        report['toolchain'] = toolchain(parent)
        report['parent_identity'] = dict(pid=os.getpid(), ppid=os.getppid(), pgid=os.getpgrp(), sid=os.getsid(0),
                                         uid=os.getuid(), euid=os.geteuid(), gid=os.getgid(), egid=os.getegid())
        report['rlimits_before'] = limits()
        original_fsize = resource.getrlimit(resource.RLIMIT_FSIZE)
        soft, hard = original_fsize
        require(hard == resource.RLIM_INFINITY or hard >= FILE_CAP, 'FSIZE_HARD_LIMIT')
        require(soft == resource.RLIM_INFINITY or soft >= FILE_CAP, 'FSIZE_SOFT_LIMIT')
        resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_CAP, hard))
        report['rlimits_diagnostic'] = limits()
        temp = Path(parent.get('RUNNER_TEMP', ''))
        require(temp.is_absolute() and temp.is_dir() and not temp.is_symlink()
                and not temp.resolve().is_relative_to(ROOT), 'PRIVATE_ROOT')
        private = temp / ('ios-discovery-' + parent['GITHUB_RUN_ID'])
        private.mkdir(mode=0o700)
        report['parent_bootstrap_env'] = env_evidence({k: parent[k] for k in BOOT_KEYS if k in parent})
        sys.path.insert(0, str(ROOT))
        from adapters import run_probe
        require(time.monotonic() - started <= 45, 'PREFLIGHT_BUDGET')
        deadline = started + TOTAL_SECONDS - 30
        guard.arm(deadline)
        def persist(rows, stopped):
            report.update(phases=rows, stopped=stopped,
                          phase_invocation_count=sum(r['status'] in ('OBSERVED', 'ADAPTER_FAILED') for r in rows),
                          native_acquisitions_observed=sum('pid' in r.get('observation', {}).get('spawn_observation', {}) for r in rows),
                          native_acquisitions_unknown=any(r['status'] == 'ADAPTER_FAILED' or r.get('observation', {}).get('identity_uncertain') for r in rows))
            write_json(public / 'diagnostic.json', report)
        rows, stopped = run_schedule(parent, private, deadline, run_probe, persist)
        report['status'] = 'STOPPED' if stopped else 'COLLECTION_COMPLETE'
        code = 1 if stopped else 0
    except BaseException as error:
        report.update(status='REFUSED_OR_FAILED', reason=str(error) if isinstance(error, Refused) else type(error).__name__)
    finally:
        if original_fsize is not None:
            try:
                resource.setrlimit(resource.RLIMIT_FSIZE, original_fsize)
                report['rlimits_after_restore'] = limits()
                require(resource.getrlimit(resource.RLIMIT_FSIZE) == original_fsize, 'FSIZE_RESTORE_MISMATCH')
            except BaseException as error:
                report.update(status='RESTORE_FAILED', restore_error_type=type(error).__name__)
                code = 1
        try:
            write_json(public / 'diagnostic.json', report)
        finally:
            if guard is not None:
                try:
                    guard.close()
                except BaseException as error:
                    report.update(status='GUARD_FINALIZATION_FAILED', guard_error_type=type(error).__name__,
                                  native_acquisitions_unknown=True)
                    code = 1
                    write_json(public / 'diagnostic.json', report)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
