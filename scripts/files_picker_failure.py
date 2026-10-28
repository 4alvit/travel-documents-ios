#!/usr/bin/env python3
"""Read one existing failed Files-picker test; never run a test or a simulator."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import sys
import uuid

HERE = Path(__file__).resolve().parent
CORE_SHA = '8cf9483d27c33e5b69a0a5e374724290c116d25ee001214fc7a7af24dbb9738e'
if hashlib.sha256((HERE/'recovery_core.py').read_bytes()).hexdigest() != CORE_SHA:
    raise RuntimeError('Evidence helper changed before import')
spec = importlib.util.spec_from_file_location('files_failure_core', HERE/'recovery_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
require = core.require
MIB = 1024**2
WHOLE, WORK, OUTPUT, FLOOR = 120, 100, 32*MIB, 8*1024**3
core.base.PER_LOG, core.base.ALL_LOG = MIB, 8*MIB
core.CAPS.update(scan_entries=4096, scan_depth=40)
CASES = [
    ('AccessibilityUITests/testMaximumTypeRestoreEntryAndTabNavigation()',
     'Restore Files picker did not present its Files navigation'),
    ('AccessibilityUITests/testMaximumTypeReadinessAndImportCancellation()',
     'Import Files picker did not present its Files navigation'),
]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    require(len(raw.encode('utf-8')) <= MIB, 'JSON cap')
    return json.loads(raw, object_pairs_hook=unique)


def bounded_text(value, limit=256):
    require(isinstance(value, str) and 0 < len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid metadata string')
    return value


def select_case(tree):
    """Prefer failed Restore even if Import or unrelated cases also failed."""
    found = {case: [] for case, _ in CASES}
    pending = list(tree['testNodes'])
    count = 0
    while pending:
        node = pending.pop()
        count += 1
        require(count <= 4096 and isinstance(node, dict), 'Test tree cap/schema')
        children = node.get('children', [])
        require(isinstance(children, list) and len(pending)+len(children) <= 4096, 'Test tree cap')
        pending.extend(children)
        if node.get('nodeType') == 'Test Case' and node.get('nodeIdentifier') in found:
            found[node['nodeIdentifier']].append(node)
    for case, label in CASES:
        require(len(found[case]) <= 1, 'Ambiguous relevant case')
        require(not found[case] or found[case][0].get('result') in ('Passed', 'Failed'),
                'Relevant case outcome unknown')
        if found[case] and found[case][0].get('result') == 'Failed':
            devices, configs = tree['devices'], tree['testPlanConfigurations']
            require(isinstance(devices, list) and len(devices) == 1
                    and isinstance(configs, list) and len(configs) == 1, 'Ambiguous device/configuration')
            device, config = devices[0], configs[0]
            require(device['platform'] == 'iOS Simulator', 'Unexpected platform')
            require(str(uuid.UUID(device['deviceId'])).upper() == device['deviceId'].upper(), 'Invalid device ID')
            actual_device = {k: bounded_text(device[k]) for k in
                             ('deviceId', 'deviceName', 'modelName', 'osVersion', 'platform')}
            actual_config = {k: bounded_text(config[k]) for k in ('configurationId', 'configurationName')}
            return dict(case=case, label=label, device=actual_device, configuration=actual_config,
                        result='Failed', selection_policy='failed Restore first; otherwise failed Import')
    raise RuntimeError('No failed relevant Files-picker case')


def select_pair(manifest, selected):
    require(isinstance(manifest, list) and len(manifest) == 1
            and manifest[0]['testIdentifier'] == selected['case'], 'Wrong export case')
    rows = manifest[0]['attachments']
    require(isinstance(rows, list) and len(rows) <= 128, 'Attachment cap/schema')
    chosen, names = {}, set()
    for row in rows:
        name = bounded_text(row['exportedFileName'])
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', name) and name not in ('.', '..')
                and name.casefold() not in names, 'Unsafe/duplicate export name')
        names.add(name.casefold())
        human = bounded_text(row['suggestedHumanReadableName'], 1024)
        # Observed xcresulttool naming: XCTest attachment label + _index_UUID.ext.
        for kind, suffix, ext in [('png', '', 'png'), ('ax', ' — accessibility hierarchy', 'txt')]:
            pattern = re.escape(selected['label'] + suffix) + r'_\d+_[0-9A-Fa-f-]{36}\.' + ext
            if not re.fullmatch(pattern, human):
                continue
            require(kind not in chosen and name.lower().endswith('.'+ext), 'Ambiguous pair/type')
            require(row['deviceId'] == selected['device']['deviceId']
                    and row['configurationName'] == selected['configuration']['configurationName'],
                    'Attachment device/configuration mismatch')
            require(type(row.get('isAssociatedWithFailure')) is bool, 'Missing attachment association')
            chosen[kind] = {k: row[k] for k in ('exportedFileName', 'suggestedHumanReadableName',
                                              'deviceId', 'configurationName', 'isAssociatedWithFailure')}
    require(set(chosen) == {'png', 'ax'}, 'Exact failed assertion pair missing')
    return chosen


class Evidence(core.base.Smoke):
    def __init__(self, repo, env, ops=None):
        self.repo = repo
        run, attempt, checkout = (env.get(k, '') for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA'))
        require(re.fullmatch(r'[1-9][0-9]{0,19}', run) and re.fullmatch(r'[1-9][0-9]{0,8}', attempt)
                and re.fullmatch(r'[0-9a-f]{40}', checkout), 'Invalid run identity')
        require(env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_OS') == 'macOS', 'Hosted macOS only')
        self.ops = ops or core.base.RealOps(dict(env), str(repo))
        self.t0 = self.ops.now()
        self.limit = self.write_deadline = self.t0 + WORK
        self.final_deadline = self.t0 + WHOLE
        core.identity_of(repo)
        core.identity_of(repo/'build')
        self.root = repo/'build'/('FilesPickerFailure-'+run+'-'+attempt)
        self.root.mkdir(mode=0o700)  # Exclusive: never reuse a same-attempt scope.
        self.root_id = core.identity_of(self.root)
        self.out, self.public = self.root/'scratch', self.root/'public'
        self.out.mkdir(mode=0o700)
        self.public.mkdir(mode=0o700)
        self.out_id, self.public_id = core.identity_of(self.out), core.identity_of(self.public)
        if ops is None:
            # Keep decoder caches and temporary output inside the owned subtree.
            (self.out/'home').mkdir(mode=0o700)
            (self.out/'tmp').mkdir(mode=0o700)
            self.ops.env = {k: env[k] for k in ('DEVELOPER_DIR', 'LANG', 'LC_ALL') if k in env}
            self.ops.env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', HOME=str(self.out/'home'),
                                CFFIXED_USER_HOME=str(self.out/'home'), TMPDIR=str(self.out/'tmp'))
        self.report = dict(commands=[], errors=[])
        self.evidence = dict(status='failed', runtime_acceptance=False, original_test_result='failure',
                             run_id=run, run_attempt=attempt, checkout_sha=checkout,
                             limits=dict(whole_seconds=WHOLE, work_seconds=WORK, cleanup_seconds=WHOLE-WORK,
                                         sampled_output_bytes=OUTPUT, free_floor_bytes=FLOOR),
                             helper_sha256=CORE_SHA, process_helper_sha256=core.HELPER_SHA,
                             temporary_cleanup_verified=False)
        self.active, self.absent_groups = {}, set()
        self.unknown_spawn, self.interrupted, self.log_total = False, False, 0
        self.next_scan, self.peak = self.t0, 0
        self.stage = 'admission'

    def check(self, final=False):
        end = self.final_deadline if final else self.limit
        require(self.ops.now() < end and (final or not self.interrupted), 'Original evidence deadline/interruption')
        require(core.identity_of(self.root) == self.root_id, 'Evidence root changed')
        require(self.ops.now() < end, 'Evidence identity check exceeded deadline')

    def checkpoint(self, force_resources=False):
        self.check()
        if force_resources or self.ops.now() >= self.next_scan:
            end = min(self.limit, self.ops.now()+5)
            pending = self.report['commands'][-1] if self.report['commands'] else None
            if pending is not None and 'finish' not in pending:
                end = min(end, self.t0+pending['work_deadline'])
            def check():
                self.check()
                require(self.ops.now() < end, 'Original command scan deadline')
            check()
            require(shutil.disk_usage(self.root).free >= FLOOR, 'Evidence free-space floor')
            check()
            row = core.live_sizes(self.root, self.root_id, self.ops.now, end, check)
            check()
            require(max(row['logical'], row['allocated']) <= OUTPUT, 'Evidence output cap')
            self.peak = max(self.peak, row['allocated'])
            self.next_scan = self.ops.now()+.25

    def read(self, path, cap):
        self.checkpoint()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap, 'Evidence file type/size')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(cap+1)
            self.checkpoint()
            after = os.fstat(fd)
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    and len(raw) == before.st_size, 'Evidence file changed')
            return raw
        finally:
            os.close(fd)

    def tool_command(self, label, args, cap):
        require(core.file_digest(self.tool, self.checkpoint) == self.tool_sha, 'Installed tool changed')
        result = self.command(label, [str(self.tool), *args], cap)
        require(core.file_digest(self.tool, self.checkpoint) == self.tool_sha, 'Installed tool changed')
        return result

    def collect(self):
        self.stage = 'checkout'
        actual = self.command('checkout', ['/usr/bin/git', 'rev-parse', 'HEAD'], 12).strip()
        require(actual == self.evidence['checkout_sha'], 'Checkout identity mismatch')
        self.evidence['source_files'] = {name: core.file_digest(self.repo/name, self.checkpoint) for name in
            ('scripts/files_picker_failure.py', 'scripts/recovery_core.py', 'scripts/recovery_process.py',
             'scripts/test-simulator.sh', 'UITests/AccessibilityUITests.swift', '.github/workflows/ci.yml')}
        self.stage = 'input'
        bundles = []
        with os.scandir(self.repo/'build') as entries:
            for index, entry in enumerate(entries):
                self.checkpoint()
                require(index < 4096, 'Build entry cap')
                if re.fullmatch(r'Tests-[0-9]{8}T[0-9]{6}Z\.xcresult', entry.name):
                    bundles.append(Path(entry.path))
        require(len(bundles) == 1, 'Expected one integration result bundle')
        bundle = bundles[0]
        original = core.tree_manifest(bundle, self.checkpoint, 512*MIB)
        self.evidence['input'] = dict(bundle=bundle.name, manifest_sha256=digest(core.encoded(original)),
                                      entries=len(original), bytes=sum(r.get('bytes', 0) for r in original.values()))
        self.stage = 'tool'
        self.tool = Path(self.command('find-tool', ['/usr/bin/xcrun', '--find', 'xcresulttool'], 12).strip())
        require(self.tool.is_absolute() and self.tool.resolve(strict=True) == self.tool
                and self.tool.name == 'xcresulttool', 'Unresolved installed tool')
        self.tool_sha = core.file_digest(self.tool, self.checkpoint)
        self.evidence['tool'] = dict(name='xcresulttool', sha256=self.tool_sha)
        self.stage = 'test-tree'
        raw = self.tool_command('test-tree', ['get', 'test-results', 'tests', '--path', str(bundle), '--compact'], 30)
        selected = select_case(parse(raw))
        self.evidence.update(selected=selected, test_tree_sha256=digest(raw.encode()))
        self.stage = 'export'
        exported = self.out/'exported'
        self.tool_command('export', ['export', 'attachments', '--path', str(bundle),
                                    '--output-path', str(exported), '--test-id', selected['case']], 60)
        self.checkpoint(force_resources=True)
        exported_id = core.identity_of(exported)
        inventory = core.tree_manifest(exported, self.checkpoint, OUTPUT)
        raw = self.read(exported/'manifest.json', MIB)
        pair = select_pair(parse(raw.decode('utf-8')), selected)
        self.evidence.update(attachment_manifest_sha256=digest(raw),
                             export_manifest_sha256=digest(core.encoded(inventory)))
        self.stage = 'pair'
        retained, payloads = {}, {}
        for kind, row in pair.items():
            cap, target = (8*MIB, 'failure.png') if kind == 'png' else (2*MIB, 'failure-ax.txt')
            require(core.identity_of(exported) == exported_id, 'Export directory changed')
            raw = self.read(exported/row['exportedFileName'], cap)
            require(inventory[row['exportedFileName']]['sha256'] == digest(raw), 'Export file changed')
            if kind == 'png':
                require(raw[:8] == b'\x89PNG\r\n\x1a\n' and raw[12:16] == b'IHDR' and len(raw) >= 24, 'Invalid PNG')
                width, height = struct.unpack('>II', raw[16:24])
                require(0 < width <= 8192 and 0 < height <= 8192 and width*height <= 16*MIB, 'PNG dimensions')
            else:
                raw.decode('utf-8')
            payloads[target] = raw
            retained[kind] = dict(file=target, bytes=len(raw), sha256=digest(raw), attachment=row)
        self.stage = 'input-recheck'
        require(core.tree_manifest(bundle, self.checkpoint, 512*MIB) == original, 'Input result changed')
        self.stage = 'publication'
        for target, raw in payloads.items():
            self.checkpoint()
            require(core.identity_of(self.public) == self.public_id, 'Public directory changed')
            with (self.public/target).open('xb') as stream:
                stream.write(raw)
            self.checkpoint()
            require(core.identity_of(self.public) == self.public_id, 'Public directory changed')
        self.evidence.update(status='complete', retained=retained, input_unchanged=True)

    def remove_scratch(self):
        """Bounded no-follow cleanup, only after every owned group is closed."""
        require(not self.active and not self.unknown_spawn, 'Process closure unresolved')
        self.check(final=True)
        require(core.identity_of(self.out) == self.out_id, 'Scratch root changed')
        encountered = 0
        def remove(parent, name, depth=0):
            nonlocal encountered
            self.check(final=True)
            encountered += 1
            require(encountered <= 4096, 'Cleanup entry cap')
            require(depth <= 40, 'Cleanup depth')
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            self.check(final=True)
            if stat.S_ISDIR(before.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    self.check(final=True)
                    opened = os.fstat(fd)
                    self.check(final=True)
                    require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'Cleanup directory changed')
                    with os.scandir(fd) as it:
                        names = []
                        for entry in it:
                            self.check(final=True)
                            require(len(names) < 4096, 'Cleanup entry cap')
                            names.append(entry.name)
                    for child in names:
                        remove(fd, child, depth+1)
                    self.check(final=True)
                    after = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    self.check(final=True)
                    require((after.st_dev, after.st_ino, after.st_mode) ==
                            (before.st_dev, before.st_ino, before.st_mode), 'Cleanup directory replaced')
                    os.rmdir(name, dir_fd=parent)
                    self.check(final=True)
                finally:
                    os.close(fd)
            else:
                require(stat.S_ISREG(before.st_mode), 'Unexpected temporary file type')
                self.check(final=True)
                os.unlink(name, dir_fd=parent)
                self.check(final=True)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self.check(final=True)
            opened = os.fstat(fd)
            require([opened.st_dev, opened.st_ino] == self.root_id, 'Cleanup root FD changed')
            remove(fd, 'scratch')
        finally:
            os.close(fd)
        self.check(final=True)
        require(not self.out.exists(), 'Scratch remains')
        self.check(final=True)
        self.evidence['temporary_cleanup_verified'] = True

    def finish(self):
        # No new process, deadline extension, or automatic rerun on this path.
        try:
            self.remove_scratch()
        except BaseException as error:
            self.evidence.update(status='failed', cleanup_error_type=type(error).__name__)
        self.check(final=True)  # Expiry ends finalization before any further I/O.
        self.evidence.update(elapsed_seconds=self.ops.now()-self.t0,
                             peak_sampled_allocated_bytes=self.peak,
                             all_owned_groups_closed=not self.active and not self.unknown_spawn,
                             commands=[{k: r[k] for k in ('id', 'start', 'finish', 'requested_cap_seconds',
                                                        'work_deadline', 'command_deadline', 'outcome', 'returncode')
                                        if k in r} for r in self.report['commands']])
        raw = core.encoded(self.evidence)
        require(len(raw) <= 16*1024, 'Public receipt cap')
        self.check(final=True)
        require(core.identity_of(self.public) == self.public_id, 'Public directory changed')
        self.check(final=True)
        with (self.public/'evidence.json').open('xb') as stream:
            stream.write(raw)
        self.check(final=True)
        require(core.identity_of(self.public) == self.public_id, 'Public directory changed')
        self.check(final=True)
        return self.evidence['status'] == 'complete'


def main():
    require(len(sys.argv) == 2 and sys.argv[1] == '--run', 'Explicit hosted invocation required')
    repo = HERE.parent
    run = Evidence(repo, os.environ)
    prior = {sig: signal.signal(sig, run.signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            run.collect()
        except BaseException as error:
            run.evidence.update(status='failed', failed_stage=run.stage, error_type=type(error).__name__,
                                error_errno=getattr(error, 'errno', None))
            if isinstance(error, RuntimeError):
                run.evidence['error'] = str(error)[:512]
        return 0 if run.finish() else 1
    finally:
        for sig, handler in prior.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
