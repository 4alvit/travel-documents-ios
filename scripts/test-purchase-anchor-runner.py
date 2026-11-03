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
        p.install_aut=lambda arm:arm.report.update(pretest_installed_aut_verified=True)
        return p

    def setup_arm(self,arm):
        arm.owned=str(__import__('uuid').uuid4()).upper();arm.create_attempted=arm.recovered=True
        arm.report['baseline']={'devices':{}};arm.report['cleanup_verified']=False

    def clean_arm(self,arm):
        arm.report['cleanup_verified']=True

    def test_aut_install_and_content_proof_precede_each_selected_test(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Context,'checkpoint',lambda self,**kw:None):
            p=self.fake_pair(Path(tmp));p.install_aut=Pair.install_aut.__get__(p,Pair)
            built=p.root/'built'/'Tripfolio.app';built.mkdir(parents=True);(built/'binary').write_bytes(b'same build')
            p.product_paths={'Tripfolio':built};p.products={'Tripfolio':q.compiled_identity(built,lambda:None)}
            events=[]
            def command(arm,label,args,cap=38):
                events.append((arm.owned,label,list(args),cap))
                if label=='pretest-installed-Tripfolio':return str(built)
                if label=='selected-tests':self.assertIs(arm.report.get('pretest_installed_aut_verified'),True)
                return ''
            with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)), \
                    mock.patch.object(Context,'command',command), \
                    mock.patch.object(Context,'owned_path',return_value=built) as owned_path, \
                    mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                p.run_arm('child',0);p.run_arm('ownedAncestor',1)
            self.assertEqual([x[1] for x in events],['install-aut','pretest-installed-Tripfolio','selected-tests']*2)
            for start in (0,3):
                owned=events[start][0]
                self.assertEqual(events[start][2],['/usr/bin/xcrun','simctl','install',owned,built])
                self.assertEqual(events[start+1][2],['/usr/bin/xcrun','simctl','get_app_container',owned,q.APP_ID,'app'])
                self.assertEqual([x[3] for x in events[start:start+3]],[120,38,780])
            self.assertNotEqual(events[0][0],events[3][0]);self.assertEqual(owned_path.call_count,2)
            for mode in m.MODES:
                receipt=json.loads((p.root/mode/'pretest-installed-aut.json').read_text())
                self.assertEqual(receipt['identity'],p.products['Tripfolio'])
                self.assertTrue(receipt['content_matches_shared'])

    def test_aut_setup_failure_prevents_test_and_second_arm(self):
        for fault in ('install','query','path','bytes','missing-proof'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(Context,'checkpoint',lambda self,**kw:None):
                p=self.fake_pair(Path(tmp));p.prepare=lambda:None
                p.install_aut=Pair.install_aut.__get__(p,Pair)
                p.product_paths={'Tripfolio':p.root/'Tripfolio.app'}
                p.products={'Tripfolio':{'content':{'expected':'build'},'modes':{}}}
                if fault=='missing-proof':p.install_aut=lambda arm:None
                events=[]
                def command(arm,label,args,cap=38):
                    events.append(label)
                    if (fault=='install' and label=='install-aut') or (fault=='query' and label=='pretest-installed-Tripfolio'):
                        raise RuntimeError(fault+' failed')
                    return str(p.root/'Tripfolio.app')
                with mock.patch.object(Context,'setup',lambda arm:self.setup_arm(arm)), \
                        mock.patch.object(Context,'command',command), \
                        mock.patch.object(Context,'owned_path',side_effect=RuntimeError('wrong owned path') if fault=='path' else None,return_value=p.root/'Tripfolio.app'), \
                        mock.patch.object(q,'compiled_identity',return_value={'content':{'other':'build'},'modes':{}}), \
                        mock.patch.object(Context,'cleanup',lambda arm:self.clean_arm(arm)):
                    self.assertEqual(p.run(),1)
                self.assertEqual(list(p.report['arms']),['child']);self.assertNotIn('selected-tests',events)
                self.assertTrue(p.report['arms']['child']['cleanup_verified'])
                self.assertNotIn('pretest_installed_aut_verified',p.report['arms']['child'])

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

    def postbuild_boot_context(self,root,active=True):
        p=self.fake_pair(root);p.report['shared_build_verified']=True
        arm=Context(p,p.root/'child',p.final,'unused');p.current=arm;arm.owned='ABC'
        now=[p.started];arm.ops.now=lambda:now[0]
        row={'id':'boot-ready','argv':['/usr/bin/xcrun','simctl','bootstatus','ABC','-b'],
             'work_deadline':1000}
        if active:row['pgid']=123;arm.active[123]=SimpleNamespace(pid=123)
        arm.report['commands'].append(row)
        return p,arm,now,row

    def test_postbuild_owned_boot_twenty_second_scan_keeps_writer_privileges_false(self):
        for active in (False,True):
            with self.subTest(active=active),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,row=self.postbuild_boot_context(Path(tmp),active)
                def scan(*args,**kwargs):now[0]+=20;return {'allocated':0}
                with mock.patch.object(core,'live_sizes',side_effect=scan) as walk, \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    arm.monitor()
                self.assertEqual(arm.report['resources'][-1]['requested_scan_seconds'],30)
                self.assertEqual(walk.call_args.args[3],p.started+30)
                self.assertFalse(walk.call_args.kwargs['allow_xcresult_restart'])
                self.assertFalse(walk.call_args.kwargs['allow_products_restart'])

    def test_postbuild_scan_rejects_missing_proof_or_different_ownership(self):
        faults=('missing-proof','false-proof','nonboolean-proof','other-current','unknown','other-group',
                'coordinator-active','coordinator-unknown','wrong-id','wrong-device','wrong-pgid','finished')
        for fault in faults:
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,row=self.postbuild_boot_context(Path(tmp))
                if fault=='missing-proof':del p.report['shared_build_verified']
                elif fault=='false-proof':p.report['shared_build_verified']=False
                elif fault=='nonboolean-proof':p.report['shared_build_verified']=1
                elif fault=='other-current':p.current=None
                elif fault=='unknown':arm.unknown_spawn=True
                elif fault=='other-group':arm.active[124]=SimpleNamespace(pid=124)
                elif fault=='coordinator-active':p.commands.active[124]=SimpleNamespace(pid=124)
                elif fault=='coordinator-unknown':p.commands.unknown_spawn=True
                elif fault=='wrong-id':row['id']='other'
                elif fault=='wrong-device':row['argv'][3]='OTHER'
                elif fault=='wrong-pgid':row['pgid']=124
                elif fault=='finished':row['finish']=1
                def scan(*args,**kwargs):now[0]+=20;return {'allocated':0}
                with mock.patch.object(core,'live_sizes',side_effect=scan) as walk, \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaises(RuntimeError):arm.monitor()
                self.assertLessEqual(walk.call_args.args[3],p.started+15)
                self.assertFalse(walk.call_args.kwargs['allow_xcresult_restart'])
                self.assertFalse(walk.call_args.kwargs['allow_products_restart'])

    def test_postbuild_scan_keeps_original_global_and_command_deadlines(self):
        for global_remaining,command_remaining in ((7,1000),(1000,8),(6,8)):
            with self.subTest(global_remaining=global_remaining,command_remaining=command_remaining),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,row=self.postbuild_boot_context(Path(tmp))
                arm.limit=p.started+global_remaining;row['work_deadline']=command_remaining
                def scan(*args,**kwargs):now[0]+=20;return {'allocated':0}
                with mock.patch.object(core,'live_sizes',side_effect=scan) as walk, \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaises(RuntimeError):arm.monitor()
                self.assertEqual(walk.call_args.args[3],p.started+min(global_remaining,command_remaining))
                self.assertEqual(arm.limit,p.started+global_remaining)
                self.assertFalse(walk.call_args.kwargs['allow_xcresult_restart'])
                self.assertFalse(walk.call_args.kwargs['allow_products_restart'])

    def test_postbuild_proof_only_after_complete_actual_prepare(self):
        for fault in (None,'build','settings','products','source-after'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p=self.fake_pair(Path(tmp));p.before={'files':{}};p.admit_build=mock.Mock();p.commands.once=mock.Mock()
                settings=json.dumps([{'target':name,'buildSettings':{'COMPILER_INDEX_STORE_ENABLE':'YES' if fault=='settings' else 'NO'}}
                                    for name in ('Tripfolio','TripfolioTests','TripfolioUITests')])
                replies={'xcode':q.XCODE_VERSION,'developer':q.DEVELOPER_DIR,'sdk':'26.2',
                         'architecture':'arm64','build-settings':settings}
                def command(label,*args):
                    self.assertIsNot(p.report.get('shared_build_verified'),True)
                    if fault=='build' and label=='build-for-testing':raise RuntimeError('build failed')
                    return replies.get(label,'')
                def source(label):
                    self.assertIsNot(p.report.get('shared_build_verified'),True)
                    if fault=='source-after' and label=='source-after-build':raise RuntimeError('source changed')
                def products(label):
                    self.assertIsNot(p.report.get('shared_build_verified'),True)
                    if fault=='products':raise RuntimeError('product identity failed')
                p.commands.command=command;p.source=source;p.product_snapshot=products
                p.commands.sim=lambda *args,**kwargs:json.dumps({'runtimes':[{'identifier':m.RUNTIME,
                    'version':'26.2','buildversion':'23C54','isAvailable':True,'supportedArchitectures':['arm64'],
                    'supportedDeviceTypes':[{'identifier':m.DEVICE}]}]})
                with mock.patch.object(q,'focused_build_selection',return_value={'build_settings':['EXCLUDED_SOURCE_FILE_NAMES=Other.swift']}), \
                        mock.patch.object(q,'shared_product_paths',return_value={}):
                    if fault:
                        with self.assertRaises(RuntimeError):p.prepare()
                        self.assertIsNot(p.report.get('shared_build_verified'),True)
                    else:
                        p.prepare();self.assertIs(p.report['shared_build_verified'],True)

    def boot_command_fixture(self,root):
        p=self.fake_pair(root);p.report['shared_build_verified']=True
        arm=Context(p,p.root/'child',p.final,'unused');p.current=arm;arm.owned='ABC'
        now=[p.started];polls=[];scans=[]
        child=SimpleNamespace(pid=77,returncode=None)
        def poll():
            polls.append(now[0])
            if len(polls)>=4:child.returncode=0
            return child.returncode
        child.poll=poll
        arm.ops=SimpleNamespace(now=lambda:now[0],spawn=lambda args:child,prepare=lambda proc:None,
            read=lambda proc:[],absent=lambda proc:True,close=lambda proc:None,
            sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
        def scan(*args,**kwargs):
            row=arm.report['commands'][-1] if arm.report['commands'] else None
            scans.append(('before' if row is None else 'post' if 'finish' in row else 'pre',args,kwargs))
            return {'logical':0,'allocated':0,'entries':1,'xcresults':{}}
        return p,arm,now,child,polls,scans,scan

    def test_actual_boot_command_has_full_boundaries_and_no_recursive_pump_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,arm,now,child,polls,scans,scan=self.boot_command_fixture(Path(tmp))
            def wait(seconds):now[0]+=10
            arm.ops.sleep=wait
            with mock.patch.object(core,'live_sizes',side_effect=scan), \
                    mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                self.assertEqual(arm.sim('boot-ready','bootstatus','ABC','-b'),'')
            row=arm.report['commands'][0];proof=row['boot_accounting']
            self.assertEqual([s[0] for s in scans],['before','pre','post'])
            self.assertGreaterEqual(proof['interim_checks'],3)
            self.assertTrue(proof['full_pre_verified']);self.assertTrue(proof['full_post_verified'])
            self.assertIn('transient',proof['policy'])
            self.assertEqual(row['returncode'],0);self.assertEqual(row['requested_cap_seconds'],188)
            self.assertAlmostEqual(row['command_deadline']-row['work_deadline'],8)
            for _,args,kwargs in scans[-2:]:
                self.assertLessEqual(args[3],p.started+row['work_deadline'])
                self.assertFalse(kwargs['allow_products_restart']);self.assertFalse(kwargs['allow_xcresult_restart'])
            self.assertFalse(arm.active);self.assertIsNone(arm._boot_boundary)

    def test_boot_postcheck_failure_preserves_native_success_but_blocks_return(self):
        for fault in ('scan','deadline','root'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.boot_command_fixture(Path(tmp))
                def walk(*args,**kwargs):
                    result=scan(*args,**kwargs)
                    if scans[-1][0]=='post':
                        if fault=='scan':raise RuntimeError('post boundary changed')
                        if fault=='deadline':now[0]=args[3]
                        if fault=='root':raise RuntimeError('root changed')
                    return result
                with mock.patch.object(core,'live_sizes',side_effect=walk), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaises(RuntimeError):arm.sim('boot-ready','bootstatus','ABC','-b')
                row=arm.report['commands'][0]
                self.assertEqual(row['returncode'],0);self.assertEqual(row['outcome'],'completed')
                self.assertFalse(row['boot_accounting']['full_post_verified'])
                self.assertEqual(row['boot_accounting']['post_status'],'failed')
                self.assertFalse(arm.active);self.assertIsNone(arm._boot_boundary)

    def test_actual_boot_slow_close_requires_proven_closure_before_postcheck(self):
        for broken in (False,True):
            with self.subTest(broken=broken),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.boot_command_fixture(Path(tmp))
                def close(proc):
                    now[0]+=core.CAPS['scan_interval_seconds']+1
                    if broken:arm.report['commands'][-1]['stop']['group_absent']=False
                arm.ops.close=close
                with mock.patch.object(core,'live_sizes',side_effect=scan), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    if broken:
                        with self.assertRaisesRegex(RuntimeError,'boot-ready failed'):
                            arm.sim('boot-ready','bootstatus','ABC','-b')
                    else:arm.sim('boot-ready','bootstatus','ABC','-b')
                row=arm.report['commands'][0]
                self.assertEqual(row['returncode'],0)
                self.assertEqual(row['boot_accounting']['full_post_verified'],not broken)
                self.assertEqual([s[0] for s in scans],['before','pre'] if broken else ['before','pre','post'])
                self.assertIsNone(arm._boot_boundary)

    def test_boot_interim_checks_fail_closed_without_recursive_scan(self):
        faults=('root','space','log','deadline','proof','foreign','unknown','coordinator','record')
        for fault in faults:
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,row=self.postbuild_boot_context(Path(tmp),False)
                row['bytes']={'stdout':0,'stderr':0};arm._boot_boundary={'record':None,'post':False}
                with mock.patch.object(core,'live_sizes',return_value={'allocated':0}), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    arm.monitor()
                child=SimpleNamespace(pid=123);arm.active[123]=child;row['pgid']=123
                if fault=='root':p.output_id=('wrong',)
                elif fault=='log':row['bytes']['stdout']=core.base.PER_LOG+1
                elif fault=='deadline':now[0]=p.started+row['work_deadline']
                elif fault=='proof':p.report['shared_build_verified']=False
                elif fault=='foreign':arm.active[124]=SimpleNamespace(pid=124)
                elif fault=='unknown':arm.unknown_spawn=True
                elif fault=='coordinator':p.commands.active[456]=SimpleNamespace(pid=456)
                elif fault=='record':arm.report['commands'][-1]=dict(row)
                free=0 if fault=='space' else core.CAPS['work_free_bytes']
                with mock.patch.object(core,'live_sizes') as full, \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=free)):
                    with self.assertRaises(RuntimeError):arm.monitor()
                full.assert_not_called()
                self.assertFalse(row['boot_accounting']['full_post_verified'])

    def test_boot_phase_only_exact_verified_owned_command(self):
        for fault in ('id','argv','device','cleaning','proof','current','active','unknown','coordinator'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.boot_command_fixture(Path(tmp))
                label='boot-ready';args=['/usr/bin/xcrun','simctl','bootstatus','ABC','-b']
                if fault=='id':label='other'
                elif fault=='argv':args[-1]='wrong'
                elif fault=='device':arm.owned='OTHER'
                elif fault=='cleaning':arm.cleaning=True
                elif fault=='proof':p.report['shared_build_verified']=False
                elif fault=='current':p.current=None
                elif fault=='active':arm.active[123]=SimpleNamespace(pid=123)
                elif fault=='unknown':arm.unknown_spawn=True
                elif fault=='coordinator':p.commands.unknown_spawn=True
                with mock.patch.object(core.Recovery,'command',return_value='base') as base:
                    self.assertEqual(arm.command(label,args,188),'base')
                base.assert_called_once_with(label,args,188)
                self.assertIsNone(getattr(arm,'_boot_boundary',None))

    def late_stop_fixture(self,root):
        with mock.patch.object(time,'monotonic',return_value=1000.0), \
                mock.patch.object(core.base.RealOps,'now',return_value=1000.0):
            p=self.fake_pair(root);arm=Context(p,p.root/'child',p.final,'unused');p.current=arm
        now=[p.started];arm.owned='ABC';arm.cleaning=True
        arm.limit=p.started+110;arm.write_deadline=p.started+120
        sent=[];child=SimpleNamespace(pid=77,returncode=None)
        child.poll=lambda:child.returncode
        def send(proc,sig):sent.append(sig);proc.returncode=-int(sig);return 'syscall_returned'
        arm.ops=SimpleNamespace(now=lambda:now[0],spawn=lambda args:child,prepare=lambda proc:None,
            read=lambda proc:[],absent=lambda proc:proc.returncode is not None,
            close=lambda proc:None,send=send,sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
        return p,arm,now,child,sent

    def test_actual_late_cleanup_first_stop_retains_timeout_and_overrun(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,arm,now,child,sent=self.late_stop_fixture(Path(tmp))
            # A real command loop loses scheduling before its work/stop boundaries.
            arm.ops.sleep=lambda seconds:now.__setitem__(0,p.started+36)
            with self.assertRaisesRegex(RuntimeError,'shutdown failed'):
                arm.command('shutdown',['/usr/bin/xcrun','simctl','shutdown','ABC'],30)
            row=arm.report['commands'][0]
            self.assertEqual(sent,[m.signal.SIGTERM]);self.assertFalse(arm.active)
            self.assertEqual(row['error'],"RuntimeError('Command timeout')")
            self.assertIn('exceeded cap',row['cap_error']);self.assertEqual(row['outcome'],'failed')
            self.assertTrue(row['stop']['attempted']);self.assertTrue(row['stop']['leader_reaped'])
            self.assertTrue(row['stop']['group_absent'])
            self.assertEqual(row['late_first_stop']['original_deadline'],30)
            self.assertEqual(row['late_first_stop']['deadline'],44)
            self.assertEqual(arm.limit,p.started+110);self.assertEqual(arm.write_deadline,p.started+120)

    def test_late_first_stop_clips_existing_parent_and_receipt_bounds(self):
        for limit,write,final,expected in ((110,120,1980,44),(39,120,1980,39),(110,49,1980,39),(110,120,49,39)):
            with self.subTest(limit=limit,write=write,final=final),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,sent=self.late_stop_fixture(Path(tmp));now[0]=p.started+36
                arm.limit=p.started+limit;arm.write_deadline=p.started+write;p.final=p.started+final
                row={'id':'shutdown','argv':['/usr/bin/xcrun','simctl','shutdown','ABC'],'pgid':77}
                arm.report['commands'].append(row);arm.active[77]=child
                arm.stop(child,p.started+30,row)
                self.assertEqual(row['late_first_stop']['deadline'],expected)
                self.assertTrue(row['stop']['group_absent']);self.assertTrue(row['stop']['leader_reaped'])
                self.assertEqual(sent,[m.signal.SIGTERM])

    def test_late_stop_negative_conditions_preserve_original_exception_and_no_signals(self):
        faults=('not-cleaning','current','id','argv','device','record','pgid','foreign','unknown','coordinator',
                'coordinator-unknown','reaped','attempted','ambiguous-stop','parent-expired','receipt-expired','final-expired')
        for fault in faults:
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,sent=self.late_stop_fixture(Path(tmp));now[0]=p.started+36
                row={'id':'shutdown','argv':['/usr/bin/xcrun','simctl','shutdown','ABC'],'pgid':77}
                arm.report['commands'].append(row);arm.active[77]=child
                if fault=='not-cleaning':arm.cleaning=False
                elif fault=='current':p.current=None
                elif fault=='id':row['id']='final-inventory'
                elif fault=='argv':row['argv'][-1]='OTHER'
                elif fault=='device':arm.owned='OTHER'
                elif fault=='record':arm.report['commands'].append(dict(row))
                elif fault=='pgid':row['pgid']=78
                elif fault=='foreign':arm.active[78]=SimpleNamespace(pid=78)
                elif fault=='unknown':arm.unknown_spawn=True
                elif fault=='coordinator':p.commands.active[78]=SimpleNamespace(pid=78)
                elif fault=='coordinator-unknown':p.commands.unknown_spawn=True
                elif fault=='reaped':child.returncode=0
                elif fault=='attempted':row['stop']={'attempted':True}
                elif fault=='ambiguous-stop':row['stop']={'attempted':False,'error':'unknown'}
                elif fault=='parent-expired':arm.limit=now[0]
                elif fault=='receipt-expired':arm.write_deadline=now[0]+10
                elif fault=='final-expired':p.final=now[0]+10
                expected='No repeated signalling' if fault=='attempted' else 'Stop deadline reached'
                with self.assertRaisesRegex(RuntimeError,expected):arm.stop(child,p.started+30,row)
                self.assertEqual(sent,[]);self.assertNotIn('late_first_stop',row)
                self.assertTrue(row['stop']['attempted']);self.assertIs(arm.active[77],child)

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


    def install_command_fixture(self,root):
        p,arm,now,child,polls,scans,scan=self.boot_command_fixture(root)
        p.product_paths={'Tripfolio':root/'shared'/'Tripfolio.app'}
        arm.report['commands'].append({'id':'boot-ready','argv':['/usr/bin/xcrun','simctl','bootstatus','ABC','-b'],
            'returncode':0,'outcome':'completed','finish':0,'work_deadline':180,
            'stop':{'group_absent':True,'leader_reaped':True},
            'boot_accounting':{'full_pre_verified':True,'full_post_verified':True,'post_status':'verified','post_elapsed':0}})
        return p,arm,now,child,polls,scans,scan

    def test_install_command_has_full_boundaries_without_recursive_pump_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,arm,now,child,polls,scans,scan=self.install_command_fixture(Path(tmp))
            def bounded_scan(*args,**kwargs):
                result=scan(*args,**kwargs)
                if arm.report['commands'][-1]['id']=='install-aut':now[0]+=6
                return result
            arm.ops.sleep=lambda seconds:now.__setitem__(0,now[0]+4)
            with mock.patch.object(core,'live_sizes',side_effect=bounded_scan), \
                    mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                self.assertEqual(arm.sim('install-aut','install','ABC',p.product_paths['Tripfolio']),'')
            row=arm.report['commands'][-1];proof=row['install_accounting']
            self.assertEqual([s[0] for s in scans],['post','pre','post'])
            self.assertGreaterEqual(proof['interim_checks'],3)
            self.assertTrue(proof['full_pre_verified']);self.assertTrue(proof['full_post_verified'])
            self.assertEqual(row['requested_cap_seconds'],38)
            self.assertAlmostEqual(row['work_deadline']-row['start'],30)
            self.assertAlmostEqual(row['command_deadline']-row['work_deadline'],8)
            self.assertIn('transient subtree size/writes unobserved',proof['policy'])
            self.assertLessEqual(proof['post_elapsed'],row['work_deadline'])
            for _,args,kwargs in scans[-2:]:
                self.assertLessEqual(args[3],p.started+row['work_deadline'])
                self.assertFalse(kwargs['allow_products_restart']);self.assertFalse(kwargs['allow_xcresult_restart'])
            self.assertFalse(arm.active);self.assertIsNone(arm._boot_boundary)

    def test_install_boundary_requires_exact_owned_product_and_completed_boot_proof(self):
        for case in ('label','argv','device','product','no-products','unverified-build','other-context',
                     'unknown','foreign-active','coordinator-active','coordinator-unknown','cleaning',
                     'no-boot','duplicate-boot','failed-boot','wrong-boot-device','missing-pre','missing-post',
                     'boot-post-late','boot-group-unclosed','boot-leader-unreaped'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.install_command_fixture(Path(tmp))
                label='install-aut';args=['/usr/bin/xcrun','simctl','install','ABC',str(p.product_paths['Tripfolio'])]
                row=arm.report['commands'][0]
                if case=='label':label='other'
                elif case=='argv':args.insert(2,'--other')
                elif case=='device':args[3]='OTHER'
                elif case=='product':args[4]+='-other'
                elif case=='no-products':p.product_paths=None
                elif case=='unverified-build':p.report['shared_build_verified']=False
                elif case=='other-context':p.current=None
                elif case=='unknown':arm.unknown_spawn=True
                elif case=='foreign-active':arm.active[999]=SimpleNamespace(pid=999)
                elif case=='coordinator-active':p.commands.active[999]=SimpleNamespace(pid=999)
                elif case=='coordinator-unknown':p.commands.unknown_spawn=True
                elif case=='cleaning':arm.cleaning=True
                elif case=='no-boot':arm.report['commands']=[]
                elif case=='duplicate-boot':arm.report['commands'].append(dict(row))
                elif case=='failed-boot':row['returncode']=1
                elif case=='wrong-boot-device':row['argv'][3]='OTHER'
                elif case=='missing-pre':row['boot_accounting']['full_pre_verified']=False
                elif case=='missing-post':row['boot_accounting']['full_post_verified']=False
                elif case=='boot-post-late':row['boot_accounting']['post_elapsed']=181
                elif case=='boot-group-unclosed':row['stop']['group_absent']=False
                elif case=='boot-leader-unreaped':row['stop']['leader_reaped']=False
                self.assertFalse(arm.install_boundary_eligible(label,args))

    def test_install_postcheck_failure_preserves_returncode_and_prevents_success(self):
        for case in ('scan-error','deadline'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.install_command_fixture(Path(tmp))
                def post_failure(*args,**kwargs):
                    row=arm.report['commands'][-1]
                    result=scan(*args,**kwargs)
                    if row['id']=='install-aut' and 'finish' in row:
                        if case=='scan-error':raise RuntimeError('synthetic full post failure')
                        now[0]=p.started+row['work_deadline']+0.01
                    return result
                with mock.patch.object(core,'live_sizes',side_effect=post_failure), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaises(RuntimeError):arm.sim('install-aut','install','ABC',p.product_paths['Tripfolio'])
                row=arm.report['commands'][-1]
                self.assertEqual(row['returncode'],0)
                self.assertTrue(row['install_accounting']['full_pre_verified'])
                self.assertFalse(row['install_accounting']['full_post_verified'])
                self.assertEqual(row['install_accounting']['post_status'],'failed')
                self.assertFalse(arm.active);self.assertIsNone(arm._boot_boundary)
                self.assertNotIn('pretest_installed_aut_verified',arm.report)

    def test_install_slow_close_requires_settled_ownership_then_full_postcheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,arm,now,child,polls,scans,scan=self.install_command_fixture(Path(tmp))
            arm.ops.close=lambda proc:now.__setitem__(0,now[0]+2)
            with mock.patch.object(core,'live_sizes',side_effect=scan), \
                    mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                arm.sim('install-aut','install','ABC',p.product_paths['Tripfolio'])
            row=arm.report['commands'][-1]
            self.assertTrue(row['install_accounting']['full_post_verified'])
            self.assertTrue(row['stop']['leader_reaped']);self.assertTrue(row['stop']['group_absent'])
            self.assertEqual([s[0] for s in scans],['post','pre','post'])
    def install_timing_fixture(self, root, completes=True):
        with mock.patch.object(m.time,'monotonic',return_value=1000.0), \
                mock.patch.object(core.base.RealOps,'now',return_value=1000.0):
            p,arm,now,child,polls,scans,scan=self.install_command_fixture(root)
        built=p.product_paths['Tripfolio'];built.mkdir(parents=True);(built/'binary').write_bytes(b'same build')
        p.products={'Tripfolio':q.compiled_identity(built,lambda:None)}
        p.install_aut=Pair.install_aut.__get__(p,Pair)
        invoked=[];spawned=[];sent=[];real_sim=arm.sim
        def sim(label,*args,cap=38):
            invoked.append((label,cap))
            if label=='pretest-installed-Tripfolio':return str(built)
            return real_sim(label,*args,cap=cap)
        arm.sim=sim;arm.owned_path=lambda *args:built
        def spawn(args):
            spawned.append((list(args),now[0]));return child
        def poll():
            polls.append(now[0])
            if completes and spawned and now[0]-spawned[0][1]>=40 and child.returncode is None:
                child.returncode=0
            return child.returncode
        def send(proc,sig):
            sent.append(int(sig));proc.returncode=-int(sig);return 'syscall_returned'
        child.poll=poll;arm.ops.spawn=spawn;arm.ops.send=send
        arm.ops.absent=lambda proc:proc.returncode is not None
        arm.ops.sleep=lambda seconds:now.__setitem__(0,now[0]+1)
        return p,arm,now,child,scans,scan,invoked,spawned,sent

    def test_install_only_timing_experiment_preserves_content_and_one_attempt(self):
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,scans,scan,invoked,spawned,sent=self.install_timing_fixture(Path(tmp))
                if changed:(p.product_paths['Tripfolio']/'binary').write_bytes(b'changed')
                with mock.patch.object(m.time,'monotonic',side_effect=lambda:now[0]), \
                        mock.patch.object(core,'live_sizes',side_effect=scan), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    if changed:
                        with self.assertRaisesRegex(RuntimeError,'bytes differ'):p.install_aut(arm)
                    else:p.install_aut(arm)
                    with self.assertRaises(RuntimeError):p.install_aut(arm)
                row=next(x for x in arm.report['commands'] if x['id']=='install-aut')
                self.assertEqual(row['requested_cap_seconds'],120)
                self.assertAlmostEqual(row['work_deadline']-row['start'],112)
                self.assertAlmostEqual(row['command_deadline']-row['work_deadline'],8)
                self.assertGreaterEqual(row['finish']-row['start'],40)
                self.assertTrue(row['install_accounting']['full_post_verified'])
                self.assertEqual(invoked,[('install-aut',120),('pretest-installed-Tripfolio',38)])
                self.assertEqual(len(spawned),1);self.assertEqual(sent,[])
                self.assertEqual(arm.report['attempts']['install-aut'],1)
                self.assertEqual(arm.report.get('pretest_installed_aut_verified',False),not changed)
                self.assertEqual((p.work_end,p.final),(2800.0,2980.0))
                self.assertFalse(arm.active)
                self.assertTrue(all(not kw['allow_products_restart'] and not kw['allow_xcresult_restart']
                                    for _,_,kw in scans))

    def test_install_only_timeout_and_parent_clipping_keep_failure(self):
        for remaining,expected_work in ((None,112),(20,12)):
            with self.subTest(remaining=remaining),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,scans,scan,invoked,spawned,sent=self.install_timing_fixture(Path(tmp),False)
                if remaining is not None:arm.limit=now[0]+remaining
                with mock.patch.object(m.time,'monotonic',side_effect=lambda:now[0]), \
                        mock.patch.object(core,'live_sizes',side_effect=scan), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaisesRegex(RuntimeError,'install-aut failed'):p.install_aut(arm)
                    with self.assertRaises(RuntimeError):p.install_aut(arm)
                row=next(x for x in arm.report['commands'] if x['id']=='install-aut')
                self.assertEqual(row['requested_cap_seconds'],120)
                self.assertAlmostEqual(row['work_deadline']-row['start'],expected_work)
                self.assertAlmostEqual(row['command_deadline']-row['work_deadline'],8)
                self.assertEqual(row['error'],"RuntimeError('Command timeout')")
                self.assertFalse(row['install_accounting']['full_post_verified'])
                self.assertTrue(row['stop']['group_absent']);self.assertTrue(row['stop']['leader_reaped'])
                self.assertEqual(invoked,[('install-aut',120)]);self.assertEqual(len(spawned),1)
                self.assertEqual(sent,[15]);self.assertFalse(arm.active)
                self.assertNotIn('pretest_installed_aut_verified',arm.report)
                self.assertEqual((p.work_end,p.final),(2800.0,2980.0))



    def query_command_fixture(self,root,label='pretest-installed-Tripfolio'):
        p,arm,now,child,polls,scans,scan=self.install_command_fixture(root)
        arm.report['commands'].append({'id':'install-aut',
            'argv':['/usr/bin/xcrun','simctl','install','ABC',str(p.product_paths['Tripfolio'])],
            'returncode':0,'outcome':'completed','finish':0,'work_deadline':112,
            'stop':{'group_absent':True,'leader_reaped':True},
            'install_accounting':{'full_pre_verified':True,'full_post_verified':True,
                                  'post_status':'verified','post_elapsed':0}})
        if label!='pretest-installed-Tripfolio':
            arm.report['pretest_installed_aut_verified']=True
            arm.report['commands'].append({'id':'selected-tests','finish':0,
                'stop':{'group_absent':True,'leader_reaped':True}})
        return p,arm,now,child,polls,scans,scan

    def test_owned_container_queries_preserve_boundaries_and_thirty_second_budget(self):
        for label,identifier in (('pretest-installed-Tripfolio',q.APP_ID),
                                 ('installed-Tripfolio',q.APP_ID),
                                 ('installed-TripfolioUITestsRunner',q.RUNNER_ID)):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.query_command_fixture(Path(tmp),label)
                arm.ops.sleep=lambda seconds:now.__setitem__(0,now[0]+4)
                spawned=[];arm.ops.spawn=lambda args:(spawned.append(args) or child)
                with mock.patch.object(core,'live_sizes',side_effect=scan), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    self.assertEqual(arm.sim(label,'get_app_container','ABC',identifier,'app'),'')
                row=arm.report['commands'][-1];proof=row['query_accounting']
                self.assertEqual([s[0] for s in scans],['post','pre','post'])
                self.assertGreaterEqual(proof['interim_checks'],3)
                self.assertTrue(proof['full_pre_verified']);self.assertTrue(proof['full_post_verified'])
                self.assertEqual(row['requested_cap_seconds'],38)
                self.assertAlmostEqual(row['work_deadline']-row['start'],30,places=4)
                self.assertAlmostEqual(row['command_deadline']-row['work_deadline'],8)
                self.assertEqual(len(spawned),1);self.assertFalse(arm.active)
                for _,args,kwargs in scans[-2:]:
                    self.assertLessEqual(args[3],p.started+row['work_deadline'])
                    self.assertFalse(kwargs['allow_products_restart']);self.assertFalse(kwargs['allow_xcresult_restart'])

    def test_container_query_accounting_rejects_changed_identity_or_unsettled_prerequisites(self):
        for case in ('label','bundle','device','container','unverified-build','other-context','unknown',
                     'foreign-active','coordinator-active','cleaning','missing-install','duplicate-install',
                     'failed-install','wrong-installed-device','missing-pre','missing-post','late-post',
                     'unclosed-install','unreaped-install','pretest-after-tests','posttest-without-tests',
                     'posttest-active-tests','posttest-without-pretest-proof'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                label='installed-Tripfolio' if case.startswith('posttest-') else 'pretest-installed-Tripfolio'
                p,arm,now,child,polls,scans,scan=self.query_command_fixture(Path(tmp),label)
                args=['/usr/bin/xcrun','simctl','get_app_container','ABC',q.APP_ID,'app']
                row=arm.report['commands'][1]
                if case=='label':label='arbitrary-query'
                elif case=='bundle':args[4]='com.other.app'
                elif case=='device':args[3]='OTHER'
                elif case=='container':args[5]='data'
                elif case=='unverified-build':p.report['shared_build_verified']=False
                elif case=='other-context':p.current=None
                elif case=='unknown':arm.unknown_spawn=True
                elif case=='foreign-active':arm.active[999]=SimpleNamespace(pid=999)
                elif case=='coordinator-active':p.commands.active[999]=SimpleNamespace(pid=999)
                elif case=='cleaning':arm.cleaning=True
                elif case=='missing-install':arm.report['commands'].pop(1)
                elif case=='duplicate-install':arm.report['commands'].append(dict(row))
                elif case=='failed-install':row['returncode']=1
                elif case=='wrong-installed-device':row['argv'][3]='OTHER'
                elif case=='missing-pre':row['install_accounting']['full_pre_verified']=False
                elif case=='missing-post':row['install_accounting']['full_post_verified']=False
                elif case=='late-post':row['install_accounting']['post_elapsed']=113
                elif case=='unclosed-install':row['stop']['group_absent']=False
                elif case=='unreaped-install':row['stop']['leader_reaped']=False
                elif case=='pretest-after-tests':arm.report['commands'].append({'id':'selected-tests'})
                elif case=='posttest-without-tests':arm.report['commands'].pop()
                elif case=='posttest-active-tests':arm.report['commands'][-1]['stop']['group_absent']=False
                elif case=='posttest-without-pretest-proof':arm.report['pretest_installed_aut_verified']=False
                self.assertFalse(arm.query_boundary_eligible(label,args))

    def test_container_query_postcheck_failure_still_blocks_content_verification(self):
        for case in ('scan-error','deadline'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.query_command_fixture(Path(tmp))
                def post_failure(*args,**kwargs):
                    row=arm.report['commands'][-1];result=scan(*args,**kwargs)
                    if row['id']=='pretest-installed-Tripfolio' and 'finish' in row:
                        if case=='scan-error':raise RuntimeError('synthetic full post failure')
                        now[0]=p.started+row['work_deadline']+0.01
                    return result
                with mock.patch.object(core,'live_sizes',side_effect=post_failure), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaises(RuntimeError):
                        arm.sim('pretest-installed-Tripfolio','get_app_container','ABC',q.APP_ID,'app')
                row=arm.report['commands'][-1]
                self.assertEqual(row['returncode'],0)
                self.assertFalse(row['query_accounting']['full_post_verified'])
                self.assertEqual(row['query_accounting']['post_status'],'failed')
                self.assertFalse(arm.active);self.assertIsNone(arm._boot_boundary)
                self.assertNotIn('pretest_installed_aut_verified',arm.report)

    def test_container_query_timeout_keeps_one_process_and_parent_deadline(self):
        for remaining,expected in ((None,30),(20,12)):
            with self.subTest(remaining=remaining),tempfile.TemporaryDirectory() as tmp:
                p,arm,now,child,polls,scans,scan=self.query_command_fixture(Path(tmp))
                if remaining is not None:arm.limit=now[0]+remaining
                spawned=[];sent=[]
                child.poll=lambda:child.returncode
                arm.ops.spawn=lambda args:(spawned.append(args) or child)
                arm.ops.absent=lambda proc:proc.returncode is not None
                def send(proc,sig):sent.append(int(sig));proc.returncode=-int(sig);return 'syscall_returned'
                arm.ops.send=send;arm.ops.sleep=lambda seconds:now.__setitem__(0,now[0]+1)
                with mock.patch.object(core,'live_sizes',side_effect=scan), \
                        mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=core.CAPS['work_free_bytes'])):
                    with self.assertRaisesRegex(RuntimeError,'pretest-installed-Tripfolio failed'):
                        arm.sim('pretest-installed-Tripfolio','get_app_container','ABC',q.APP_ID,'app')
                row=arm.report['commands'][-1]
                self.assertAlmostEqual(row['work_deadline']-row['start'],expected,places=4)
                self.assertEqual(row['error'],"RuntimeError('Command timeout')")
                self.assertFalse(row['query_accounting']['full_post_verified'])
                self.assertEqual(len(spawned),1);self.assertEqual(sent,[15]);self.assertFalse(arm.active)
                self.assertTrue(row['stop']['group_absent']);self.assertTrue(row['stop']['leader_reaped'])


if __name__=='__main__':unittest.main()
