"""Offline regressions for hosted-only boundaries. No native process execution."""
import contextlib
import copy
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('hosted',HERE/'recovery_hosted.py')
hosted=importlib.util.module_from_spec(spec)
with patch('subprocess.Popen') as startup,patch('os.killpg') as signals:
    spec.loader.exec_module(hosted)
    startup.assert_not_called();signals.assert_not_called()
PROFILE=json.loads((HERE/'recovery-hosted-profile.json').read_text())
SHA='a'*40;BASE='b'*40;HEAD='c'*40


class Process:
    def __init__(self, ops, pid, options):
        self.ops, self.pid, self.options = ops, pid, options
        self.started, self.returncode = ops.now(), None
        self.dead = False
        self.poll_calls, self.probe_calls = 0, 0
        self.output = list(options.get('output', []))

    def poll(self):
        self.poll_calls += 1
        if self.poll_calls in self.options.get('poll_errors', {}):
            raise self.options['poll_errors'][self.poll_calls]
        if self.dead:
            self.returncode = self.options.get('exit', 0)
        elif self.ops.now() - self.started >= self.options.get('delay', 0):
            self.returncode = self.options.get('exit', 0)
        return self.returncode


class Ops:
    def __init__(self, *plans):
        self.t, self.plans, self.processes, self.signals = 0., list(plans), [], []
        self.on_spawn = None
        self.probes = []

    def now(self):
        return self.t

    def sleep(self, amount):
        assert amount >= 0
        self.t += amount

    def spawn(self, argv):
        if self.on_spawn:
            self.on_spawn(argv)
        options = self.plans.pop(0) if self.plans else {}
        if options.get('spawn_error'):
            raise OSError('ambiguous constructor failure')
        p = Process(self, len(self.processes) + 101, options)
        self.processes.append(p)
        return p

    def prepare(self, p):
        if p.options.get('prepare_error'):
            raise OSError('pipe setup failure')

    def read(self, p):
        self.t += p.options.get('read_seconds', 0)
        if p.output:
            return [p.output.pop(0)]
        if p.options.get('flood'):
            return [('stdout', b'flood')]
        return []

    def absent(self, p):
        self.probes.append(p.pid)
        p.probe_calls += 1
        if p.probe_calls in p.options.get('probe_errors', {}):
            raise p.options['probe_errors'][p.probe_calls]
        if p.options.get('probe_error'):
            raise PermissionError(errno.EPERM, 'EPERM probe')
        if p.options.get('absent_sequence'):
            return p.options['absent_sequence'].pop(0)
        return p.dead or (p.returncode is not None and not p.options.get('lingering'))

    def send(self, p, sig):
        self.signals.append((p.pid, sig, self.t))
        if p.options.get('signal_error'):
            raise PermissionError(errno.EPERM, 'EPERM signal')
        if not p.options.get('ignore_all') and (sig == signal.SIGKILL or not p.options.get('ignore_term')):
            p.dead = True
        return 'syscall_returned'

    def close(self, p):
        if p.options.get('close_error'):
            raise OSError('close failed')


class PostKillOps(Ops):
    """Pure clock model: post-KILL EPERM stays unknown until explicit absence."""
    def __init__(self, reap_after=.1, absent_after=.2, probe_error=None, kill_result='syscall_returned'):
        super().__init__({'delay': float('inf'), 'ignore_all': True, 'exit': -9})
        self.reap_after, self.absent_after = reap_after, absent_after
        self.probe_error, self.kill_result = probe_error, kill_result
        self.kill_at, self.unknown_count, self.events = None, 0, []
        self.after_poll = self.after_probe = self.after_send = lambda: None

    def spawn(self, argv):
        p = super().spawn(argv)
        original_poll = p.poll
        def poll():
            self.events.append(('poll', self.t))
            if self.kill_at is not None and self.t - self.kill_at >= self.reap_after:
                p.dead = True
            result = original_poll()
            self.after_poll()
            return result
        p.poll = poll
        return p

    def absent(self, p):
        self.events.append(('probe', self.t))
        self.probes.append(p.pid)
        p.probe_calls += 1
        self.after_probe()
        if self.kill_at is None:
            return False
        if self.probe_error is not None:
            raise self.probe_error
        if self.t - self.kill_at < self.absent_after:
            self.unknown_count += 1
            raise PermissionError(errno.EPERM, 'post-KILL unknown')
        return True  # Model RealOps.absent's explicit ESRCH result only.

    def send(self, p, sig):
        self.events.append(('signal', self.t))
        super().send(p, sig)
        if sig == signal.SIGKILL:
            self.kill_at = self.t
        self.after_send()
        return self.kill_result if sig == signal.SIGKILL else 'syscall_returned'


class PostTermOps(Ops):
    """Pure clock model: post-TERM EPERM stays unknown until explicit absence."""
    def __init__(self, reap_after=.1, absent_after=.2, probe_error=None, term_result='syscall_returned'):
        super().__init__({'delay': float('inf'), 'ignore_all': True, 'exit': -15})
        self.reap_after, self.absent_after = reap_after, absent_after
        self.probe_error, self.term_result = probe_error, term_result
        self.term_at, self.unknown_count, self.events = None, 0, []
        self.after_poll = self.after_probe = self.after_send = lambda: None

    def spawn(self, argv):
        p = super().spawn(argv)
        original_poll = p.poll
        def poll():
            self.events.append(('poll', self.t))
            if self.term_at is not None and self.t - self.term_at >= self.reap_after:
                p.dead = True
            result = original_poll()
            self.after_poll()
            return result
        p.poll = poll
        return p

    def absent(self, p):
        self.events.append(('probe', self.t))
        self.probes.append(p.pid)
        p.probe_calls += 1
        self.after_probe()
        if self.term_at is None:
            return False
        if self.probe_error is not None:
            raise self.probe_error
        if self.t - self.term_at < self.absent_after:
            self.unknown_count += 1
            raise PermissionError(errno.EPERM, 'post-TERM unknown')
        return True  # Model RealOps.absent's explicit ESRCH result only.

    def send(self, p, sig):
        assert sig == signal.SIGTERM, 'No escalation after TERM became unknown'
        self.events.append(('signal', self.t))
        super().send(p, sig)
        if sig == signal.SIGTERM:
            self.term_at = self.t
        self.after_send()
        return self.term_result if sig == signal.SIGTERM else 'syscall_returned'


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='trip-hosted-injected-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.guards=[]
        for name in ['subprocess.Popen','os.killpg','os.kill','os.system']:
            p=patch(name,side_effect=AssertionError('NO NATIVE PROCESS OR SIGNAL'))
            self.guards.append(p.start());self.addCleanup(p.stop)
        p=patch.object(hosted.core.shutil,'disk_usage',return_value=SimpleNamespace(free=32*hosted.core.GIB))
        p.start();self.addCleanup(p.stop)

    def tearDown(self):
        for guard in self.guards:guard.assert_not_called()

    def env(self):
        return {'CI':'true','GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':PROFILE['repository'],'GITHUB_JOB':'recovery',
                'GITHUB_WORKFLOW':'CI','TRIPDOCKET_RUNNER_LABEL':'macos-15','TRIPDOCKET_RUNNER_ENVIRONMENT':'github-hosted',
                'RUNNER_OS':'macOS','TRIPDOCKET_RUNNER_ARCH':'ARM64','ImageOS':'macos15','ImageVersion':'test-image',
                'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'123','GITHUB_EVENT_NAME':'pull_request',
                'GITHUB_SHA':SHA,'GITHUB_REF':'refs/pull/1/merge'}

    def test_default_cli_and_invalid_environment_are_inert(self):
        with contextlib.redirect_stdout(io.StringIO()) as text:
            self.assertEqual(hosted.main([]),0)
        self.assertEqual(json.loads(text.getvalue())['native_calls'],0)
        with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(io.StringIO()), \
             patch.object(hosted.core.base,'RealOps',side_effect=AssertionError('NO BOUNDARY')) as boundary:
            self.assertEqual(hosted.main(['--run']),1);boundary.assert_not_called()

    def test_job_requires_matching_host_profile_and_valid_attempt(self):
        env=self.env();hosted.job_context(env,PROFILE,'arm64')
        for key,value in [('GITHUB_ACTIONS','false'),('GITHUB_REPOSITORY','other/repo'),('GITHUB_JOB','validate'),
                          ('TRIPDOCKET_RUNNER_LABEL','macos-15-intel'),('TRIPDOCKET_RUNNER_ENVIRONMENT','self-hosted'),
                          ('TRIPDOCKET_RUNNER_ARCH','X64'),('GITHUB_RUN_ATTEMPT','0'),('ImageVersion',''),
                          ('ImageOS','macos14'),('GITHUB_EVENT_NAME','pull_request_target'),('GITHUB_SHA','bad'),
                          ('SIMCTL_CHILD_TEST','1'),('DYLD_INSERT_LIBRARIES','/tmp/example')]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):hosted.job_context({**env,key:value},PROFILE,'arm64')
        with self.assertRaises(RuntimeError):hosted.job_context(env,PROFILE,'x86_64')

    def test_explicit_workflow_attempt_metadata_is_positive_and_canonical(self):
        for attempt in ('1', '2', '17'):
            with self.subTest(attempt=attempt):
                env={**self.env(),'GITHUB_RUN_ATTEMPT':attempt}
                self.assertEqual(hosted.job_context(env,PROFILE,'arm64')['GITHUB_RUN_ATTEMPT'],attempt)
        for attempt in (None, '', '0', '-1', '+2', '02', '2.0', '2 ', ' 2', '2\n', '٢', 2):
            with self.subTest(attempt=attempt),self.assertRaises(RuntimeError):
                hosted.job_context({**self.env(),'GITHUB_RUN_ATTEMPT':attempt},PROFILE,'arm64')
        env=self.env();del env['GITHUB_RUN_ATTEMPT']
        with self.assertRaises(RuntimeError):hosted.job_context(env,PROFILE,'arm64')

    def test_explicit_attempts_keep_distinct_owned_identity_and_receipts(self):
        workspace=self.root/'repo';workspace.mkdir()
        runners=[];original=[]
        for run,attempt in [('123','1'),('123','2'),('124','2')]:
            env={**self.env(),'GITHUB_RUN_ID':run,'GITHUB_RUN_ATTEMPT':attempt}
            job=hosted.job_context(env,PROFILE,'arm64')
            out=hosted.attempt_output(workspace,job)
            r=hosted.HostedRecovery(Ops(),out,copy.deepcopy(PROFILE),job,self.event(),workspace,0)
            receipt=(out/'receipt.json').read_bytes()
            self.assertEqual(json.loads(receipt)['job']['GITHUB_RUN_ID'],run)
            self.assertEqual(json.loads(receipt)['job']['GITHUB_RUN_ATTEMPT'],attempt)
            with self.assertRaisesRegex(RuntimeError,'never reused'):
                hosted.attempt_output(workspace,job)
            with self.assertRaises(FileExistsError):
                hosted.HostedRecovery(Ops(),out,copy.deepcopy(PROFILE),job,self.event(),workspace,0)
            runners.append(r);original.append(receipt)
        self.assertEqual(len({r.out for r in runners}),3)
        self.assertEqual(len({r.folder_name for r in runners}),3)
        for r,receipt in zip(runners,original):
            self.assertEqual((r.out/'receipt.json').read_bytes(),receipt)
            self.assertEqual(r.ops.processes,[])

    def test_attempt_output_rejects_dangling_evidence_and_symlink_parent(self):
        workspace=self.root/'repo';workspace.mkdir();job=hosted.job_context(self.env(),PROFILE,'arm64')
        out=hosted.attempt_output(workspace,job)
        out.symlink_to(self.root/'missing')
        with self.assertRaisesRegex(RuntimeError,'never reused'):hosted.attempt_output(workspace,job)
        out.unlink();out.parent.rmdir()
        target=self.root/'other';target.mkdir();(workspace/'build').symlink_to(target,target_is_directory=True)
        with self.assertRaises(RuntimeError):hosted.attempt_output(workspace,job)
        self.assertEqual(list(target.iterdir()),[])

    def test_ci_artifacts_bind_run_attempt_without_broadening_recovery_uploads(self):
        workflow=(HERE.parent/'.github/workflows/ci.yml').read_text()
        names=[line.strip() for line in workflow.splitlines() if 'name: TripDocket-' in line]
        self.assertEqual(len(names),4)
        self.assertTrue(all('${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}' in name for name in names))
        prefix='build/RecoveryHosted-${{ github.run_id }}-${{ github.run_attempt }}/'
        paths=[line.strip() for line in workflow.splitlines() if 'build/RecoveryHosted' in line]
        self.assertTrue(all(path.startswith(prefix) for path in paths))
        self.assertEqual({path[len(prefix):] for path in paths},
                         {'*.json','PhaseLogs/','Capability/','*.xcresult/','BeforeReset/','AfterRestore/','*-attachments/'})
        self.assertNotIn('/*.log',workflow)

    def runtime(self,version='18.5'):
        return {'version':version,'identifier':'com.apple.CoreSimulator.SimRuntime.iOS-'+version.replace('.','-'),
                'isAvailable':True,'supportedArchitectures':['arm64','x86_64'],
                'supportedDeviceTypes':[{'identifier':PROFILE['device_type']}]}

    def test_runtime_matches_complete_sdk_version_not_latest(self):
        selected=self.runtime();newer=self.runtime('26.0.1')
        self.assertEqual(hosted.select_runtime('18.5',{'runtimes':[newer,selected]},PROFILE),selected)
        with self.assertRaises(RuntimeError):hosted.select_runtime('26.0',{'runtimes':[newer]},PROFILE)

    def test_runtime_unknown_ambiguous_or_incompatible_fails(self):
        row=self.runtime()
        variants=[[],[row,row],[{**row,'isAvailable':False}],[{**row,'supportedArchitectures':['x86_64']}],
                  [{**row,'supportedArchitectures':'arm64'}],[{**row,'supportedDeviceTypes':[]}],
                  [{**row,'supportedDeviceTypes':row['supportedDeviceTypes']*2}]]
        for values in variants:
            with self.subTest(values=values),self.assertRaises(RuntimeError):hosted.select_runtime('18.5',{'runtimes':values},PROFILE)

    def test_toolchain_paths_cannot_mix_xcodes_or_escape_applications(self):
        dev=Path('/Applications/Xcode_16.4.app/Contents/Developer')
        hosted.toolchain_paths(dev,dev/'Platforms/iPhoneSimulator.platform/Developer/SDKs/iPhoneSimulator18.5.sdk')
        for bad in [Path('/tmp/Xcode.app/Contents/Developer'),Path('/Applications/Developer'),Path('/Applications/Xcode/Contents/Developer')]:
            with self.assertRaises(RuntimeError):hosted.toolchain_paths(bad)
        with self.assertRaises(RuntimeError):hosted.toolchain_paths(dev,Path('/Applications/Other.app/Contents/Developer/SDKs/iPhone.sdk'))

    def commit(self,parents=(),signed=False):
        raw='tree '+SHA+'\n'+''.join('parent '+p+'\n' for p in parents)+'author Test <test@example.invalid> 0 +0000\ncommitter Test <test@example.invalid> 0 +0000\n'
        if signed:raw+='gpgsig -----BEGIN PGP SIGNATURE-----\n synthetic\n -----END PGP SIGNATURE-----\n'
        raw+='\nsynthetic source object\n'
        data=raw.encode();oid=hashlib.sha1(b'commit '+str(len(data)).encode()+b'\0'+data).hexdigest()
        return raw,oid

    def test_raw_commit_object_binds_tree_parents_and_signature_scope(self):
        raw,oid=self.commit([BASE,HEAD],True);result=hosted.parse_commit(raw,oid)
        self.assertEqual(result['parents'],[BASE,HEAD]);self.assertEqual(result['tree'],SHA)
        self.assertTrue(result['signature_present']);self.assertFalse(result['signature_cryptographically_verified_here'])
        with self.assertRaises(RuntimeError):hosted.parse_commit(raw+'changed',oid)

    def event(self,head=HEAD,base=BASE):
        return {'repository':{'full_name':PROFILE['repository']},'number':1,
                'pull_request':{'head':{'sha':head,'repo':{'full_name':PROFILE['repository']}},'base':{'sha':base}}}

    def test_pr_merge_is_distinct_from_signed_head_and_requires_exact_parents(self):
        job=self.env();commit={'commit':SHA,'parents':[BASE,HEAD],'tree':'d'*40}
        result=hosted.source_event(job,self.event(),commit)
        self.assertEqual(result['pr_head'],HEAD);self.assertEqual(result['checkout']['commit'],SHA)
        for changed in [{**commit,'commit':HEAD},{**commit,'parents':[HEAD,BASE]},{**commit,'parents':[BASE]}]:
            with self.assertRaises(RuntimeError):hosted.source_event(job,self.event(),changed)
        event=self.event();event['pull_request']['head']['repo']['full_name']='fork/repo'
        with self.assertRaises(RuntimeError):hosted.source_event(job,event,commit)

    def test_push_and_merge_group_bind_their_actual_checkout(self):
        job=self.env();commit={'commit':SHA,'parents':[BASE],'tree':'d'*40}
        event={'repository':{'full_name':PROFILE['repository']},'after':SHA}
        hosted.source_event({**job,'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/main'},event,commit)
        with self.assertRaises(RuntimeError):hosted.source_event({**job,'GITHUB_EVENT_NAME':'push'},event,commit)
        event['merge_group']={'head_sha':SHA,'base_sha':BASE}
        result=hosted.source_event({**job,'GITHUB_EVENT_NAME':'merge_group'},event,commit)
        self.assertEqual(result['merge_group_base'],BASE)

    def test_git_tree_rejects_links_submodules_duplicate_and_unsafe_names(self):
        entry='100644 blob '+SHA+'\tApp/a.swift\0'
        self.assertEqual(hosted.parse_tree(entry)['App/a.swift']['oid'],SHA)
        variants=[entry+entry,entry[:-1],entry.replace('100644','120000'),entry.replace('blob','commit'),
                  entry.replace('App/a.swift','../escape'),entry.replace('App/a.swift','/escape'),
                  entry.replace('App/a.swift','build/owned'),entry.replace('App/a.swift','App//a.swift')]
        for raw in variants:
            with self.subTest(raw=raw),self.assertRaises((RuntimeError,ValueError)):hosted.parse_tree(raw)

    def runner(self,ops=None):
        workspace=self.root/'repo';workspace.mkdir();out=self.root/'out'
        ops=ops or Ops();ops.env={};ops.cwd=workspace
        r=hosted.HostedRecovery(ops,out,copy.deepcopy(PROFILE),self.env(),self.event(),workspace,0)
        r.report['source_manifest']={'path':'synthetic-only','sha256':'0'*64}
        return r

    def source_fixture(self,r):
        signed,head=self.commit(signed=True);merged,merge=self.commit([BASE,head])
        r.job['GITHUB_SHA']=merge;r.event=self.event(head)
        files={'Tripfolio.xcodeproj/project.pbxproj':b'project','scripts/example.py':b'print(1)\n'}
        tree=''
        for name,data in files.items():
            p=r.workspace/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o644)
            oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            tree+='100644 blob '+oid+'\t'+name+'\0'
        responses={'git-clean':'','git-head':merge+'\n','git-commit':merged,'git-pr-head':signed,'git-tree':tree}
        r.command=lambda label,*args:responses[label]
        return responses

    def test_source_snapshot_is_bound_to_actual_git_bytes_and_modes(self):
        r=self.runner();self.source_fixture(r);r.capture_source()
        self.assertEqual(len(r.source_manifest),2)
        identity=json.loads((r.out/'source-identity.json').read_text())
        self.assertNotEqual(identity['checkout']['commit'],identity['pr_head'])
        self.assertTrue(identity['pr_head_commit']['signature_present'])
        self.assertEqual((r.candidate/'scripts/example.py').read_bytes(),b'print(1)\n')
        (r.workspace/'scripts/example.py').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):r.source()

    def test_source_capture_rejects_dirty_symlink_changed_blob_or_mode(self):
        for kind in ['dirty','symlink','blob','mode']:
            with self.subTest(kind=kind):
                case=self.root/kind;case.mkdir();old=self.root;self.root=case
                r=self.runner();responses=self.source_fixture(r)
                p=r.workspace/'scripts/example.py'
                if kind=='dirty':responses['git-clean']=' M App/file\n'
                if kind=='symlink':p.unlink();p.symlink_to(r.workspace/'Tripfolio.xcodeproj/project.pbxproj')
                if kind=='blob':p.write_bytes(b'changed')
                if kind=='mode':p.chmod(0o755)
                with self.assertRaises(RuntimeError):r.capture_source()
                self.root=old

    def proof(self):
        stop={'group_absent':True,'leader_reaped':True}
        normal={'pgid':101,'returncode':0,'outcome':'completed','stop':copy.deepcopy(stop)}
        failed={'pgid':102,'error':"RuntimeError('Command timeout')",'outcome':'failed','start':1,'finish':20,
                'stop':{**stop,'signals':[int(signal.SIGTERM),int(signal.SIGKILL)]},
                'process_observations':{'stop.signal_'+str(int(sig)):
                    {'calls':1,'outcome':'returned','result':'syscall_returned'}
                    for sig in [signal.SIGTERM,signal.SIGKILL]}}
        observations=[[{'kind':'normal','pid':101,'pgid':101}],
                      [{'kind':'parent','pid':102,'pgid':102},{'kind':'descendant','pid':103,'ppid':102,'pgid':102}]]
        return normal,failed,observations

    def test_only_actual_complete_capability_can_be_approved(self):
        normal,failed,observations=self.proof()
        result=hosted.capability_result(normal,failed,observations,21,True)
        self.assertTrue(result['approved']);self.assertEqual(result['scope'],'owned subprocess boundary only')
        with self.assertRaises(RuntimeError):hosted.capability_result(normal,failed,observations,21,False)
        for kind in ['lineage','timeout','unreaped','signals','elapsed','missing_outcome','ESRCH','repeated_signal']:
            n,f,o=copy.deepcopy(self.proof());elapsed=21
            if kind=='lineage':o[1][1]['ppid']=999
            if kind=='timeout':f['error']='unrelated failure'
            if kind=='unreaped':f['stop']['leader_reaped']=False
            if kind=='signals':f['stop']['signals']=[int(signal.SIGTERM)]
            if kind=='elapsed':elapsed=61
            if kind=='missing_outcome':f.pop('process_observations')
            if kind=='ESRCH':f['process_observations']['stop.signal_15']['result']='already_absent_ESRCH'
            if kind=='repeated_signal':f['process_observations']['stop.signal_15']['calls']=2
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):hosted.capability_result(n,f,o,elapsed,True)

    def test_failed_log_publication_cannot_expose_process_listing(self):
        r=self.runner();ps=r.out/'2-stdout.log';ps.write_text('private process listing')
        xcode=r.out/'1-stdout.log';xcode.write_text('xcode diagnostic')
        r.report['commands']=[{'id':'phase-export','logs':{'stdout':str(xcode)}},
                              {'id':'export-app-stopped','logs':{'stdout':str(ps)}}]
        with patch.object(hosted.core.Recovery,'run_phase',side_effect=RuntimeError('app running')), \
             patch.object(Path,'rename',side_effect=OSError('failed move')):
            with self.assertRaises(OSError):r.run_phase('export')
        self.assertEqual(list((r.out/'PhaseLogs').glob('*')),[])
        self.assertEqual(ps.read_text(),'private process listing')
        workflow=(HERE.parent/'.github/workflows/ci.yml').read_text()
        self.assertNotIn('/*.log',workflow)
        self.assertIn('build/RecoveryHosted-${{ github.run_id }}-${{ github.run_attempt }}/PhaseLogs/',workflow)

    def test_only_xcode_phase_logs_enter_public_directory(self):
        r=self.runner();ps=r.out/'2-stdout.log';ps.write_text('private process listing')
        xcode=r.out/'1-stdout.log';xcode.write_text('xcode diagnostic')
        r.report['commands']=[{'id':'phase-export','logs':{'stdout':str(xcode)}},
                              {'id':'export-app-stopped','logs':{'stdout':str(ps)}}]
        with patch.object(hosted.core.Recovery,'run_phase',return_value=Path('/synthetic')):
            r.run_phase('export')
        self.assertEqual((r.out/'PhaseLogs/export-stdout.log').read_text(),'xcode diagnostic')
        self.assertEqual(ps.read_text(),'private process listing')

    def capability_ops(self):
        normal=(json.dumps({'kind':'normal','pid':101,'pgid':101})+'\n').encode()
        timed=('\n'.join(json.dumps(row) for row in [
            {'kind':'parent','pid':102,'pgid':102},
            {'kind':'descendant','pid':103,'ppid':102,'pgid':102}])+'\n').encode()
        return Ops({'output':[('stdout',normal)]},
                   {'output':[('stdout',timed)],'delay':float('inf'),'ignore_term':True})

    def test_actual_check_orchestration_rejects_fake_and_preserves_shared_log_count(self):
        r=self.runner(self.capability_ops());r.log_total=123
        with self.assertRaisesRegex(RuntimeError,'Injected boundary'):r.check_capability()
        saved=json.loads((r.out/'Capability/receipt.json').read_text())
        self.assertEqual(len(saved['commands']),2)
        count=sum(sum(x['bytes'].values()) for x in saved['commands'])
        self.assertEqual(r.log_total,123+count)
        self.assertFalse(r.active);self.assertFalse(r.unknown_spawn)
        self.assertNotIn('host_capability',r.report)
        self.assertEqual(r.limit,1380)

    def delegated_capability_scan(self, stage):
        r=self.runner(self.capability_ops());r.ops.t=100.
        # The actual parent previously finished runtime discovery; only the
        # delegated probe has a pending normal command (work107, stop115).
        r.report['commands']=[{'id':'profile-runtimes','work_deadline':52.,'finish':80.}]
        original_save=hosted.core.Recovery.save;original_stop=hosted.core.Recovery.stop
        probe=None;fired=False;stopping=False;stop_intervals=[]
        def save(subject):
            nonlocal probe
            value=original_save(subject)
            if subject is not r and subject.out==r.out/'Capability':
                probe=subject
                if stage=='admission' and subject.report['commands']:
                    row=subject.report['commands'][-1]
                    if row['id']=='normal' and 'pgid' not in row and 'finish' not in row:
                        r.ops.t=106.
            return value
        def stop(subject,p,deadline,record):
            nonlocal stopping
            stopping=True;began=r.ops.t
            try:return original_stop(subject,p,deadline,record)
            finally:
                stop_intervals.append((began,r.ops.t,deadline));stopping=False
                if stage=='finalization':r.ops.t=106.
        def usage(_):
            nonlocal fired
            self.assertFalse(stopping,'Resource sampling must not enter process-stop grace')
            if probe is not None and probe.report['commands'] and r.ops.t==106. and not fired:
                fired=True;r.ops.t=107.
            return SimpleNamespace(free=32*hosted.core.GIB)
        if stage=='active':
            r.ops.plans[0]['delay']=float('inf')
            r.ops.on_spawn=lambda argv:setattr(r.ops,'t',106.)
        with patch.object(hosted.core.Recovery,'save',save), \
             patch.object(hosted.core.Recovery,'stop',stop), \
             patch.object(hosted.core.shutil,'disk_usage',side_effect=usage):
            with self.assertRaisesRegex(RuntimeError,'normal failed'):r.check_capability()
        self.assertTrue(fired);self.assertIsNotNone(probe)
        row=probe.report['commands'][0];failed=r.report['resource_scan_failure']
        self.assertEqual((row['start'],row['work_deadline'],row['command_deadline']),(100.,107.,115.))
        self.assertEqual(row['error'],"RuntimeError('Output scan deadline exceeded')")
        self.assertEqual((failed['started_elapsed'],failed['deadline_elapsed'],failed['finished_elapsed']),(106.,107.,107.))
        self.assertEqual(failed['stage'],'free_space_before')
        self.assertEqual(len(probe.report['commands']),1)
        self.assertEqual(len(r.ops.processes),0 if stage=='admission' else 1)
        self.assertFalse(probe.active);self.assertFalse(r.active)
        self.assertNotIn('host_capability',r.report)
        self.assertEqual((r.limit,r.final),(1380.,1500.))
        self.assertEqual(probe.limit,160.)
        if stage=='admission':self.assertEqual(stop_intervals,[])
        else:
            self.assertEqual(len(stop_intervals),1)
            self.assertEqual(stop_intervals[0][2],115.)
            self.assertLessEqual(stop_intervals[0][1],115.)
        # No probe deadline remains installed on parent work after finally.
        deadlines=[];original_scan=hosted.core.live_sizes
        def scan(*args,**kwargs):
            deadlines.append(args[3]);return original_scan(*args,**kwargs)
        with patch.object(hosted.core,'live_sizes',side_effect=scan):r.monitor()
        self.assertEqual(deadlines,[112.])
        self.assertEqual(r.report['resource_scan_failure'],failed)
        return row

    def test_delegated_capability_pending_admission_preserves_stop_reserve(self):
        row=self.delegated_capability_scan('admission')
        self.assertNotIn('pgid',row);self.assertNotIn('stop',row)

    def test_delegated_capability_active_scan_preserves_stop_and_cleanup(self):
        row=self.delegated_capability_scan('active')
        self.assertEqual(row['stop']['signals'],[15])
        self.assertTrue(row['stop']['leader_reaped'] and row['stop']['group_absent'])
        self.assertNotIn('stop_error',row)

    def test_delegated_capability_finalization_restores_parent_deadline(self):
        row=self.delegated_capability_scan('finalization')
        self.assertEqual(row['stop']['signals'],[])
        self.assertEqual(row['finalization_error'],"RuntimeError('Output scan deadline exceeded')")

    def test_prep_cannot_spend_a_second_global_log_allowance(self):
        r=self.runner(Ops({'output':[('stdout',b'abcdef')]}))
        r.log_total=64*hosted.core.MIB-3
        with self.assertRaises(RuntimeError):r.check_capability()
        self.assertEqual(r.log_total,64*hosted.core.MIB)
        self.assertEqual((r.out/'Capability/1-stdout.log').read_bytes(),b'abc')
        self.assertEqual(len(r.ops.processes),1)

    def test_unknown_capability_spawn_blocks_simulator_setup(self):
        r=self.runner(Ops({'spawn_error':True}))
        r.capture_source=lambda:None;r.discover_profile=lambda:None
        with patch.object(hosted.core.Recovery,'setup',side_effect=AssertionError('NO SIMULATOR')) as setup:
            with self.assertRaises(RuntimeError) as failure:r.setup()
            self.assertIsInstance(failure.exception.__cause__,OSError)
            setup.assert_not_called()
        self.assertTrue(r.unknown_spawn)
        with patch.object(r,'sim',side_effect=AssertionError('NO CLEANUP SPAWN')) as sim:
            r.cleanup();sim.assert_not_called()

    def test_unresolved_capability_group_propagates_to_cleanup(self):
        r=self.runner(Ops({'delay':float('inf'),'ignore_all':True}))
        with self.assertRaises(RuntimeError):r.check_capability()
        self.assertTrue(r.active)
        with patch.object(r,'sim',side_effect=AssertionError('NO CLEANUP SPAWN')) as sim:
            r.cleanup();sim.assert_not_called()
        self.assertFalse(r.report['cleanup_verified'])

    def test_signal_during_capability_spawn_is_reaped_and_not_accepted(self):
        r=self.runner(self.capability_ops());r.ops.on_spawn=lambda _:r.signal()
        with self.assertRaises(RuntimeError):r.check_capability()
        self.assertTrue(r.interrupted);self.assertFalse(r.active)
        self.assertNotIn('host_capability',r.report);self.assertEqual(r.limit,1380)

    def test_capability_keeps_original_global_start_and_cleanup_reserve(self):
        r=self.runner(self.capability_ops());r.ops.t=1373
        with self.assertRaises(RuntimeError):r.check_capability()
        self.assertEqual(r.t0,0);self.assertEqual(r.limit,1380);self.assertEqual(r.final,1500)
        self.assertFalse(r.ops.processes)

    def test_prep_receipt_hash_past_deadline_blocks_simulator_setup(self):
        r=self.runner(self.capability_ops());r.capture_source=lambda:None;r.discover_profile=lambda:None
        original=hosted.core.file_digest
        def slow_hash(path,checkpoint=lambda:None):
            if Path(path)==r.out/'Capability/receipt.json':r.ops.t=61
            return original(path,checkpoint)
        # The proof remains explicitly synthetic; this injection reaches the
        # post-proof hashing boundary without ever fabricating actual approval.
        with patch.object(hosted,'capability_result',return_value={'approved':False,'actual_execution':False}), \
             patch.object(hosted.core,'file_digest',side_effect=slow_hash), \
             patch.object(hosted.core.Recovery,'setup',side_effect=AssertionError('NO SIMULATOR')) as setup:
            with self.assertRaisesRegex(RuntimeError,'deadline'):r.setup()
            setup.assert_not_called()
        self.assertNotIn('host_capability',r.report)
        self.assertFalse((r.out/'host-capability.json').exists());self.assertEqual(r.limit,1380)

    def test_existing_core_process_and_recovery_methods_are_reused(self):
        for name in ['take_snapshot','authorize_restore','copy_tree','preserve_result','read_result','cleanup']:
            self.assertIs(getattr(hosted.HostedRecovery,name),getattr(hosted.core.Recovery,name))
        for name in ['command','pump','stop','save','signal','recover']:
            self.assertIs(getattr(hosted.HostedRecovery,name),getattr(hosted.core.base.Smoke,name))
        self.assertEqual((hosted.core.CAPS['total_seconds'],hosted.core.CAPS['cleanup_seconds']),(1500,120))

    def discovery_runner(self, **runtime_options):
        developer=self.root/'Xcode.app/Contents/Developer'
        sdk_path=developer/'Platforms/iPhoneSimulator.platform/Developer/SDKs/iPhoneSimulator18.5.sdk'
        sdk_path.mkdir(parents=True)
        texts=[str(developer),'Xcode 16.4\nBuild version 16F6','18.5',str(sdk_path)]
        plans=[{'output':[('stdout',text.encode())]} for text in texts]
        plans.append({'output':[('stdout',json.dumps({'runtimes':[self.runtime()]}).encode())],**runtime_options})
        return self.runner(Ops(*plans))

    def discover(self, runner):
        # Only filesystem/tool identities are synthetic; command, timing, stop,
        # parsing and selection use the actual candidate implementation.
        with patch.object(hosted,'toolchain_paths'),patch.object(hosted.core,'file_digest',return_value='a'*64):
            runner.discover_profile()

    def test_first_runtime_query_allows_70_seconds_inside_120_cap(self):
        r=self.discovery_runner(delay=70)
        self.discover(r)
        rows=r.report['commands']
        self.assertEqual([x['requested_cap_seconds'] for x in rows],[20,20,20,20,120])
        self.assertEqual(rows[-1]['argv'],['/usr/bin/xcrun','simctl','list','runtimes','--json'])
        self.assertEqual(len(r.ops.processes),5)
        self.assertEqual((r.t0,r.limit,r.final),(0,1380,1500))
        self.assertEqual(PROFILE['prep_seconds'],60)
        self.assertEqual(r.report['profile_discovery']['sdk_version'],'18.5')
        self.assertEqual(r.report['profile_discovery']['runtime_inventory_status'],'returned')
        self.assertTrue((r.out/'resolved-profile.json').is_file())
        self.assertEqual(r.report['profile_discovery']['runtime_inventory_cap_seconds'],120)
        self.assertAlmostEqual(rows[-1]['work_deadline']-rows[-1]['start'],112,places=6)
        self.assertGreaterEqual(rows[-1]['finish']-rows[-1]['start'],70)
        self.assertLess(rows[-1]['finish']-rows[-1]['start'],112)
        # The separate pre-create inventory and every other sim call keep 30s.
        with patch.object(r,'command',return_value='{}') as call:
            r.sim('runtime-inventory','list','runtimes','--json')
        self.assertEqual(call.call_args.args[-1],30)

    def test_runtime_query_still_times_out_once_and_preserves_pending_facts(self):
        r=self.discovery_runner(delay=float('inf'))
        with self.assertRaises(RuntimeError):self.discover(r)
        row=r.report['commands'][-1]
        self.assertEqual(row['error'],"RuntimeError('Command timeout')")
        self.assertAlmostEqual(row['finish']-row['start'],112,places=6)
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        self.assertFalse(r.active)
        self.assertEqual(len(r.ops.processes),5)
        saved=json.loads((r.out/'receipt.json').read_text())
        self.assertEqual(saved['profile_discovery']['runtime_inventory_status'],'pending')
        self.assertEqual(saved['profile_discovery']['xcode_version'],'Xcode 16.4\nBuild version 16F6')
        self.assertNotIn('resolved_profile',saved)
        self.assertNotIn('host_capability',saved)

    def test_runtime_command_uses_remaining_global_budget_and_reserves_stop(self):
        r=self.runner(Ops({'delay':float('inf')}));r.ops.t=1370
        with self.assertRaises(RuntimeError):r.sim('profile-runtimes','list','runtimes','--json',cap=120)
        row=r.report['commands'][-1]
        self.assertEqual((row['work_deadline'],row['command_deadline']),(1372,1380))
        self.assertLessEqual(row['finish'],1380)
        self.assertEqual((r.limit,r.final),(1380,1500))
        r.ops.t=1372
        with self.assertRaisesRegex(RuntimeError,'Insufficient command/stop budget'):
            r.sim('profile-runtimes','list','runtimes','--json',cap=120)
        self.assertEqual(len(r.ops.processes),1)

    def test_first_runtime_response_at_or_after_work_deadline_is_not_accepted(self):
        for delay in (112.,112.01):
            with self.subTest(delay=delay):
                old=self.root;self.root=old/str(delay);self.root.mkdir()
                r=self.discovery_runner(delay=delay)
                with self.assertRaises(RuntimeError):self.discover(r)
                self.assertNotIn('resolved_profile',r.report)
                self.assertNotIn('host_capability',r.report)
                self.assertEqual(r.report['profile_discovery']['runtime_inventory_status'],'pending')
                self.assertEqual(len(r.ops.processes),5)
                self.assertFalse(r.active)
                self.assertLessEqual(r.report['commands'][-1]['finish'],120.)
                self.root=old

    def test_initial_runtime_timeout_keeps_TERM_KILL_inside_original_stop_reserve(self):
        r=self.discovery_runner(delay=float('inf'),ignore_term=True)
        with self.assertRaises(RuntimeError):self.discover(r)
        row=r.report['commands'][-1]
        self.assertEqual((row['requested_cap_seconds'],row['work_deadline'],row['command_deadline']),(120,112,120))
        self.assertEqual(row['stop']['signals'],[15,9])
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        self.assertGreaterEqual(row['finish'],117)
        self.assertLess(row['finish'],120)
        self.assertEqual((r.limit,r.final,PROFILE['prep_seconds']),(1380,1500,60))
        self.assertNotIn('resolved_profile',r.report);self.assertEqual(len(r.ops.processes),5)

    def test_runtime_output_cap_invalid_json_and_wrong_sdk_have_no_fallback(self):
        for kind in ['output','json','sdk']:
            with self.subTest(kind=kind):
                old=self.root;self.root=old/kind;self.root.mkdir()
                data=b'not json' if kind=='json' else json.dumps({'runtimes':[self.runtime('26.0')]}).encode()
                r=self.discovery_runner(delay=70,output=[('stdout',data)])
                if kind=='output':
                    r.ops.on_spawn=lambda _:setattr(r,'log_total',64*hosted.core.MIB-1) if len(r.ops.processes)==4 else None
                with self.assertRaises((RuntimeError,json.JSONDecodeError)):self.discover(r)
                self.assertLessEqual(len(r.ops.processes),5)
                self.assertNotIn('host_capability',r.report)
                self.assertFalse(r.create_attempted)
                self.assertNotIn('resolved_profile',r.report)
                self.root=old

    def test_real_signal_boundary_distinguishes_return_ESRCH_and_EPERM(self):
        ops=hosted.core.base.RealOps({},self.root);p=SimpleNamespace(pid=321)
        outcomes=[None,ProcessLookupError(errno.ESRCH,'gone'),PermissionError(errno.EPERM,'denied'),ProcessLookupError('unknown')]
        with patch('os.killpg',side_effect=outcomes) as raw:
            self.assertEqual(ops.send(p,signal.SIGTERM),'syscall_returned')
            self.assertEqual(ops.send(p,signal.SIGTERM),'already_absent_ESRCH')
            with self.assertRaises(PermissionError):ops.send(p,signal.SIGTERM)
            with self.assertRaises(ProcessLookupError):ops.send(p,signal.SIGTERM)
            self.assertEqual(raw.call_count,4)
            self.assertTrue(all(x.args==(321,signal.SIGTERM) for x in raw.call_args_list))
        with patch('os.killpg',side_effect=[ProcessLookupError(errno.ESRCH,'gone'),PermissionError(errno.EPERM,'denied'),ProcessLookupError('unknown')]):
            self.assertTrue(ops.absent(p))
            with self.assertRaises(PermissionError):ops.absent(p)
            with self.assertRaises(ProcessLookupError):ops.absent(p)

    def test_command_and_stop_poll_errors_are_separate_and_fail_closed(self):
        r=self.runner(Ops({'poll_errors':{1:OSError(errno.EIO,'first poll'),2:PermissionError(errno.EPERM,'stop poll')}}))
        with self.assertRaises(RuntimeError):r.command('poll-errors',['synthetic'],30)
        row=r.report['commands'][0];obs=row['process_observations']
        self.assertEqual(obs['command.poll']['errno'],errno.EIO)
        self.assertEqual(obs['stop.poll']['errno'],errno.EPERM)
        self.assertEqual(obs['stop.poll']['exception_type'],'PermissionError')
        self.assertGreaterEqual(obs['stop.poll']['last_finish'],obs['stop.poll']['last_start'])
        self.assertFalse(row['stop']['group_absent'] or row['stop']['leader_reaped'])
        with self.assertRaisesRegex(RuntimeError,'ownership unresolved'):r.command('next',['synthetic'],30)
        self.assertEqual(len(r.ops.processes),1)

    def owned_stop(self, ops):
        r = hosted.core.base.Smoke()
        r.ops, r.t0, r.absent_groups = ops, 0., set()
        p = ops.spawn(['synthetic'])
        r.active = {p.pid: p}
        return r, p, {}

    def test_post_kill_unknown_can_settle_only_with_both_actual_proofs(self):
        ops = PostKillOps()
        r, p, row = self.owned_stop(ops)
        r.stop(p, 8., row)
        stop = row['stop']
        self.assertEqual(stop['signals'], [15, 9])
        self.assertTrue(stop['leader_reaped'] and stop['group_absent'])
        self.assertFalse(r.active)
        self.assertEqual(stop['post_kill_confirmation']['status'], 'confirmed')
        self.assertEqual(stop['post_kill_confirmation']['deadline'], ops.kill_at + 2.)
        self.assertLess(ops.t, stop['post_kill_confirmation']['deadline'])
        self.assertEqual(stop['post_kill_unknown_probes']['count'], ops.unknown_count)
        self.assertGreater(ops.unknown_count, 1)
        probe = row['process_observations']['stop.group_probe']
        self.assertTrue(probe['result'])
        self.assertNotIn('errno', probe)
        self.assertNotIn('error', stop)
        self.assertEqual(len(ops.signals), 2)

    def test_post_kill_permanent_unknown_stops_at_fixed_deadline_with_bounded_history(self):
        ops = PostKillOps(absent_after=float('inf'))
        r, p, row = self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError, 'Stop deadline reached'):
            r.stop(p, 8., row)
        stop = row['stop']; unknown = stop['post_kill_unknown_probes']
        self.assertTrue(stop['leader_reaped'])
        self.assertFalse(stop['group_absent'])
        self.assertIs(r.active[p.pid], p)
        self.assertEqual(stop['post_kill_confirmation']['status'], 'unconfirmed')
        self.assertEqual(ops.t, ops.kill_at + 2.)
        self.assertEqual(unknown['count'], ops.unknown_count)
        self.assertGreater(unknown['count'], 20)
        self.assertEqual(set(unknown), {'count', 'first_start', 'last_start', 'last_finish', 'exception_type', 'errno'})
        self.assertLess(len(json.dumps(unknown)), 300)
        self.assertEqual(row['process_observations']['stop.group_probe']['errno'], errno.EPERM)
        self.assertTrue(all(t < ops.t for _, t in ops.events))
        with self.assertRaisesRegex(RuntimeError, 'No repeated signalling'):
            r.stop(p, 20., row)
        self.assertEqual(len(ops.signals), 2)

    def test_post_kill_group_absence_alone_never_releases_owned_child(self):
        ops = PostKillOps(reap_after=float('inf'), absent_after=0.)
        r, p, row = self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError, 'Stop deadline reached'):
            r.stop(p, 8., row)
        self.assertTrue(row['stop']['group_absent'])
        self.assertFalse(row['stop']['leader_reaped'])
        self.assertIs(r.active[p.pid], p)
        self.assertEqual(len(ops.signals), 2)

    def test_post_kill_other_errors_and_unsuccessful_send_are_not_settled(self):
        poll_error = PostKillOps()
        def denied_poll():
            if poll_error.kill_at is not None:
                raise PermissionError(errno.EPERM, 'poll denied')
        poll_error.after_poll = denied_poll
        cases = [poll_error, PostKillOps(probe_error=PermissionError(errno.EACCES, 'denied')),
                 PostKillOps(probe_error=OSError(errno.EIO, 'probe I/O')),
                 PostKillOps(kill_result='already_absent_ESRCH')]
        for ops in cases:
            with self.subTest(error=repr(ops.probe_error), result=ops.kill_result):
                r, p, row = self.owned_stop(ops)
                with self.assertRaises(OSError):
                    r.stop(p, 8., row)
                self.assertNotIn('post_kill_unknown_probes', row['stop'])
                self.assertIs(r.active[p.pid], p)
                self.assertEqual(ops.t, ops.kill_at)
                self.assertEqual(len(ops.signals), 2)

    def test_post_kill_late_poll_or_probe_cannot_supply_terminal_proof(self):
        for operation in ('poll', 'probe'):
            with self.subTest(operation=operation):
                ops = PostKillOps(reap_after=0., absent_after=0.)
                r, p, row = self.owned_stop(ops)
                def late():
                    if ops.kill_at is not None:
                        ops.t = ops.kill_at + 2.
                setattr(ops, 'after_' + operation, late)
                with self.assertRaisesRegex(RuntimeError, 'Stop deadline reached'):
                    r.stop(p, 8., row)
                self.assertIs(r.active[p.pid], p)
                self.assertFalse(row['stop']['group_absent'])
                if operation == 'poll':
                    self.assertFalse(row['stop']['leader_reaped'])
                    self.assertEqual(ops.events[-1][0], 'poll')
                self.assertTrue(all(t < ops.t for _, t in ops.events))
                self.assertEqual(len(ops.signals), 2)

    def test_post_kill_confirmation_uses_original_deadline_and_exact_owner(self):
        ops = PostKillOps(absent_after=float('inf'))
        r, p, row = self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError, 'Stop deadline reached'):
            r.stop(p, 5.25, row)
        self.assertEqual(row['stop']['post_kill_confirmation']['deadline'], 5.25)
        self.assertEqual(ops.t, 5.25)
        self.assertTrue(all(t < 5.25 for _, t in ops.events))
        ops = PostKillOps()
        r, p, row = self.owned_stop(ops)
        def rebind():
            if ops.kill_at is not None:
                r.active[p.pid] = SimpleNamespace(pid=p.pid)
        ops.after_poll = rebind
        with self.assertRaisesRegex(RuntimeError, 'Unowned group'):
            r.stop(p, 8., row)
        self.assertNotIn('post_kill_unknown_probes', row['stop'])
        self.assertEqual(ops.events[-1][0], 'poll')
        self.assertEqual(len(ops.signals), 2)

    def test_stop_never_observes_or_signals_after_deadline(self):
        ops = PostKillOps()
        r, p, row = self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError, 'Stop deadline reached'):
            r.stop(p, 0., row)
        self.assertEqual(ops.events, [])
        ops = PostKillOps()
        r, p, row = self.owned_stop(ops)
        ops.after_send = lambda: setattr(ops, 't', 8.)
        with self.assertRaisesRegex(RuntimeError, 'Stop deadline reached'):
            r.stop(p, 8., row)
        self.assertEqual(row['stop']['signals'], [15])
        self.assertEqual(ops.events[-1][0], 'signal')
        self.assertTrue(all(t < 8. for _, t in ops.events))

    def test_EPERM_after_TERM_can_confirm_without_another_signal(self):
        r=self.runner(Ops({'delay':float('inf'),'probe_errors':{2:PermissionError(errno.EPERM,'after TERM')}}))
        with self.assertRaises(RuntimeError):r.command('after-term',['synthetic'],30)
        row=r.report['commands'][0];obs=row['process_observations']
        self.assertEqual(row['error'],"RuntimeError('Command timeout')")
        self.assertEqual(obs['stop.signal_15']['result'],'syscall_returned')
        self.assertNotIn('stop.signal_9',obs)
        self.assertEqual(row['stop']['signals'],[15])
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        self.assertFalse(r.active)
        self.assertNotIn('stop_error',row)
        self.assertEqual(row['stop']['post_term_unknown_probes']['count'],1)
        self.assertEqual(row['stop']['post_term_confirmation']['status'],'confirmed')

    def test_post_term_transient_unknown_requires_both_actual_proofs(self):
        ops=PostTermOps();r,p,row=self.owned_stop(ops)
        r.stop(p,8.,row)
        self.assertEqual(row['stop']['signals'],[15])
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        self.assertFalse(r.active)
        self.assertEqual(row['stop']['post_term_confirmation'],{'deadline':5.,'status':'confirmed'})
        self.assertEqual(row['stop']['post_term_unknown_probes']['count'],ops.unknown_count)
        self.assertGreater(ops.unknown_count,1)
        self.assertEqual(len(ops.signals),1)
        self.assertNotIn('errno',row['process_observations']['stop.group_probe'])

    def test_post_term_permanent_unknown_fails_at_same_grace_without_escalation(self):
        ops=PostTermOps(absent_after=float('inf'));r,p,row=self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError,'Stop deadline reached'):r.stop(p,8.,row)
        self.assertEqual(ops.t,5.);self.assertIs(r.active[p.pid],p)
        self.assertTrue(row['stop']['leader_reaped']);self.assertFalse(row['stop']['group_absent'])
        self.assertEqual(row['stop']['signals'],[15])
        self.assertEqual(row['stop']['post_term_confirmation']['status'],'unconfirmed')
        unknown=row['stop']['post_term_unknown_probes']
        self.assertEqual(unknown['count'],ops.unknown_count);self.assertGreater(unknown['count'],50)
        self.assertLess(len(json.dumps(unknown)),300)
        self.assertTrue(all(t<5. for _,t in ops.events))
        with self.assertRaisesRegex(RuntimeError,'No repeated signalling'):r.stop(p,20.,row)
        self.assertEqual(len(ops.signals),1)

    def test_post_term_absence_without_reap_is_still_unconfirmed(self):
        ops=PostTermOps(reap_after=float('inf'),absent_after=.1);r,p,row=self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError,'Stop deadline reached'):r.stop(p,8.,row)
        self.assertTrue(row['stop']['group_absent']);self.assertFalse(row['stop']['leader_reaped'])
        self.assertIs(r.active[p.pid],p);self.assertEqual(len(ops.signals),1)
        self.assertEqual(ops.t,5.)

    def test_post_term_deadline_and_owner_are_not_relaxed(self):
        ops=PostTermOps(absent_after=float('inf'));r,p,row=self.owned_stop(ops)
        with self.assertRaisesRegex(RuntimeError,'Stop deadline reached'):r.stop(p,.15,row)
        self.assertEqual(row['stop']['post_term_confirmation']['deadline'],.15)
        self.assertEqual(ops.t,.15);self.assertTrue(all(t<.15 for _,t in ops.events))
        ops=PostTermOps(reap_after=0,absent_after=0);r,p,row=self.owned_stop(ops)
        def late():
            if ops.term_at is not None:ops.t=5.
        ops.after_probe=late
        with self.assertRaisesRegex(RuntimeError,'Stop deadline reached'):r.stop(p,5.,row)
        self.assertFalse(row['stop']['group_absent']);self.assertIs(r.active[p.pid],p)
        ops=PostTermOps();r,p,row=self.owned_stop(ops)
        def rebind():
            if ops.term_at is not None:r.active[p.pid]=SimpleNamespace(pid=p.pid)
        ops.after_probe=rebind
        with self.assertRaisesRegex(RuntimeError,'Unowned group'):r.stop(p,8.,row)
        self.assertNotIn('post_term_unknown_probes',row['stop']);self.assertEqual(len(ops.signals),1)

    def test_post_term_only_group_probe_EPERM_after_successful_TERM_may_settle(self):
        ops=Ops({'delay':float('inf'),'probe_error':True});r,p,row=self.owned_stop(ops)
        with self.assertRaises(PermissionError):r.stop(p,8.,row)
        self.assertEqual(ops.signals,[]);self.assertNotIn('post_term_confirmation',row['stop'])
        denied=PostTermOps()
        def poll_denied():
            if denied.term_at is not None:raise PermissionError(errno.EPERM,'poll')
        denied.after_poll=poll_denied
        for ops in [denied,PostTermOps(probe_error=PermissionError(errno.EACCES,'probe')),PostTermOps(term_result='already_absent_ESRCH')]:
            with self.subTest(kind=repr(ops.probe_error),result=ops.term_result):
                r,p,row=self.owned_stop(ops)
                with self.assertRaises(OSError):r.stop(p,8.,row)
                self.assertNotIn('post_term_unknown_probes',row['stop'])
                self.assertEqual(ops.t,0.);self.assertEqual(len(ops.signals),1)

    def test_signal_EPERM_is_distinct_from_probe_failure(self):
        r=self.runner(Ops({'delay':float('inf'),'signal_error':True}))
        with self.assertRaises(RuntimeError):r.command('signal-denied',['synthetic'],30)
        row=r.report['commands'][0];obs=row['process_observations']
        self.assertEqual(obs['stop.signal_15']['outcome'],'raised')
        self.assertEqual(obs['stop.signal_15']['errno'],errno.EPERM)
        self.assertEqual(obs['stop.group_probe']['outcome'],'returned')
        self.assertEqual(row['stop']['signals'],[])
        self.assertTrue(r.active)
        with self.assertRaisesRegex(RuntimeError,'ownership unresolved'):r.command('next',['synthetic'],30)
        self.assertEqual(len(r.ops.signals),1)

    def test_signal_ESRCH_is_recorded_without_claiming_delivery(self):
        r=self.runner(Ops({'delay':float('inf')}));real=hosted.core.base.RealOps({},self.root)
        def vanished(p,sig):
            outcome=real.send(p,sig);p.dead=True;return outcome
        with patch('os.killpg',side_effect=ProcessLookupError(errno.ESRCH,'gone')) as raw,patch.object(r.ops,'send',side_effect=vanished):
            with self.assertRaises(RuntimeError):r.command('gone',['synthetic'],30)
            self.assertEqual(raw.call_count,1)
        row=r.report['commands'][0]
        self.assertEqual(row['process_observations']['stop.signal_15']['result'],'already_absent_ESRCH')
        self.assertEqual(row['stop']['signals_semantics'],'send_wrapper_returned_not_delivery')
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        self.assertFalse(r.active)
        self.assertEqual(row['error'],"RuntimeError('Command timeout')")

    def test_returned_signals_do_not_establish_absence_or_reap(self):
        r=self.runner(Ops({'delay':float('inf'),'ignore_all':True}))
        with self.assertRaises(RuntimeError):r.command('unresolved',['synthetic'],30)
        row=r.report['commands'][0]
        for sig in [15,9]:self.assertEqual(row['process_observations']['stop.signal_'+str(sig)]['result'],'syscall_returned')
        self.assertFalse(row['stop']['group_absent'] or row['stop']['leader_reaped'])
        self.assertTrue(r.active)
        with self.assertRaisesRegex(RuntimeError,'ownership unresolved'):r.command('next',['synthetic'],30)
        self.assertEqual(len(r.ops.processes),1)

    def test_exited_leader_with_live_group_is_never_command_success(self):
        r=self.runner(Ops({'lingering':True}))
        with self.assertRaises(RuntimeError):r.command('descendant',['synthetic'],30)
        row=r.report['commands'][0]
        self.assertIn('Leader exited but process group remains',row['error'])
        self.assertFalse(row['process_observations']['command.group_probe']['result'])
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])

    def test_many_polls_keep_fixed_diagnostics_and_existing_save_count(self):
        r=self.runner(Ops({'delay':25}))
        with patch.object(r,'save',wraps=r.save) as save:r.command('slow',['synthetic'],60)
        row=r.report['commands'][0];obs=row['process_observations'];p=r.ops.processes[0]
        self.assertGreater(p.poll_calls,1000)
        self.assertEqual(p.poll_calls,sum(v['calls'] for k,v in obs.items() if k.endswith('.poll')))
        self.assertEqual(p.probe_calls,sum(v['calls'] for k,v in obs.items() if k.endswith('.group_probe')))
        self.assertLessEqual(len(obs),6)
        self.assertLess(len(json.dumps(obs)),3000)
        self.assertEqual(save.call_count,3)
        self.assertFalse(r.ops.signals)

    def files_runner(self, launch=None, terminate=None, group=None):
        home=self.root/'home'
        owned='10000000-0000-0000-0000-000000000001'
        container=home/'Library/Developer/CoreSimulator/Devices'/owned/'data/Containers/Shared/AppGroup/20000000-0000-0000-0000-000000000002'
        provider=container/'File Provider Storage';provider.mkdir(parents=True)
        home_patch=patch.object(Path,'home',return_value=home)
        home_patch.start();self.addCleanup(home_patch.stop)
        launch={'output':[('stdout',(hosted.core.FILES_BUNDLE+': 123\n').encode())],**(launch or {})}
        lookup={'output':[('stdout',(hosted.core.GROUP+'\t'+str(container)+'\n').encode())],**(group or {})}
        r=self.runner(Ops(launch,lookup,terminate or {}))
        r.owned,r.recovered=owned,True
        return r,provider

    def test_files_60s_caps_allow_slow_launch_and_terminate_with_real_provider_checks(self):
        r,provider=self.files_runner({'delay':25},{'delay':45})
        r.setup_files()
        self.assertEqual(r.folder,provider/r.folder_name)
        self.assertEqual(list(r.folder.iterdir()),[])
        self.assertEqual([x['requested_cap_seconds'] for x in r.report['commands']],[60,30,60])
        self.assertEqual(r.report['attempts'],{'files-launch':1,'files-terminate':1})
        self.assertFalse(r.active);self.assertEqual((r.limit,r.final),(1380,1500))
        with self.assertRaisesRegex(RuntimeError,'One-shot'):r.setup_files()
        self.assertEqual(len(r.ops.processes),3)

    def test_files_double_timeout_retains_launch_failure_and_attempts_terminate_once(self):
        r,_=self.files_runner({'delay':float('inf')})
        r.ops.plans=[r.ops.plans[0],{'delay':float('inf')}]
        with self.assertRaisesRegex(RuntimeError,'files-launch failed') as failure:r.setup_files()
        self.assertEqual(str(failure.exception.__cause__),'Command timeout')
        self.assertEqual(r.report['files_setup_terminate_error'],"RuntimeError('files-terminate failed')")
        self.assertEqual([x['id'] for x in r.report['commands']],['files-launch','files-terminate'])
        self.assertTrue(all(x['requested_cap_seconds']==60 for x in r.report['commands']))
        self.assertAlmostEqual(r.ops.t,104,places=6)
        self.assertIsNone(r.folder);self.assertFalse(r.active)

    def test_files_successful_launch_still_requires_successful_termination(self):
        r,provider=self.files_runner(terminate={'exit':2})
        with self.assertRaisesRegex(RuntimeError,'files-terminate failed'):r.setup_files()
        self.assertNotIn('files_setup_primary_error',r.report)
        self.assertFalse((provider/r.folder_name).exists());self.assertFalse(r.active)

    def test_files_provider_error_is_not_masked_by_termination_failure(self):
        r,_=self.files_runner(group={'output':[('stdout',b'invalid-group-list')]},terminate={'exit':2})
        with self.assertRaisesRegex(RuntimeError,'Malformed Files group list'):r.setup_files()
        self.assertIn('files-terminate failed',r.report['files_setup_terminate_error'])
        self.assertIsNone(r.folder)

    def test_files_provider_identity_is_rechecked_after_terminate(self):
        r,provider=self.files_runner()
        def replace_provider(argv):
            if argv[2]=='terminate':
                provider.rename(provider.with_name('original-provider'))
                provider.mkdir()
        r.ops.on_spawn=replace_provider
        with self.assertRaisesRegex(RuntimeError,'Provider changed before mkdir'):r.setup_files()
        self.assertFalse((provider/r.folder_name).exists());self.assertEqual(len(r.ops.processes),3)

    def test_files_cancelled_before_launch_creates_no_process(self):
        r,_=self.files_runner();r.interrupted=True
        with self.assertRaisesRegex(RuntimeError,'Interrupted'):r.setup_files()
        self.assertEqual(r.ops.processes,[])

    def test_files_cancelled_during_spawn_stops_group_without_terminate_spawn(self):
        r,_=self.files_runner();r.ops.on_spawn=lambda _:r.signal()
        with self.assertRaisesRegex(RuntimeError,'files-launch failed'):r.setup_files()
        self.assertEqual(len(r.ops.processes),1);self.assertFalse(r.active)
        self.assertTrue(r.interrupted);self.assertIsNone(r.folder)

    def test_files_unknown_spawn_or_unresolved_group_withholds_terminate(self):
        for kind,plan in [('unknown',{'spawn_error':True}),('unresolved',{'delay':float('inf'),'ignore_all':True})]:
            with self.subTest(kind=kind):
                old=self.root;self.root=old/kind;self.root.mkdir()
                r,_=self.files_runner(plan)
                with self.assertRaisesRegex(RuntimeError,'files-launch failed'):r.setup_files()
                self.assertEqual(r.report['attempts'],{'files-launch':1})
                self.assertEqual(len(r.report['commands']),1)
                self.assertTrue(r.unknown_spawn or r.active)
                self.root=old

    def test_files_caps_use_remaining_budget_and_never_spend_cleanup_reserve(self):
        r,_=self.files_runner({'delay':float('inf')});r.ops.t=1370
        with self.assertRaisesRegex(RuntimeError,'files-launch failed'):r.setup_files()
        row=r.report['commands'][0]
        self.assertEqual((row['work_deadline'],row['command_deadline']),(1372,1380))
        self.assertLessEqual(r.ops.t,1380);self.assertEqual(len(r.ops.processes),1)
        self.assertFalse(r.active);self.assertEqual((r.limit,r.final),(1380,1500))

    def test_only_exact_hosted_files_actions_get_larger_caps(self):
        r,_=self.files_runner()
        with patch.object(r,'command',return_value='') as command:
            r.sim('other','launch',r.owned,hosted.core.FILES_BUNDLE)
            self.assertEqual(command.call_args.args[-1],30)
            hosted.core.Recovery.sim(r,'files-launch','launch',r.owned,hosted.core.FILES_BUNDLE)
            self.assertEqual(command.call_args.args[-1],30)
            for args in [('launch','foreign',hosted.core.FILES_BUNDLE),('terminate',r.owned,hosted.core.FILES_BUNDLE),('launch',r.owned,'foreign.bundle')]:
                with self.assertRaisesRegex(RuntimeError,'Unexpected Files'):r.sim('files-launch',*args)
            with self.assertRaisesRegex(RuntimeError,'Unexpected Files'):
                r.sim('files-launch','launch',r.owned,hosted.core.FILES_BUNDLE,cap=90)
            self.assertEqual(command.call_count,2)

    def test_files_failure_retains_only_exact_closed_streams_and_keeps_primary(self):
        r,_=self.files_runner({'delay':float('inf'),'output':[]})
        r.ops.plans=[r.ops.plans[0],{'exit':3,'output':[('stderr',b'synthetic termination diagnostic')]}]
        private=r.out/'1-stdout.log';private.write_text('private process listing')
        r.report['commands'].append({'id':'export-app-stopped','finish':0,'outcome':'completed',
                                     'logs':{'stdout':str(private)}})
        with self.assertRaisesRegex(RuntimeError,'files-launch failed') as failure:r.setup_files()
        self.assertEqual(str(failure.exception.__cause__),'Command timeout')
        self.assertEqual(r.report['files_setup_terminate_error'],"RuntimeError('files-terminate failed')")
        self.assertEqual(private.read_text(),'private process listing')
        public=r.out/'PhaseLogs'
        self.assertEqual({p.name for p in public.iterdir()},
                         {label+'-'+channel+'.log' for label in ['files-launch','files-terminate']
                          for channel in ['stdout','stderr']})
        self.assertEqual((public/'files-terminate-stderr.log').read_bytes(),b'synthetic termination diagnostic')
        self.assertEqual(len(r.ops.processes),2);self.assertFalse(r.active)
        self.assertEqual(r.report['attempts'],{'files-launch':1,'files-terminate':1})
        for row in r.report['commands'][1:]:
            self.assertEqual(row['requested_cap_seconds'],60)
            self.assertTrue(all(Path(p).parent==public for p in row['logs'].values()))
        self.assertEqual((r.limit,r.final),(1380,1500))

    def test_files_log_move_failure_keeps_primary_and_raw_logs_private(self):
        r,_=self.files_runner({'delay':float('inf')})
        r.ops.plans=[r.ops.plans[0],{'exit':3}]
        with patch.object(Path,'rename',side_effect=OSError('synthetic move failed')):
            with self.assertRaisesRegex(RuntimeError,'files-launch failed') as failure:r.setup_files()
        self.assertEqual(str(failure.exception.__cause__),'Command timeout')
        self.assertIn('synthetic move failed',r.report['files_log_publication_error'])
        self.assertEqual(list((r.out/'PhaseLogs').iterdir()),[])
        self.assertTrue((r.out/'1-stdout.log').exists());self.assertFalse(r.active)
        self.assertNotIn('/*.log',(HERE.parent/'.github/workflows/ci.yml').read_text())

    def test_files_log_publication_failure_after_setup_success_still_fails(self):
        r,_=self.files_runner()
        with patch.object(Path,'rename',side_effect=OSError('synthetic move failed')):
            with self.assertRaisesRegex(OSError,'synthetic move failed'):r.setup_files()
        self.assertIn('synthetic move failed',r.report['files_log_publication_error'])
        self.assertTrue(any('Files log publication' in e for e in r.report['errors']))
        self.assertFalse(r.active);self.assertEqual(len(r.ops.processes),3)

    def test_files_log_allowlist_rejects_forgery_unknown_ownership_and_replacement(self):
        kinds=['argv','ps-path','symlink','unreaped','unclosed','unknown','collision','size','deadline']
        for kind in kinds:
            with self.subTest(kind=kind):
                root=self.root;self.root=root/kind;self.root.mkdir()
                r=self.runner(Ops({'output':[('stdout',b'synthetic Files output')]}));r.owned='10000000-0000-0000-0000-000000000001'
                r.sim('files-launch','launch',r.owned,hosted.core.FILES_BUNDLE)
                row=r.report['commands'][0];private=r.out/'private-ps.log';private.write_text('private process listing')
                if kind=='argv':row['argv']=['/bin/ps','-axww']
                if kind=='ps-path':row['logs']['stdout']=str(private)
                if kind=='symlink':
                    path=Path(row['logs']['stdout']);path.unlink();path.symlink_to(private)
                if kind=='unreaped':row['stop']['leader_reaped']=False
                if kind=='unclosed':row['log_close_errors']={'stdout':'unknown'}
                if kind=='unknown':r.unknown_spawn=True
                if kind=='collision':
                    public=r.out/'PhaseLogs';public.mkdir();(public/'files-launch-stdout.log').write_text('prior evidence')
                if kind=='size':row['bytes']['stdout']+=1
                if kind=='deadline':r.ops.t=r.limit
                with self.assertRaises(RuntimeError):r.retain_files_logs(0)
                self.assertEqual(private.read_text(),'private process listing')
                if (r.out/'PhaseLogs').exists():
                    self.assertTrue(all(p.read_text()=='prior evidence' for p in (r.out/'PhaseLogs').iterdir()))
                self.assertEqual(len(r.ops.processes),1)
                self.root=root

    def test_files_log_unknown_group_is_not_published_or_reinterpreted(self):
        r,_=self.files_runner({'delay':float('inf'),'ignore_all':True})
        with self.assertRaisesRegex(RuntimeError,'files-launch failed'):r.setup_files()
        self.assertTrue(r.active);self.assertIn('unresolved',r.report['files_log_publication_error'])
        self.assertFalse((r.out/'PhaseLogs').exists())
        self.assertEqual(r.report['attempts'],{'files-launch':1})
        self.assertEqual(len(r.ops.processes),1)

    def test_files_log_read_checks_consuming_deadline_withhold_rename(self):
        r=self.runner(Ops({'output':[('stdout',b'synthetic Files output')]}));r.owned='10000000-0000-0000-0000-000000000001'
        r.sim('files-launch','launch',r.owned,hosted.core.FILES_BUNDLE)
        original=hosted.os.path.lexists
        def late_check(path):
            result=original(path)
            if str(path).endswith('files-launch-stdout.log'):r.ops.t=r.limit
            return result
        with patch.object(hosted.os.path,'lexists',side_effect=late_check), \
             patch.object(Path,'rename',side_effect=AssertionError('NO LATE MUTATION')) as rename:
            with self.assertRaisesRegex(RuntimeError,'deadline reached'):r.retain_files_logs(0)
        rename.assert_not_called();self.assertEqual(list((r.out/'PhaseLogs').iterdir()),[])

    def test_nested_capability_probe_preserves_exact_EPERM_operation(self):
        r=self.runner(Ops({'probe_error':True}))
        with self.assertRaises(RuntimeError):r.check_capability()
        saved=json.loads((r.out/'Capability/receipt.json').read_text())
        obs=saved['commands'][0]['process_observations']
        self.assertEqual(obs['command.group_probe']['errno'],errno.EPERM)
        self.assertEqual(obs['stop.group_probe']['errno'],errno.EPERM)
        self.assertTrue(r.active)
        self.assertEqual(r.limit,1380)
        with self.assertRaisesRegex(RuntimeError,'ownership unresolved'):r.command('next',['synthetic'],30)
        self.assertEqual(len(r.ops.processes),1)


    # C12: exercise the actual command implementation with synthetic process/file boundaries.
    def c12_after_first_save(self, runner, action):
        original=runner.save;calls=0
        def save():
            nonlocal calls
            calls+=1
            if calls==1:action()
            return original()
        return patch.object(runner,'save',side_effect=save)

    def c12_command_pair(self, runner, cap=60):
        runner.command('first',['synthetic-only'],cap)
        runner.command('second',['synthetic-only'],cap)

    def test_c12_deadline_during_intent_prevents_spawn(self):
        r=self.runner()
        with self.c12_after_first_save(r,lambda:setattr(r.ops,'t',61)):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[]);self.assertFalse(r.unknown_spawn)
        self.assertEqual(r.report['commands'][0]['outcome'],'failed')

    def test_c12_cancel_during_intent_prevents_spawn(self):
        r=self.runner()
        with self.c12_after_first_save(r,r.signal):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[]);self.assertFalse(r.unknown_spawn)

    def test_c12_resource_during_intent_forces_fresh_scan(self):
        r=self.runner();free=SimpleNamespace(free=32*hosted.core.GIB)
        with patch.object(hosted.core.shutil,'disk_usage',return_value=free),self.c12_after_first_save(r,lambda:setattr(free,'free',1)):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[]);self.assertFalse(r.unknown_spawn)
        self.assertEqual(r.ops.now(),0)  # The periodic scan is not due yet.

    def test_c12_exact_eight_seconds_rejected(self):
        r=self.runner()
        with self.c12_after_first_save(r,lambda:setattr(r.ops,'t',52)):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[])
        row=r.report['commands'][0];self.assertEqual((row['command_deadline'],row['work_deadline'],row['stop_reserve_seconds']),(60,52,8))

    def test_c12_more_than_eight_seconds_retains_positive_control(self):
        r=self.runner()
        with self.c12_after_first_save(r,lambda:setattr(r.ops,'t',51.999)):
            self.c12_command_pair(r)
        self.assertEqual(len(r.ops.processes),2);self.assertTrue(all(row['outcome']=='completed' for row in r.report['commands']))

    def c12_open_hook(self, runner, action):
        original=Path.open
        def open_(path,*args,**kwargs):
            if path==runner.out/'1-stderr.log':action()
            return original(path,*args,**kwargs)
        return patch.object(Path,'open',open_)

    def test_c12_cancel_during_log_setup_prevents_spawn(self):
        r=self.runner()
        with self.c12_open_hook(r,r.signal):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[])

    def test_c12_resource_during_log_setup_prevents_spawn(self):
        r=self.runner();free=SimpleNamespace(free=32*hosted.core.GIB)
        with patch.object(hosted.core.shutil,'disk_usage',return_value=free),self.c12_open_hook(r,lambda:setattr(free,'free',1)):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[]);self.assertEqual(r.ops.now(),0)

    def test_c12_deadline_during_log_setup_prevents_spawn(self):
        r=self.runner()
        with self.c12_open_hook(r,lambda:setattr(r.ops,'t',61)):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[])

    def test_c12_partial_log_open_closes_first_handle(self):
        r=self.runner();opened=[];original=Path.open
        def open_(path,*args,**kwargs):
            if path==r.out/'1-stderr.log':raise OSError('synthetic second log open')
            f=original(path,*args,**kwargs)
            if path==r.out/'1-stdout.log':opened.append(f)
            return f
        with patch.object(Path,'open',open_):
            with self.assertRaises(RuntimeError) as caught:self.c12_command_pair(r)
        self.assertIsInstance(caught.exception.__cause__,OSError)
        self.assertEqual(len(opened),1);self.assertTrue(opened[0].closed);self.assertEqual(r.ops.processes,[])
        self.assertEqual(r.report['commands'][0]['outcome'],'failed')

    def c12_log_close_errors(self, runner, names=('1-stdout.log','1-stderr.log')):
        original=Path.open;closed=[]
        class Log:
            def __init__(self,f,name):self.file,self.name=f,name
            def write(self,data):return self.file.write(data)
            def close(self):
                self.file.close();closed.append(self.name)
                raise OSError('synthetic close '+self.name)
        def open_(path,*args,**kwargs):
            f=original(path,*args,**kwargs)
            return Log(f,path.name) if path.parent==runner.out and path.name in names and args and args[0]=='wb' else f
        return patch.object(Path,'open',open_),closed

    def test_c12_primary_and_all_secondary_errors_are_preserved(self):
        primary=RuntimeError('synthetic primary poll')
        r=self.runner(Ops({'poll_errors':{1:primary,2:PermissionError(errno.EPERM,'synthetic stop poll')},'close_error':True}))
        original=r.save;calls=0
        def save():
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('synthetic receipt failure')
            return original()
        logs,closed=self.c12_log_close_errors(r)
        with logs,patch.object(r,'save',side_effect=save):
            with self.assertRaises(RuntimeError) as caught:self.c12_command_pair(r)
        self.assertIs(caught.exception.__cause__,primary)
        row=r.report['commands'][0];self.assertEqual(row['error'],repr(primary));self.assertEqual(row['outcome'],'failed')
        self.assertCountEqual(closed,['1-stdout.log','1-stderr.log'])
        self.assertEqual(set(row['log_close_errors']),{'stdout','stderr'})
        self.assertIn('stop_error',row);self.assertIn('close_error',row);self.assertIn('receipt_error',row)
        self.assertEqual(row['process_observations']['command.poll']['exception_type'],'RuntimeError')
        self.assertEqual(row['process_observations']['stop.poll']['errno'],errno.EPERM)
        self.assertEqual(len(r.ops.processes),1)

    def test_c12_initial_receipt_failure_is_recorded_without_spawn(self):
        r=self.runner();original=r.save;calls=0
        def save():
            nonlocal calls
            calls+=1
            if calls==1:raise OSError('synthetic intent write failure')
            return original()
        with patch.object(r,'save',side_effect=save):
            with self.assertRaises(RuntimeError) as caught:self.c12_command_pair(r)
        self.assertIn('intent write failure',str(caught.exception.__cause__))
        self.assertEqual(r.ops.processes,[]);self.assertEqual(r.report['commands'][0]['outcome'],'failed')
        saved=json.loads((r.out/'receipt.json').read_text());self.assertIn('intent write failure',saved['commands'][0]['error'])

    def test_c12_successful_child_then_stdout_read_failure_stops_pair(self):
        r=self.runner();original=Path.read_text
        def read(path,*args,**kwargs):
            if path==r.out/'1-stdout.log':raise OSError('synthetic stdout read failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):
            with self.assertRaises(RuntimeError) as caught:self.c12_command_pair(r)
        self.assertIn('stdout read failure',str(caught.exception.__cause__));self.assertEqual(len(r.ops.processes),1)
        row=r.report['commands'][0];self.assertEqual(row['outcome'],'failed');self.assertIn('stdout_read_error',row)

    def test_c12_final_save_failure_after_success_stops_pair(self):
        r=self.runner();original=r.save;calls=0
        def save():
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('synthetic final receipt error')
            return original()
        with patch.object(r,'save',side_effect=save):
            with self.assertRaises(RuntimeError) as caught:self.c12_command_pair(r)
        self.assertIn('final receipt error',str(caught.exception.__cause__));self.assertEqual(len(r.ops.processes),1)
        row=r.report['commands'][0];self.assertEqual(row['outcome'],'failed');self.assertIn('receipt_error',row)

    def test_c12_final_save_crossing_cap_keeps_command_failure(self):
        r=self.runner();original=r.save;calls=0
        def save():
            nonlocal calls
            calls+=1;result=original()
            if calls==3:r.ops.t=61
            return result
        with patch.object(r,'save',side_effect=save):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(len(r.ops.processes),1);row=r.report['commands'][0]
        self.assertEqual(row['outcome'],'failed');self.assertIn('exceeded cap',row['error'])
        self.assertTrue(any('exceeded cap' in e for e in r.report['errors']))
        self.assertEqual((row['requested_cap_seconds'],row['work_deadline'],row['command_deadline'],row['stop_reserve_seconds']),(60,52,60,8))

    def test_c12_capability_rejects_secondary_errors_and_wrong_outcomes(self):
        for which in [0,1]:
            for key,value in [('log_close_errors',{'stdout':'synthetic'}),('receipt_error','synthetic'),('stdout_read_error','synthetic'),('finalization_error','synthetic'),('cap_error','synthetic'),('outcome','unknown')]:
                with self.subTest(which=which,key=key):
                    normal,failed,observations=self.proof();[normal,failed][which][key]=value
                    with self.assertRaises(RuntimeError):hosted.capability_result(normal,failed,observations,21,True)

    def test_c12_capability_secondary_failure_cannot_reach_setup(self):
        r=self.runner(self.capability_ops());r.capture_source=lambda:None;r.discover_profile=lambda:None
        original_save=hosted.core.Recovery.save;injected=False;checked=[]
        def save(probe):
            nonlocal injected
            if probe is not r and len(probe.report['commands'])==2 and 'finish' in probe.report['commands'][-1] and not injected:
                injected=True;raise OSError('synthetic capability final receipt failure')
            return original_save(probe)
        real_validator=hosted.capability_result
        def validate(normal,failed,observations,elapsed,actual):
            # Exercise validation on synthetic records without fabricating accepted capability.
            self.assertFalse(actual);checked.append(True)
            return real_validator(normal,failed,observations,elapsed,True)
        with patch.object(hosted.core.Recovery,'save',save),patch.object(hosted,'capability_result',side_effect=validate),patch.object(hosted.core.Recovery,'setup',side_effect=AssertionError('NO SETUP')) as setup:
            with self.assertRaises(RuntimeError):r.setup()
        self.assertTrue(injected and checked);setup.assert_not_called();self.assertNotIn('host_capability',r.report)
        self.assertEqual(len(r.ops.processes),2)

    def test_c12_command_failure_skips_restore_and_preserves_observations(self):
        r=self.runner(Ops({'exit':7}));steps=[]
        def work():
            r.command('phase-export',['synthetic-only'],60);steps.append('restore')
        with patch.object(r,'work',side_effect=work),patch.object(r,'cleanup',side_effect=lambda:r.report.update(cleanup_verified=True)):
            self.assertEqual(r.run(),1)
        self.assertEqual(steps,[]);row=r.report['commands'][0]
        self.assertEqual(row['outcome'],'failed');self.assertEqual(row['returncode'],7)
        self.assertEqual(row['process_observations']['command.poll']['result'],7)
        self.assertEqual(r.report['status'],'failed');self.assertFalse(r.report['runtime_accepted'])


    def test_c12_cancel_in_final_admission_resource_read_prevents_spawn(self):
        r=self.runner();calls=0
        def usage(_):
            nonlocal calls
            calls+=1
            if calls==4:r.signal()
            return SimpleNamespace(free=32*hosted.core.GIB)
        with patch.object(hosted.core.shutil,'disk_usage',side_effect=usage):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(calls,4);self.assertEqual(r.ops.processes,[])

    def test_c12_forced_scan_cannot_spend_stop_reserve(self):
        r=self.runner();original=r.monitor;calls=0
        def monitor():
            nonlocal calls
            calls+=1;original()
            if calls==2:r.ops.t=52
        with patch.object(r,'monitor',side_effect=monitor):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(r.ops.processes,[])

    def test_c12_periodic_scan_and_cleanup_bypass_are_unchanged(self):
        r=self.runner()
        with patch.object(r,'monitor',wraps=r.monitor) as monitor:
            r.checkpoint();r.checkpoint();self.assertEqual(monitor.call_count,1)
            r.checkpoint(force_resources=True);self.assertEqual(monitor.call_count,2)
            r.cleaning=True;r.interrupted=True
            r.checkpoint(force_resources=True);self.assertEqual(monitor.call_count,2)

    def test_scan_policy_clips_allowance_to_global_and_pending_command_work(self):
        r=self.runner();deadlines=[]
        def scan(root,identity,now,deadline,checkpoint,*,observation):
            deadlines.append(deadline)
            return {'logical':0,'allocated':0,'entries':0,'xcresults':{}}
        with patch.object(hosted.core,'live_sizes',side_effect=scan):
            r.monitor()
            r.report['commands'].append({'work_deadline':3,'command_deadline':11})
            r.monitor()  # Includes admission before Popen, not only an active PID.
            r.report['commands'][-1]['finish']=0
            r.monitor()
            r.limit=2;r.monitor()
        self.assertEqual(deadlines,[5,3,5,2])
        self.assertEqual(r.next_scan,1)
        self.assertEqual(r.ops.processes,[])

    def test_scan_policy_delayed_disk_read_cannot_publish_or_restart_budget(self):
        r=self.runner()
        def usage(_):
            r.ops.t+=5
            return SimpleNamespace(free=32*hosted.core.GIB)
        with patch.object(hosted.core.shutil,'disk_usage',side_effect=usage), \
             patch.object(hosted.core,'live_sizes') as scan:
            with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):r.monitor()
            first=copy.deepcopy(r.report['resource_scan_failure'])
            with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):r.monitor()
            scan.assert_not_called()
        self.assertEqual(r.report['resource_scan_failure'],first)
        self.assertEqual(first['stage'],'free_space_before')
        self.assertEqual((first['started_elapsed'],first['deadline_elapsed'],first['finished_elapsed']),(0,5,5))
        self.assertTrue(first['partial_counts_are_not_valid_accounting'])
        self.assertEqual(r.report['resources'],[]);self.assertEqual(r.next_scan,0)
        self.assertEqual(r.ops.processes,[])

    def test_scan_policy_late_final_disk_read_rejects_completed_traversal(self):
        r=self.runner();calls=0
        def usage(_):
            nonlocal calls
            calls+=1
            if calls==2:r.ops.t=5
            return SimpleNamespace(free=32*hosted.core.GIB)
        with patch.object(hosted.core.shutil,'disk_usage',side_effect=usage):
            with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):r.monitor()
        failed=r.report['resource_scan_failure']
        self.assertEqual(failed['stage'],'free_space_after')
        self.assertEqual(failed['traversal']['status'],'completed')
        self.assertTrue(failed['partial_counts_are_not_valid_accounting'])
        self.assertEqual(r.report['resources'],[])

    def test_scan_failure_keeps_original_error_and_first_bounded_progress(self):
        r=self.runner();error=PermissionError(errno.EPERM,'synthetic denied')
        def scan(*args,observation,**kwargs):
            observation.update(status='failed',partial_totals={'entries':7,'logical':12,'allocated':512})
            raise error
        with patch.object(hosted.core,'live_sizes',side_effect=scan):
            with self.assertRaises(PermissionError) as caught:r.monitor()
        self.assertIs(caught.exception,error)
        failed=copy.deepcopy(r.report['resource_scan_failure'])
        self.assertEqual(failed['stage'],'traversal')
        self.assertEqual(failed['traversal']['partial_totals']['entries'],7)
        with patch.object(hosted.core,'live_sizes',side_effect=RuntimeError('later diagnostic scan')):
            with self.assertRaisesRegex(RuntimeError,'later diagnostic scan'):r.monitor()
        self.assertEqual(r.report['resource_scan_failure'],failed)
        self.assertEqual(r.report['resources'],[])

    def combined_scan_timeout(self, ops):
        r=self.runner(ops);original=hosted.core.os.scandir;delayed=False
        # A slow spawn returns within the existing cap, leaving two seconds
        # before the command's work deadline and the unchanged eight for stop.
        ops.on_spawn=lambda argv:setattr(ops,'t',50.)
        def scandir(fd):
            nonlocal delayed
            result=original(fd)
            if r.active and not delayed:
                delayed=True;ops.t+=2.
            return result
        with patch.object(hosted.core.os,'scandir',side_effect=scandir):
            with self.assertRaisesRegex(RuntimeError,'combined failed'):
                r.command('combined',['synthetic-only'],60)
        self.assertTrue(delayed)
        row=r.report['commands'][0]
        self.assertEqual(row['error'],"RuntimeError('Output scan deadline exceeded')")
        self.assertEqual((row['work_deadline'],row['command_deadline']),(52.,60.))
        failed=r.report['resource_scan_failure']
        self.assertEqual((failed['started_elapsed'],failed['deadline_elapsed'],failed['finished_elapsed']),(50.,52.,52.))
        self.assertEqual(failed['traversal']['last_operation']['operation'],'scandir_open')
        self.assertEqual(failed['traversal']['partial_totals']['entries'],0)
        self.assertEqual(row['stop']['signals'],[15])
        self.assertEqual(row['stop']['post_term_confirmation']['deadline'],57.)
        self.assertEqual(len(ops.processes),1)
        self.assertEqual(json.loads((r.out/'receipt.json').read_text())['resource_scan_failure'],failed)
        return r,row

    def test_combined_scan_timeout_can_confirm_TERM_without_passing_command(self):
        ops=PostTermOps();r,row=self.combined_scan_timeout(ops)
        self.assertEqual(row['outcome'],'failed')
        self.assertNotIn('stop_error',row)
        self.assertEqual(row['stop']['post_term_confirmation']['status'],'confirmed')
        self.assertTrue(row['stop']['leader_reaped'] and row['stop']['group_absent'])
        self.assertFalse(r.active);self.assertLess(ops.t,57.)
        self.assertFalse(r.report['runtime_accepted'])

    def test_combined_scan_timeout_unknown_TERM_preserves_owner_and_blocks_spawn(self):
        ops=PostTermOps(absent_after=float('inf'));r,row=self.combined_scan_timeout(ops)
        self.assertEqual(row['stop']['post_term_confirmation']['status'],'unconfirmed')
        self.assertIn('Stop deadline reached',row['stop_error'])
        self.assertEqual(ops.t,57.);self.assertEqual(len(r.active),1)
        with self.assertRaisesRegex(RuntimeError,'Prior process ownership unresolved'):
            r.command('withheld',['synthetic-only'],60)
        self.assertEqual(len(ops.processes),1);self.assertEqual(len(ops.signals),1)
        self.assertFalse(r.report['runtime_accepted'])

    def test_c12_cancel_during_stdout_finalization_stops_pair(self):
        r=self.runner();original=Path.read_text
        def read(path,*args,**kwargs):
            data=original(path,*args,**kwargs)
            if path==r.out/'1-stdout.log':r.signal()
            return data
        with patch.object(Path,'read_text',read):
            with self.assertRaises(RuntimeError):self.c12_command_pair(r)
        self.assertEqual(len(r.ops.processes),1);row=r.report['commands'][0]
        self.assertEqual(row['outcome'],'failed');self.assertIn('Interrupted',row['finalization_error'])


class ResourceAccountingTests(unittest.TestCase):
    """Small filesystem fixtures and fake metadata; no native jobs or signals."""

    def setUp(self):
        stack = self.enterContext(contextlib.ExitStack())
        for name in ('subprocess.Popen', 'os.system', 'os.kill', 'os.killpg'):
            stack.enter_context(patch(name, side_effect=AssertionError('No native operation')))
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp).resolve() / 'owned'
        self.root.mkdir()

    def scan(self, **caps):
        with patch.dict(hosted.core.CAPS, caps):
            return hosted.core.live_sizes(self.root, hosted.core.identity_of(self.root), lambda: 0, 10)

    @staticmethod
    def metadata(*, size=0, blocks=0, directory=False, inode=2):
        return SimpleNamespace(st_dev=1, st_ino=inode,
            st_mode=(stat.S_IFDIR if directory else stat.S_IFREG) | 0o600,
            st_size=size, st_blocks=blocks)

    def fake_scan(self, root_stat, entries, **caps):
        """Keep the production walk/checks, replacing only filesystem reads."""
        children = []
        calls = []
        for name, metadata in entries:
            def read(*, follow_symlinks, metadata=metadata):
                calls.append(follow_symlinks)
                return metadata
            children.append(SimpleNamespace(name=name, stat=read))
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(hosted.core.CAPS, caps))
            stack.enter_context(patch.object(hosted.core, 'identity_of', return_value=[1, 1]))
            opened = stack.enter_context(patch.object(hosted.core.os, 'open', return_value=123))
            stack.enter_context(patch.object(hosted.core.os, 'fstat', return_value=root_stat))
            closed = stack.enter_context(patch.object(hosted.core.os, 'close'))
            stack.enter_context(patch.object(hosted.core.os, 'scandir',
                side_effect=lambda fd: contextlib.nullcontext(iter(children))))
            try:
                result = hosted.core.live_sizes(self.root, [1, 1], lambda: 0, 10)
            finally:
                opened.assert_called_once_with(self.root,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                closed.assert_called_once_with(123)
        self.assertEqual(calls, [False] * len(entries))
        return result

    def sparse(self, path, size=2 * 1024**2):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as stream:
            stream.truncate(size)
        self.assertEqual(path.stat().st_size, size)
        return path

    def test_sparse_derived_data_uses_allocated_disk_budget(self):
        sparse = self.sparse(self.root / 'DerivedData' / 'index')
        expected_allocated = sum(p.lstat().st_blocks * 512
            for p in (self.root, sparse.parent, sparse))
        self.assertLess(expected_allocated, 64 * 1024, 'Fixture must be physically sparse')
        result = self.scan(output_bytes=64 * 1024)
        self.assertEqual(result['logical'], 2 * 1024**2)
        self.assertEqual(result['allocated'], expected_allocated)
        self.assertEqual(result['entries'], 2)
        self.assertEqual(result['xcresults'], {})

    def test_dense_over_cap_still_rejected(self):
        dense = self.root / 'dense'
        dense.write_bytes(b'x' * (128 * 1024))
        self.assertGreater(dense.stat().st_blocks * 512, 64 * 1024)
        with self.assertRaisesRegex(RuntimeError, 'Owned output size cap exceeded'):
            self.scan(output_bytes=64 * 1024)

    def test_empty_root_allocation_is_capped(self):
        with self.assertRaisesRegex(RuntimeError, 'Owned output size cap exceeded'):
            self.fake_scan(self.metadata(directory=True, inode=1, blocks=129), [],
                output_bytes=64 * 1024)

    def test_root_allocation_unknown_fails_closed(self):
        for value in (None, -1, 1.5, True, '8', 'missing'):
            with self.subTest(value=value):
                root = self.metadata(directory=True, inode=1, blocks=value)
                if value == 'missing':
                    del root.st_blocks
                with self.assertRaisesRegex(RuntimeError, 'Allocation unknown'):
                    self.fake_scan(root, [])

    def test_entry_allocation_unknown_fails_closed(self):
        for value in (None, -1, 1.5, True, '8', 'missing'):
            with self.subTest(value=value):
                entry = self.metadata(size=1, blocks=value)
                if value == 'missing':
                    del entry.st_blocks
                with self.assertRaisesRegex(RuntimeError, 'Allocation unknown'):
                    self.fake_scan(self.metadata(directory=True, inode=1), [('index', entry)])

    def test_zero_blocks_remain_valid_for_sparse_files(self):
        result = self.fake_scan(self.metadata(directory=True, inode=1),
            [('index', self.metadata(size=2 * 1024**2))], output_bytes=0)
        self.assertEqual(result['allocated'], 0)
        self.assertEqual(result['logical'], 2 * 1024**2)

    def test_hardlinks_conservatively_count_each_entry_and_rescan_growth(self):
        first = self.root / 'first'
        first.write_bytes(b'x' * 4096)
        second = self.root / 'second'
        os.link(first, second)
        self.assertEqual(first.stat().st_ino, second.stat().st_ino)
        before = self.scan()
        self.assertEqual(before['logical'], 8192)
        self.assertEqual(before['allocated'],
            self.root.stat().st_blocks * 512 + 2 * first.stat().st_blocks * 512)
        with first.open('ab') as stream:
            stream.write(b'y' * (16 * 1024))
        after = self.scan()
        self.assertEqual(after['logical'], 2 * (4096 + 16 * 1024))
        self.assertEqual(after['allocated'],
            self.root.stat().st_blocks * 512 + 2 * first.stat().st_blocks * 512)
        self.assertGreater(after['allocated'], before['allocated'])
        with self.assertRaisesRegex(RuntimeError, 'Owned output size cap exceeded'):
            self.scan(output_bytes=before['allocated'])

    def test_later_hardlink_alias_uses_fresh_grown_stat(self):
        result = self.fake_scan(self.metadata(directory=True, inode=1, blocks=1), [
            ('first', self.metadata(size=4096, blocks=8, inode=2)),
            ('second', self.metadata(size=8192, blocks=16, inode=2))])
        self.assertEqual(result['logical'], 12288)
        self.assertEqual(result['allocated'], 512 + 12288)
        self.assertEqual(result['entries'], 2)

    def test_symlink_targets_are_never_counted_or_traversed(self):
        outside = Path(self.temp).resolve() / 'outside'
        outside.mkdir()
        target = outside / 'dense'
        target.write_bytes(b'x' * (128 * 1024))
        file_link, directory_link = self.root / 'file-link', self.root / 'dir-link'
        file_link.symlink_to(target)
        directory_link.symlink_to(outside, target_is_directory=True)
        result = self.scan()
        self.assertEqual(result['logical'], 0)
        self.assertEqual(result['allocated'], sum(p.lstat().st_blocks * 512
            for p in (self.root, file_link, directory_link)))
        self.assertEqual(result['entries'], 2)
        with self.assertRaisesRegex(RuntimeError, 'Manifest rejects links and special files'):
            hosted.core.tree_manifest(self.root)

    def test_xcresult_sparse_logical_content_limit_is_unchanged(self):
        self.sparse(self.root / 'result.xcresult' / 'data')
        with self.assertRaisesRegex(RuntimeError, 'xcresult size cap exceeded'):
            self.scan(output_bytes=8 * 1024**2, xcresult_bytes=64 * 1024)

    def test_xcresult_allocated_limit_also_remains(self):
        with self.assertRaisesRegex(RuntimeError, 'xcresult size cap exceeded'):
            self.fake_scan(self.metadata(directory=True, inode=1),
                [('result.xcresult', self.metadata(size=1, blocks=128))],
                output_bytes=1024**2, xcresult_bytes=32 * 1024)

    def test_manifest_logical_content_limit_still_precedes_hashing(self):
        self.sparse(self.root / 'content')
        with patch.object(hosted.core, 'file_digest', side_effect=AssertionError('No content read')) as digest:
            with self.assertRaisesRegex(RuntimeError, 'Manifest size cap exceeded'):
                hosted.core.tree_manifest(self.root, max_bytes=64 * 1024)
            digest.assert_not_called()

    def test_entry_limit_is_unchanged(self):
        (self.root / 'one').touch()
        (self.root / 'two').touch()
        with self.assertRaisesRegex(RuntimeError, 'Output scan entry cap exceeded'):
            self.scan(scan_entries=1)

    def test_depth_limit_is_unchanged(self):
        (self.root / 'nested').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'Output scan depth exceeded'):
            self.scan(scan_depth=0)

    def test_scan_deadline_is_unchanged(self):
        with self.assertRaisesRegex(RuntimeError, 'Output scan deadline exceeded'):
            hosted.core.live_sizes(self.root, hosted.core.identity_of(self.root), lambda: 10, 10)

    def timed_scan(self, *, delay, deadline, operation='stat', entries=1, error=None):
        clock=[0.];observation={};stat_calls=[];next_calls=[]
        def read(*,follow_symlinks):
            stat_calls.append(follow_symlinks)
            if operation=='stat':clock[0]+=delay
            if error is not None:raise error
            return self.metadata(size=4096,blocks=8)
        children=[SimpleNamespace(name='synthetic-'+str(i),stat=read) for i in range(entries)]
        def iterate():
            for child in children:
                next_calls.append(child.name)
                if operation=='next':clock[0]+=delay
                yield child
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(hosted.core,'identity_of',return_value=[1,1]))
            stack.enter_context(patch.object(hosted.core.os,'open',return_value=123))
            stack.enter_context(patch.object(hosted.core.os,'fstat',return_value=self.metadata(directory=True,inode=1,blocks=1)))
            closed=stack.enter_context(patch.object(hosted.core.os,'close'))
            stack.enter_context(patch.object(hosted.core.os,'scandir',side_effect=lambda fd:contextlib.nullcontext(iterate())))
            try:
                value=hosted.core.live_sizes(self.root,[1,1],lambda:clock[0],deadline,observation=observation)
            except BaseException as caught:
                value=caught
            closed.assert_called_once_with(123)
        return value,observation,stat_calls,next_calls

    def test_finite_scan_policy_allows_slow_complete_accounting_but_still_times_out(self):
        value,observation,stats,_=self.timed_scan(delay=2.5,deadline=hosted.core.CAPS['scan_seconds'])
        self.assertEqual(value,{'logical':4096,'allocated':4608,'entries':1,'xcresults':{}})
        self.assertEqual(stats,[False]);self.assertEqual(observation['status'],'completed')
        self.assertEqual(observation['longest_operation']['duration_seconds'],2.5)
        value,observation,_,_=self.timed_scan(delay=2.5,deadline=2)
        self.assertIsInstance(value,RuntimeError)
        self.assertEqual(observation['partial_totals']['entries'],0)
        value,observation,_,_=self.timed_scan(delay=5,deadline=hosted.core.CAPS['scan_seconds'])
        self.assertIsInstance(value,RuntimeError)
        self.assertEqual(observation['status'],'failed')
        self.assertEqual(observation['last_operation']['operation'],'entry_stat')
        self.assertEqual(observation['last_operation']['duration_seconds'],5)

    def test_scan_next_after_deadline_cannot_start_entry_stat(self):
        value,observation,stats,nexts=self.timed_scan(delay=3,deadline=3,operation='next',entries=2)
        self.assertIsInstance(value,RuntimeError)
        self.assertEqual(stats,[]);self.assertEqual(len(nexts),1)
        self.assertEqual(observation['last_operation']['operation'],'scandir_next')
        self.assertEqual(observation['partial_totals'],{'logical':0,'allocated':512,'entries':0})

    def test_scan_entry_permission_error_is_not_skipped(self):
        error=PermissionError(errno.EACCES,'synthetic denied')
        value,observation,stats,nexts=self.timed_scan(delay=.2,deadline=5,error=error,entries=2)
        self.assertIs(value,error);self.assertEqual(stats,[False]);self.assertEqual(len(nexts),1)
        self.assertEqual(observation['last_operation']['outcome'],'raised')
        self.assertEqual(observation['last_operation']['operation'],'entry_stat')
        self.assertEqual(observation['partial_totals']['entries'],0)

    def test_scan_failure_observation_size_does_not_grow_per_entry(self):
        value,observation,_,_=self.timed_scan(delay=.1,deadline=4.95,entries=60)
        self.assertIsInstance(value,RuntimeError)
        self.assertEqual(observation['partial_totals']['entries'],49)
        self.assertEqual(set(observation),{'status','operation_count','max_depth','last_operation',
            'longest_operation','error','duration_seconds','partial_totals','xcresult_count'})
        self.assertLess(len(json.dumps(observation)),2048)

    def test_scan_late_directory_open_closes_descriptor_without_fstat(self):
        clock=[0.];observation={}
        def opened(*args,**kwargs):clock[0]=5;return 123
        with patch.object(hosted.core,'identity_of',return_value=[1,1]), \
             patch.object(hosted.core.os,'open',side_effect=opened), \
             patch.object(hosted.core.os,'close') as closed, \
             patch.object(hosted.core.os,'fstat') as fstat:
            with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):
                hosted.core.live_sizes(self.root,[1,1],lambda:clock[0],5,observation=observation)
        closed.assert_called_once_with(123);fstat.assert_not_called()
        self.assertEqual(observation['last_operation']['operation'],'directory_open')

    def test_scan_final_root_identity_cannot_complete_after_deadline(self):
        clock=[0.];calls=0;identity=hosted.core.identity_of(self.root);observation={}
        def read(_):
            nonlocal calls
            calls+=1
            if calls==2:clock[0]=5
            return identity
        with patch.object(hosted.core,'identity_of',side_effect=read):
            with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):
                hosted.core.live_sizes(self.root,identity,lambda:clock[0],5,observation=observation)
        self.assertEqual(observation['status'],'failed')
        self.assertEqual(observation['last_operation']['operation'],'root_identity')


if __name__=='__main__':unittest.main(verbosity=2)
