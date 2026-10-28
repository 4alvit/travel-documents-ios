#!/usr/bin/env python3
"""Portable two-phase recovery core extracted from the reviewed source-only executor."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
HELPER_SHA = '5e418add4d13dc364563696de4728bdd10da88b8a25868a7b8372630124fa5fb'
if hashlib.sha256((HERE/'recovery_process.py').read_bytes()).hexdigest() != HELPER_SHA:
    raise RuntimeError('Process helper changed before import')
spec = importlib.util.spec_from_file_location('recovery_functional_v1', HERE / 'recovery_process.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
require = base.require
GIB = 1024 ** 3
MIB = 1024 ** 2
CAPS = dict(total_seconds=1500, cleanup_seconds=120, receipt_seconds=10,
            phase_seconds=600, testcase_seconds=300, admission_free_bytes=16*GIB,
            work_free_bytes=8*GIB, output_bytes=8*GIB, xcresult_bytes=2*GIB,
            stream_bytes=16*MIB, total_log_bytes=64*MIB, scan_seconds=5,
            scan_entries=100000, scan_depth=40, scan_interval_seconds=1)
CASES = {
    'export': 'BatchImportUITests/testRecoveryExportFullBackupThroughFiles()',
    'restore': 'BatchImportUITests/testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal()',
}
BUNDLE = 'com.4alvit.tripfolio'
FILES_BUNDLE = 'com.apple.DocumentsApp'
GROUP = 'group.com.apple.FileProvider.LocalStorage'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def json_file(path, limit=MIB):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, 'Invalid JSON input')
    return json.loads(path.read_text())


def identity_of(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'Unresolved/symlink path')
    s = path.lstat()
    require(stat.S_ISDIR(s.st_mode), 'Expected real directory')
    return [s.st_dev, s.st_ino]


def file_digest(path, checkpoint=lambda: None):
    checkpoint()
    path = Path(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), 'Expected regular evidence file')
        h = hashlib.sha256()
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            while chunk := stream.read(MIB):
                checkpoint()
                h.update(chunk)
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'File changed while hashing')
        checkpoint()
        return h.hexdigest()
    finally:
        os.close(fd)


def tree_manifest(root, checkpoint=lambda: None, max_bytes=2*GIB):
    """Complete stable file/directory manifest, never follows links."""
    root = Path(root)
    root_id = identity_of(root)
    result, total = {}, 0
    def walk(folder, depth):
        nonlocal total
        checkpoint()
        require(depth <= CAPS['scan_depth'], 'Manifest depth exceeded')
        before = folder.lstat()
        require(stat.S_ISDIR(before.st_mode), 'Manifest directory replaced by link')
        children = []
        for path in folder.iterdir():
            checkpoint()
            require(len(result)+len(children) < CAPS['scan_entries'], 'Manifest entry cap exceeded')
            children.append(path)
        for path in sorted(children):
            checkpoint()
            s = path.lstat()
            require(len(result) < CAPS['scan_entries'], 'Manifest entry cap exceeded')
            relative = path.relative_to(root).as_posix()
            mode = stat.S_IMODE(s.st_mode)
            if stat.S_ISDIR(s.st_mode):
                result[relative] = {'kind': 'directory', 'mode': mode}
                walk(path, depth + 1)
            else:
                require(stat.S_ISREG(s.st_mode), 'Manifest rejects links and special files')
                total += s.st_size
                require(total <= max_bytes, 'Manifest size cap exceeded')
                result[relative] = {'kind': 'file', 'bytes': s.st_size, 'mode': mode,
                                    'sha256': file_digest(path, checkpoint)}
        after = folder.lstat()
        require(stat.S_ISDIR(after.st_mode), 'Manifest directory replaced by link')
        require((before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns), 'Directory changed during manifest')
    walk(root, 0)
    require(identity_of(root) == root_id, 'Manifest root changed')
    return result


def live_sizes(root, root_id, now, deadline, checkpoint=lambda: None, *, observation=None):
    """Bounded no-follow FD traversal of the owned output, including active jobs.

    Directory mtimes may change during a writer. Every encountered entry is
    measured; traversal errors/limits fail closed. The disk cap uses allocated
    512-byte blocks, not sparse logical lengths. Hardlinks are conservatively
    charged per entry with fresh stats, including growth seen on later aliases
    or scans. This is sampled accounting, not a quota or an instantaneous peak.
    """
    totals = {'logical': 0, 'allocated': 0, 'entries': 0, 'xcresults': {}}
    observation = {} if observation is None else observation
    started = now()
    observation.update(status='running', operation_count=0, max_depth=0)
    def observe(operation, relative, depth, call):
        # These are elapsed operation spans (including scheduling), not syscall
        # timings. Keep only the last and longest span, with bounded path/error.
        path = '/'.join(relative) or '.'
        span = dict(operation=operation, path=path[:256], path_truncated=len(path)>256,
                    depth=depth, started_seconds=now()-started)
        observation['operation_count'] += 1
        observation['last_operation'] = span
        try:
            value = call()
            span['outcome'] = 'returned'
            return value
        except BaseException as error:
            span.update(outcome='raised', error=repr(error)[:512])
            raise
        finally:
            span['finished_seconds'] = now()-started
            span['duration_seconds'] = span['finished_seconds']-span['started_seconds']
            if span['duration_seconds'] >= observation.get('longest_operation', {}).get('duration_seconds', -1):
                observation['longest_operation'] = dict(span)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    def allocated_bytes(metadata):
        blocks = getattr(metadata, 'st_blocks', None)
        require(type(blocks) is int and blocks >= 0, 'Allocation unknown')
        return blocks * 512
    def check():
        checkpoint()
        require(now() < deadline, 'Output scan deadline exceeded')
    def walk(fd, depth, prefix=(), bundle=None):
        check()
        observation['max_depth'] = max(observation['max_depth'], depth)
        require(depth <= CAPS['scan_depth'], 'Output scan depth exceeded')
        with observe('scandir_open', prefix, depth, lambda: os.scandir(fd)) as children:
            check()
            iterator, exhausted = iter(children), object()
            while True:
                check()
                child = observe('scandir_next', prefix, depth, lambda: next(iterator, exhausted))
                check()
                if child is exhausted:
                    break
                relative = prefix + (child.name,)
                s = observe('entry_stat', relative, depth, lambda: child.stat(follow_symlinks=False))
                check()
                totals['entries'] += 1
                require(totals['entries'] <= CAPS['scan_entries'], 'Output scan entry cap exceeded')
                require(s.st_dev == root_id[0], 'Output filesystem boundary')
                logical = s.st_size if stat.S_ISREG(s.st_mode) else 0
                allocated = allocated_bytes(s)
                totals['logical'] += logical
                totals['allocated'] += allocated
                current = '/'.join(relative) if child.name.endswith('.xcresult') else bundle
                if current:
                    row = totals['xcresults'].setdefault(current, {'logical': 0, 'allocated': 0})
                    row['logical'] += logical
                    row['allocated'] += allocated
                    require(max(row.values()) <= CAPS['xcresult_bytes'], 'xcresult size cap exceeded')
                require(totals['allocated'] <= CAPS['output_bytes'], 'Owned output size cap exceeded')
                if stat.S_ISDIR(s.st_mode):
                    check()
                    nested = observe('directory_open', relative, depth+1,
                                     lambda: os.open(child.name,flags,dir_fd=fd))
                    try:
                        check()
                        opened = observe('directory_fstat', relative, depth+1, lambda: os.fstat(nested))
                        check()
                        require((opened.st_dev,opened.st_ino)==(s.st_dev,s.st_ino), 'Output directory replaced')
                        walk(nested,depth+1,relative,current)
                    finally: os.close(nested)
                else:
                    require(stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode), 'Unexpected output special file')
    try:
        check()
        require(observe('root_identity', (), 0, lambda: identity_of(root)) == root_id, 'Output root replaced')
        check()
        fd = observe('directory_open', (), 0, lambda: os.open(root,flags))
        try:
            check()
            opened = observe('directory_fstat', (), 0, lambda: os.fstat(fd))
            check()
            require([opened.st_dev,opened.st_ino]==root_id,'Output root replaced at open')
            totals['allocated'] = allocated_bytes(opened)
            require(totals['allocated'] <= CAPS['output_bytes'], 'Owned output size cap exceeded')
            walk(fd,0)
        finally: os.close(fd)
        check()
        require(observe('root_identity', (), 0, lambda: identity_of(root)) == root_id, 'Output root replaced')
        check()
        observation['status'] = 'completed'
        return totals
    except BaseException as error:
        observation.update(status='failed', error=repr(error)[:512])
        raise
    finally:
        observation.update(duration_seconds=now()-started,
            partial_totals={key:totals[key] for key in ('logical','allocated','entries')},
            xcresult_count=len(totals['xcresults']))








class Recovery:
    # Shared owned-process primitives, including bounded operation diagnostics.
    command = base.Smoke.command
    pump = base.Smoke.pump
    stop = base.Smoke.stop
    save = base.Smoke.save
    error = base.Smoke.error
    signal = base.Smoke.signal
    devices = staticmethod(base.Smoke.devices)
    recover = base.Smoke.recover

    def __init__(self, ops, out, plan, host, run_id, started=None, *, candidate, source_manifest):
        self.ops, self.out, self.plan, self.host = ops, Path(out), plan, host
        self.candidate = Path(candidate)
        self.source_manifest = source_manifest
        self.t0 = ops.now() if started is None else started
        self.final = self.t0 + CAPS['total_seconds']
        self.limit = self.final - CAPS['cleanup_seconds']
        self.write_deadline, self.phase = self.final, 'work'
        self.active, self.absent_groups = {}, set()
        self.log_total, self.interrupted, self.cleaning = 0, False, False
        self.unknown_spawn, self.create_attempted, self.recovered = False, False, False
        self.owned, self.baseline, self.before_pin = None, set(), None
        self.originals, self.root_id, self.folder = {}, None, None
        self.folder_name = 'TripDocket-Recovery-'+run_id
        self.intent = {'name':self.folder_name, 'runtime':plan['runtime'], 'type':plan['device_type']}
        self.next_scan = self.t0
        self.report = {'status':'running','commands':[],'errors':[],'attempts':{},'resources':[],
                       'cleanup_verified':False,'ui_runtime_accepted':False,'pixel_review_accepted':False,
                       'runtime_accepted':False,'started_epoch':time.time(),'whole_device_allocation':'NOT_MEASURED'}
        self.out.mkdir(mode=0o700)
        self.output_id = identity_of(self.out)
        self.save()

    def timecheck(self):
        require(self.ops.now() < self.limit, self.phase+' deadline reached')
        require(self.cleaning or not self.interrupted, 'Interrupted')

    def checkpoint(self, *, force_resources=False, command_owner=None):
        self.timecheck()
        if not self.cleaning and (force_resources or self.ops.now() >= self.next_scan):
            if command_owner is None:
                self.monitor()
            else:
                self.monitor(command_owner=command_owner)
        if force_resources:
            self.timecheck()  # Include the final resource read in admission.

    def monitor(self, *, command_owner=None):
        started = self.ops.now()
        deadline = min(self.limit, started+CAPS['scan_seconds'])
        # A pending command's work deadline applies during admission, execution
        # and finalization, including a capability probe delegating its scan.
        # Pass context per checkpoint; never install a sticky parent deadline.
        owner = self if command_owner is None else command_owner
        deadline = min(deadline, owner.limit)
        pending = owner.report['commands'][-1] if owner.report['commands'] else None
        if pending is not None and 'finish' not in pending:
            deadline = min(deadline, owner.t0+pending['work_deadline'])
        observation = dict(started_elapsed=started-self.t0, deadline_elapsed=deadline-self.t0,
                           stage='free_space_before', traversal={})
        def check():
            self.timecheck()
            require(self.ops.now() < deadline, 'Output scan deadline exceeded')
        try:
            check()
            require(shutil.disk_usage(self.out).free >= CAPS['work_free_bytes'], 'Work free-space floor reached')
            check()
            observation['stage'] = 'traversal'
            row = live_sizes(self.out, self.output_id, self.ops.now, deadline, self.timecheck,
                             observation=observation['traversal'])
            check()
            observation['stage'] = 'free_space_after'
            free = shutil.disk_usage(self.out).free
            check()
            require(free >= CAPS['work_free_bytes'], 'Work free-space floor reached')
            row.update(elapsed=self.ops.now()-self.t0, free_bytes=free)
        except BaseException as error:
            observation.update(status='failed', finished_elapsed=self.ops.now()-self.t0,
                               error=repr(error)[:512], partial_counts_are_not_valid_accounting=True)
            # Preserve the first failure if later evidence handling also scans.
            # No I/O, extra probe or child process is added on this failure path.
            self.report.setdefault('resource_scan_failure', observation)
            raise
        self.report['resources'].append(row)
        self.next_scan = self.ops.now()+CAPS['scan_interval_seconds']

    def persist(self, name, value):
        self.checkpoint()
        data = encoded(value)
        require(len(data) <= 32*MIB, 'Sidecar exceeds cap')
        with (self.out/name).open('xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        self.checkpoint()
        return {'path':name,'sha256':hashlib.sha256(data).hexdigest()}

    def sim(self, label, *args, cap=30):
        return self.command(label,['/usr/bin/xcrun','simctl',*args],cap)

    def once(self, label):
        require(not self.report['attempts'].get(label), 'One-shot action already attempted: '+label)
        self.report['attempts'][label] = 1
        self.save()

    def source(self):
        expected = self.source_manifest
        actual = tree_manifest(self.candidate,self.checkpoint,64*MIB)
        actual = {k: {'sha256':v['sha256'],'bytes':v['bytes'],'executable':bool(v['mode']&0o111)}
                  for k,v in actual.items() if v['kind']=='file'}
        require(actual == expected,'Integrated candidate changed')
        self.report['candidate_verified'] = True

    def owned_root(self):
        require(self.owned and self.recovered and self.owned not in self.baseline,'Unconfirmed device ownership')
        root = Path.home()/'Library/Developer/CoreSimulator/Devices'/self.owned
        current = identity_of(root)
        if self.root_id is None: self.root_id = current
        require(current == self.root_id,'Owned simulator root changed')
        return root

    def owned_path(self, value, relative_prefix, leaf=None):
        root = self.owned_root()
        path = Path(value.strip())
        identity_of(path)
        require(path.is_relative_to(root),'Path escaped owned simulator')
        relative = path.relative_to(root).parts
        require(tuple(relative[:len(relative_prefix)]) == relative_prefix,'Unexpected container layout')
        tail = relative[len(relative_prefix):]
        require(len(tail) == (2 if leaf else 1),'Unexpected container depth')
        uuid.UUID(tail[0])
        if leaf: require(tail[1] == leaf,'Unexpected app bundle')
        return path

    def setup(self):
        self.source()
        require(shutil.disk_usage(self.out).free >= CAPS['admission_free_bytes'],'Admission space fell before native work')
        runtime = json.loads(self.sim('runtime-inventory','list','runtimes','--json'))
        matches = [r for r in runtime['runtimes'] if r['identifier']==self.plan['runtime']]
        require(len(matches)==1 and matches[0].get('isAvailable') is True,'Runtime unavailable')
        require(self.host['machine'] in matches[0].get('supportedArchitectures',[]) and any(
            d['identifier']==self.plan['device_type'] for d in matches[0].get('supportedDeviceTypes',[])), 'Unsupported device/runtime')
        inventory = json.loads(self.sim('baseline-inventory','list','devices','--json'))
        self.baseline = {d['udid'].upper() for _,d in self.devices(inventory)}
        require(not any(d.get('name')==self.intent['name'] for _,d in self.devices(inventory)),'Device intent collision')
        self.report['baseline'] = inventory
        self.report['create_intent'] = self.intent
        self.create_attempted = True
        self.once('create')
        claimed = self.sim('create','create',self.intent['name'],self.intent['type'],self.intent['runtime']).strip()
        claimed = str(uuid.UUID(claimed)).upper()
        self.recover(json.loads(self.sim('created-inventory','list','devices','--json')))
        require(self.owned == claimed,'Create output/inventory mismatch')
        self.owned_root()
        self.sim('boot','boot',self.owned)
        self.sim('boot-ready','bootstatus',self.owned,'-b',cap=120)
        self.setup_files()

    def setup_files(self):
        self.once('files-launch')
        provider_fd = None
        primary_error = None
        try:
            try:
                launched = self.sim('files-launch','launch',self.owned,FILES_BUNDLE)
                require(re.fullmatch(re.escape(FILES_BUNDLE)+r': [1-9][0-9]*',launched.strip()),'Files launch PID missing')
                output = self.sim('files-group','get_app_container',self.owned,FILES_BUNDLE,'groups')
                pairs = [line.split('\t') for line in output.splitlines() if line.strip()]
                require(all(len(x)==2 and all(x) for x in pairs),'Malformed Files group list')
                matches = [value for key,value in pairs if key==GROUP]
                require(len(matches)==1,'Missing or ambiguous local Files group')
                group = self.owned_path(matches[0],('data','Containers','Shared','AppGroup'))
                provider = group/'File Provider Storage'
                self.provider_id = identity_of(provider)
                provider_fd = os.open(provider,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                st = os.fstat(provider_fd)
                require([st.st_dev,st.st_ino]==self.provider_id,'Provider changed during open')
            except BaseException as error:
                primary_error = error
                self.report['files_setup_primary_error'] = repr(error)
                raise
            finally:
                if not self.active and not self.unknown_spawn:
                    try:
                        self.once('files-terminate')
                        self.sim('files-terminate','terminate',self.owned,FILES_BUNDLE)
                    except BaseException as error:
                        self.report['files_setup_terminate_error'] = repr(error)
                        if primary_error is None:
                            raise
            # The async termination boundary cannot turn a checked pathname
            # into permission to create a folder through a replaced symlink.
            self.owned_root()
            require(identity_of(provider)==self.provider_id,'Provider changed before mkdir')
            st = os.fstat(provider_fd)
            require([st.st_dev,st.st_ino]==self.provider_id,'Pinned provider descriptor changed')
            os.mkdir(self.folder_name,mode=0o700,dir_fd=provider_fd)
            child_fd = os.open(self.folder_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=provider_fd)
            try:
                child = os.fstat(child_fd)
                self.folder_id = [child.st_dev,child.st_ino]
                require(not os.listdir(child_fd),'Owned folder did not start empty')
            finally: os.close(child_fd)
            self.folder = provider/self.folder_name
            self.verify_folder()
            self.report['files_folder'] = {'path':str(self.folder),'identity':self.folder_id,'provider_identity':self.provider_id,'initially_empty':True}
            self.save()
        finally:
            if provider_fd is not None: os.close(provider_fd)

    def verify_folder(self):
        self.owned_root()
        require(self.folder is not None and identity_of(self.folder)==self.folder_id
                and identity_of(self.folder.parent)==self.provider_id,'Files ownership changed')

    def copy_tree(self, source, target, manifest):
        self.checkpoint()
        target.mkdir(mode=0o700)
        for relative, item in manifest.items():
            self.checkpoint()
            destination = target/relative
            if item['kind']=='directory':
                destination.mkdir(mode=0o700)
            else:
                fd = os.open(source/relative,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                with os.fdopen(fd,'rb') as inp, destination.open('xb') as out:
                    while chunk := inp.read(MIB):
                        self.checkpoint()
                        out.write(chunk)
                destination.chmod(item['mode'])
        for relative,item in reversed(list(manifest.items())):
            if item['kind']=='directory': (target/relative).chmod(item['mode'])
        require(tree_manifest(target,self.checkpoint)==manifest,'Copied evidence mismatch')
        require(tree_manifest(source,self.checkpoint)==manifest,'Original changed during copy')

    def preserve_result(self, phase):
        raw = self.out/(phase+'.xcresult')
        manifest = tree_manifest(raw,self.checkpoint)
        require(manifest,'Empty xcresult')
        reference = self.persist(phase+'-original-manifest.json',manifest)
        self.originals[phase] = manifest
        self.report.setdefault('original_results',{})[phase] = reference
        self.save()  # Original manifest is durable before any reader starts.
        copy = self.out/(phase+'-inspection.xcresult')
        self.copy_tree(raw,copy,manifest)
        return copy

    def verify_original_results(self):
        for phase,manifest in self.originals.items():
            require(tree_manifest(self.out/(phase+'.xcresult'),self.checkpoint)==manifest,'Original xcresult changed or disappeared')

    def read_result(self, phase, copy, diagnostic=False):
        summary = json.loads(self.command(phase+'-summary',['/usr/bin/xcrun','xcresulttool','get','test-results','summary','--path',str(copy),'--compact'],30))
        tree = json.loads(self.command(phase+'-tests',['/usr/bin/xcrun','xcresulttool','get','test-results','tests','--path',str(copy),'--compact'],30))
        validation_error = None
        try: validate_result(summary,tree,CASES[phase],self.owned)
        except BaseException as error: validation_error = error
        if validation_error is None and not diagnostic:
            self.report.setdefault('phase_passed',{})[phase] = True
        self.persist(phase+'-parsed-tests.json',{'summary':summary,'tests':tree})
        destination = self.out/(phase+'-attachments')
        require(not destination.exists(),'Attachment destination preexists')
        self.command(phase+'-attachments',['/usr/bin/xcrun','xcresulttool','export','attachments','--path',str(copy),'--output-path',str(destination),'--test-id',CASES[phase]],60)
        attachments = tree_manifest(destination,self.checkpoint)
        require(any(n.endswith('.png') for n in attachments) and any(n.endswith('.txt') for n in attachments),'Missing PNG or AX attachments')
        self.persist(phase+'-attachment-manifest.json',attachments)
        self.verify_original_results()
        if validation_error is not None and not diagnostic: raise validation_error

    def app_state(self, phase):
        bundle = self.owned_path(self.sim(phase+'-bundle','get_app_container',self.owned,BUNDLE,'app'),
                                 ('data','Containers','Bundle','Application'),'Tripfolio.app')
        manifest = tree_manifest(bundle,self.checkpoint,256*MIB)
        require('Tripfolio' in manifest and manifest['Tripfolio']['mode']&0o111,'App executable missing')
        if 'app_manifest' in self.report: require(manifest==self.report['app_manifest'],'App changed across phases')
        self.report['app_manifest'] = manifest
        # Exact executable path, not a substring of a bundle ID or a global kill.
        processes = self.command(phase+'-app-stopped',['/bin/ps','-axww','-o','pid=,command='],20)
        executable = str(bundle/'Tripfolio')
        records = [record for record in self.report['commands'] if record['id']==phase+'-app-stopped']
        require(len(records)==1 and records[0].get('returncode')==0
                and type(records[0].get('pgid')) is int, 'Unbound process listing')
        reader_pid = records[0]['pgid']
        reader_seen = False
        require(processes.strip(), 'Empty process listing cannot prove the app stopped')
        for line in processes.splitlines():
            match = re.fullmatch(r'\s*([0-9]+)\s+(.*)',line)
            require(match is not None,'Unexpected process listing')
            command = match.group(2)
            if int(match.group(1)) == reader_pid:
                require(command.startswith('/bin/ps ') or command.startswith('ps '), 'Process reader PID has unexpected command')
                reader_seen = True
            require(command != executable and not command.startswith(executable+' ')
                    and command != 'Tripfolio' and not command.startswith('Tripfolio '),
                    'App running or ambiguous at snapshot boundary')
        require(reader_seen, 'Process listing omitted its own reader')
        data = self.owned_path(self.sim(phase+'-data','get_app_container',self.owned,BUNDLE,'data'),
                               ('data','Containers','Data','Application'))
        root = data/'Library/Application Support/TripfolioUITesting'
        identity_of(root)
        self.source()
        return root

    def phase_argv(self, phase):
        return [self.host['developer_dir']+'/usr/bin/xcodebuild','-project','Tripfolio.xcodeproj','-scheme','Tripfolio',
                '-configuration','Debug','-destination','platform=iOS Simulator,id='+self.owned,
                '-destination-timeout','30','-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1',
                '-collect-test-diagnostics','never','-default-test-execution-time-allowance','300',
                '-maximum-test-execution-time-allowance','300','-derivedDataPath',str(self.out/'DerivedData'),
                '-resultBundlePath',str(self.out/(phase+'.xcresult')),
                '-only-testing:TripfolioUITests/'+CASES[phase].removesuffix('()'),'CODE_SIGNING_ALLOWED=NO','test']

    def run_phase(self, phase):
        require(phase in CASES,'Unknown phase')
        if phase=='restore': self.authorize_restore()
        self.verify_folder()
        self.once('phase-'+phase)
        old_env,old_cwd = self.ops.env,self.ops.cwd
        self.ops.env = {**old_env,'TEST_RUNNER_TRIPDOCKET_RECOVERY_UI':'1',
                        'TEST_RUNNER_TRIPDOCKET_RECOVERY_PHASE':phase,'TEST_RUNNER_TRIPDOCKET_RECOVERY_FOLDER':self.folder_name,
                        'TEST_RUNNER_NSUnbufferedIO':'YES','NSUnbufferedIO':'YES'}
        self.ops.cwd = self.candidate
        try:
            self.command('phase-'+phase,self.phase_argv(phase),CAPS['phase_seconds'])
        except BaseException:
            self.failure_evidence(phase)
            raise
        finally:
            self.ops.env,self.ops.cwd = old_env,old_cwd
        copy = self.preserve_result(phase)
        self.read_result(phase,copy)
        return self.app_state(phase)

    def failure_evidence(self, phase):
        row = self.report.setdefault('failure_evidence',{}).setdefault(phase,{'preserved':False})
        original_limit = self.limit
        try:
            require(not self.active and not self.unknown_spawn, 'Writer ownership unresolved')
            require(original_limit-self.ops.now() > 10, 'No work budget remains for failure evidence')
            self.limit = min(original_limit,self.ops.now()+60)
            raw = self.out/(phase+'.xcresult')
            require(raw.is_dir() and not raw.is_symlink(), 'No complete result directory was produced')
            copy = self.preserve_result(phase)
            row['preserved'] = True
            row['manifest'] = self.report['original_results'][phase]
            # Diagnostic readers never mark a phase passed and never run a test.
            self.read_result(phase,copy,diagnostic=True)
            row['diagnostics_complete'] = True
        except BaseException as error:
            row['unpreserved_or_incomplete_reason'] = repr(error)
        finally:
            self.limit = original_limit
            self.save()

    def comparator(self, label, args):
        self.verify_folder()
        self.source()
        raw = self.command(label,[self.host['python'],'-B',str(self.candidate/'scripts/verify-recovery-evidence.py'),
                                *args,'--files-folder',str(self.folder)],45)
        result = json.loads(raw)
        require(result.get('comparison')=='PASS' and result.get('ui_execution_accepted') is False
                and result.get('pixel_review_accepted') is False,'Comparator did not return bounded evidence PASS')
        return result

    def snapshot_valid(self, path, pin):
        require(file_digest(path/'manifest.json',self.checkpoint)==pin,'Snapshot manifest changed')
        manifest = json_file(path/'manifest.json',16384)
        required = {'active-before.json','catalog-before.json','original-before.pdf','Documents.tripbackup'}
        require(manifest.get('format')==1 and manifest.get('scope')=='offline-synthetic-equality-only'
                and set(manifest.get('files',{}))==required,'Incomplete snapshot manifest')
        require({p.name for p in path.iterdir()}==required|{'manifest.json'},'Unexpected snapshot contents')
        for name,item in manifest['files'].items():
            require(file_digest(path/name,self.checkpoint)==item['sha256'] and (path/name).stat().st_size==item['bytes'],'Incomplete or changed snapshot')
        self.verify_folder()
        require(file_digest(self.folder/'Documents.tripbackup',self.checkpoint)==manifest['files']['Documents.tripbackup']['sha256'],
                'UI backup changed after snapshot')
        return manifest

    def take_snapshot(self, library):
        result = self.comparator('before-snapshot',['snapshot','--library-root',str(library),'--output',str(self.out/'BeforeReset')])
        require(result.get('stage')=='snapshot','Wrong snapshot stage')
        pin = result['manifest_sha256']
        self.snapshot_valid(self.out/'BeforeReset',pin)
        self.before_pin = pin
        self.report['before_reset_pin'] = pin
        self.save()
        require(json_file(self.out/'receipt.json')['before_reset_pin']==pin,'Snapshot pin was not durably recorded')

    def authorize_restore(self):
        require(self.report.get('phase_passed',{}).get('export') is True and self.before_pin,'Export or snapshot gate incomplete')
        require(json_file(self.out/'receipt.json').get('before_reset_pin')==self.before_pin,'Durable snapshot pin missing')
        self.snapshot_valid(self.out/'BeforeReset',self.before_pin)
        self.verify_original_results()

    def work(self):
        self.setup()
        library = self.run_phase('export')
        self.take_snapshot(library)
        library = self.run_phase('restore')
        result = self.comparator('after-compare',['compare','--library-root',str(library),'--baseline',str(self.out/'BeforeReset'),
                                                '--expected-manifest-sha256',self.before_pin])
        require(result.get('stage')=='compare' and all(result.get(k) is True for k in
                ['metadata_equal','original_bytes_equal','backup_unchanged','new_active_generation']),'Incomplete restored equality')
        self.persist('comparison.json',result)
        after = self.comparator('after-snapshot',['snapshot','--library-root',str(library),'--output',str(self.out/'AfterRestore')])
        self.snapshot_valid(self.out/'AfterRestore',after['manifest_sha256'])
        self.report['after_restore_pin'] = after['manifest_sha256']
        self.verify_original_results()
        self.source()
        self.monitor()
        self.report['work_complete'] = True
        self.save()

    def cleanup(self):
        self.cleaning,self.phase = True,'cleanup'
        self.write_deadline = min(self.final,self.ops.now()+CAPS['cleanup_seconds'])
        self.limit = self.write_deadline-CAPS['receipt_seconds']
        if self.active or self.unknown_spawn:
            self.error('Unresolved process ownership; all further child processes withheld')
            return
        if self.create_attempted and self.owned is None and not self.recovered:
            try: self.recover(json.loads(self.sim('recover-created','list','devices','--json',cap=20)))
            except BaseException as error: self.error('Create recovery: '+repr(error))
        if self.owned:
            try:
                self.owned_root()
                for label in ['shutdown','delete']:
                    if self.active or self.unknown_spawn: break
                    try:
                        self.once(label)
                        self.sim(label,label,self.owned,cap=30)
                    except BaseException as error: self.error('Cleanup '+label+': '+repr(error))
            except BaseException as error: self.error('Owned root: '+repr(error))
        if self.create_attempted and not self.active and not self.unknown_spawn:
            try:
                final = json.loads(self.sim('final-inventory','list','devices','--json',cap=20))
                self.report['final_inventory'] = final
                root = Path.home()/'Library/Developer/CoreSimulator/Devices'/(self.owned or '')
                self.report['cleanup_verified'] = (self.owned is not None and final==self.report['baseline']
                                                   and not os.path.lexists(root))
                require(self.report['cleanup_verified'],'Final inventory or owned root differs')
            except BaseException as error: self.error('Final inventory: '+repr(error))
        elif not self.create_attempted:
            self.report['cleanup_verified'] = True

    def run(self):
        require(not self.report.get('run_started'),'Run already attempted')
        self.report['run_started'] = True
        self.save()
        try: self.work()
        except BaseException as error: self.error('Work: '+repr(error))
        finally:
            try: self.cleanup()
            except BaseException as error: self.error('Cleanup: '+repr(error))
            self.phase,self.limit = 'receipt',self.write_deadline
            if self.interrupted: self.error('Interrupted')
            good = (not self.report['errors'] and self.report.get('work_complete') is True
                    and self.report['cleanup_verified'] and not self.active and not self.unknown_spawn)
            self.report['status'] = 'completed_pending_independent_ui_and_pixel_review' if good else 'failed'
            self.report['unresolved_groups'] = sorted(self.active)
            self.report['unknown_spawn'] = self.unknown_spawn
            self.save()
        return 0 if good else 1


def validate_result(summary, tree, case, device):
    counts = {'totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0}
    require(summary.get('result')=='Passed' and all(type(summary.get(k)) is int and summary[k]==v for k,v in counts.items()),'Unexpected result counts')
    nodes,cases = list(tree['testNodes']),[]
    while nodes:
        require(len(nodes)<10000 and len(cases)<2,'Unexpected result tree size')
        node=nodes.pop();nodes.extend(node.get('children',[]))
        if node.get('nodeType')=='Test Case': cases.append((node.get('nodeIdentifier'),node.get('result')))
    require(cases==[(case,'Passed')],'Expected exactly the selected passing case')
    require([{'id':d.get('deviceId','').upper(),'platform':d.get('platform')} for d in tree['devices']]
            ==[{'id':device,'platform':'iOS Simulator'}],'Unexpected result device')
    configurations=summary.get('devicesAndConfigurations',[])
    require(len(configurations)==1 and configurations[0].get('device',{}).get('deviceId','').upper()==device,'Unexpected result configuration')




