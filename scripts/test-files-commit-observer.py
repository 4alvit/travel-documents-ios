"""Offline contracts for the new observer only. Never starts a native child."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent

def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    result=importlib.util.module_from_spec(spec)
    with patch('subprocess.Popen') as spawn,patch('os.killpg') as kill:
        spec.loader.exec_module(result)
        spawn.assert_not_called();kill.assert_not_called()
    return result

observer=load('files_commit_observer');entry=load('observe_files_commit')
TOKEN='11111111-1111-4111-8111-111111111111';DEVICE='22222222-2222-4222-8222-222222222222'

def marker(stage,t=100):return f'TD_FILES_COMMIT_V1|{TOKEN}|{stage}|{t}.0\n'.encode()

def sequence(outcome="postcondition_failed"):
    p=observer.Markers(TOKEN)
    for i,s in enumerate(('start','editor_inline','before_done','after_done',outcome)):
        p.feed(marker(s,100+i),i)
    return p

class MarkerTests(unittest.TestCase):
    def test_split_noise_and_exact_failed_sequence(self):
        p=observer.Markers(TOKEN);data=b'compiler output\n'+marker('start')
        for b in data:p.feed(bytes([b]),1)
        self.assertEqual([r['stage'] for r in p.rows],['start'])
        self.assertEqual(len(sequence().rows),5)
    def test_foreign_token(self):
        with self.assertRaisesRegex(RuntimeError,'foreign'):observer.Markers(DEVICE).feed(marker('start'),1)
    def test_duplicate(self):
        p=observer.Markers(TOKEN);p.feed(marker('start'),1)
        with self.assertRaisesRegex(RuntimeError,'duplicate'):p.feed(marker('start'),2)
    def test_after_done_without_before(self):
        p=observer.Markers(TOKEN);p.feed(marker('start'),1)
        with self.assertRaisesRegex(RuntimeError,'out-of-order'):p.feed(marker('after_done'),2)
    def test_no_false_pass_after_failure(self):
        with self.assertRaises(RuntimeError):sequence().feed(marker('postcondition_passed',110),10)
    def test_malformed_line(self):
        with self.assertRaisesRegex(RuntimeError,'malformed'):observer.Markers(TOKEN).feed(b'TD_FILES_COMMIT_V1|bad\n',1)
    def test_unterminated_marker_after_valid_sequence(self):
        p=sequence();p.feed(b'TD_FILES_COMMIT_V1|bad',10)
        with self.assertRaisesRegex(RuntimeError,'EOF'):p.finish()
    def test_wall_time_reversal(self):
        p=observer.Markers(TOKEN);p.feed(marker('start',100),1)
        with self.assertRaises(RuntimeError):p.feed(marker('editor_inline',99),2)
    def test_unbounded_line(self):
        with self.assertRaises(RuntimeError):observer.Markers(TOKEN).feed(b'x'*(256*1024+1),1)

class LogTests(unittest.TestCase):
    def sample(self,**kw):
        return dict(eventMessage='rename commit rejected NSCocoaErrorDomain Code=4 '+TOKEN+' person@example.org /Users/private/passport.pdf',
                    subsystem='com.apple.FileProvider',processImagePath='/private/fileproviderd',
                    timestamp='1970-01-01 00:01:42.000+0000',**kw)
    def test_closed_vocabulary_removes_private_text_and_preserves_domain(self):
        out=observer.sanitize_logs(json.dumps([self.sample()]).encode(),TOKEN,100,110)
        row=out['signals'][0];self.assertEqual(row['numeric_codes'],['4'])
        self.assertEqual(row['error_domains'],['NSCocoaErrorDomain']);self.assertTrue(row['mentions_owned_uuid'])
        text=json.dumps(out)
        for secret in ('person@','/Users/','passport.pdf',TOKEN):self.assertNotIn(secret,text)
        self.assertIn('unknown',out['causal_interpretation'])
    def test_no_signal_is_not_no_rejection(self):
        out=observer.sanitize_logs(b'[]',TOKEN,100,110)
        self.assertEqual(out['signals'],[]);self.assertIn('unknown',out['causal_interpretation'])
    def test_outside_window_is_excluded(self):
        out=observer.sanitize_logs(json.dumps([self.sample()]).encode(),TOKEN,200,210)
        self.assertEqual(out['signals'],[]);self.assertEqual(out['discarded_timestamp'],1)
    def test_invalid_timezone_excluded(self):
        item=self.sample();item['timestamp']='1970-01-01 00:01:42'
        out=observer.sanitize_logs(json.dumps([item]).encode(),TOKEN,100,110)
        self.assertEqual(out['discarded_timestamp'],1)
    def test_foreign_process_excluded(self):
        item=self.sample();item.update(subsystem='private.application',processImagePath='/private/Unknown')
        self.assertEqual(observer.sanitize_logs(json.dumps([item]).encode(),TOKEN,100,110)['signals'],[])
    def test_bad_shape_and_cap(self):
        for raw in (b'{}',b'[]'+b' '*observer.LOG_CAP):
            with self.assertRaises(RuntimeError):observer.sanitize_logs(raw,TOKEN,100,110)

class FileTests(unittest.TestCase):
    def test_placeholder_and_incomplete_movie_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'video.mp4'
            for raw in (b'Unexpected Error: Finished test run with pending attachment.',struct.pack('>I4s',8,b'ftyp')):
                p.write_bytes(raw)
                with self.assertRaises(RuntimeError):observer.movie_structure(p)
    def test_finalized_structure_is_not_playback_proof(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'video.mp4';p.write_bytes(b''.join(struct.pack('>I4s',8,k) for k in (b'ftyp',b'mdat',b'moov')))
            row=observer.movie_structure(p)
            self.assertFalse(row['playback_verified']);self.assertFalse(row['boundary_visibility_verified'])
    def test_publication_rejects_symlink_and_oversize(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').write_bytes(b'123');(root/'link').symlink_to(root/'data')
            with self.assertRaises(OSError):entry.read_pinned(root/'link',8,lambda:None)
            with self.assertRaises(RuntimeError):entry.read_pinned(root/'data',2,lambda:None)
    def test_publication_detects_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data';p.write_bytes(b'abc');calls=0
            def check():
                nonlocal calls
                calls+=1
                if calls==2:p.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):entry.read_pinned(p,100,check)

class IntegrationContracts(unittest.TestCase):
    def test_prepare_wrapper_preserves_original_entire_argv_and_all_other_phases(self):
        obj=entry.ObservedRecovery.__new__(entry.ObservedRecovery)
        obj.host={'developer_dir':'/Applications/Xcode.app/Contents/Developer'}
        obj.owned=DEVICE;obj.out=Path('/owned/out');obj.candidate=Path('/owned/source');obj.folder_name='TripDocket-Recovery-'+TOKEN
        for phase in ('prepare','export','restore'):
            expected=entry.hosted.HostedRecovery.phase_argv(obj,phase)
            actual=obj.phase_argv(phase)
            self.assertEqual(actual[actual.index('--')+1:] if phase=='prepare' else actual,expected)
        self.assertEqual(entry.hosted.core.CAPS['phase_seconds'],600)
        self.assertEqual(entry.hosted.core.CAPS['total_seconds'],1500)
        self.assertEqual(entry.hosted.core.CAPS['cleanup_seconds'],120)
    def test_children_inherit_outer_group_and_only_xcode_gets_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            s=observer.Supervisor(DEVICE,TOKEN,Path(d)/'obs',[])
            child=SimpleNamespace(pid=55,stdout=Mock(),stderr=Mock())
            with patch.object(s,'save'),patch.object(s.selector,'register'),patch('os.set_blocking'),patch('subprocess.Popen',return_value=child) as spawn:
                s.spawn('xcode',['xcodebuild'])
                self.assertFalse(spawn.call_args.kwargs['start_new_session'])
                self.assertEqual(spawn.call_args.kwargs['env']['TEST_RUNNER_TRIPDOCKET_FILES_COMMIT_OBSERVATION'],'1')
            s.selector.close()
    def test_unknown_spawn_blocks_further_acquisition(self):
        with tempfile.TemporaryDirectory() as d:
            s=observer.Supervisor(DEVICE,TOKEN,Path(d)/'obs',[])
            with patch('subprocess.Popen',side_effect=OSError('synthetic')) as spawn:
                with self.assertRaises(OSError):s.spawn('xcode',['xcodebuild'])
                with self.assertRaises(RuntimeError):s.spawn('recorder',['simctl'])
                self.assertEqual(spawn.call_count,1)
            self.assertTrue(s.receipt['children']['xcode']['spawn_unknown']);s.selector.close()
    def test_existing_helper_and_core_pins_still_exact(self):
        for filename,expected in (('recovery_core.py',entry.hosted.CORE_SHA),('recovery_process.py',entry.hosted.core.HELPER_SHA)):
            self.assertEqual(hashlib.sha256((HERE/filename).read_bytes()).hexdigest(),expected)
    def test_swift_preserves_single_action_and_failure_before_capture(self):
        s=(HERE.parent/'UITests/BatchImportUITests.swift').read_text()
        part=s[s.index('func testRecoveryCreateOwnedFilesDestination'):s.index('private func presentRecoverySave')]
        self.assertEqual(part.count('create.element.tap()'),1)
        self.assertIn('onTimeout: (@MainActor () -> Void)? = nil',s)
        self.assertLess(s.index('onTimeout?()'),s.index('capture(app, message, springboard: springboard)'))
        self.assertIn('ContinuousClock.now.advanced(by: .seconds(15))',s)
        self.assertIn('inlineNames.count == 0 &&',part)
    def test_failures_cannot_be_converted_to_success_and_cleanup_always_runs(self):
        for code,diagnostics,outcome,expected in ((65,True,'postcondition_failed',65),(0,True,'postcondition_failed',70),(0,False,'postcondition_passed',70),(0,True,'postcondition_passed',0)):
            with tempfile.TemporaryDirectory() as d:
                s=observer.Supervisor(DEVICE,TOKEN,Path(d)/'obs',[]);s.markers=sequence(outcome)
                child=SimpleNamespace(returncode=code,poll=lambda:code)
                def video():s.receipt['video']['status']='structurally_finalized_pending_playback_review' if diagnostics else 'unavailable'
                def logs():s.receipt['native_logs']['status']='sanitized'
                with patch.object(s,'spawn',return_value=child),patch.object(s,'stop_video',side_effect=video),patch.object(s,'collect_logs',side_effect=logs),patch.object(s,'stop_child') as stop:
                    self.assertEqual(s.run(),expected);self.assertEqual(stop.call_count,3)
    def test_profile_gate_fails_before_any_device_setup(self):
        obj=entry.ObservedRecovery.__new__(entry.ObservedRecovery);obj.host={'xcode_version':'Xcode 99','sdk_version':'99'}
        with patch.object(entry.hosted.HostedRecovery,'discover_profile'):
            with self.assertRaises(RuntimeError):obj.discover_profile()

class StopContracts(unittest.TestCase):
    def test_polite_signal_then_bounded_kill_and_reap(self):
        with tempfile.TemporaryDirectory() as d:
            s=observer.Supervisor(DEVICE,TOKEN,Path(d)/'obs',[])
            clock=[0.0];signals=[];state=[None]
            child=SimpleNamespace(poll=lambda:state[0],send_signal=lambda sig:signals.append(sig),
                                  kill=lambda:(signals.append(signal.SIGKILL),state.__setitem__(0,-9)))
            s.children['recorder']=child;s.receipt['children']['recorder']={}
            def read(delay=.02,native=None):clock[0]+=delay
            with patch.object(s,'read',side_effect=read),patch('time.monotonic',side_effect=lambda:clock[0]):
                s.stop_child('recorder',signal.SIGINT,1.5)
            self.assertEqual(signals,[signal.SIGINT,signal.SIGKILL])
            self.assertTrue(s.receipt['children']['recorder']['leader_reaped'])
            self.assertLessEqual(clock[0],2.01);s.selector.close()
    def test_unreaped_child_is_never_reported_closed(self):
        with tempfile.TemporaryDirectory() as d:
            s=observer.Supervisor(DEVICE,TOKEN,Path(d)/'obs',[]);clock=[0.0]
            child=SimpleNamespace(poll=lambda:None,send_signal=lambda sig:None,kill=lambda:None)
            s.children['recorder']=child;s.receipt['children']['recorder']={}
            def read(delay=.02,native=None):clock[0]+=delay
            with patch.object(s,'read',side_effect=read),patch('time.monotonic',side_effect=lambda:clock[0]):
                with self.assertRaisesRegex(RuntimeError,'outer group cleanup'):
                    s.stop_child('recorder',signal.SIGINT,1.5)
            self.assertFalse(s.receipt['children']['recorder']['leader_reaped']);s.selector.close()

class PublicationContracts(unittest.TestCase):
    def setup_runner(self,root):
        obj=entry.ObservedRecovery.__new__(entry.ObservedRecovery)
        obj.out=root;obj.owned=DEVICE;obj.folder_name='TripDocket-Recovery-'+TOKEN
        obj.active={};obj.unknown_spawn=False;obj.timecheck=lambda:None
        obj.report={'commands':[{'id':'phase-prepare','stop':{'group_absent':True,'leader_reaped':True}}]}
        folder=root/'CommitObservation';folder.mkdir()
        data=b''.join(struct.pack('>I4s',8,k) for k in (b'ftyp',b'mdat',b'moov'))
        (folder/'boundary.mp4').write_bytes(data)
        (folder/'receipt.json').write_text(json.dumps({'owned_uuid':DEVICE,'run_token':TOKEN,
            'video':{'status':'structurally_finalized_pending_playback_review','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}))
        return obj
    def test_changed_video_after_move_is_never_exposed_to_upload(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();obj=self.setup_runner(root);original=Path.rename
            def rename(path,target):
                result=original(path,target)
                if path.name=='boundary.mp4':Path(target).write_bytes(b'mutated after move')
                return result
            with patch.object(entry.hosted.HostedRecovery,'run',return_value=0),patch.object(Path,'rename',rename),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(obj.run(),70)
            self.assertFalse((root/'CommitObservationPublic').exists())
    def test_receipt_write_failure_exposes_no_partial_video(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();obj=self.setup_runner(root);original=Path.open
            def open_file(path,*args,**kwargs):
                if path.parent.name=='CommitObservationStaging' and path.name=='receipt.json' and args and args[0]=='xb':
                    raise OSError('synthetic write failure')
                return original(path,*args,**kwargs)
            with patch.object(entry.hosted.HostedRecovery,'run',return_value=0),patch.object(Path,'open',open_file),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(obj.run(),70)
            self.assertFalse((root/'CommitObservationPublic').exists())
    def test_complete_set_publishes_together(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();obj=self.setup_runner(root)
            with patch.object(entry.hosted.HostedRecovery,'run',return_value=0):self.assertEqual(obj.run(),0)
            public=root/'CommitObservationPublic'
            self.assertEqual({p.name for p in public.iterdir()},{'receipt.json','boundary.mp4'})
            self.assertTrue(json.loads((public/'receipt.json').read_text())['outer_group_absence_verified'])
            self.assertFalse((root/'CommitObservationStaging').exists())
    def test_unresolved_parent_group_denies_publication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();obj=self.setup_runner(root);obj.report['commands'][0]['stop']['group_absent']=False
            with patch.object(entry.hosted.HostedRecovery,'run',return_value=1),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(obj.run(),1)
            self.assertFalse((root/'CommitObservationPublic').exists())

class PushSourceContracts(unittest.TestCase):
    def fixture(self,parents=None,tree=None,signed=True,message=None):
        tree=tree or 'a'*40
        parents=[entry.BASE_COMMIT] if parents is None else parents
        message=entry.expected_commit_message(tree) if message is None else message
        raw='tree '+tree+'\n'+''.join('parent '+p+'\n' for p in parents)
        raw+='author QA <qa@example.test> 1 +0000\ncommitter QA <qa@example.test> 1 +0000\n'
        if signed:raw+='gpgsig -----BEGIN SSH SIGNATURE-----\n synthetic-test-only\n -----END SSH SIGNATURE-----\n'
        raw+='\n'+message;encoded=raw.encode();sha=hashlib.sha1(b'commit '+str(len(encoded)).encode()+b'\0'+encoded).hexdigest()
        job={'GITHUB_EVENT_NAME':'push','GITHUB_REF':entry.DIAGNOSTIC_REF,'GITHUB_RUN_ATTEMPT':'1',
             'GITHUB_REPOSITORY':'4alvit/travel-documents-ios','GITHUB_SHA':sha}
        event={'repository':{'full_name':job['GITHUB_REPOSITORY']},'ref':entry.DIAGNOSTIC_REF,
               'created':True,'deleted':False,'forced':False,'before':'0'*40,'after':sha,
               'head_commit':{'id':sha,'message':message.rstrip('\n')}}
        return job,event,entry.hosted.parse_commit(raw,sha),raw
    def test_real_first_push_preserved_and_source_bound_without_claiming_review_verification(self):
        values=self.fixture();before=copy.deepcopy(values)
        result=entry.diagnostic_source_context(*values)
        self.assertEqual(values,before);self.assertEqual(result['kind'],'push')
        self.assertEqual(result['checkout']['parents'],[entry.BASE_COMMIT])
        self.assertFalse(result['diagnostic_source_binding']['signature_cryptographically_verified_here'])
        self.assertNotIn('review_verified',json.dumps(result))
    def test_job_event_ref_attempt_repository_sha_mismatch_denied(self):
        for field,bad in [('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/heads/main'),
                          ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_RUN_ATTEMPT','01'),
                          ('GITHUB_REPOSITORY','elsewhere/repo'),('GITHUB_SHA','b'*40),('GITHUB_SHA','')]:
            with self.subTest(field=field,bad=bad):
                job,event,commit,raw=self.fixture();job[field]=bad
                with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw)
    def test_event_heads_and_ref_must_match(self):
        for field in ('ref','after','before'):
            job,event,commit,raw=self.fixture();event[field]='wrong'
            with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw)
        for value in ('b'*40,None):
            job,event,commit,raw=self.fixture();event['head_commit']['id']=value
            with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw)
    def test_missing_or_wrongly_typed_booleans_denied(self):
        for field,expected in [('created',True),('deleted',False),('forced',False)]:
            for value in (None,'true','false',int(expected),not expected):
                job,event,commit,raw=self.fixture();event[field]=value
                with self.subTest(field=field,value=value),self.assertRaises(RuntimeError):
                    entry.diagnostic_source_context(job,event,commit,raw)
            job,event,commit,raw=self.fixture();del event[field]
            with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw)
    def test_update_instead_of_new_branch_denied(self):
        job,event,commit,raw=self.fixture();event.update(created=False,before=entry.BASE_COMMIT)
        with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw)
    def test_exact_single_parent_required(self):
        for parents in ([],['b'*40],[entry.BASE_COMMIT,'b'*40]):
            with self.assertRaises(RuntimeError):entry.diagnostic_source_context(*self.fixture(parents=parents))
    def test_unsigned_or_raw_tampered_commit_denied(self):
        with self.assertRaises(RuntimeError):entry.diagnostic_source_context(*self.fixture(signed=False))
        job,event,commit,raw=self.fixture()
        with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw+'x')
    def test_trailer_mismatch_duplicate_or_extra_text_denied(self):
        good=entry.expected_commit_message('a'*40)
        for bad in (entry.expected_commit_message('b'*40),good+'TripDocket-Reviewed-Tree: '+'a'*40+'\n',good+'extra\n',good.replace(entry.BASE_COMMIT,'b'*40)):
            with self.assertRaises(RuntimeError):entry.diagnostic_source_context(*self.fixture(message=bad))
    def test_event_message_cannot_substitute_signed_message(self):
        job,event,commit,raw=self.fixture();event['head_commit']['message']+='changed'
        with self.assertRaises(RuntimeError):entry.diagnostic_source_context(job,event,commit,raw)
    def test_default_hook_retains_original_event_validator(self):
        job,event,commit,raw=self.fixture()
        parent=entry.hosted.HostedRecovery.__new__(entry.hosted.HostedRecovery);parent.job=job;parent.event=event
        with self.assertRaises(RuntimeError):parent.source_context(commit,raw)
        for kind in ('workflow_dispatch','push','merge_group','pull_request'):
            parent.job={**job,'GITHUB_EVENT_NAME':kind,'GITHUB_REF':'refs/heads/main'}
            parent.event={**event,'merge_group':{'head_sha':commit['commit'],'base_sha':entry.BASE_COMMIT},
                          'number':1,'pull_request':{'head':{'sha':'b'*40,'repo':{'full_name':job['GITHUB_REPOSITORY']}},'base':{'sha':entry.BASE_COMMIT}}}
            candidate=copy.deepcopy(commit)
            if kind=='pull_request':candidate['parents']=[entry.BASE_COMMIT,'b'*40]
            self.assertEqual(parent.source_context(candidate,raw),entry.hosted.source_event(parent.job,parent.event,candidate))
    def test_bad_event_denied_before_source_commands(self):
        job,event,commit,raw=self.fixture();event['created']=False
        obj=entry.ObservedRecovery.__new__(entry.ObservedRecovery);obj.job=job;obj.event=event
        with patch.object(entry.hosted.HostedRecovery,'capture_source') as parent:
            with self.assertRaises(RuntimeError):obj.capture_source()
            parent.assert_not_called()

if __name__=='__main__':unittest.main()
