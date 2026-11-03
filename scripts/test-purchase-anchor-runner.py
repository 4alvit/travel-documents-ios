#!/usr/bin/env python3
"""Offline guards for the explicit purchase-anchor diagnostic; no native execution."""
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
if '--source-root' in sys.argv:
    index=sys.argv.index('--source-root'); ROOT=Path(sys.argv[index+1]).resolve(); del sys.argv[index:index+2]
spec=importlib.util.spec_from_file_location('anchor_runner',HERE/'diagnose-purchase-anchor.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
q,core=m.load_helpers(ROOT)
Pair=m.make_runner(q,core)
Context=inspect.getclosurevars(Pair.run_arm).nonlocals['Context']


class Guards(unittest.TestCase):
    def env(self):
        return dict(GITHUB_ACTIONS='true',RUNNER_OS='macOS',RUNNER_ARCH='ARM64',PURCHASE_ANCHOR_RUNNER='macos-15',
                    GITHUB_REPOSITORY='4alvit/travel-documents-ios',GITHUB_EVENT_NAME='workflow_dispatch',
                    GITHUB_WORKFLOW='Purchase anchor diagnostic',GITHUB_JOB='anchor',
                    GITHUB_REF='refs/heads/diagnostic/purchase-anchor',GITHUB_SHA='a'*40,
                    GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',DEVELOPER_DIR=q.DEVELOPER_DIR)

    def test_context_is_explicit_manual_arm_branch(self):
        self.assertEqual(m.context(self.env(),'arm64')['GITHUB_RUN_ID'],'123')
        for key,bad in [('RUNNER_ARCH','X64'),('GITHUB_EVENT_NAME','push'),('GITHUB_REF','refs/heads/main'),
                        ('GITHUB_WORKFLOW','Release qualification'),('GITHUB_JOB','qualify'),
                        ('GITHUB_SHA','x'*40),('GITHUB_RUN_ATTEMPT','0')]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                m.context({**self.env(),key:bad},'arm64')

    def test_profile_context_exact_mapping_and_original_caps(self):
        for runner,arch,machine,name in (('macos-15-intel','X64','x86_64','intel-batch'),
                                         ('macos-15','ARM64','arm64','default')):
            env={**self.env(),'PURCHASE_ANCHOR_RUNNER':runner,'RUNNER_ARCH':arch}
            job=m.context(env,machine)
            self.assertEqual(job['runner_profile'],{'runner':runner,'runner_architecture':arch,
                                                   'architecture':machine,'name':name})
            for bad_env,bad_machine in (({**env,'PURCHASE_ANCHOR_RUNNER':'other'},machine),
                                        ({k:v for k,v in env.items() if k!='PURCHASE_ANCHOR_RUNNER'},machine),
                                        ({**env,'RUNNER_ARCH':'wrong'},machine),
                                        (env,'x86_64' if machine=='arm64' else 'arm64')):
                with self.subTest(runner=runner,bad_env=bad_env,bad_machine=bad_machine),self.assertRaises(RuntimeError):
                    m.context(bad_env,bad_machine)
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(m.time,'monotonic',return_value=1000.0), \
                    mock.patch.object(core.base.RealOps,'now',return_value=1000.0):
                root=Path(tmp).resolve();(root/'build').mkdir();p=Pair(root,job)
                self.assertEqual(p.work_end,2800.0);self.assertEqual(p.final,2980.0)
                self.assertEqual(p.report['runner_profile'],job['runner_profile'])
                self.assertEqual(p.commands.host['machine'],machine)
                with mock.patch.object(Context,'command',return_value='') as command:
                    p.commands.sim('boot-ready','bootstatus','ABC','-b')
                self.assertEqual(command.call_args.args[-1],188)
        workflow=(HERE.parent/'.github/workflows/release-qualification.yml').read_text()
        self.assertIn('runs-on: ${{ inputs.runner }}',workflow)
        self.assertIn('PURCHASE_ANCHOR_RUNNER: ${{ inputs.runner }}',workflow)
        self.assertIn('default: macos-15',workflow)
        self.assertIn('- macos-15-intel',workflow)

    def test_intel_profile_reaches_actual_prepare_and_contexts(self):
        for fault in (None,'machine','runtime-architecture','runtime-build'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p=self.fake_pair(Path(tmp))
                p.profile=m.context({**self.env(),'PURCHASE_ANCHOR_RUNNER':'macos-15-intel',
                                     'RUNNER_ARCH':'X64'},'x86_64')['runner_profile']
                p.before={'files':{}};p.admit_build=mock.Mock();p.commands.once=mock.Mock()
                rows=[{'target':name,'buildSettings':{'COMPILER_INDEX_STORE_ENABLE':'NO'}}
                      for name in ('Tripfolio','TripfolioTests','TripfolioUITests')]
                replies={'xcode':q.XCODE_VERSION,'developer':q.DEVELOPER_DIR,'sdk':'26.2',
                         'architecture':'arm64' if fault=='machine' else 'x86_64',
                         'build-settings':json.dumps(rows)}
                commands=[]
                def command(label,args,cap=38):
                    commands.append((label,args,cap));return replies.get(label,'')
                p.commands.command=command
                p.commands.sim=lambda *args,**kwargs:json.dumps({'runtimes':[{'identifier':m.RUNTIME,
                    'version':'26.2','buildversion':'wrong' if fault=='runtime-build' else '23C54',
                    'isAvailable':True,'supportedArchitectures':['arm64' if fault=='runtime-architecture' else 'x86_64'],
                    'supportedDeviceTypes':[{'identifier':m.DEVICE}]}]})
                with mock.patch.object(q,'focused_build_selection',return_value={'build_settings':['EXCLUDED_SOURCE_FILE_NAMES=Other.swift']}) as selected, \
                        mock.patch.object(q,'shared_product_paths',return_value={}):
                    if fault:
                        with self.assertRaises(RuntimeError):p.prepare()
                        self.assertFalse(any(c[0]=='build-for-testing' for c in commands));continue
                    p.prepare()
                self.assertEqual(selected.call_args.args[1],p.profile)
                self.assertEqual(p.selection['architecture'],'x86_64')
                self.assertEqual(p.report['toolchain']['architecture'],'x86_64')
                hosts=[]
                def setup(arm):hosts.append(arm.host['machine']);self.setup_arm(arm)
                def native(arm,label,args,cap=38):commands.append((arm.out.name,args,cap));return ''
                with mock.patch.object(Context,'setup',setup),mock.patch.object(Context,'command',native), \
                        mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                    p.run_arm('child',0);p.run_arm('ownedAncestor',1)
                self.assertEqual(hosts,['x86_64','x86_64'])
                selected=[c for c in commands if c[0] in ('build-for-testing','build-settings','child','ownedAncestor')]
                self.assertEqual([c[0] for c in selected],['build-for-testing','build-settings','child','ownedAncestor'])
                self.assertEqual([c[2] for c in selected],[420,48,780,780])
                for _,args,_ in selected:self.assertEqual(args.count('COMPILER_INDEX_STORE_ENABLE=NO'),1)

    def test_actual_result_architecture_matches_selected_profile(self):
        for architecture in ('arm64','x86_64'):
            selection={'identifier':m.RUNTIME,'version':'26.2','build':'23C54','architecture':architecture,
                       'sdk_version':'26.2','sdk_matched':True}
            summary={'result':'Passed','totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,
                     'expectedFailures':0,'testFailures':[], 'devicesAndConfigurations':[{'device':{'deviceId':'ABC',
                     'osVersion':'26.2','osBuildNumber':'23C54','architecture':architecture}}]}
            tree={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':m.CASE,'result':'Passed'}],
                  'devices':[{'deviceId':'ABC','platform':'iOS Simulator'}]}
            m.validate_result(q,summary,tree,'ABC',selection)
            summary['devicesAndConfigurations'][0]['device']['architecture']='x86_64' if architecture=='arm64' else 'arm64'
            with self.assertRaises(RuntimeError):m.validate_result(q,summary,tree,'ABC',selection)

    def test_only_single_exact_case_and_fixed_bounds(self):
        for operation in ('build-for-testing','test-without-building'):
            args=m.argv_for(Path('/repo'),Path('/derived'),['EXCLUDED_SOURCE_FILE_NAMES=Other.swift'],operation,
                            None if operation=='build-for-testing' else 'A'*8+'-AAAA-AAAA-AAAA-'+'A'*12,
                            None if operation=='build-for-testing' else Path('/result.xcresult'))
            self.assertEqual([x for x in args if x.startswith('-only-testing:')],['-only-testing:'+m.SELECTOR])
            self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'180')
            self.assertEqual(args[args.index('-default-test-execution-time-allowance')+1],'180')
            self.assertEqual(args[-1],operation)
            self.assertNotIn('test',args)
            self.assertFalse(any('retry' in x.lower() for x in args))
        self.assertEqual((m.WORK_SECONDS,m.CLEANUP_SECONDS,m.BUILD_CAP,m.TEST_CAP),(1800,180,420,780))

    def fake_pair(self,root):
        root=root.resolve();p=object.__new__(Pair);p.root=root;p.out=root;p.started=time.monotonic()
        p.work_end=p.started+1800;p.final=p.work_end+180;p.current=None
        p.job=m.context(self.env(),'arm64');p.profile=p.job['runner_profile'];p.before={};p.products={};p.product_paths={};p.derived=root/'derived';p.settings=[]
        p.baseline=None;p.used_devices=set();p.report={'arms':{},'errors':[]};p.selection={}
        p.commands=SimpleNamespace(active={},unknown_spawn=False,interrupted=False,checkpoint=lambda:None,save=lambda:None,
            create_attempted=False,owned=None,report={'commands':[]})
        p.source=mock.Mock(return_value={});p.product_snapshot=mock.Mock(return_value={})
        p.capture=lambda arm,mode:arm.report.update(native_result={'selected_case_passed':True,
            'evidence_capture_complete':True,'inspection_copy_closed':True})
        p.installed=lambda arm:arm.report.update(installed_product_content_verified=True)
        return p

    def setup_arm(self,arm):
        arm.owned=str(__import__('uuid').uuid4()).upper();arm.create_attempted=arm.recovered=True
        arm.report['baseline']={'devices':{}};arm.report['cleanup_verified']=False

    def clean_arm(self,arm):
        arm.report['cleanup_verified']=True

    def test_failed_first_test_still_runs_second_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));events=[]
            def command(arm,label,args,cap=38):
                events.append((arm.out.name,label,cap))
                if arm.out.name=='child': raise RuntimeError('retained native failure')
                return ''
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',command),mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                self.assertEqual(p.run_arm('child',0),'failed')
                self.assertEqual(p.run_arm('ownedAncestor',1),'passed_pending_independent_review')
            self.assertEqual(events,[('child','selected-tests',780),('ownedAncestor','selected-tests',780)])
            self.assertEqual(len(p.used_devices),2)
            self.assertTrue(p.report['arms']['child']['errors'])

    def test_unconfirmed_cleanup_aborts_before_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));p.prepare=lambda:None
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',return_value=''),mock.patch.object(Context,'cleanup',lambda arm:None):
                self.assertEqual(p.run(),1)
            self.assertEqual(list(p.report['arms']),['child'])
            self.assertTrue(p.report['errors'])

    def test_unknown_spawn_cannot_run_global_source_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp))
            arm=Context(p,p.root/'child',p.final,'intent');p.current=arm
            arm.unknown_spawn=True
            coordinator=Context(p,p.root/'coordinator',p.final,'unused');p.commands=coordinator
            with self.assertRaisesRegex(RuntimeError,'Other diagnostic process ownership'):
                coordinator.checkpoint()

    def test_unknown_test_process_aborts_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));p.prepare=lambda:None
            def command(arm,*args): arm.unknown_spawn=True;raise RuntimeError('unknown spawn')
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',command),mock.patch.object(Context,'cleanup',lambda arm:None):
                self.assertEqual(p.run(),1)
            self.assertEqual(list(p.report['arms']),['child'])
            self.assertEqual(p.source.call_count,1)

    def test_normal_cleanup_uses_work_deadline_final_arm_uses_fixed_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));clocks=[]
            def clean(arm):
                clocks.append((arm.t0,arm.final,arm.limit));self.clean_arm(arm)
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',return_value=''),mock.patch.object(Context,'cleanup',clean):
                p.run_arm('child',0);p.run_arm('ownedAncestor',1)
            self.assertEqual(clocks,[(p.started,p.work_end,p.work_end),(p.started,p.final,p.work_end)])

    def test_insufficient_interarm_cleanup_budget_uses_final_reserve_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));p.work_end=time.monotonic()+30;clocks=[]
            def clean(arm): clocks.append(arm.final);self.clean_arm(arm)
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',return_value=''),mock.patch.object(Context,'cleanup',clean):
                with self.assertRaisesRegex(RuntimeError,'No work budget'):p.run_arm('child',0)
            self.assertEqual(clocks,[p.final])

    def test_interrupt_uses_final_cleanup_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));clocks=[]
            def command(arm,*args):p.signal();raise RuntimeError('interrupted')
            def clean(arm):clocks.append(arm.final);self.clean_arm(arm)
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',command),mock.patch.object(Context,'cleanup',clean):
                with self.assertRaisesRegex(RuntimeError,'did not close'):p.run_arm('child',0)
            self.assertEqual(clocks,[p.final]);self.assertTrue(p.commands.interrupted)

    def test_source_or_product_change_aborts_even_after_cleanup(self):
        for fault in ('source','product_snapshot'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p=self.fake_pair(Path(tmp));getattr(p,fault).side_effect=[{},RuntimeError('changed')]
                with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',return_value=''),mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                    with self.assertRaisesRegex(RuntimeError,'did not close'):p.run_arm('child',0)

    def test_runtime_validation_rejects_extra_cases_and_wrong_device(self):
        sample=json.loads((ROOT/'scripts'/'../Tripfolio.xctestplan').read_text())
        self.assertEqual(len(sample['configurations']),1)
        self.assertEqual(sample['configurations'][0]['options'],{})
        summary={'result':'Passed','totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0,
                 'devicesAndConfigurations':[{'device':{'deviceId':'ABC'}}]}
        tree={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':m.CASE,'result':'Passed'}],
              'devices':[{'deviceId':'ABC','platform':'iOS Simulator'}]}
        core.validate_result(summary,tree,m.CASE,'ABC')
        with self.assertRaises(RuntimeError):core.validate_result({**summary,'skippedTests':1},tree,m.CASE,'ABC')
        with self.assertRaises(RuntimeError):core.validate_result(summary,tree,m.CASE,'OTHER')
        with self.assertRaises(RuntimeError):core.validate_result(summary,{**tree,'testNodes':tree['testNodes']*2},m.CASE,'ABC')

    def test_real_initializer_and_cleanup_keep_original_clock(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(m.time, "monotonic", return_value=1000.0), \
                mock.patch.object(core.base.RealOps, "now", return_value=1000.0):
            root=Path(tmp).resolve();(root/'build').mkdir()
            p=Pair(root,m.context(self.env(),'arm64'))
            self.assertEqual(p.commands.t0,p.started)
            self.assertEqual(p.commands.limit,p.work_end)
            self.assertEqual(p.final-p.started,1980)
            self.assertEqual(p.derived,p.out/'DerivedData')
            arm=Context(p,root/'arm',p.work_end,'unused')
            arm.ops=SimpleNamespace(now=lambda:p.work_end-20)
            arm.cleanup()
            self.assertEqual(arm.write_deadline,p.work_end)
            self.assertEqual(arm.limit,p.work_end-core.CAPS['receipt_seconds'])
            self.assertTrue(arm.report['cleanup_verified'])

    def test_actual_result_validator_binds_runtime_and_rejects_warning(self):
        selection={'identifier':m.RUNTIME,'version':'26.2','build':'23C54','architecture':'arm64',
                   'sdk_version':'26.2','sdk_matched':True}
        summary={'result':'Passed','totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0,
                 'testFailures':[], 'devicesAndConfigurations':[{'device':{'deviceId':'ABC','osVersion':'26.2',
                 'osBuildNumber':'23C54','architecture':'arm64'}}]}
        tree={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':m.CASE,'result':'Passed'}],
              'devices':[{'deviceId':'ABC','platform':'iOS Simulator'}]}
        m.validate_result(q,summary,tree,'ABC',selection)
        with self.assertRaises(RuntimeError):m.validate_result(q,{**summary,'runtimeWarnings':['warning']},tree,'ABC',selection)
        with self.assertRaises(RuntimeError):m.validate_result(q,summary,tree,'ABC',{**selection,'build':'OTHER'})
        with self.assertRaises(RuntimeError):m.validate_result(q,summary,{**tree,'testNodes':[{'nodeType':'Runtime Warning'}]},'ABC',selection)

    def capture_fixture(self, p, fail=False):
        arm=Context(p,p.root/'child',p.final,'unused');p.current=arm;arm.owned='ABC'
        p.selection={'identifier':m.RUNTIME,'version':'26.2','build':'23C54','architecture':'arm64',
                     'sdk_version':'26.2','sdk_matched':True}
        raw=p.out/'child.xcresult';raw.mkdir();(raw/'Data').mkdir();(raw/'Info.plist').write_bytes(b'fixture')
        summary={'result':'Passed','totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0,
                 'testFailures':[],'devicesAndConfigurations':[{'device':{'deviceId':'ABC','osVersion':'26.2',
                 'osBuildNumber':'23C54','architecture':'arm64'}}]}
        tree={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':m.CASE,'result':'Passed'}],
              'devices':[{'deviceId':'ABC','platform':'iOS Simulator'}]}
        events=[]
        def command(label,args,cap=38):
            events.append((label,cap))
            if label=='export-diagnostics' and fail:raise RuntimeError('export failed')
            if label.startswith('export-'):
                dest=Path(args[args.index('--output-path')+1]);dest.mkdir();(dest/'evidence.txt').write_text('raw evidence')
                return ''
            (p.out/'child-inspection.xcresult'/'database.sqlite3').write_bytes(b'sqlite fixture')
            return json.dumps(summary if label=='result-summary' else tree)
        arm.command=command
        return arm,raw,events

    def test_actual_capture_preserves_original_and_removes_owned_copy(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(Context,'checkpoint',lambda self,**kwargs:None):
            p=self.fake_pair(Path(tmp));arm,raw,events=self.capture_fixture(p)
            before=core.tree_manifest(raw);p.capture=Pair.capture.__get__(p,Pair);p.capture(arm,'child')
            self.assertEqual(core.tree_manifest(raw),before)
            self.assertFalse((p.out/'child-inspection.xcresult').exists())
            self.assertTrue(arm.report['native_result']['selected_case_passed'])
            self.assertEqual([x[0] for x in events],['export-attachments','export-diagnostics','result-summary','result-tests'])
            self.assertTrue(all(x[1]==68 for x in events))
            self.assertIn('unclassified',arm.report['native_result']['storekit_entry'])
            self.assertTrue(arm.report['native_result']['inspection_copy_closed'])

    def test_actual_capture_rejects_other_sidecar_or_changed_original_entry(self):
        for name in ('unexpected.db','Info.plist','sidecar-mode','sidecar-size'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp,mock.patch.object(Context,'checkpoint',lambda self,**kwargs:None):
                p=self.fake_pair(Path(tmp));arm,raw,events=self.capture_fixture(p)
                before=core.tree_manifest(raw);original_command=arm.command
                def command(label,args,cap=38):
                    result=original_command(label,args,cap)
                    if label=='result-tests':
                        copy=p.out/'child-inspection.xcresult'
                        if name=='sidecar-mode':(copy/'database.sqlite3').chmod(0o666)
                        elif name=='sidecar-size':
                            with (copy/'database.sqlite3').open('r+b') as file:file.truncate(16*1024*1024+1)
                        else:(copy/name).write_text('changed')
                    return result
                arm.command=command;p.capture=Pair.capture.__get__(p,Pair)
                with self.assertRaises(RuntimeError):p.capture(arm,'child')
                self.assertEqual(core.tree_manifest(raw),before)
                self.assertFalse(arm.report['native_result']['inspection_copy_closed'])
                self.assertFalse(arm.report['native_result']['evidence_capture_complete'])

    def test_actual_capture_export_failure_retains_failure_and_original(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(Context,'checkpoint',lambda self,**kwargs:None):
            p=self.fake_pair(Path(tmp));arm,raw,events=self.capture_fixture(p,fail=True)
            before=core.tree_manifest(raw);p.capture=Pair.capture.__get__(p,Pair)
            with self.assertRaisesRegex(RuntimeError,'export failed'):p.capture(arm,'child')
            self.assertEqual(core.tree_manifest(raw),before)
            self.assertFalse((p.out/'child-inspection.xcresult').exists())
            self.assertNotIn('selected_case_passed',arm.report['native_result'])

    def test_actual_nonzero_command_retains65_and_reaps_group(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(Context,'checkpoint',lambda self,**kwargs:None):
            p=self.fake_pair(Path(tmp));arm=Context(p,p.root/'child',p.final,'unused')
            child=SimpleNamespace(pid=77,returncode=65,poll=lambda:65)
            closed=[]
            arm.ops=SimpleNamespace(now=time.monotonic,spawn=lambda args:child,prepare=lambda proc:None,
                read=lambda proc:[],absent=lambda proc:True,close=lambda proc:closed.append(proc.pid),
                sleep=lambda seconds:None)
            with self.assertRaisesRegex(RuntimeError,'selected-tests failed'):
                arm.command('selected-tests',['fake-native'],38)
            row=arm.report['commands'][0]
            self.assertEqual(row['returncode'],65)
            self.assertIn('Nonzero command exit: 65',row['error'])
            self.assertNotIn('AttributeError',row['error'])
            self.assertTrue(row['stop']['group_absent']);self.assertTrue(row['stop']['leader_reaped'])
            self.assertFalse(arm.active);self.assertEqual(closed,[77])

    def test_coordinator_closure_is_explicit_and_unknown_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));p.prepare=lambda:(_ for _ in ()).throw(RuntimeError('build failed'))
            self.assertEqual(p.run(),1)
            self.assertTrue(p.commands.report['cleanup_verified'])
            self.assertTrue(p.report['cleanup_verified'])
            p.commands.unknown_spawn=True
            self.assertEqual(p.run(),1)
            self.assertFalse(p.commands.report['cleanup_verified'])
            self.assertFalse(p.report['cleanup_verified'])

    def test_build_admission_checks_space_and_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));p.commands.checkpoint=mock.Mock()
            with mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['admission_free_bytes'])):
                p.admit_build()
            self.assertEqual(p.commands.checkpoint.call_count,2)
            self.assertEqual(p.report['build_admission']['free_bytes'],core.CAPS['admission_free_bytes'])
            with mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['admission_free_bytes']-1)):
                with self.assertRaisesRegex(RuntimeError,'Insufficient space'):p.admit_build()
            p.commands.checkpoint.side_effect=[None,RuntimeError('deadline')]
            with mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['admission_free_bytes'])):
                with self.assertRaisesRegex(RuntimeError,'deadline'):p.admit_build()

    def test_full_pair_output_scan_has_owned_writer_and_command_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));arm=Context(p,p.root/'child',p.final,'unused')
            pid=123;arm.active[pid]=SimpleNamespace(pid=pid)
            arm.report['commands'].append({'id':'selected-tests','pgid':pid,'work_deadline':90,
                'argv':['xcodebuild','test-without-building']})
            with mock.patch.object(core,'live_sizes',return_value={'allocated':0}) as scan:
                arm.monitor()
                args,kw=scan.call_args
                self.assertEqual(args[0],p.out)
                self.assertLessEqual(args[3],p.started+90)
                self.assertTrue(kw['allow_xcresult_restart'])
                self.assertTrue(kw['allow_products_restart'])
                arm.active.clear();arm.monitor()
                self.assertFalse(scan.call_args.kwargs['allow_xcresult_restart'])

    def test_owned_boot_scan_preserves_fifteen_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));arm=Context(p,p.root/'child',p.final,'unused')
            arm.owned='ABC';arm.active[123]=SimpleNamespace(pid=123)
            arm.report['commands'].append({'id':'boot-ready','pgid':123,'work_deadline':100,
                'argv':['/usr/bin/xcrun','simctl','bootstatus','ABC','-b']})
            with mock.patch.object(core,'live_sizes',return_value={'allocated':0}):arm.monitor()
            self.assertEqual(arm.report['resources'][-1]['requested_scan_seconds'],15)
            arm.owned='DIFFERENT'
            with mock.patch.object(core,'live_sizes',return_value={'allocated':0}):arm.monitor()
            self.assertEqual(arm.report['resources'][-1]['requested_scan_seconds'],5)

    def test_copy_or_installed_proof_missing_stops_second_arm(self):
        for missing in ('installed','copy'):
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as tmp:
                p=self.fake_pair(Path(tmp))
                if missing=='installed':p.installed=lambda arm:None
                else:p.capture=lambda arm,mode:arm.report.update(native_result={'evidence_capture_complete':True,'inspection_copy_closed':False})
                with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)),mock.patch.object(Context,'command',return_value=''),mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                    with self.assertRaisesRegex(RuntimeError,'did not close'):p.run_arm('child',0)

    def test_pending_owned_boot_scan_allows_six_seconds_without_writer_privileges(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));arm=Context(p,p.root/'child',p.final,'unused')
            now=[p.started];arm.ops.now=lambda:now[0];arm.owned='ABC'
            arm.report['commands'].append({'id':'boot-ready','work_deadline':100,
                'argv':['/usr/bin/xcrun','simctl','bootstatus','ABC','-b']})
            def traverse(*args,**kwargs):
                now[0]+=6
                return {'allocated':0}
            with mock.patch.object(core,'live_sizes',side_effect=traverse) as scan, \
                    mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                arm.monitor()
            self.assertEqual(arm.report['resources'][-1]['requested_scan_seconds'],15)
            self.assertEqual(scan.call_args.args[0],p.out)
            self.assertEqual(scan.call_args.args[3],p.started+15)
            self.assertFalse(scan.call_args.kwargs['allow_xcresult_restart'])
            self.assertFalse(scan.call_args.kwargs['allow_products_restart'])
            self.assertEqual(arm.active,{})

    def test_pending_boot_scan_wrong_identity_or_ownership_stays_five_seconds(self):
        for fault in ('id','argv','device','no-device','finished','pgid-none','foreign-active','foreign-pgid','unknown'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p=self.fake_pair(Path(tmp));arm=Context(p,p.root/'child',p.final,'unused')
                arm.ops.now=lambda:p.started;arm.owned='ABC'
                command={'id':'boot-ready','work_deadline':100,
                    'argv':['/usr/bin/xcrun','simctl','bootstatus','ABC','-b']}
                arm.report['commands'].append(command)
                if fault=='id':command['id']='other'
                elif fault=='argv':command['argv'][-1]='-x'
                elif fault=='device':command['argv'][3]='OTHER'
                elif fault=='no-device':arm.owned=None
                elif fault=='finished':command['finish']=0
                elif fault=='pgid-none':command['pgid']=None
                elif fault=='foreign-active':arm.active[123]=SimpleNamespace(pid=123)
                elif fault=='foreign-pgid':
                    command['pgid']=124;arm.active[123]=SimpleNamespace(pid=123)
                elif fault=='unknown':arm.unknown_spawn=True
                with mock.patch.object(core,'live_sizes',return_value={'allocated':0}) as scan, \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    arm.monitor()
                self.assertEqual(arm.report['resources'][-1]['requested_scan_seconds'],5)
                self.assertFalse(scan.call_args.kwargs['allow_xcresult_restart'])
                self.assertFalse(scan.call_args.kwargs['allow_products_restart'])

    def test_pending_boot_scan_keeps_original_global_and_command_deadlines(self):
        for global_remaining,command_remaining,expected in ((4,100,4),(100,3,3),(2,3,2)):
            with self.subTest(global_remaining=global_remaining,command_remaining=command_remaining),tempfile.TemporaryDirectory() as tmp:
                p=self.fake_pair(Path(tmp));arm=Context(p,p.root/'child',p.final,'unused')
                now=[p.started];arm.ops.now=lambda:now[0];arm.owned='ABC';arm.limit=p.started+global_remaining
                arm.report['commands'].append({'id':'boot-ready','work_deadline':command_remaining,
                    'argv':['/usr/bin/xcrun','simctl','bootstatus','ABC','-b']})
                def traverse(*args,**kwargs):
                    now[0]+=6
                    return {'allocated':0}
                with mock.patch.object(core,'live_sizes',side_effect=traverse) as scan, \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaises(RuntimeError):arm.monitor()
                self.assertEqual(scan.call_args.args[3],p.started+expected)
                self.assertEqual(arm.limit,p.started+global_remaining)
                self.assertFalse(scan.call_args.kwargs['allow_xcresult_restart'])
                self.assertFalse(scan.call_args.kwargs['allow_products_restart'])

    def test_log_accounting_is_shared_across_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));a=Context(p,p.root/'child',p.final,'a');b=Context(p,p.root/'ancestor',p.final,'b')
            seen=[]
            def pump(context,*args):seen.append(context.log_total);context.log_total+=10
            with mock.patch.object(core.Recovery,'pump',pump):
                a.pump(None,None,None);b.pump(None,None,None);a.pump(None,None,None)
            self.assertEqual(seen,[0,10,20]);self.assertEqual(p.log_total,30)

    def test_no_files_or_hardcoded_recovery_phases(self):
        self.assertEqual(inspect.getsource(Context.prepare_files_ui_baseline).strip().splitlines()[-1].strip(),'pass')
        body=inspect.getsource(Pair)
        self.assertNotIn('.run_phase(',body);self.assertNotIn('.read_result(',body)
        self.assertIn("for index,mode in enumerate(MODES)",body)
        workflow=(HERE.parent/'.github/workflows/release-qualification.yml').read_text()
        self.assertIn('if: always()',workflow)
        self.assertNotIn('matrix:',workflow)
        self.assertNotIn('pull_request:',workflow)
        self.assertNotIn('continue-on-error:',workflow)

    def test_diagnostic_index_setting_reaches_build_query_and_both_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fake_pair(Path(tmp));p.before={'files':{}};p.admit_build=mock.Mock()
            targets=('Tripfolio','TripfolioTests','TripfolioUITests')
            settings=json.dumps([{'target':name,'buildSettings':{'COMPILER_INDEX_STORE_ENABLE':'NO'}} for name in targets])
            replies={'xcode':q.XCODE_VERSION,'developer':q.DEVELOPER_DIR,'sdk':'26.2',
                     'architecture':'arm64','build-settings':settings}
            calls=[]
            def command(label,args,cap=38):
                calls.append((label,args,cap));return replies.get(label,'')
            p.commands.command=command;p.commands.once=mock.Mock()
            p.commands.sim=lambda *args,**kwargs:json.dumps({'runtimes':[{'identifier':m.RUNTIME,
                'version':'26.2','buildversion':'23C54','isAvailable':True,'supportedArchitectures':['arm64'],
                'supportedDeviceTypes':[{'identifier':m.DEVICE}]}]})
            selection={'build_settings':['EXCLUDED_SOURCE_FILE_NAMES=Other.swift']}
            with mock.patch.object(q,'focused_build_selection',return_value=selection), \
                    mock.patch.object(q,'shared_product_paths',return_value={}) as paths:
                p.prepare()
            def native(arm,label,args,cap=38):
                calls.append((arm.out.name,args,cap));return ''
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)), \
                    mock.patch.object(Context,'command',native), \
                    mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                p.run_arm('child',0);p.run_arm('ownedAncestor',1)
            relevant=[(label,args,cap) for label,args,cap in calls if label in ('build-for-testing','build-settings','child','ownedAncestor')]
            self.assertEqual([label for label,_,_ in relevant],['build-for-testing','build-settings','child','ownedAncestor'])
            for label,args,cap in relevant:
                self.assertEqual(args.count('COMPILER_INDEX_STORE_ENABLE=NO'),1,label)
                self.assertIn('EXCLUDED_SOURCE_FILE_NAMES=Other.swift',args)
            self.assertEqual([cap for _,_,cap in relevant],[420,48,780,780])
            self.assertEqual(paths.call_args.args[2],tuple(p.settings))
            self.assertEqual(selection['build_settings'],['EXCLUDED_SOURCE_FILE_NAMES=Other.swift'])
            self.assertEqual(p.report['diagnostic_build_settings'],p.settings)
            self.assertEqual(p.report['compiler_index_store'],{name:'NO' for name in targets})

    def test_effective_index_setting_requires_every_exact_target(self):
        targets=('Tripfolio','TripfolioTests','TripfolioUITests')
        rows=[{'target':name,'buildSettings':{'COMPILER_INDEX_STORE_ENABLE':'NO'}} for name in targets]
        self.assertEqual(m.validate_index_store_disabled(json.dumps(rows)),{name:'NO' for name in targets})
        for target in targets:
            for value in ('Default','YES','',None,False):
                changed=json.loads(json.dumps(rows))
                next(row for row in changed if row['target']==target)['buildSettings']['COMPILER_INDEX_STORE_ENABLE']=value
                with self.subTest(target=target,value=value),self.assertRaises(RuntimeError):
                    m.validate_index_store_disabled(json.dumps(changed))
        for changed in (rows[:-1],rows+[rows[0]],{},rows*6):
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):
                m.validate_index_store_disabled(json.dumps(changed))


if __name__=='__main__':unittest.main()
