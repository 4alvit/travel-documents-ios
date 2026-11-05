#!/usr/bin/env python3
"""Capture one bounded hosted toolchain inventory; never run or qualify app tests."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

DEVELOPER = '/Applications/Xcode_26.2.app/Contents/Developer'
LIMIT, RESERVE, STREAM_LIMIT = 300, 8, 4 * 1024 * 1024
QUERIES = (
    ('source', ['git', 'rev-parse', 'HEAD']),
    ('developer', ['xcode-select', '-p']),
    ('xcode', ['xcodebuild', '-version']),
    ('sdk', ['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']),
    ('swift', ['xcrun', 'swift', '--version']),
    ('runtimes', ['xcrun', 'simctl', 'list', 'runtimes', '--json']),
    ('device-types', ['xcrun', 'simctl', 'list', 'devicetypes', '--json']),
    ('xcresulttool', ['xcrun', 'xcresulttool', 'version']),
    ('summary-schema', ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--schema']),
    ('tests-schema', ['xcrun', 'xcresulttool', 'get', 'test-results', 'tests', '--schema']),
)
ENV_KEYS = ('GITHUB_REPOSITORY', 'GITHUB_REF', 'GITHUB_SHA', 'GITHUB_RUN_ID',
            'GITHUB_RUN_ATTEMPT', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'DEVELOPER_DIR')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def close_group(process, deadline):
    intervention = process.poll() is None or group_exists(process.pid)
    for sig, stop in ((signal.SIGTERM, min(deadline - 2, time.monotonic() + 2)),
                      (signal.SIGKILL, deadline)):
        if group_exists(process.pid):
            require(time.monotonic() < deadline, 'Process closure deadline exceeded')
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        while time.monotonic() < stop:
            process.poll()
            if not group_exists(process.pid):
                break
            time.sleep(max(0, min(.05, stop - time.monotonic())))
    process.poll()
    require(process.returncode is not None and not group_exists(process.pid), 'Process group did not close')
    return intervention


def command(name, argv, output, deadline, report):
    row = {'id': name, 'argv': argv, 'started': time.monotonic() - report['start']}
    report['commands'].append(row)
    process = None
    paths = [output / (name + '-' + channel + '.txt') for channel in ('stdout', 'stderr')]
    try:
        require(time.monotonic() < deadline - RESERVE, 'Shared probe budget exhausted')
        with paths[0].open('xb') as stdout, paths[1].open('xb') as stderr:
            try:
                process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)
                while process.poll() is None:
                    require(time.monotonic() < deadline - RESERVE, 'Shared probe work deadline exceeded')
                    require(all(path.stat().st_size <= STREAM_LIMIT for path in paths), 'Probe stream limit exceeded')
                    time.sleep(.05)
            except BaseException as error:
                row['error'] = repr(error)
                raise
            finally:
                if process is not None:
                    try:
                        row['stop_intervention'] = close_group(process, deadline)
                        row['returncode'] = process.returncode
                        row['group_closed'] = True
                    except BaseException as error:
                        row['cleanup_error'] = repr(error)
                        if 'error' not in row:
                            raise
        require(row['returncode'] == 0 and not row['stop_intervention'], 'Probe command failed or left descendants')
        require(all(path.stat().st_size <= STREAM_LIMIT for path in paths), 'Probe stream limit exceeded')
    except BaseException as error:
        row['error'] = repr(error)
        raise
    finally:
        row['finished'] = time.monotonic() - report['start']
        row['streams'] = {}
        for path in paths:
            if path.exists():
                size = path.stat().st_size
                row['streams'][path.name] = {'bytes': size,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if size <= STREAM_LIMIT else None}


def parse_metadata(output, report):
    text = lambda name: (output / (name + '-stdout.txt')).read_text().strip()
    require(text('source') == report['environment']['GITHUB_SHA'], 'Checkout differs from dispatched source')
    require(text('developer') == DEVELOPER and text('xcode') == 'Xcode 26.2\nBuild version 17C52', 'Unexpected Xcode')
    require(text('sdk') == '26.2' and re.search(r'\bSwift version 6\.2(?:\.|\s)', text('swift')), 'Unexpected SDK or Swift')
    for name, key in (('runtimes', 'runtimes'), ('device-types', 'devicetypes')):
        value = json.loads(text(name))
        require(isinstance(value, dict) and isinstance(value.get(key), list), 'Malformed ' + name)
        report[name] = value[key]
    report['schema_json'] = {}
    for name in ('summary-schema', 'tests-schema'):
        try:
            json.loads(text(name))
            report['schema_json'][name] = {'valid_json': True}
        except ValueError as error:
            # Producer schema documents may be stale/malformed; retain the raw bytes.
            report['schema_json'][name] = {'valid_json': False, 'error': str(error)}


def main():
    def interrupted(signum, frame):
        raise InterruptedError('Probe interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    output = Path('build/ToolchainProbe')
    output.mkdir(parents=True, exist_ok=False)
    report = {'start': time.monotonic(), 'commands': [], 'status': 'failed', 'machine': os.uname().machine,
              'release_acceptance': False, 'environment': {key: os.environ.get(key) for key in ENV_KEYS}}
    try:
        require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'macOS'
                and os.environ.get('RUNNER_ARCH') == 'ARM64' and os.uname().machine == 'arm64', 'Wrong hosted architecture')
        require(os.environ.get('GITHUB_REPOSITORY') == '4alvit/travel-documents-ios'
                and os.environ.get('GITHUB_REF') == 'refs/heads/diagnostic/arm-262-capacity'
                and os.environ.get('DEVELOPER_DIR') == DEVELOPER, 'Wrong probe context')
        for name, argv in QUERIES:
            command(name, argv, output, report['start'] + LIMIT, report)
        parse_metadata(output, report)
        require(time.monotonic() < report['start'] + LIMIT, 'Shared probe deadline exceeded')
        report['status'] = 'metadata_collected'
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        report['elapsed'] = time.monotonic() - report.pop('start')
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
