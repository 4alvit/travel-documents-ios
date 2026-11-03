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
        return dict(GITHUB_ACTIONS='true',RUNNER_OS='macOS',RUNNER_ARCH='ARM64',
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
        p.job={};p.before={};p.products={};p.product_paths={};p.derived=root/'derived';p.settings=[]
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
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'build').mkdir()
            p=Pair(root,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40})
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


if __name__=='__main__':unittest.main()
