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

    def test_job_requires_matching_host_profile_and_first_attempt(self):
        env=self.env();hosted.job_context(env,PROFILE,'arm64')
        for key,value in [('GITHUB_ACTIONS','false'),('GITHUB_REPOSITORY','other/repo'),('GITHUB_JOB','validate'),
                          ('TRIPDOCKET_RUNNER_LABEL','macos-15-intel'),('TRIPDOCKET_RUNNER_ENVIRONMENT','self-hosted'),
                          ('TRIPDOCKET_RUNNER_ARCH','X64'),('GITHUB_RUN_ATTEMPT','2'),('ImageVersion',''),
                          ('ImageOS','macos14'),('GITHUB_EVENT_NAME','pull_request_target'),('GITHUB_SHA','bad'),
                          ('SIMCTL_CHILD_TEST','1'),('DYLD_INSERT_LIBRARIES','/tmp/example')]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):hosted.job_context({**env,key:value},PROFILE,'arm64')
        with self.assertRaises(RuntimeError):hosted.job_context(env,PROFILE,'x86_64')

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
        self.assertNotIn('build/RecoveryHosted/*.log',workflow)
        self.assertIn('build/RecoveryHosted/PhaseLogs/',workflow)

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

    def test_first_runtime_query_gets_60_seconds_and_retains_toolchain_facts(self):
        r=self.discovery_runner(delay=25)
        self.discover(r)
        rows=r.report['commands']
        self.assertEqual([x['requested_cap_seconds'] for x in rows],[20,20,20,20,60])
        self.assertEqual(rows[-1]['argv'],['/usr/bin/xcrun','simctl','list','runtimes','--json'])
        self.assertEqual(len(r.ops.processes),5)
        self.assertEqual((r.t0,r.limit,r.final),(0,1380,1500))
        self.assertEqual(PROFILE['prep_seconds'],60)
        self.assertEqual(r.report['profile_discovery']['sdk_version'],'18.5')
        self.assertEqual(r.report['profile_discovery']['runtime_inventory_status'],'returned')
        self.assertTrue((r.out/'resolved-profile.json').is_file())
        self.assertAlmostEqual(rows[-1]['work_deadline']-rows[-1]['start'],52,places=6)
        # The separate pre-create inventory and every other sim call keep 30s.
        with patch.object(r,'command',return_value='{}') as call:
            r.sim('runtime-inventory','list','runtimes','--json')
        self.assertEqual(call.call_args.args[-1],30)

    def test_runtime_query_still_times_out_once_and_preserves_pending_facts(self):
        r=self.discovery_runner(delay=float('inf'))
        with self.assertRaises(RuntimeError):self.discover(r)
        row=r.report['commands'][-1]
        self.assertEqual(row['error'],"RuntimeError('Command timeout')")
        self.assertAlmostEqual(row['finish']-row['start'],52,places=6)
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
        with self.assertRaises(RuntimeError):r.sim('profile-runtimes','list','runtimes','--json',cap=60)
        row=r.report['commands'][-1]
        self.assertEqual((row['work_deadline'],row['command_deadline']),(1372,1380))
        self.assertLessEqual(row['finish'],1380)
        self.assertEqual((r.limit,r.final),(1380,1500))
        r.ops.t=1372
        with self.assertRaisesRegex(RuntimeError,'Insufficient command/stop budget'):
            r.sim('profile-runtimes','list','runtimes','--json',cap=60)
        self.assertEqual(len(r.ops.processes),1)

    def test_runtime_output_cap_invalid_json_and_wrong_sdk_have_no_fallback(self):
        for kind in ['output','json','sdk']:
            with self.subTest(kind=kind):
                old=self.root;self.root=old/kind;self.root.mkdir()
                data=b'not json' if kind=='json' else json.dumps({'runtimes':[self.runtime('26.0')]}).encode()
                r=self.discovery_runner(output=[('stdout',data)])
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

    def test_EPERM_after_TERM_identifies_group_probe_and_never_retries_stop(self):
        r=self.runner(Ops({'delay':float('inf'),'probe_errors':{2:PermissionError(errno.EPERM,'after TERM')}}))
        with self.assertRaises(RuntimeError):r.command('after-term',['synthetic'],30)
        row=r.report['commands'][0];obs=row['process_observations'];p=r.ops.processes[0]
        self.assertEqual(obs['stop.signal_15']['result'],'syscall_returned')
        self.assertEqual(obs['stop.group_probe']['errno'],errno.EPERM)
        self.assertEqual(obs['stop.group_probe']['calls'],2)
        self.assertEqual(row['stop']['signals'],[15])
        self.assertEqual(row['stop']['signals_semantics'],'send_wrapper_returned_not_delivery')
        self.assertNotIn('stop.signal_9',obs)
        self.assertFalse(row['stop']['group_absent'])
        self.assertIn(p.pid,r.active)
        with self.assertRaisesRegex(RuntimeError,'No repeated signalling'):r.stop(p,60,row)
        with self.assertRaisesRegex(RuntimeError,'Unowned group'):r.stop(SimpleNamespace(pid=p.pid),60,{})
        with patch.object(r,'sim',side_effect=AssertionError('NO CLEANUP CHILD')) as sim:
            r.cleanup();sim.assert_not_called()
        self.assertFalse(r.report['cleanup_verified'])
        self.assertEqual(len(r.ops.signals),1)

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


if __name__=='__main__':unittest.main(verbosity=2)
