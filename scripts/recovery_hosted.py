#!/usr/bin/env python3
"""One bounded GitHub-hosted recovery job. Default CLI performs no work."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import stat
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
CORE_SHA = 'f1f21348a04c67964876e5b122e0738e83ddba4c59d4a73c50c8fa795971c7f6'
if hashlib.sha256((HERE/'recovery_core.py').read_bytes()).hexdigest() != CORE_SHA:
    raise RuntimeError('Recovery core changed before import')
spec = importlib.util.spec_from_file_location('hosted_recovery_core',HERE/'recovery_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
require = core.require


def job_context(env, profile, machine):
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('CI') == 'true','Not a CI job')
    require(env.get('GITHUB_REPOSITORY') == profile['repository'],'Wrong repository')
    require(env.get('GITHUB_JOB') == 'recovery' and env.get('GITHUB_WORKFLOW') == 'CI','Wrong job')
    require(env.get('TRIPDOCKET_RUNNER_LABEL') == profile['runner_label'],'Wrong runner label')
    require(env.get('TRIPDOCKET_RUNNER_ENVIRONMENT') == profile['runner_environment'],'Not hosted')
    require(env.get('RUNNER_OS') == 'macOS' and env.get('TRIPDOCKET_RUNNER_ARCH') == profile['runner_arch']
            and machine == profile['machine'],'Unexpected architecture')
    require(env.get('ImageOS','').startswith(profile['image_os_prefix']) and bool(env.get('ImageVersion')),
            'Missing or mismatched image identity')
    attempt=env.get('GITHUB_RUN_ATTEMPT')
    require(isinstance(attempt,str) and re.fullmatch(r'[1-9][0-9]*',attempt) is not None,
            'Invalid workflow run attempt')
    require(re.fullmatch(r'[0-9]+',env.get('GITHUB_RUN_ID','')) is not None,'Invalid run ID')
    require(env.get('GITHUB_EVENT_NAME') in ['pull_request','push','workflow_dispatch','merge_group'],'Unsupported event')
    require(re.fullmatch(r'[0-9a-f]{40}',env.get('GITHUB_SHA','')) is not None,'Invalid event SHA')
    require(not any(k.startswith(('SIMCTL_CHILD_','DYLD_','XCTest','TEST_RUNNER_')) for k in env),
            'Injected process environment')
    return {k:env[k] for k in ['GITHUB_REPOSITORY','GITHUB_WORKFLOW','GITHUB_JOB','GITHUB_EVENT_NAME',
            'GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REF','GITHUB_SHA','ImageOS','ImageVersion',
            'TRIPDOCKET_RUNNER_LABEL','TRIPDOCKET_RUNNER_ARCH','TRIPDOCKET_RUNNER_ENVIRONMENT']}


def attempt_output(workspace, job):
    out=Path(workspace)/'build'/('RecoveryHosted-'+job['GITHUB_RUN_ID']+'-'+job['GITHUB_RUN_ATTEMPT'])
    require(not os.path.lexists(out),'Existing recovery attempt is never reused')
    out.parent.mkdir(exist_ok=True);core.identity_of(out.parent)
    return out


def parse_commit(raw, expected):
    payload = raw.encode('utf-8')
    oid = hashlib.sha1(b'commit '+str(len(payload)).encode()+b'\0'+payload).hexdigest()
    require(oid == expected,'Raw Git commit identity mismatch')
    header,separator,_ = raw.partition('\n\n')
    require(separator,'Missing commit header')
    lines = header.splitlines()
    trees = [line[5:] for line in lines if line.startswith('tree ')]
    parents = [line[7:] for line in lines if line.startswith('parent ')]
    require(len(trees)==1 and all(re.fullmatch(r'[0-9a-f]{40}',s) for s in trees+parents),'Malformed commit')
    return {'commit':expected,'tree':trees[0],'parents':parents,
            'signature_present':any(line.startswith('gpgsig ') for line in lines),
            'signature_cryptographically_verified_here':False}


def source_event(job, event, commit):
    require(event.get('repository',{}).get('full_name') == job['GITHUB_REPOSITORY'],'Event repository mismatch')
    require(commit['commit'] == job['GITHUB_SHA'],'Checkout differs from event commit')
    kind = job['GITHUB_EVENT_NAME']
    result = {'kind':kind,'checkout':commit}
    if kind == 'pull_request':
        pr = event['pull_request']
        require(pr['head']['repo']['full_name'] == job['GITHUB_REPOSITORY'],'Foreign PR head not admitted')
        head,base = pr['head']['sha'],pr['base']['sha']
        require(commit['parents'] == [base,head],'PR merge parents do not match event head/base')
        result.update(pr_head=head,pr_base=base,pr_number=event['number'])
    elif kind == 'merge_group':
        require(event['merge_group']['head_sha'] == commit['commit'],'Merge-group checkout mismatch')
        result['merge_group_base'] = event['merge_group']['base_sha']
    elif kind == 'push':
        require(event.get('after') == commit['commit'] and job['GITHUB_REF']=='refs/heads/main','Push identity mismatch')
    return result


def parse_tree(raw):
    require(raw.endswith('\0'),'Truncated Git tree inventory')
    result = {}
    for entry in raw[:-1].split('\0'):
        metadata,name = entry.split('\t',1)
        mode,kind,oid = metadata.split(' ')
        path = PurePosixPath(name)
        require(mode in ['100644','100755'] and kind=='blob','Unsupported Git object type')
        require(re.fullmatch(r'[0-9a-f]{40}',oid) is not None,'Invalid Git blob')
        require(not path.is_absolute() and path.parts and '..' not in path.parts and '.' not in path.parts
                and path.as_posix()==name and path.parts[0] not in ['.git','build']
                and not any(c in name for c in '\n\r\0') and name not in result,'Unsafe or duplicate source path')
        result[name]={'oid':oid,'executable':mode=='100755'}
    require(0<len(result)<10000,'Unexpected source inventory size')
    return result


def select_runtime(sdk, inventory, profile):
    require(re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}',sdk) is not None,'Unknown SDK version')
    runtimes=inventory.get('runtimes')
    require(isinstance(runtimes,list) and all(isinstance(r,dict) for r in runtimes),'Unknown runtime inventory')
    matches=[r for r in runtimes if r.get('version')==sdk and r.get('identifier','').startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
    require(len(matches)==1,'No unique exact SDK-matched installed runtime')
    selected=matches[0]
    require(selected.get('isAvailable') is True,'SDK-matched runtime unavailable')
    arches=selected.get('supportedArchitectures');devices=selected.get('supportedDeviceTypes')
    require(isinstance(arches,list) and all(isinstance(a,str) for a in arches)
            and profile['machine'] in arches,'Installed runtime architecture not established')
    require(isinstance(devices,list) and all(isinstance(d,dict) for d in devices)
            and len([d for d in devices if d.get('identifier')==profile['device_type']])==1,
            'Selected runtime does not uniquely support required phone')
    return selected


def toolchain_paths(developer,sdk=None):
    require(developer.is_absolute() and len(developer.parts)==5 and developer.parts[1]=='Applications'
            and developer.parts[2].endswith('.app') and developer.parts[-2:]==('Contents','Developer'),
            'Selected Xcode is not an installed application')
    if sdk is not None:require(sdk.is_relative_to(developer),'SDK belongs to another Xcode')


CAPABILITY_CHILD = r'''
import json,os,signal,subprocess,sys,time
mode=sys.argv[1]
print(json.dumps(dict(kind=mode,pid=os.getpid(),ppid=os.getppid(),pgid=os.getpgrp())),flush=True)
if mode=='normal':sys.exit(0)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
if mode=='parent':subprocess.Popen([sys.executable,'-I','-c',sys.argv[2],'descendant'])
deadline=time.monotonic()+25
while time.monotonic()<deadline:time.sleep(.1)
'''


def capability_result(normal, failed, observations, elapsed, actual):
    require(actual is True,'Injected boundary cannot approve actual capability')
    require(normal.get('outcome')=='completed' and normal.get('returncode')==0
            and not normal.get('error'),'Normal capability command failed')
    require(failed.get('outcome')=='failed','Timeout capability outcome missing')
    for row in [normal,failed]:
        require(not any(row.get(key) for key in ['log_close_errors','receipt_error','stdout_read_error',
                                                'finalization_error','cap_error']),
                'Capability command finalization failed')
        stop=row.get('stop',{})
        require(stop.get('group_absent') is True and stop.get('leader_reaped') is True
                and not stop.get('error') and not row.get('stop_error') and not row.get('close_error'),
                'Capability group cleanup incomplete')
    require(failed.get('error')=="RuntimeError('Command timeout')"
            and failed['stop'].get('signals')==[int(signal.SIGTERM),int(signal.SIGKILL)],'Expected bounded timeout not observed')
    for sig in [signal.SIGTERM,signal.SIGKILL]:
        row=failed.get('process_observations',{}).get('stop.signal_'+str(int(sig)),{})
        require(row.get('calls')==1 and row.get('outcome')=='returned'
                and row.get('result')=='syscall_returned',
                'Capability signal syscall outcome not established')
    require(0<=elapsed<=60 and 0<=failed['finish']-failed['start']<=20,'Capability exceeded cap')
    normal_rows,failed_rows=observations
    require(len(normal_rows)==1 and normal_rows[0]['kind']=='normal'
            and normal_rows[0]['pid']==normal_rows[0]['pgid']==normal['pgid'],'Normal process identity mismatch')
    require(len(failed_rows)==2,'Missing capability lineage')
    parent=next((r for r in failed_rows if r.get('kind')=='parent'),{})
    child=next((r for r in failed_rows if r.get('kind')=='descendant'),{})
    require(parent.get('pid')==parent.get('pgid')==failed['pgid']
            and child.get('ppid')==parent['pid'] and child.get('pgid')==parent['pid']
            and child.get('pid')!=parent['pid'],'Descendant ownership mismatch')
    return {'actual_execution':True,'approved':True,'scope':'owned subprocess boundary only',
            'owned_group_absence':True,'leader_reaped':True,'bounded_stop':True,'failure_receipt':True}


class HostedRecovery(core.Recovery):
    def __init__(self,ops,out,profile,job,event,workspace,started):
        self.profile,self.job,self.event,self.workspace=profile,job,event,Path(workspace)
        plan={'runtime':'UNSELECTED','device_type':profile['device_type']}
        host={'machine':profile['machine'],'python':str(Path(sys.executable).resolve())}
        run_id=str(uuid.uuid5(uuid.NAMESPACE_URL,job['GITHUB_REPOSITORY']+'/'+job['GITHUB_RUN_ID']+'/recovery/'+job['GITHUB_RUN_ATTEMPT']))
        super().__init__(ops,out,plan,host,run_id,started,candidate=Path(out)/'Source',source_manifest={})
        self.report['job']=job
        self.save()  # Persist the actual run/attempt before any process acquisition.

    def sim(self,label,*args,cap=30):
        # Only the initial owned Files preparation gets a larger command cap.
        action={'files-launch':'launch','files-terminate':'terminate'}.get(label)
        if action:
            require(self.owned and args==(action,self.owned,core.FILES_BUNDLE) and cap==30,
                    'Unexpected Files preparation command')
            cap=120 if label=='files-launch' else 60
        if label=='files-group':
            require(self.owned and args==('get_app_container',self.owned,core.FILES_BUNDLE,'groups') and cap==30,
                    'Unexpected Files group lookup')
            cap=60
        return super().sim(label,*args,cap=cap)

    def accept_nonzero_exit(self, p, record, handles):
        # simctl may find Files already stopped after its successful launch.
        # Recognize only the observed response for this one preparation action;
        # command() still verifies stop, pipe/log closure, finalization and cap.
        if record.get('id')!='files-terminate' or p.returncode!=3:
            return False
        first=getattr(self,'_files_setup_command_start',None)
        rows=self.report['commands']
        if (type(first) is not int or len(rows)!=first+3 or rows[-1] is not record
                or [r['id'] for r in rows[first:]]!=['files-launch','files-group','files-terminate']):
            return False
        expected=[['/usr/bin/xcrun','simctl',action,self.owned,core.FILES_BUNDLE]
                  for action in ('launch','get_app_container','terminate')]
        expected[1].append('groups')
        if (any(r.get('argv')!=argv for r,argv in zip(rows[first:],expected))
                or any(r.get('outcome')!='completed' or r.get('returncode')!=0 or r.get('error')
                       for r in rows[first:first+2])):
            return False
        require(self.active=={p.pid:p} and p.pid==record.get('pgid')
                and p.pid in self.absent_groups and not self.unknown_spawn,
                'Files termination process ownership unresolved')
        def check():
            self.timecheck()
            require(self.ops.now()<self.t0+record['work_deadline'],
                    'Files termination classification deadline reached')
        check()
        self.owned_root()
        require(self.provider_id is not None,'Files provider was not established')
        require(core.identity_of(self.out)==self.output_id,'Output root changed during Files termination')
        diagnostic=(
            'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\n'
            'Simulator device failed to terminate com.apple.DocumentsApp.\n'
            'found nothing to terminate\n'
            'Underlying error (domain=NSPOSIXErrorDomain, code=3):\n'
            '\tThe request to terminate "com.apple.DocumentsApp" failed. found nothing to terminate\n'
            '\tfound nothing to terminate\n').encode('utf-8')
        if record.get('bytes')!={'stdout':0,'stderr':len(diagnostic)}:
            return False
        require(set(handles)=={'stdout','stderr'},'Files termination streams missing')
        for stream in handles.values():
            check();stream.flush();check()
        path=Path(record['logs']['stderr'])
        require(path==self.out/(str(len(rows))+'-stderr.log') and path.resolve(strict=True)==path
                and not path.is_symlink() and path.is_file(),'Unexpected Files termination log path')
        check()
        with path.open('rb') as stream:
            info=os.fstat(stream.fileno());writer=os.fstat(handles['stderr'].fileno())
            require((info.st_dev,info.st_ino)==(writer.st_dev,writer.st_ino)
                    and info.st_size==len(diagnostic),'Files termination log changed')
            check();actual=stream.read(len(diagnostic)+1);check()
        if actual!=diagnostic:
            return False
        check()
        record['accepted_nonzero_exit']={'kind':'simctl_reported_files_already_absent',
                                         'returncode':3,'stderr_sha256':hashlib.sha256(actual).hexdigest()}
        return True

    def capture_source(self):
        require(not self.command('git-clean',['/usr/bin/git','status','--porcelain'],20).strip(),'Checkout is not clean')
        head=self.command('git-head',['/usr/bin/git','rev-parse','HEAD'],20).strip()
        commit=parse_commit(self.command('git-commit',['/usr/bin/git','cat-file','commit',head],20),head)
        context=source_event(self.job,self.event,commit)
        if 'pr_head' in context:
            signed=parse_commit(self.command('git-pr-head',['/usr/bin/git','cat-file','commit',context['pr_head']],20),context['pr_head'])
            require(signed['signature_present'],'PR head lacks required signature record')
            context['pr_head_commit']=signed
        entries=parse_tree(self.command('git-tree',['/usr/bin/git','ls-tree','-rz','--full-tree',head],30))
        self.candidate.mkdir(mode=0o700)
        total=0
        for name,item in entries.items():
            self.checkpoint()
            source=self.workspace/name
            require(source.resolve(strict=True)==source and stat.S_ISREG(source.lstat().st_mode),'Source path is not a regular canonical file')
            require(source.stat().st_size<=64*core.MIB,'Oversized source file')
            with source.open('rb') as stream:data=stream.read(64*core.MIB+1)
            require(len(data)<=64*core.MIB,'Oversized source file')
            total+=len(data);require(total<=64*core.MIB,'Source snapshot exceeds cap')
            blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            require(blob==item['oid'] and bool(source.stat().st_mode&0o111)==item['executable'],'Checkout differs from Git blob')
            target=self.candidate/name;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(data)
            target.chmod(0o755 if item['executable'] else 0o644)
            self.source_manifest[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'executable':item['executable']}
        require('Tripfolio.xcodeproj/project.pbxproj' in self.source_manifest,'Missing checked-in Xcode project')
        self.report['source_identity']=self.persist('source-identity.json',context)
        self.report['source_manifest']=self.persist('source-manifest.json',self.source_manifest)
        self.source()
        self.save()

    def source(self):
        super().source()
        for name,expected in self.source_manifest.items():
            self.checkpoint();path=self.workspace/name
            require(path.resolve(strict=True)==path and core.file_digest(path,self.checkpoint)==expected['sha256']
                    and bool(path.stat().st_mode&0o111)==expected['executable'],'Checkout changed after snapshot')

    def discover_profile(self):
        selected=self.command('selected-xcode',['/usr/bin/xcode-select','-p'],20).strip()
        developer=Path(selected).resolve(strict=True)
        toolchain_paths(developer)
        core.identity_of(developer)
        self.host['developer_dir']=str(developer);self.ops.env['DEVELOPER_DIR']=str(developer)
        version=self.command('xcode-version',[str(developer/'usr/bin/xcodebuild'),'-version'],20).strip()
        match=re.fullmatch(r'Xcode ([0-9]+)(?:\.[0-9]+){0,2}\nBuild version ([A-Za-z0-9]+)',version)
        require(len(version)<=128 and match and int(match[1])>=self.profile['xcode_minimum_major'],'Unsupported Xcode')
        sdk=self.command('sdk-version',['/usr/bin/xcrun','--sdk','iphonesimulator','--show-sdk-version'],20).strip()
        sdk_path=Path(self.command('sdk-path',['/usr/bin/xcrun','--sdk','iphonesimulator','--show-sdk-path'],20).strip()).resolve(strict=True)
        toolchain_paths(developer,sdk_path)
        # Publish only bounded toolchain facts in the existing receipt allowlist.
        # The first runtime query gets 112s work + 8s stop inside the same global
        # budget. This is a finite scheduling policy, not a proven OS fix.
        discovery={'xcode_version':version,'developer_dir':str(developer),
                   'sdk_version':sdk if len(sdk)<=32 and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}',sdk) else 'INVALID_FORMAT',
                   'sdk_path':str(sdk_path),'runtime_inventory_cap_seconds':120,
                   'runtime_inventory_status':'pending'}
        self.report['profile_discovery']=discovery
        raw_inventory=self.sim('profile-runtimes','list','runtimes','--json',cap=120)
        inventory_command=self.report['commands'][-1]
        require(self.ops.now() < self.t0+inventory_command['work_deadline'],
                'Initial runtime inventory work deadline reached')
        discovery.update(runtime_inventory_status='returned',
                         runtime_inventory_utf8_bytes=len(raw_inventory.encode()),
                         runtime_inventory_sha256=hashlib.sha256(raw_inventory.encode()).hexdigest())
        inventory=json.loads(raw_inventory)
        runtime=select_runtime(sdk,inventory,self.profile)
        self.plan['runtime']=runtime['identifier'];self.intent['runtime']=runtime['identifier']
        paths=[Path(self.host['python']),Path('/usr/bin/git'),Path('/usr/bin/xcrun'),Path('/bin/ps'),
               developer/'usr/bin/xcodebuild',developer/'usr/bin/simctl']
        self.host.update(xcode_version=version,sdk_version=sdk,sdk_path=str(sdk_path),
                         tools={str(p):core.file_digest(p,self.checkpoint) for p in paths})
        self.report['resolved_profile']=self.persist('resolved-profile.json',{'policy':self.profile,'host':self.host,'runtime':runtime})
        self.save()

    def check_capability(self):
        started=self.ops.now()
        original_limit=self.limit;self.limit=min(original_limit,started+self.profile['prep_seconds'])
        probe=None
        try:
            self.checkpoint()
            probe=core.Recovery(self.ops,self.out/'Capability',self.plan,self.host,self.folder_name.removeprefix('TripDocket-Recovery-'),
                                self.t0,candidate=self.candidate,source_manifest=self.source_manifest)
            probe.limit=self.limit;probe.write_deadline=self.limit
            # The parent owns the output tree; the probe owns the pending
            # command and its stop reserve. Keep both contexts for each scan.
            probe.checkpoint=lambda *,force_resources=False: self.checkpoint(
                force_resources=force_resources,command_owner=probe)
            probe.log_total=self.log_total
            probe.command('normal',[self.host['python'],'-I','-c',CAPABILITY_CHILD,'normal'],15)
            try:probe.command('controlled-timeout',[self.host['python'],'-I','-c',CAPABILITY_CHILD,'parent',CAPABILITY_CHILD],20)
            except RuntimeError:pass
            else:raise RuntimeError('Timeout capability command unexpectedly succeeded')
            probe.save()
            saved=core.json_file(probe.out/'receipt.json')
            require(saved['commands']==probe.report['commands'] and len(saved['commands'])==2,'Failure receipt not preserved')
            observations=[[json.loads(line) for line in Path(r['logs']['stdout']).read_text().splitlines()] for r in saved['commands']]
            result=capability_result(*saved['commands'],observations,self.ops.now()-started,type(self.ops) is core.base.RealOps)
            require(not probe.active and not probe.unknown_spawn,'Capability has unresolved process ownership')
            result.update(job=self.job,host=self.host,source_manifest=self.report['source_manifest'],
                          raw_receipt_sha256=core.file_digest(probe.out/'receipt.json',self.checkpoint))
            self.report['host_capability']=self.persist('host-capability.json',result)
            self.save()
            self.checkpoint()  # Receipt/hash/persist are part of the same prep deadline.
        finally:
            if probe is not None:
                self.log_total=probe.log_total
                self.active.update(probe.active);self.unknown_spawn=self.unknown_spawn or probe.unknown_spawn
            self.limit=original_limit

    def setup(self):
        require(shutil.disk_usage(self.out).free>=core.CAPS['admission_free_bytes'],'Hosted admission space below 16GiB')
        self.capture_source()
        self.discover_profile()
        self.check_capability()
        super().setup()

    def setup_files(self):
        first=len(self.report['commands'])
        primary=None
        require(not hasattr(self,'_files_setup_command_start'),'Files setup already active')
        self._files_setup_command_start=first
        try:
            return super().setup_files()
        except BaseException as error:
            primary=error
            raise
        finally:
            del self._files_setup_command_start
            try:
                self.retain_files_logs(first)
                self.save()
            except BaseException as error:
                self.report['files_log_publication_error']=repr(error)
                self.error('Files log publication: '+repr(error))
                if primary is None:
                    raise

    def retain_files_logs(self, first):
        # Raw root logs include ps output and must never be uploaded wholesale.
        # Move only closed streams of these exact owned Files commands. No copy
        # doubles their resource charge and no extra native command is needed.
        seen=set()
        for index,record in enumerate(self.report['commands'][first:],start=first):
            action={'files-launch':'launch','files-terminate':'terminate'}.get(record['id'])
            if action is None:
                continue
            self.timecheck()
            require(record['id'] not in seen,'Duplicate Files log command')
            seen.add(record['id'])
            require(self.owned and record.get('argv')==['/usr/bin/xcrun','simctl',action,self.owned,core.FILES_BUNDLE],
                    'Unexpected Files log command')
            stop=record.get('stop',{})
            require(not self.active and not self.unknown_spawn and stop.get('leader_reaped') is True
                    and stop.get('group_absent') is True and not record.get('close_error')
                    and not record.get('log_close_errors'),'Files log ownership or closure unresolved')
            require(core.identity_of(self.out)==self.output_id,'Output root changed before Files log publication')
            directory=self.out/'PhaseLogs'
            self.timecheck()
            directory.mkdir(exist_ok=True)
            self.timecheck()
            directory_id=core.identity_of(directory)
            require(set(record.get('logs',{}))=={'stdout','stderr'},'Unexpected Files log streams')
            for channel in ('stdout','stderr'):
                self.timecheck()
                path=Path(record['logs'][channel])
                require(path==self.out/(str(index+1)+'-'+channel+'.log') and path.resolve(strict=True)==path
                        and not path.is_symlink() and path.is_file(),'Unexpected Files log path')
                require(path.stat().st_size==record['bytes'][channel]<=core.base.PER_LOG,'Files log size differs')
                require(core.identity_of(directory)==directory_id,'Files log directory changed')
                public=directory/(record['id']+'-'+channel+'.log')
                require(not os.path.lexists(public),'Public Files log already exists')
                self.timecheck()
                path.rename(public);record['logs'][channel]=str(public)
                self.timecheck()

    def work(self):
        super().work()
        identity=core.json_file(self.out/'source-identity.json')['checkout']
        require(self.command('git-final-head',['/usr/bin/git','rev-parse','HEAD'],20).strip()==identity['commit'],
                'Checkout commit changed during recovery')
        require(not self.command('git-final-clean',['/usr/bin/git','status','--porcelain'],20).strip(),
                'Checkout changed during recovery')

    def run_phase(self,phase):
        try:return super().run_phase(phase)
        finally:
            # Raw root logs are never public. This route selects only Xcode
            # phase logs; the separate Files route also excludes every ps log.
            for record in self.report['commands']:
                if record['id']=='phase-'+phase:
                    directory=self.out/'PhaseLogs'
                    directory.mkdir(exist_ok=True);core.identity_of(directory)
                    for key,value in list(record.get('logs',{}).items()):
                        path=Path(value)
                        if path.exists():
                            require(path.parent==self.out and not path.is_symlink() and path.is_file(),'Unexpected phase log path')
                            public=directory/(phase+'-'+key+'.log')
                            require(not os.path.lexists(public),'Public phase log already exists')
                            path.rename(public);record['logs'][key]=str(public)
            self.save()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not args.run:
        print(json.dumps({'status':'NOT_RUN','native_calls':0}));return 0
    try:
        started=time.monotonic();profile=core.json_file(HERE/'recovery-hosted-profile.json')
        require(sys.version_info[:2]>=tuple(profile['python_minimum']),'Python version unsupported')
        require((profile['total_seconds'],profile['cleanup_seconds'],profile['minimum_admission_free_GiB'],
                 profile['minimum_work_free_GiB'],profile['maximum_output_GiB'],profile['maximum_xcresult_GiB'])
                ==(1500,120,16,8,8,2) and profile['prep_seconds']==60 and profile['case_attempts']=={'export':1,'restore':1},'Policy changed')
        job=job_context(os.environ,profile,platform.machine())
        workspace=Path(os.environ['GITHUB_WORKSPACE']);core.identity_of(workspace)
        require(HERE==workspace/'scripts','Entrypoint not from checked-out source')
        event=core.json_file(os.environ['GITHUB_EVENT_PATH'],8*core.MIB)
        require(shutil.disk_usage(workspace).free>=core.CAPS['admission_free_bytes'],'Hosted admission space below 16GiB')
        out=attempt_output(workspace,job)
        env={k:os.environ[k] for k in ['HOME','USER','TMPDIR','DEVELOPER_DIR'] if k in os.environ}
        env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin',GIT_OPTIONAL_LOCKS='0')
        runner=HostedRecovery(core.base.RealOps(env,workspace),out,profile,job,event,workspace,started)
        old={s:signal.signal(s,runner.signal) for s in [signal.SIGTERM,signal.SIGINT]}
        try:return runner.run()
        finally:
            for s,handler in old.items():signal.signal(s,handler)
    except BaseException as error:
        print(json.dumps({'status':'DENIED_OR_FAILED','error':repr(error),'runtime_accepted':False}));return 1


if __name__=='__main__':sys.exit(main())
