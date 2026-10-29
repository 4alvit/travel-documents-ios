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
FILES_ALREADY_ABSENT = b'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\nSimulator device failed to terminate com.apple.DocumentsApp.\nfound nothing to terminate\nUnderlying error (domain=NSPOSIXErrorDomain, code=3):\n\tThe request to terminate "com.apple.DocumentsApp" failed. found nothing to terminate\n\tfound nothing to terminate\n'


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
        self.assertEqual(len(names),5)
        self.assertEqual({name.split('${{')[0].strip() for name in names},
                         {'name: TripDocket-tests-', 'name: TripDocket-simulator-',
                          'name: TripDocket-privacy-ipad-', 'name: TripDocket-recovery-',
                          'name: TripDocket-files-picker-failure-'})
        self.assertTrue(all('${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}' in name for name in names))
        prefix='build/RecoveryHosted-${{ github.run_id }}-${{ github.run_attempt }}/'
        paths=[line.strip() for line in workflow.splitlines() if 'build/RecoveryHosted' in line]
        self.assertTrue(all(path.startswith(prefix) for path in paths))
        self.assertEqual({path[len(prefix):] for path in paths},
                         {'*.json','PhaseLogs/','Capability/','*.xcresult/','BeforeReset/','AfterRestore/','*-attachments/'})
        self.assertNotIn('/*.log',workflow)

    def test_settings_counts_bind_real_model_to_localized_visible_and_accessible_value(self):
        source=(HERE.parent/'App/Views.swift').read_text()
        for key,label,member in [('trips','Trips','trips'),('people','People','travelers'),('documents','Documents','documents')]:
            localization='documents.title' if key=='documents' else 'nav.'+key
            binding=f'libraryCount(L10n.ui("{localization}", defaultValue: "{label}"), count: model.library.{member}.count, identifier: "settings.count.{key}")'
            self.assertEqual(source.count(binding),1)
            self.assertEqual(source.count(f'"settings.count.{key}"'),1)
        helper=source.split('private func libraryCount(',1)[1].split('\n    }',1)[0]
        for contract in ['count.formatted(.number.locale(L10n.formattingLocale()))','LabeledContent(label, value: value)',
                         '.accessibilityElement(children: .ignore)','.accessibilityLabel(Text(verbatim: label))',
                         '.accessibilityValue(Text(verbatim: value))','.accessibilityIdentifier(identifier)']:
            self.assertIn(contract,helper)

    def test_recovery_counts_require_unique_reachable_row_exact_label_and_value(self):
        source=(HERE.parent/'UITests/BatchImportUITests.swift').read_text()
        helper=source.split('private func recoveryCounts(',1)[1].split('private func localStoreSession()',1)[0]
        for key,label,count in [('trips','Trips','trips'),('people','People','people'),('documents','Documents','documents')]:
            self.assertIn(f'("settings.count.{key}", "{label}", {count})',helper)
        self.assertIn('app.descendants(matching: .any).matching(identifier: identifier)',helper)
        self.assertIn('try await reveal(row, app: app, navigation: "Settings")',helper)
        self.assertIn('rows.count == 1 && row.isHittable && row.label == label',helper)
        self.assertIn('(row.value as? String) == String(count)',helper)
        self.assertNotIn('||',helper);self.assertNotIn('row.staticTexts',helper)
        for expected in ['recoveryCounts(trips: 1, people: 1, documents: 1, app: app)',
                         'recoveryCounts(trips: 1, people: 2, documents: 1, app: app)',
                         'recoveryCounts(trips: 0, people: 0, documents: 0, app: app)']:
            self.assertIn(expected,source)

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

    def test_recovery_index_policy_preserves_exact_phase_selection(self):
        r=self.runner();r.host['developer_dir']='/Applications/Controlled.app/Contents/Developer';r.owned='10000000-0000-0000-0000-000000000001'
        for phase,case in hosted.core.CASES.items():
            with self.subTest(phase=phase):
                argv=r.phase_argv(phase)
                self.assertEqual(argv.count('COMPILER_INDEX_STORE_ENABLE=NO'),1)
                self.assertEqual([arg for arg in argv if arg.startswith('-only-testing:')],
                                 ['-only-testing:TripfolioUITests/'+case.removesuffix('()')])
                self.assertEqual(argv[argv.index('-configuration')+1],'Debug')
                self.assertEqual(argv[argv.index('-derivedDataPath')+1],str(r.out/'DerivedData'))
                self.assertEqual(argv[argv.index('-resultBundlePath')+1],str(r.out/(phase+'.xcresult')))
                self.assertEqual(argv[argv.index('-parallel-testing-enabled')+1],'NO')
                self.assertEqual(argv[argv.index('-maximum-concurrent-test-simulator-destinations')+1],'1')
                self.assertEqual(argv[argv.index('-default-test-execution-time-allowance')+1],'300')
                self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance')+1],'300')
                self.assertEqual(argv[-2:],['CODE_SIGNING_ALLOWED=NO','test'])
        self.assertEqual((hosted.core.CAPS['scan_seconds'],hosted.core.CAPS['phase_seconds'],r.limit,r.final),(5,600,1380,1500))

    def test_recovery_index_policy_keeps_phase_gates_and_command_budget(self):
        r=self.runner();r.host['developer_dir']='/Applications/Controlled.app/Contents/Developer';r.owned='10000000-0000-0000-0000-000000000001'
        original_env,original_cwd=r.ops.env,r.ops.cwd
        with patch.object(r,'verify_folder'),patch.object(r,'once') as once, \
             patch.object(r,'authorize_restore') as authorize,patch.object(r,'command') as command, \
             patch.object(r,'preserve_result',return_value=r.out/'copy.xcresult') as preserve, \
             patch.object(r,'read_result') as read,patch.object(r,'app_state',return_value='validated library'):
            for phase in ['export','restore']:
                def observed(label,argv,cap):
                    self.assertEqual(label,'phase-'+phase);self.assertEqual(cap,600)
                    self.assertIn('COMPILER_INDEX_STORE_ENABLE=NO',argv)
                    self.assertEqual(r.ops.env['TEST_RUNNER_TRIPDOCKET_RECOVERY_PHASE'],phase)
                    self.assertEqual(r.ops.cwd,r.candidate)
                command.side_effect=observed
                self.assertEqual(hosted.core.Recovery.run_phase(r,phase),'validated library')
                once.assert_called_with('phase-'+phase);preserve.assert_called_with(phase)
                read.assert_called_with(phase,r.out/'copy.xcresult')
                self.assertIs(r.ops.env,original_env);self.assertIs(r.ops.cwd,original_cwd)
            authorize.assert_called_once_with();self.assertEqual(command.call_count,2)
            with self.assertRaisesRegex(RuntimeError,'Unknown phase'):hosted.core.Recovery.run_phase(r,'other')
            self.assertEqual(command.call_count,2)

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

    def files_runner(self, group=None):
        home=self.root/'home'
        owned='10000000-0000-0000-0000-000000000001'
        container=home/'Library/Developer/CoreSimulator/Devices'/owned/'data/Containers/Shared/AppGroup/20000000-0000-0000-0000-000000000002'
        provider=container/'File Provider Storage';provider.mkdir(parents=True)
        home_patch=patch.object(Path,'home',return_value=home)
        home_patch.start();self.addCleanup(home_patch.stop)
        lookup={'output':[('stdout',(hosted.core.GROUP+'\t'+str(container)+'\n').encode())],**(group or {})}
        r=self.runner(Ops(lookup))
        r.owned,r.recovered=owned,True
        return r,provider

    def test_files_group60_allows35seconds_and_reuses_original_lookup_work_deadline(self):
        r,provider=self.files_runner(group={'delay':35});r.setup_files()
        group=r.report['commands'][0]
        self.assertEqual(group['argv'],['/usr/bin/xcrun','simctl','get_app_container',r.owned,hosted.core.FILES_BUNDLE,'groups'])
        self.assertEqual(group['requested_cap_seconds'],60)
        self.assertAlmostEqual(group['work_deadline']-group['start'],52)
        self.assertAlmostEqual(group['command_deadline']-group['start'],60)
        self.assertEqual(r.report['files_provider_readiness']['work_deadline'],group['work_deadline'])
        self.assertEqual([x['requested_cap_seconds'] for x in r.report['commands']],[60])
        self.assertEqual(r.folder,provider/r.folder_name);self.assertEqual(len(r.ops.processes),1)
        self.assertEqual((r.limit,r.final),(1380,1500));self.assertFalse(r.active)

    def test_files_group60_times_out_at52_keeps_primary_and_stop_proofs(self):
        r,_=self.files_runner(group={'delay':52.5,'output':[]})
        with self.assertRaisesRegex(RuntimeError,'files-group failed'):r.setup_files()
        group=r.report['commands'][0]
        self.assertEqual(group['requested_cap_seconds'],60)
        self.assertAlmostEqual(group['work_deadline']-group['start'],52)
        self.assertEqual(group['stop_reserve_seconds'],8)
        self.assertLessEqual(group['finish'],group['command_deadline'])
        self.assertEqual(group['bytes']['stdout'],0)
        self.assertTrue(group['stop']['leader_reaped'] and group['stop']['group_absent'])
        self.assertEqual(r.report['files_setup_primary_error'],"RuntimeError('files-group failed')")
        self.assertEqual(r.report['files_setup_failure']['stage'],'group_lookup')
        self.assertNotIn('files_provider_readiness',r.report)
        self.assertNotIn('files_setup_terminate_error',r.report)
        self.assertEqual(len(r.ops.processes),1);self.assertIsNone(r.folder)

    def test_files_group60_clips_to_original_global_work_and_retains_cleanup(self):
        r,_=self.files_runner(group={'delay':30,'output':[]});r.ops.t=1350
        with self.assertRaisesRegex(RuntimeError,'files-group failed'):r.setup_files()
        group=r.report['commands'][0]
        self.assertEqual((group['requested_cap_seconds'],group['work_deadline'],group['command_deadline']),(60,1372,1380))
        self.assertTrue(group['stop']['leader_reaped'] and group['stop']['group_absent'])
        self.assertLessEqual(r.ops.t,1380);self.assertEqual((r.limit,r.final),(1380,1500))
        self.assertEqual(len(r.ops.processes),1);self.assertFalse(r.active)
        self.assertNotIn('files_provider_readiness',r.report)

    def test_files_group60_scope_is_exact_and_other_app_state_lookups_stay30(self):
        r=self.runner();r.owned='10000000-0000-0000-0000-000000000001'
        wrong=[('get_app_container','other',hosted.core.FILES_BUNDLE,'groups'),
               ('get_app_container',r.owned,hosted.core.BUNDLE,'groups'),
               ('get_app_container',r.owned,hosted.core.FILES_BUNDLE,'app'),
               ('launch',r.owned,hosted.core.FILES_BUNDLE)]
        for argv in wrong:
            with self.assertRaisesRegex(RuntimeError,'Unexpected Files group lookup'):r.sim('files-group',*argv)
        with self.assertRaisesRegex(RuntimeError,'Unexpected Files group lookup'):
            r.sim('files-group','get_app_container',r.owned,hosted.core.FILES_BUNDLE,'groups',cap=60)
        self.assertEqual(r.ops.processes,[])
        for label,kind in [('export-bundle','app'),('export-data','data'),('restore-bundle','app'),('restore-data','data')]:
            r.sim(label,'get_app_container',r.owned,hosted.core.BUNDLE,kind)
        self.assertEqual([x['requested_cap_seconds'] for x in r.report['commands']],[30]*4)
        r.ops.t=1372
        with self.assertRaisesRegex(RuntimeError,'Insufficient command/stop budget'):
            r.sim('files-group','get_app_container',r.owned,hosted.core.FILES_BUNDLE,'groups')
        self.assertEqual(len(r.ops.processes),4)

    def test_provider_readiness_observes_exact_leaf_without_relaunch_or_bootstrap(self):
        r,provider=self.files_runner(group={'delay':3})
        provider.rmdir()
        original_sleep=r.ops.sleep
        def appear(seconds):
            original_sleep(seconds)
            observation=r.report.get('files_provider_readiness')
            if observation and r.ops.now()>=observation['start']+.2 and not provider.exists():
                provider.mkdir()  # Model the provider, never production bootstrap.
        r.ops.sleep=appear
        r.setup_files()
        observation=r.report['files_provider_readiness']
        self.assertEqual(observation['status'],'ready')
        self.assertGreater(observation['absent_observations'],0)
        self.assertEqual(observation['work_deadline'],r.report['commands'][0]['work_deadline'])
        self.assertLess(observation['finish'],observation['work_deadline'])
        self.assertEqual([x['id'] for x in r.report['commands']],['files-group'])
        self.assertEqual([x['requested_cap_seconds'] for x in r.report['commands']],[60])
        self.assertEqual(r.folder,provider/r.folder_name)
        self.assertEqual((r.limit,r.final),(1380,1500))
        self.assertFalse(r.active)

    def test_provider_readiness_does_not_renew_lookup_work_deadline(self):
        r,provider=self.files_runner(group={'delay':51})
        provider.rmdir()
        with self.assertRaisesRegex(RuntimeError,'(?:provider readiness|work) deadline reached'):r.setup_files()
        observation=r.report['files_provider_readiness'];lookup=r.report['commands'][0]
        self.assertEqual(observation['work_deadline'],lookup['work_deadline'])
        self.assertLess(observation['finish']-observation['start'],1.1)
        self.assertEqual(observation['status'],'failed')
        self.assertEqual(observation['last_absence'],{'errno':errno.ENOENT,'filename':'File Provider Storage'})
        self.assertEqual(r.report['files_setup_failure']['stage'],'provider_readiness')
        self.assertFalse(provider.exists())
        self.assertEqual(len(r.ops.processes),1)
        self.assertEqual((r.limit,r.final),(1380,1500))
        self.assertLess(observation['probes'],25)

    def test_provider_readiness_global_clip_keeps_stop_and_cleanup_reserves(self):
        r,provider=self.files_runner();provider.rmdir();r.ops.t=1350
        with self.assertRaisesRegex(RuntimeError,'(?:provider readiness|work) deadline reached'):r.setup_files()
        observation=r.report['files_provider_readiness'];lookup=r.report['commands'][0]
        self.assertEqual((lookup['work_deadline'],lookup['command_deadline']),(1372,1380))
        self.assertEqual(observation['finish'],1372)
        self.assertEqual((r.limit,r.final),(1380,1500))
        self.assertEqual(len(r.ops.processes),1)
        self.assertNotIn('files_setup_terminate_error',r.report)
        self.assertFalse(r.active)
        self.assertLessEqual(observation['probes'],445)

    def test_provider_readiness_rejects_appearance_at_original_deadline(self):
        r,provider=self.files_runner(group={'delay':51});provider.rmdir()
        original_sleep=r.ops.sleep
        def too_late(seconds):
            original_sleep(seconds)
            observation=r.report.get('files_provider_readiness')
            if observation and r.ops.now()>=observation['work_deadline'] and not provider.exists():provider.mkdir()
        r.ops.sleep=too_late
        with self.assertRaisesRegex(RuntimeError,'(?:provider readiness|work) deadline reached'):r.setup_files()
        self.assertTrue(provider.exists());self.assertIsNone(r.folder)
        self.assertEqual(r.report['files_provider_readiness']['status'],'failed')
        self.assertEqual((r.limit,r.final),(1380,1500))

    def test_provider_readiness_rejects_symlink_without_wait(self):
        r,provider=self.files_runner();provider.rmdir()
        target=self.root/'alternate';target.mkdir();provider.symlink_to(target,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'not a real directory'):r.setup_files()
        self.assertEqual(r.report['files_provider_readiness']['probes'],1)
        self.assertEqual(r.report['files_provider_readiness']['absent_observations'],0)
        self.assertFalse(list(target.iterdir()))
        self.assertEqual(len(r.ops.processes),1)

    def test_provider_readiness_permission_error_is_immediate_and_bounded(self):
        r,provider=self.files_runner();original_stat=hosted.core.os.stat
        def denied(path,*args,**kwargs):
            if path==provider.name and kwargs.get('dir_fd') is not None:
                raise PermissionError(errno.EACCES,'denied',provider.name)
            return original_stat(path,*args,**kwargs)
        with patch.object(hosted.core.os,'stat',side_effect=denied):
            with self.assertRaises(PermissionError):r.setup_files()
        diagnostic=r.report['files_setup_failure']
        self.assertEqual(diagnostic,{'stage':'provider_readiness','type':'PermissionError',
            'errno':errno.EACCES,'provider_leaf_filename':'File Provider Storage'})
        self.assertEqual(r.report['files_provider_readiness']['probes'],1)
        self.assertEqual(r.report['files_provider_readiness']['absent_observations'],0)
        self.assertEqual(len(r.ops.processes),1)

    def test_provider_readiness_rejects_group_replacement_during_absence(self):
        r,provider=self.files_runner();provider.rmdir();original_sleep=r.ops.sleep;replaced=[]
        def replace_group(seconds):
            original_sleep(seconds)
            if r.report.get('files_provider_readiness') and not replaced:
                group=provider.parent;group.rename(group.with_name('old-group'));group.mkdir();replaced.append(True)
        r.ops.sleep=replace_group
        with self.assertRaisesRegex(RuntimeError,'group changed while observing'):r.setup_files()
        self.assertEqual(r.report['files_provider_readiness']['probes'],1)
        self.assertIsNone(r.folder);self.assertEqual((r.limit,r.final),(1380,1500))
        self.assertEqual(len(r.ops.processes),1)

    def test_provider_readiness_does_not_rebind_disappeared_observed_leaf(self):
        r,provider=self.files_runner();original_open=hosted.core.os.open
        def vanished(path,*args,**kwargs):
            if path==provider.name and kwargs.get('dir_fd') is not None:provider.rmdir()
            return original_open(path,*args,**kwargs)
        with patch.object(hosted.core.os,'open',side_effect=vanished):
            with self.assertRaises(FileNotFoundError):r.setup_files()
        observation=r.report['files_provider_readiness']
        self.assertEqual((observation['probes'],observation['absent_observations']),(1,0))
        self.assertEqual(r.report['files_setup_failure']['provider_leaf_filename'],'File Provider Storage')
        self.assertIsNone(r.folder);self.assertEqual(len(r.ops.processes),1)

    def test_provider_readiness_expiry_during_open_closes_descriptors_and_restores_deadline(self):
        r,provider=self.files_runner();original_open=hosted.core.os.open;opened=[]
        def expire_after_open(path,*args,**kwargs):
            fd=original_open(path,*args,**kwargs)
            if path==provider.parent or (path==provider.name and kwargs.get('dir_fd') is not None):opened.append(fd)
            if path==provider.name and kwargs.get('dir_fd') is not None:
                r.ops.t=r.report['files_provider_readiness']['work_deadline']
            return fd
        with patch.object(hosted.core.os,'open',side_effect=expire_after_open):
            with self.assertRaisesRegex(RuntimeError,'(?:provider readiness|work) deadline reached'):r.setup_files()
        self.assertEqual(len(opened),2)
        for fd in opened:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assertEqual((r.limit,r.final),(1380,1500));self.assertIsNone(r.folder)
        self.assertEqual(r.report['files_provider_readiness']['status'],'failed')
        self.assertEqual(len(r.ops.processes),1)

    def test_provider_readiness_expired_identity_cannot_start_later_filesystem_open(self):
        for kind in ('group','provider'):
            with self.subTest(kind=kind):
                r,provider=self.files_runner();original_identity=hosted.core.identity_of
                original_open=hosted.core.os.open;expired=[];late_opens=[]
                target=provider.parent if kind=='group' else provider
                def identity(path):
                    result=original_identity(path)
                    if path==target and r.report.get('files_provider_readiness') and not expired:
                        r.ops.t=r.report['files_provider_readiness']['work_deadline'];expired.append(True)
                    return result
                def opened(path,*args,**kwargs):
                    if expired and (path==provider.parent or path==provider.name):late_opens.append(str(path))
                    return original_open(path,*args,**kwargs)
                with patch.object(hosted.core,'identity_of',side_effect=identity),patch.object(hosted.core.os,'open',side_effect=opened):
                    with self.assertRaisesRegex(RuntimeError,'(?:provider readiness|work) deadline reached'):r.setup_files()
                self.assertTrue(expired);self.assertEqual(late_opens,[])
                self.assertEqual((r.limit,r.final),(1380,1500));self.assertIsNone(r.folder)
                self.assertEqual(len(r.ops.processes),1)
                self.tearDown();self.doCleanups();self.setUp()

    def test_provider_readiness_missing_group_fails_before_observation_with_relative_filename(self):
        r,provider=self.files_runner();provider.rmdir();provider.parent.rmdir()
        with self.assertRaises(FileNotFoundError):r.setup_files()
        diagnostic=r.report['files_setup_failure']
        self.assertEqual(diagnostic['stage'],'group_identity')
        self.assertEqual(diagnostic['errno'],errno.ENOENT)
        self.assertTrue(diagnostic['owned_relative_filename'].startswith('data/Containers/Shared/AppGroup/'))
        self.assertNotIn(str(self.root),json.dumps(diagnostic))
        self.assertNotIn('files_provider_readiness',r.report)
        self.assertEqual(len(r.ops.processes),1)


    def test_files_already_absent_is_not_generic_exit3_or_direct_sim_policy(self):
        r,_=self.files_runner()
        r.ops.plans=[{'exit':3,'output':[('stderr',FILES_ALREADY_ABSENT)]}]
        with self.assertRaisesRegex(RuntimeError,'files-terminate failed'):
            r.sim('files-terminate','terminate',r.owned,hosted.core.FILES_BUNDLE)
        self.assertNotIn('accepted_nonzero_exit',r.report['commands'][-1])
        r.ops.plans=[{'exit':3,'output':[('stderr',FILES_ALREADY_ABSENT)]}]
        with self.assertRaisesRegex(RuntimeError,'other failed'):
            r.command('other',['synthetic'],30)
        self.assertNotIn('accepted_nonzero_exit',r.report['commands'][-1])
        self.assertFalse(hosted.core.base.Smoke.accept_nonzero_exit(r,None,{},{}))


    def test_files_cancelled_before_lookup_creates_no_process(self):
        r,_=self.files_runner();r.interrupted=True
        with self.assertRaisesRegex(RuntimeError,'Interrupted'):r.setup_files()
        self.assertEqual(r.ops.processes,[])

    def test_files_cancelled_during_spawn_stops_group_without_later_spawn(self):
        r,_=self.files_runner();r.ops.on_spawn=lambda _:r.signal()
        with self.assertRaisesRegex(RuntimeError,'files-group failed'):r.setup_files()
        self.assertEqual(len(r.ops.processes),1);self.assertFalse(r.active)
        self.assertTrue(r.interrupted);self.assertIsNone(r.folder)

    def test_files_unknown_spawn_or_unresolved_group_withholds_later_work(self):
        for kind,plan in [('unknown',{'spawn_error':True}),('unresolved',{'delay':float('inf'),'ignore_all':True})]:
            with self.subTest(kind=kind):
                old=self.root;self.root=old/kind;self.root.mkdir()
                r,_=self.files_runner(group=plan)
                with self.assertRaisesRegex(RuntimeError,'files-group failed'):r.setup_files()
                self.assertEqual(r.report['attempts'],{'files-group':1})
                self.assertEqual(len(r.report['commands']),1)
                self.assertTrue(r.unknown_spawn or r.active)
                self.root=old

    def test_files_caps_use_remaining_budget_and_never_spend_cleanup_reserve(self):
        r,_=self.files_runner(group={'delay':float('inf')});r.ops.t=1370
        with self.assertRaisesRegex(RuntimeError,'files-group failed'):r.setup_files()
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
            r.sim('files-launch','launch',r.owned,hosted.core.FILES_BUNDLE)
            self.assertEqual(command.call_args.args[1],['/usr/bin/xcrun','simctl','launch',r.owned,hosted.core.FILES_BUNDLE])
            self.assertEqual(command.call_args.args[-1],120)
            r.sim('files-terminate','terminate',r.owned,hosted.core.FILES_BUNDLE)
            self.assertEqual(command.call_args.args[-1],60)
            self.assertEqual(command.call_count,4)

    def test_files_group_failure_keeps_primary_and_raw_logs_private(self):
        r,_=self.files_runner(group={'delay':float('inf'),'output':[]})
        private=r.out/'1-stdout.log';private.write_text('private process listing')
        r.report['commands'].append({'id':'export-app-stopped','finish':0,'outcome':'completed','logs':{'stdout':str(private)}})
        with self.assertRaisesRegex(RuntimeError,'files-group failed') as failure:r.setup_files()
        self.assertEqual(str(failure.exception.__cause__),'Command timeout')
        self.assertEqual(private.read_text(),'private process listing')
        self.assertFalse((r.out/'PhaseLogs').exists())
        self.assertTrue((r.out/'2-stdout.log').exists())
        self.assertEqual(len(r.ops.processes),1);self.assertFalse(r.active)
        self.assertEqual(r.report['attempts'],{'files-group':1})
        self.assertNotIn('files_setup_terminate_error',r.report)

    def test_files_log_finalization_failure_keeps_lookup_primary(self):
        r,_=self.files_runner(group={'delay':float('inf')})
        with patch.object(r,'retain_files_logs',side_effect=OSError('synthetic publication failed')):
            with self.assertRaisesRegex(RuntimeError,'files-group failed') as failure:r.setup_files()
        self.assertEqual(str(failure.exception.__cause__),'Command timeout')
        self.assertIn('synthetic publication failed',r.report['files_log_publication_error'])
        self.assertFalse((r.out/'PhaseLogs').exists())
        self.assertTrue((r.out/'1-stdout.log').exists());self.assertFalse(r.active)
        self.assertNotIn('/*.log',(HERE.parent/'.github/workflows/ci.yml').read_text())

    def test_files_log_publication_failure_after_provider_ready_still_fails(self):
        r,_=self.files_runner()
        with patch.object(r,'retain_files_logs',side_effect=OSError('synthetic publication failed')):
            with self.assertRaisesRegex(OSError,'synthetic publication failed'):r.setup_files()
        self.assertIn('synthetic publication failed',r.report['files_log_publication_error'])
        self.assertTrue(any('Files log publication' in e for e in r.report['errors']))
        self.assertFalse(r.active);self.assertEqual(len(r.ops.processes),1)

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
        r,_=self.files_runner(group={'delay':float('inf'),'ignore_all':True})
        with self.assertRaisesRegex(RuntimeError,'files-group failed'):r.setup_files()
        self.assertTrue(r.active);self.assertIsNone(r.folder)
        self.assertFalse((r.out/'PhaseLogs').exists())
        self.assertEqual(r.report['attempts'],{'files-group':1})
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

    def test_files_provider_only_ready_creates_exact_empty_folder_once(self):
        r,provider=self.files_runner();r.setup_files()
        self.assertEqual([x['id'] for x in r.report['commands']],['files-group'])
        self.assertEqual(r.report['attempts'],{'files-group':1})
        self.assertEqual(r.folder,provider/r.folder_name);self.assertEqual(list(r.folder.iterdir()),[])
        self.assertEqual(r.report['files_folder']['identity'],hosted.core.identity_of(r.folder))
        self.assertEqual(r.report['files_folder']['provider_identity'],hosted.core.identity_of(provider))
        self.assertTrue(r.report['files_folder']['initially_empty']);self.assertFalse(r.active)
        with self.assertRaisesRegex(RuntimeError,'One-shot'):r.setup_files()
        self.assertEqual(len(r.ops.processes),1)

    def test_files_provider_only_rejects_lookup_errors_without_startup_fallback(self):
        for kind,plan,error in [('malformed',{'output':[('stdout',b'invalid-group-list')]},'Malformed Files group list'),
                                ('nonzero',{'exit':3,'output':[('stderr',FILES_ALREADY_ABSENT)]},'files-group failed'),
                                ('close',{'close_error':True},'files-group failed')]:
            with self.subTest(kind=kind):
                root=self.root;self.root=root/kind;self.root.mkdir()
                r,_=self.files_runner(group=plan)
                with self.assertRaisesRegex(RuntimeError,error):r.setup_files()
                self.assertIsNone(r.folder);self.assertEqual(len(r.ops.processes),1)
                self.assertEqual([x['id'] for x in r.report['commands']],['files-group'])
                self.assertIn('files_setup_primary_error',r.report)
                self.assertNotIn('files_setup_terminate_error',r.report)
                self.assertNotIn('accepted_nonzero_exit',r.report['commands'][0])
                self.root=root

    def test_files_provider_identity_rechecked_before_owned_mkdir(self):
        r,provider=self.files_runner();original=r.wait_files_provider
        def ready(*args):
            result=original(*args)
            provider.rename(provider.with_name('original-provider'));provider.mkdir()
            return result
        with patch.object(r,'wait_files_provider',side_effect=ready):
            with self.assertRaisesRegex(RuntimeError,'Provider changed before mkdir'):r.setup_files()
        self.assertFalse((provider/r.folder_name).exists());self.assertIsNone(r.folder)
        self.assertEqual(len(r.ops.processes),1)

    def test_files_provider_only_keeps_later_phases_clipped_to_original_global_limit(self):
        r,_=self.files_runner(group={'delay':20});r.ops.t=500;r.setup_files()
        r.ops.plans=[{'delay':590},{'delay':float('inf')}]
        r.command('phase-export',['synthetic-export'],hosted.core.CAPS['phase_seconds'])
        with self.assertRaisesRegex(RuntimeError,'phase-restore failed'):
            r.command('phase-restore',['synthetic-restore'],hosted.core.CAPS['phase_seconds'])
        export,restore=r.report['commands'][-2:]
        self.assertEqual(export['requested_cap_seconds'],600)
        self.assertEqual((restore['requested_cap_seconds'],restore['work_deadline'],restore['command_deadline']),(600,1372,1380))
        self.assertLessEqual(r.ops.t,1380);self.assertEqual((r.limit,r.final),(1380,1500))
        self.assertFalse(r.active or r.unknown_spawn)
        self.assertFalse(r.report['cleanup_verified'] or r.report['runtime_accepted'])

    def test_files_provider_only_no_admission_with_stop_reserve_only(self):
        r,_=self.files_runner();r.ops.t=1372
        with self.assertRaisesRegex(RuntimeError,'Insufficient command/stop budget'):r.setup_files()
        self.assertEqual(r.ops.processes,[]);self.assertEqual(r.report['commands'],[])
        self.assertEqual(r.ops.t,1372);self.assertEqual((r.limit,r.final),(1380,1500));self.assertIsNone(r.folder)

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

    def test_phase_scan_ceiling_only_applies_to_unfinished_native_phase_context(self):
        r=self.runner();deadlines=[]
        def scan(*args,**kwargs):
            deadlines.append(args[3])
            return {'logical':0,'allocated':0,'entries':0,'xcresults':{}}
        with patch.object(hosted.core,'live_sizes',side_effect=scan):
            r.monitor()
            row={'id':'phase-export','work_deadline':592.,'command_deadline':600.}
            r.report['commands'].append(row);r.monitor()
            row['id']='phase-restore';r.monitor()
            row['id']='export-summary';r.monitor()
            row.update(id='phase-export',finish=0.);r.monitor()
            del row['finish'];row['work_deadline']=7.;r.monitor()
            row['work_deadline']=592.;r.limit=4.;r.monitor();r.limit=1380.
            probe=SimpleNamespace(t0=0.,limit=60.,report={'commands':[{'id':'normal','work_deadline':3.}]})
            r.monitor(command_owner=probe)
        self.assertEqual(deadlines,[5.,15.,15.,5.,5.,7.,4.,3.])
        self.assertEqual((hosted.core.CAPS['scan_seconds'],hosted.core.CAPS['phase_scan_seconds']), (5,15))
        self.assertEqual((r.limit,r.final,hosted.core.CAPS['phase_seconds']), (1380.,1500.,600))
        self.assertEqual(r.ops.processes,[])

    def test_phase_scan_slow_return_completes_uncached_traversal_within_fixed_15(self):
        r=self.runner();(r.out/'synthetic.bin').write_bytes(b'complete original')
        r.report['commands'].append({'id':'phase-export','work_deadline':592.})
        real=hosted.core.os.scandir;delayed=False
        def scan(fd):
            nonlocal delayed
            value=real(fd)
            if not delayed:delayed=True;r.ops.t+=6.
            return value
        with patch.object(hosted.core.os,'scandir',side_effect=scan):r.monitor()
        self.assertTrue(delayed);self.assertEqual(len(r.report['resources']),1)
        self.assertGreaterEqual(r.report['resources'][0]['entries'],2)
        self.assertEqual((r.report['resources'][0]['elapsed'],r.next_scan),(6.,7.))
        self.assertNotIn('resource_scan_failure',r.report)
        self.assertEqual(r.ops.processes,[])

    def test_phase_scan_cooperative_overshoot_keeps_failed_totals_and_never_renews(self):
        r=self.runner();r.report['commands'].append({'id':'phase-export','work_deadline':592.})
        real=hosted.core.os.scandir;calls=0
        def scan(fd):
            nonlocal calls
            calls+=1;value=real(fd);r.ops.t+=15.25;return value
        with patch.object(hosted.core.os,'scandir',side_effect=scan):
            with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):r.monitor()
        row=r.report['resource_scan_failure']
        self.assertEqual(calls,1)
        self.assertEqual((row['started_elapsed'],row['deadline_elapsed'],row['finished_elapsed']),(0.,15.,15.25))
        self.assertEqual(row['requested_scan_seconds'],15)
        self.assertEqual(row['traversal']['last_operation']['operation'],'scandir_open')
        self.assertEqual(row['traversal']['partial_totals']['entries'],0)
        self.assertTrue(row['partial_counts_are_not_valid_accounting'])
        self.assertEqual((r.report['resources'],r.next_scan),([],0))
        self.assertEqual(r.ops.processes,[])

    def test_phase_scan_actual_command_clips_15_to_original_work_and_stop_reserve(self):
        r=self.runner(Ops({'delay':float('inf')}));real=hosted.core.os.scandir;delayed=False
        r.ops.on_spawn=lambda argv:setattr(r.ops,'t',50.)
        def scan(fd):
            nonlocal delayed
            value=real(fd)
            if r.active and not delayed:delayed=True;r.ops.t+=2.25
            return value
        with patch.object(hosted.core.os,'scandir',side_effect=scan):
            with self.assertRaisesRegex(RuntimeError,'phase-export failed'):
                r.command('phase-export',['synthetic-only'],60)
        row=r.report['commands'][0];failed=r.report['resource_scan_failure']
        self.assertTrue(delayed);self.assertEqual(len(r.ops.processes),1)
        self.assertEqual((row['work_deadline'],row['command_deadline']),(52.,60.))
        self.assertEqual((failed['started_elapsed'],failed['deadline_elapsed'],failed['finished_elapsed']),(50.,52.,52.25))
        self.assertEqual(failed['requested_scan_seconds'],15)
        self.assertTrue(failed['partial_counts_are_not_valid_accounting'])
        self.assertEqual(row['stop']['signals'],[15])
        self.assertTrue(row['stop']['leader_reaped'] and row['stop']['group_absent'])
        self.assertLess(r.ops.t,60.);self.assertEqual((r.limit,r.final),(1380.,1500.))
        self.assertFalse(r.active);self.assertFalse(r.unknown_spawn)

    def test_combined_phase15_rescan_uses_same_original_command_deadline(self):
        for name,work,success,passes in [('phase-export',592.,True,2),
                ('selected-tests',592.,False,1),('phase-export',10.,False,2)]:
            with self.subTest(name=name,work=work):
                parent=self.root;self.root=parent/(name+'-'+str(work));self.root.mkdir()
                try:r=self.runner()
                finally:self.root=parent
                target=r.out/'Tests.xcresult'/'Data'/'_tmp.IJNVOw'
                target.parent.mkdir(parents=True);target.write_bytes(b'transient')
                r.report['commands'].append({'id':name,'pgid':123,'work_deadline':work})
                r.active[123]=SimpleNamespace(pid=123)
                root_passes=[0];vanished=[False];real=os.scandir
                def entry_stat(entry,*,follow_symlinks):
                    if entry.name==target.name and not vanished[0]:
                        vanished[0]=True;target.unlink()
                    return entry.stat(follow_symlinks=follow_symlinks)
                @contextlib.contextmanager
                def scan(fd):
                    info=os.fstat(fd)
                    if [info.st_dev,info.st_ino]==r.output_id:
                        root_passes[0]+=1;r.ops.t+=6.
                    with real(fd) as it:
                        yield (SimpleNamespace(name=e.name,
                            stat=lambda *,follow_symlinks,e=e:entry_stat(e,follow_symlinks=follow_symlinks),
                            is_file=lambda *,follow_symlinks,e=e:e.is_file(follow_symlinks=follow_symlinks)) for e in it)
                with patch.object(hosted.core.os,'scandir',side_effect=scan):
                    if success:r.monitor()
                    else:
                        with self.assertRaisesRegex(RuntimeError,'Output scan deadline exceeded'):r.monitor()
                self.assertEqual(root_passes[0],passes);self.assertEqual(r.ops.t,6.*passes)
                if success:
                    row=r.report['resources'][-1];self.assertEqual(row['complete_scan_attempts'],2)
                    self.assertEqual(row['elapsed'],12.);self.assertEqual(r.next_scan,13.)
                else:
                    self.assertEqual(r.report['resources'],[]);self.assertEqual(r.next_scan,0)
                    failed=r.report['resource_scan_failure']
                    self.assertEqual(failed['deadline_elapsed'],min(work,15. if name=='phase-export' else 5.))
                    self.assertTrue(failed['partial_counts_are_not_valid_accounting'])
                self.assertEqual(r.ops.processes,[])

    def test_biometric_bridge_checkpoint_binds_primary_writer_and_both_deadlines(self):
        cases=[('active',10.,3.,True,True,3.),('active',2.,10.,True,True,2.),
               ('active',10.,10.,True,True,5.),('ended',10.,3.,True,False,3.),
               ('absent',10.,3.,True,False,3.),('unowned',10.,3.,True,False,3.),
               ('wrong-pid',10.,3.,True,False,3.),('active',10.,3.,False,False,3.),
               ('unrelated-report',10.,3.,True,False,3.),('other-command',10.,3.,True,False,3.)]
        for index,(state,primary_work,child_work,linked,expected,end) in enumerate(cases):
            with self.subTest(state=state,primary_work=primary_work,child_work=child_work):
                root=self.root;self.root=root/str(index);self.root.mkdir()
                try:r=self.runner()
                finally:self.root=root
                primary={'id':'selected-tests','pgid':123,'work_deadline':primary_work}
                if state=='ended':primary['finish']=0.
                if state=='other-command':primary['id']='initial-runtimes'
                if state!='absent':r.report['commands']=[primary]
                if state!='unowned':r.active[123]=SimpleNamespace(pid=456 if state=='wrong-pid' else 123)
                report={'commands':[{'id':'biometric-1-match','pgid':456,'work_deadline':child_work}]}
                r.report['biometric_bridge']=report
                bridge=SimpleNamespace(parent=r if linked else object(),ops=r.ops,t0=r.t0,
                    limit=50.,report=copy.deepcopy(report) if state=='unrelated-report' else report,
                    active={456:SimpleNamespace(pid=456)})
                def checkpoint(*,force_resources=False):
                    r.checkpoint(force_resources=force_resources,command_owner=bridge)
                def scan(root,pin,now,deadline,check,*,observation,allow_xcresult_restart):
                    self.assertEqual(allow_xcresult_restart,expected);self.assertEqual(deadline,end)
                    return {'logical':0,'allocated':0,'entries':0,'xcresults':{}}
                with patch.object(hosted.core,'live_sizes',side_effect=scan):
                    checkpoint(force_resources=True)
                self.assertEqual(len(r.report['resources']),1);self.assertEqual(r.ops.processes,[])

    def test_scan_policy_clips_allowance_to_global_and_pending_command_work(self):
        r=self.runner();deadlines=[]
        def scan(root,identity,now,deadline,checkpoint,*,observation,allow_xcresult_restart):
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

    def derived_vanish_scan(self, *, relative=None, scenario='absent', allow_xcresult_restart=False, **caps):
        relative=relative or 'DerivedData/Build/Intermediates.noindex/Tripfolio.build/Debug-iphonesimulator/Tripfolio.build/Objects-normal/arm64/OCRService-bf16349b.o.tmp'
        root=Path(tempfile.mkdtemp(dir=self.temp)).resolve();target=root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        directory=scenario in ('directory','directory_open')
        target.mkdir() if directory else target.symlink_to('missing-target') if scenario=='symlink' else target.write_bytes(b'mutable derived output')
        (root/'retained-output').write_bytes(b'x'*4096)
        if scenario=='late_dense_cap':
            caps['output_bytes']=sum(path.lstat().st_blocks*512 for path in [root]+list(root.rglob('*')) if path!=target)-1
        identity=hosted.core.identity_of(root);observation={};clock=[0.];triggered=[False]
        opened=[];closed=[];absence_stats=[]
        real_scan,real_stat,real_open,real_close,real_fstat=os.scandir,os.stat,os.open,os.close,os.fstat
        def entry_stat(entry,*,follow_symlinks):
            if entry.name==target.name and not triggered[0]:
                triggered[0]=True
                if scenario=='entry_permission':raise PermissionError(errno.EACCES,'synthetic denied')
                if scenario=='entry_other_errno':raise FileNotFoundError(errno.ENOTDIR,'synthetic wrong type')
                if scenario=='directory_open':return entry.stat(follow_symlinks=follow_symlinks)
                target.rmdir() if directory else target.unlink()
                try:return entry.stat(follow_symlinks=follow_symlinks)
                except FileNotFoundError:
                    if scenario=='reappeared':target.write_bytes(b'new entry')
                    if scenario=='root_replaced':root.rename(root.with_name(root.name+'-old'));root.mkdir()
                    if scenario=='parent_replaced':target.parent.rename(target.parent.with_name(target.parent.name+'-old'));target.parent.mkdir()
                    if scenario=='late_entry':clock[0]=10.
                    raise
            return entry.stat(follow_symlinks=follow_symlinks)
        @contextlib.contextmanager
        def entries(fd):
            with real_scan(fd) as iterator:
                entries=sorted(iterator,key=lambda entry:entry.name=='retained-output')
                yield (SimpleNamespace(name=e.name,
                    stat=lambda *,follow_symlinks,e=e:entry_stat(e,follow_symlinks=follow_symlinks),
                    is_file=lambda *,follow_symlinks,e=e:False if scenario=='unknown_kind' and e.name==target.name else e.is_file(follow_symlinks=follow_symlinks)) for e in entries)
        def metadata(path,*args,**kwargs):
            if path==target.name and kwargs.get('dir_fd') is not None:
                self.assertIs(kwargs.get('follow_symlinks'),False);absence_stats.append(path)
                if scenario=='confirmation_permission':raise PermissionError(errno.EACCES,'synthetic denied')
                if scenario=='confirmation_other_errno':raise FileNotFoundError(errno.ENOTDIR,'synthetic wrong type')
                try:return real_stat(path,*args,**kwargs)
                except FileNotFoundError:
                    if scenario=='late_confirmation':clock[0]=10.
                    if scenario=='final_root_replaced':root.rename(root.with_name(root.name+'-old'));root.mkdir()
                    raise
            return real_stat(path,*args,**kwargs)
        def open_fd(path,*args,**kwargs):
            if scenario=='directory_open' and path==target.name:raise FileNotFoundError(errno.ENOENT,'synthetic directory vanished')
            fd=real_open(path,*args,**kwargs);opened.append(fd);return fd
        def close_fd(fd):closed.append(fd);return real_close(fd)
        def fd_stat(fd):
            value=real_fstat(fd)
            if scenario=='fd_replaced' and triggered[0]:
                return SimpleNamespace(st_dev=value.st_dev,st_ino=value.st_ino+1,st_mode=value.st_mode)
            return value
        with patch.dict(hosted.core.CAPS,caps),patch.object(hosted.core.os,'scandir',side_effect=entries), \
             patch.object(hosted.core.os,'stat',side_effect=metadata),patch.object(hosted.core.os,'open',side_effect=open_fd), \
             patch.object(hosted.core.os,'close',side_effect=close_fd),patch.object(hosted.core.os,'fstat',side_effect=fd_stat):
            try:result=hosted.core.live_sizes(root,identity,lambda:clock[0],10,observation=observation,
                                             allow_xcresult_restart=allow_xcresult_restart)
            except BaseException as error:result=error
        self.assertTrue(triggered[0]);self.assertCountEqual(opened,closed)
        return result,observation,root,absence_stats,clock[0]

    def test_derived_leaf_stat_race_confirms_absence_and_finishes_actual_accounting(self):
        paths = [
            'DerivedData/Build/Intermediates.noindex/Tripfolio.build/Debug-iphonesimulator/Tripfolio.build/Objects-normal/arm64/OCRService-bf16349b.o.tmp',
            'DerivedData/Index.noindex/DataStore/v5/_strings-252B4LO3KJQZ2.pcm-1XFHK3MYD85V5-a4840fb3',
            'DerivedData/Index.noindex/DataStore/v5/records/AB/Tripfolio-record',
            'DerivedData/ModuleCache.noindex/AB/Tripfolio.pcm',
            'DerivedData/Build/Intermediates.noindex/Tripfolio.swiftdeps',
        ]
        for relative in paths:
            with self.subTest(relative=relative):
                result,observation,root,probes,_=self.derived_vanish_scan(relative=relative)
                self.assertIsInstance(result,dict);self.assertEqual(probes,[Path(relative).name])
                retained=[root]+list(root.rglob('*'))
                self.assertEqual(result['allocated'],sum(p.lstat().st_blocks*512 for p in retained))
                self.assertEqual(result['logical'],sum(p.stat().st_size for p in retained if p.is_file()))
                self.assertEqual(result['entries'],len(retained)) # Includes the vanished encounter.
                self.assertEqual(result['confirmed_absent_derived_entries'],1)
                self.assertEqual(observation['status'],'completed')
                self.assertEqual(observation['last_confirmed_absent_path'],relative)

    def test_derived_leaf_absence_scope_excludes_products_xcresults_and_outside(self):
        for relative in [
                'evidence.xcresult/result.o.tmp', 'Source/input.tmp', 'Cache/Index.noindex/record.tmp',
                'DerivedData/Build/Products/Debug-iphonesimulator/Tripfolio.app/Tripfolio',
                'DerivedData/Build/Products',
                'DerivedData/evidence.xcresult/result.o.tmp',
                'DerivedData/Build/Intermediates.noindex/evidence.xcresult/result.tmp',
                'DerivedData/ModuleCache.noindex/final.xcresult']:
            with self.subTest(relative=relative):
                result,observation,_,probes,_=self.derived_vanish_scan(relative=relative)
                self.assertIsInstance(result,FileNotFoundError);self.assertEqual(probes,[])
                self.assertEqual(observation['status'],'failed')
                self.assertNotIn('confirmed_absent_derived_entries',observation)

    def test_derived_leaf_absence_never_suppresses_permission_or_other_errno(self):
        for relative in [None,'DerivedData/Index.noindex/DataStore/v5/index-record']:
            for scenario in ['entry_permission','entry_other_errno','confirmation_permission','confirmation_other_errno']:
                with self.subTest(relative=relative,scenario=scenario):
                    result,observation,_,_,_=self.derived_vanish_scan(relative=relative,scenario=scenario)
                    self.assertIsInstance(result,OSError);self.assertNotEqual(result.errno,errno.ENOENT)
                    self.assertEqual(observation['status'],'failed')

    def test_derived_leaf_absence_rejects_root_parent_and_descriptor_replacement(self):
        for relative in [None,'DerivedData/ModuleCache.noindex/AB/Tripfolio.pcm']:
            for scenario in ['root_replaced','parent_replaced','fd_replaced','final_root_replaced']:
                with self.subTest(relative=relative,scenario=scenario):
                    result,observation,_,_,_=self.derived_vanish_scan(relative=relative,scenario=scenario)
                    self.assertIsInstance(result,RuntimeError);self.assertIn('replaced',str(result))
                    self.assertEqual(observation['status'],'failed')
                    self.assertNotIn('confirmed_absent_derived_entries',observation)

    def test_derived_leaf_absence_requires_known_regular_kind_and_strict_directory_open(self):
        for relative in [None,'DerivedData/Index.noindex/DataStore/v5/index-record']:
            for scenario in ['directory','symlink','unknown_kind','directory_open']:
                with self.subTest(relative=relative,scenario=scenario):
                    result,observation,_,probes,_=self.derived_vanish_scan(relative=relative,scenario=scenario)
                    self.assertIsInstance(result,(RuntimeError,FileNotFoundError));self.assertEqual(probes,[])
                    self.assertEqual(observation['status'],'failed')

    def test_derived_leaf_reappearance_never_rebinds_or_accepts_partial_scan(self):
        for relative in [None,'DerivedData/Index.noindex/DataStore/v5/index-record']:
            with self.subTest(relative=relative):
                result,observation,_,probes,_=self.derived_vanish_scan(relative=relative,scenario='reappeared')
                self.assertIsInstance(result,RuntimeError);self.assertIn('reappeared',str(result))
                self.assertEqual(len(probes),1);self.assertEqual(observation['status'],'failed')
                self.assertNotIn('confirmed_absent_derived_entries',observation)

    def test_derived_leaf_absence_preserves_encounter_deadline_and_allocation_caps(self):
        for relative,cap in [(None,8),('DerivedData/Index.noindex/DataStore/v5/index-record',4)]:
            with self.subTest(relative=relative):
                result,observation,_,probes,_=self.derived_vanish_scan(relative=relative,scan_entries=cap)
                self.assertIsInstance(result,RuntimeError);self.assertIn('entry cap',str(result));self.assertEqual(probes,[])
                for scenario,expected_probes in [('late_entry',0),('late_confirmation',1)]:
                    with self.subTest(scenario=scenario):
                        result,observation,_,probes,elapsed=self.derived_vanish_scan(relative=relative,scenario=scenario)
                        self.assertIsInstance(result,RuntimeError);self.assertIn('deadline',str(result))
                        self.assertEqual(elapsed,10.);self.assertEqual(len(probes),expected_probes)
                        self.assertEqual(observation['status'],'failed')
                result,observation,_,_,_=self.derived_vanish_scan(relative=relative,scenario='late_dense_cap')
                self.assertIsInstance(result,RuntimeError);self.assertIn('size cap',str(result))
                self.assertEqual(observation['status'],'failed')

    def xcresult_rescan_fixture(self, *, repeated=False, end_first=False,
                                end_second=False, entry_cap=100000, dense_cap=None):
        root=Path(tempfile.mkdtemp(dir=self.temp)).resolve()
        data=root/'Tests.xcresult'/'Data';data.mkdir(parents=True)
        stable=root/'00-stable';stable.write_bytes(b'old')
        first=data/'_tmp.IJNVOw';first.write_bytes(b'first incomplete writer entry')
        second=data/'_tmp.second'
        if repeated:second.write_bytes(b'second incomplete writer entry')
        identity=hosted.core.identity_of(root);clock=[0.];observation={}
        root_passes=[0];seen=[];triggered=set();opened=[];closed=[]
        real_scan,real_open,real_close=os.scandir,os.open,os.close
        def entry_stat(entry,*,follow_symlinks):
            seen.append((root_passes[0],entry.name))
            if entry.name.startswith('_tmp.') and entry.name not in triggered:
                triggered.add(entry.name);(data/entry.name).unlink()
                stable.write_bytes(b'fresh complete sample'*4096)
            return entry.stat(follow_symlinks=follow_symlinks)
        @contextlib.contextmanager
        def entries(fd):
            metadata=os.fstat(fd)
            if [metadata.st_dev,metadata.st_ino]==identity:
                root_passes[0]+=1
                if root_passes[0]==2 and end_second:clock[0]=10.
            with real_scan(fd) as iterator:
                rows=sorted(iterator,key=lambda e:e.name)
                yield (SimpleNamespace(name=e.name,
                    stat=lambda *,follow_symlinks,e=e:entry_stat(e,follow_symlinks=follow_symlinks),
                    is_file=lambda *,follow_symlinks,e=e:e.is_file(follow_symlinks=follow_symlinks)) for e in rows)
        def open_fd(path,*args,**kwargs):
            fd=real_open(path,*args,**kwargs);opened.append(fd);return fd
        def close_fd(fd):
            info=os.fstat(fd);closed.append(fd);real_close(fd)
            if end_first and [info.st_dev,info.st_ino]==identity and root_passes[0]==1:clock[0]=10.
        caps={'scan_entries':entry_cap}
        if dense_cap is not None:caps['output_bytes']=dense_cap
        with patch.dict(hosted.core.CAPS,caps),patch.object(hosted.core.os,'scandir',side_effect=entries), \
             patch.object(hosted.core.os,'open',side_effect=open_fd),patch.object(hosted.core.os,'close',side_effect=close_fd):
            try:result=hosted.core.live_sizes(root,identity,lambda:clock[0],10,
                    observation=observation,allow_xcresult_restart=True)
            except BaseException as error:result=error
        self.assertCountEqual(opened,closed)
        return result,observation,root,root_passes[0],seen,clock[0]

    def test_xcresult_temp_disappearance_restarts_complete_accounting_once(self):
        result,observation,root,passes,seen,_=self.xcresult_rescan_fixture()
        self.assertIsInstance(result,dict);self.assertEqual(passes,2)
        paths=[root]+list(root.rglob('*'))
        self.assertEqual(result['allocated'],sum(x.lstat().st_blocks*512 for x in paths))
        self.assertEqual(result['logical'],sum(x.stat().st_size for x in paths if x.is_file()))
        self.assertEqual(result['entries'],len(paths)-1)
        self.assertEqual([n for _,n in seen].count('00-stable'),2)
        self.assertEqual(observation['encounter_count'],7)
        self.assertEqual(observation['traversal_attempts'],2)
        self.assertEqual((result['complete_scan_attempts'],result['scan_encounters']), (2,7))
        self.assertTrue(observation['discarded_scan']['partial_counts_are_not_valid_accounting'])
        self.assertEqual(observation['discarded_scan']['path'],'Tests.xcresult/Data/_tmp.IJNVOw')
        self.assertNotEqual(observation['discarded_scan']['partial_totals']['logical'],result['logical'])
        self.assertEqual(observation['status'],'completed')

    def test_xcresult_second_disappearance_fails_without_third_traversal(self):
        result,observation,_,passes,_,_=self.xcresult_rescan_fixture(repeated=True)
        self.assertIsInstance(result,FileNotFoundError);self.assertEqual(passes,2)
        self.assertEqual(observation['status'],'failed')
        self.assertEqual(observation['traversal_attempts'],2)

    def test_xcresult_rescan_never_renews_deadline_or_encounter_budget(self):
        for options,passes in [({'end_first':True},1),({'end_second':True},2)]:
            with self.subTest(options=options):
                result,observation,_,actual,_,elapsed=self.xcresult_rescan_fixture(**options)
                self.assertIsInstance(result,RuntimeError);self.assertIn('deadline',str(result))
                self.assertEqual(actual,passes);self.assertEqual(elapsed,10.)
                self.assertEqual(observation['status'],'failed')
        result,observation,_,passes,_,_=self.xcresult_rescan_fixture(entry_cap=6)
        self.assertIsInstance(result,RuntimeError);self.assertIn('entry cap',str(result))
        self.assertEqual(passes,2);self.assertEqual(observation['encounter_count'],7)
        result,observation,_,passes,_,_=self.xcresult_rescan_fixture(dense_cap=32768)
        self.assertIsInstance(result,RuntimeError);self.assertIn('size cap',str(result))
        self.assertEqual(passes,2);self.assertEqual(observation['status'],'failed')

    def test_xcresult_rescan_requires_opt_in_and_exact_result_data_temp_scope(self):
        for relative in ['Tests.xcresult/Data/_tmp.IJNVOw','Tests.xcresult/Data/record',
                'Tests.xcresult/Other/_tmp.IJNVOw','Tests.xcresult/Data/nested/_tmp.IJNVOw',
                'Source/_tmp.IJNVOw','DerivedData/nested.xcresult/Data/_tmp.IJNVOw']:
            for enabled in ([False] if relative=='Tests.xcresult/Data/_tmp.IJNVOw' else [False,True]):
                with self.subTest(relative=relative,enabled=enabled):
                    result,observation,_,probes,_=self.derived_vanish_scan(relative=relative,
                        allow_xcresult_restart=enabled)
                    self.assertIsInstance(result,FileNotFoundError);self.assertEqual(probes,[])
                    self.assertEqual(observation['traversal_attempts'],1)
                    self.assertNotIn('discarded_scan',observation)

    def test_xcresult_rescan_retains_identity_kind_absence_and_error_guards(self):
        for scenario in ['directory','symlink','unknown_kind','directory_open','reappeared',
                'root_replaced','parent_replaced','fd_replaced','final_root_replaced',
                'entry_permission','entry_other_errno','confirmation_permission','confirmation_other_errno',
                'late_entry','late_confirmation']:
            with self.subTest(scenario=scenario):
                result,observation,_,_,_=self.derived_vanish_scan(
                    relative='Tests.xcresult/Data/_tmp.IJNVOw',scenario=scenario,allow_xcresult_restart=True)
                self.assertIsInstance(result,(OSError,RuntimeError))
                self.assertEqual(observation['status'],'failed')
                self.assertEqual(observation['traversal_attempts'],1)
                self.assertNotIn('discarded_scan',observation)

    def test_xcresult_rescan_monitor_requires_active_owned_test_context(self):
        for name,active,finished,expected in [
                ('selected-tests',True,False,True),('phase-export',True,False,True),
                ('phase-restore',True,False,True),('selected-tests',False,False,False),
                ('selected-tests',True,True,False),('capability-normal',True,False,False)]:
            for delegated in [False,True]:
                with self.subTest(name=name,active=active,finished=finished,delegated=delegated):
                    r=object.__new__(hosted.core.Recovery);r.ops=SimpleNamespace(now=lambda:0.)
                    r.t0=0.;r.limit=100.;r.out=self.root;r.output_id=hosted.core.identity_of(self.root)
                    r.timecheck=lambda:None;r.report={'commands':[],'resources':[]};r.active={}
                    owner=SimpleNamespace(t0=0.,limit=50.,report={'commands':[]},active={}) if delegated else r
                    command={'id':name,'pgid':123,'work_deadline':2.}
                    if finished:command['finish']=1.
                    owner.report['commands']=[command]
                    if active:owner.active[123]=SimpleNamespace(pid=123)
                    def sample(root,pin,now,deadline,checkpoint,*,observation,allow_xcresult_restart):
                        self.assertEqual(allow_xcresult_restart,expected)
                        self.assertEqual(deadline,5. if finished else 2.)
                        return {'allocated':0,'logical':0,'entries':0,'xcresults':{}}
                    with patch.object(hosted.core,'live_sizes',side_effect=sample), \
                         patch.object(hosted.core.shutil,'disk_usage',return_value=SimpleNamespace(free=100*hosted.core.GIB)):
                        r.monitor(command_owner=owner if delegated else None)
                    self.assertEqual(len(r.report['resources']),1)

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
            'longest_operation','error','duration_seconds','partial_totals','xcresult_count',
            'traversal_attempts','encounter_count'})
        self.assertEqual(observation['traversal_attempts'],1)
        self.assertEqual(observation['encounter_count'],49)
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
