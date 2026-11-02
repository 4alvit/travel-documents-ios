#!/usr/bin/env python3
"""Offline actual-protocol/host guards; no Simulator or app is launched."""
import copy, hashlib, importlib.util, itertools, json, os, subprocess, sys
from pathlib import Path
import tempfile, time, unittest, uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

def load(name,file):
 s=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
q=load('checkpoint_q','qualify-release.py');cp=q.checkpoint
SESSION='11111111-1111-4111-8111-111111111111';TOKEN='22222222-2222-4222-8222-222222222222';NONCE='33333333-3333-4333-8333-333333333333'
OWNED='44444444-4444-4444-8444-444444444444'

def lines():
 result=[]
 for i,test in enumerate(cp.TESTS):
  target,cls,method=test.split('/');prefix=f"Test Case '-[{target}.{cls} {method}]' "
  result.append(prefix+'started.')
  if i==1:result.append(f'{cp.PREFIX} {SESSION} {TOKEN} {NONCE}')
  result.append(prefix+'passed (1.000 seconds).')
 return result

def raw(value=None):return ('\n'.join(lines() if value is None else value)+'\n').encode()

def preparation_lines():
 result=[]
 for test in cp.PREPARATION_TESTS:
  target,cls,method=test.split('/');prefix=f"Test Case '-[{target}.{cls} {method}]' "
  result.extend([prefix+'started.',prefix+'passed (1.000 seconds).'])
 return result

class PreparationOrderGuards(unittest.TestCase):
 def test_exact_pair_and_log_binding(self):
  data=raw(preparation_lines());proof=cp.preparation_order(data)
  self.assertEqual(proof['schema_version'],2)
  self.assertEqual([x['case'] for x in proof['events']], [x for c in cp.PREPARATION_CASES for x in (c,c)])
  self.assertEqual([x['event'] for x in proof['events']],['started','passed','started','passed'])
  self.assertEqual(proof['log'],{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 def test_every_incomplete_duplicate_or_reordered_pair_rejects(self):
  good=preparation_lines()
  bad=[good[:i]+good[i+1:] for i in range(4)]+[good[:i]+[good[i]]+good[i:] for i in range(4)]
  bad.extend(list(p) for p in itertools.permutations(good) if list(p)!=good)
  for value in bad:
   with self.subTest(value=value),self.assertRaises(RuntimeError):cp.preparation_order(raw(value))
 def test_wrong_failed_skipped_malformed_or_overlong_case_rejects(self):
  good=preparation_lines();bad=[]
  for i in (1,3):
   for replacement in ('failed (1.000 seconds).','skipped (1.000 seconds).','passed (nan seconds).','passed (-1 seconds).'):
    bad.append(good[:i]+[good[i].split('passed')[0]+replacement]+good[i+1:])
   value=good.copy();value[i]=value[i].replace('1.000','300.001' if i==1 else '180.001');bad.append(value)
  bad += [good+lines()[:1],lines()[:1]+good,good+[f'{cp.PREFIX} {SESSION} {TOKEN} {NONCE}'],good+["Test Case '-[Other.Suite testUnexpected]' passed (1.000 seconds)."]]
  for value in bad:
   with self.subTest(value=value),self.assertRaises(RuntimeError):cp.preparation_order(raw(value))
  for data in (b'',b'x'*(cp.MAX_LOG+1),b'x'*(cp.MAX_LINE+1)+b'\n'+raw(good),b'\xff'+raw(good),b'\0'+raw(good)):
   with self.assertRaises((RuntimeError,UnicodeError)):cp.preparation_order(data)
 def test_previous_single_preparation_is_not_accepted(self):
  with self.assertRaises(RuntimeError):cp.preparation_order(raw(preparation_lines()[2:]))

class ProtocolGuards(unittest.TestCase):
 def test_exact_order_and_marker(self):
  x=cp.execution_order(raw(),SESSION,TOKEN)
  self.assertEqual(len(x['events']),4);self.assertEqual(x['request']['nonce'],NONCE)
  self.assertEqual(x['schema_version'],2)
  self.assertTrue(x['strict_observed_order'])
 def test_bad_order_duplicates_foreign_and_missing_markers_reject(self):
  good=lines()
  cases=[good[:2]+[good[3],good[2]]+good[4:],good[:3]+good[4:],good+[good[3]],good[:2]+[good[0]]+good[2:],good[:1]+good[2:],good[::-1],good[:3]+[good[3].replace(SESSION,NONCE)]+good[4:],good[:3]+[good[3].lower()]+good[4:],good[:1]+[good[1].replace('1.000','180.001')]+good[2:],good[:4]+[good[4].replace('1.000','600.001')],preparation_lines()[:2]+good,good+preparation_lines()[2:]]
  for x in cases:
   with self.subTest(x=x),self.assertRaises((RuntimeError,ValueError)):cp.execution_order(raw(x),SESSION,TOKEN)
 def test_bounded_input_and_native_failure(self):
  for data in (b'',b'x'*(cp.MAX_LOG+1),b'x\0',b'\xff'):
   with self.assertRaises((RuntimeError,UnicodeError)):cp.execution_order(data,SESSION,TOKEN)
  with self.assertRaises(cp.NativeCaseFailed):cp.execution_order(raw([*lines()[:1],lines()[1].replace('passed','failed')]),SESSION,TOKEN)
 def monitor(self,path,*,code=0,callback=None,now=None):
  process=SimpleNamespace(poll=Mock(side_effect=[None,code]),wait=Mock(return_value=code))
  return cp.monitor(process,path,50,SESSION,TOKEN,callback or Mock(),started=0,now=now or (lambda:1),sleep=lambda _:None)
 def test_actual_tail_calls_once_and_returns_native_status(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(raw());callback=Mock()
   self.assertEqual(self.monitor(p,callback=callback)["returncode"],0);callback.assert_called_once()
 def test_native_failure_preserves_terminal_exit_without_ack(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(raw([lines()[0],lines()[1].replace('passed','failed')]))
   callback=Mock();process=SimpleNamespace(poll=lambda:65,wait=lambda **_:65)
   self.assertEqual(cp.monitor(process,p,50,SESSION,TOKEN,callback,started=0,now=lambda:1)["returncode"],65);callback.assert_not_called()
 def test_expired_deadline_late_callback_and_symlink_reject(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(raw())
   with self.assertRaisesRegex(RuntimeError,'deadline'):self.monitor(p,now=lambda:51)
   clock=[1]
   with self.assertRaisesRegex(RuntimeError,'transport'):self.monitor(p,now=lambda:clock[0],callback=lambda *_:clock.__setitem__(0,70))
   link=Path(td)/'link';link.symlink_to(p)
   with self.assertRaises(RuntimeError):self.monitor(link)

 def test_actual_benign_child_tail_and_owned_cleanup(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';callback=Mock()
   with p.open('wb') as stream:
    started=time.monotonic()
    child=subprocess.Popen([sys.executable,'-c',"import sys,time;sys.stdout.write("+repr(raw().decode())+");sys.stdout.flush();time.sleep(.2)"],stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    try:
     result=cp.monitor(child,p,started+5,SESSION,TOKEN,callback,started=started)
     self.assertEqual(result['returncode'],0);callback.assert_called_once();self.assertIsNotNone(child.poll())
    finally:
     if child.poll() is None:child.kill()
     child.wait(timeout=2)
 def test_seed_envelope_includes_startup_before_any_test(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(b'');clock=[1.]
   child=SimpleNamespace(poll=lambda:None)
   def sleep(_):clock[0]+=301
   with self.assertRaisesRegex(RuntimeError,'Seed stage'):
    cp.monitor(child,p,1000,SESSION,TOKEN,Mock(),started=0,now=lambda:clock[0],sleep=sleep)
 def test_delayed_monitor_entry_does_not_restart_seed_allowance(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(raw());callback=Mock()
   for current in (300,301):
    with self.subTest(current=current),self.assertRaisesRegex(RuntimeError,'Seed stage'):
     cp.monitor(SimpleNamespace(poll=lambda:None),p,1000,SESSION,TOKEN,callback,started=0,now=lambda:current)
   callback.assert_not_called()
 def test_invalid_or_future_start_rejects_before_ack(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(raw());callback=Mock()
   for start in (None,True,float('nan'),float('inf'),2):
    with self.subTest(start=start),self.assertRaises(RuntimeError):
     cp.monitor(SimpleNamespace(poll=lambda:None),p,1000,SESSION,TOKEN,callback,started=start,now=lambda:1)
   callback.assert_not_called()
 def test_chunk_cannot_clear_expired_seed_envelope(self):
  for crossing in (0,1):
   with self.subTest(crossing=crossing),tempfile.TemporaryDirectory() as td:
    p=Path(td)/'log';p.write_bytes(raw());clock=[0.]
    original=cp.Transcript.line
    def line(parser,data):
     result=original(parser,data)
     if data.decode()==lines()[crossing]:clock[0]=301.
     return result
    child=SimpleNamespace(poll=Mock(side_effect=[None,0]),wait=lambda **_:0)
    with patch.object(cp.Transcript,'line',line),self.assertRaisesRegex(RuntimeError,'Seed stage'):
     cp.monitor(child,p,1000,SESSION,TOKEN,Mock(),started=0,now=lambda:clock[0])
 def test_terminal_wait_cannot_return_success_past_original_deadline(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log';p.write_bytes(raw());clock=[1.]
   def wait(**_):clock[0]=51.;return 0
   child=SimpleNamespace(poll=Mock(side_effect=[None,0]),wait=wait)
   with self.assertRaisesRegex(RuntimeError,'deadline'):
    cp.monitor(child,p,50,SESSION,TOKEN,Mock(),started=0,now=lambda:clock[0])
 def test_combined_actual_driver_uses_exact_ui_pair_and_existing_limits(self):
  d=load('checkpoint_driver','test-batch-simulator.py')
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();derived=root/'build/Shared';derived.mkdir(parents=True)
   run=d.Driver.__new__(d.Driver);run.root=run.directory=root;run.qualified_build=derived
   run.args=SimpleNamespace(device=OWNED,native_root=True,native_seed=True,combined_batch=True)
   run.token=TOKEN;run.folder_name='TripDocket-Batch-QA-'+TOKEN;run.deadline=time.monotonic()+5
   run.summary={'result_bundle':str(root/'Tests.xcresult')};run.save=Mock();run.record=Mock();run.native_root_identity=Mock();run.remaining=lambda:5
   run.combined_protocol=cp;run.checkpoint_session=SESSION;run.checkpoint_callback=Mock()
   result={'result':'Passed','totalTestCount':2,'passedTests':2,'failedTests':0,'skippedTests':0,'expectedFailures':0,'devicesAndConfigurations':[{'device':{'deviceId':OWNED}}]}
   tree={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':case,'result':'Passed'} for case in cp.CASES],'devices':[{'deviceId':OWNED,'platform':'iOS Simulator'}]}
   run.command=lambda *a:json.dumps({'summary':result,'tests':tree}[a[4]]).encode()
   child=SimpleNamespace(poll=Mock(side_effect=[None,0]),wait=Mock(return_value=0))
   def spawn(argv,**kwargs):kwargs['stdout'].write(raw());kwargs['stdout'].flush();return child
   with patch.object(d.subprocess,'Popen',side_effect=spawn) as call,patch('builtins.print'):run.run_test()
   argv=call.call_args.args[0];env=call.call_args.kwargs['env']
   self.assertEqual([x for x in argv if x.startswith('-only-testing:')],['-only-testing:'+x for x in cp.TESTS])
   self.assertEqual(argv[-1],'test-without-building');self.assertEqual(argv[argv.index('-maximum-test-execution-time-allowance')+1],'600')
   self.assertEqual(env['TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_TOKEN'],TOKEN);self.assertEqual(env['TEST_RUNNER_TRIPDOCKET_BATCH_CHECKPOINT_SESSION'],SESSION)
   self.assertEqual(run.summary['execution_order'],cp.execution_order(raw(),SESSION,TOKEN))
   run.checkpoint_callback.assert_called_once()
   result.update(totalTestCount=1,passedTests=1)
   with self.assertRaisesRegex(RuntimeError,'both exact'):run.validate_result()

class HostGuards(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
  env={'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_WORKFLOW':'Release qualification','GITHUB_JOB':'qualify','GITHUB_REPOSITORY':'4alvit/travel-documents-ios','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'12','GITHUB_RUN_ATTEMPT':'1'}
  self.run=q.Qualification(self.root,'batch',env);r=self.run;r.owned=OWNED;r.baseline={};r.driver_calls=1
  self.preparation_proof={'order':cp.preparation_order(raw(preparation_lines())), 'original_manifest_sha256':'c'*64,'summary_sha256':'d'*64,'tests_sha256':'e'*64}
  r.verify_preparation_prerequisite=Mock(return_value=copy.deepcopy(self.preparation_proof))
  r.report['combined_batch']={'preparation_prerequisite':copy.deepcopy(self.preparation_proof)}
  p=SimpleNamespace(pid=123,poll=lambda:None);r.xcode.active={123:p}
  self.driver=SimpleNamespace(process=p,args=SimpleNamespace(device=OWNED),checkpoint_session=SESSION,token=TOKEN,deadline=time.monotonic()+60,summary={'combined_batch':True,'fixtures':[{'name':'synthetic-ticket.pdf','bytes':713,'sha256':'a'*64},{'name':'synthetic-insurance.pdf','bytes':716,'sha256':'b'*64}]},fixture_directory=self.root/'provider',provider_identity=(1,2))
  self.bundle=self.root/'Tripfolio.app';self.bundle.mkdir();(self.bundle/'Tripfolio').write_bytes(b'executable')
  r.container_path=Mock(return_value=self.bundle);r.native_seed_files=Mock();r.before={'files':{}}
  self.commands=[];self.listing='999 /bin/ps -axww -o pid=,command=\n123 /usr/bin/xcodebuild\n'
  def command(label,argv,seconds):
   if label=='checkpoint-ack':
    proof=json.loads((r.out/'receipt.json').read_text())['batch_checkpoint']
    self.assertTrue(proof['aut_stopped']);self.assertTrue(proof['source_unchanged'])
    self.assertEqual(proof['status'],'verifying');self.assertEqual(proof['fixtures'],self.driver.summary['fixtures'])
   self.commands.append((label,argv,seconds));r.commands.report['commands'].append({'id':label,'returncode':0,'pgid':999})
   return str(self.bundle) if label=='checkpoint-app' else self.listing if label=='checkpoint-app-stopped' else ''
  r.command=command;self.request=cp.execution_order(raw(),SESSION,TOKEN)['request']
 def invoke(self):return self.run.acknowledge_batch_seed(self.driver,self.request,time.monotonic()+60)
 def test_ack_requires_stopped_app_bytes_and_clips_scoped_commands(self):
  limit=self.run.commands.limit;self.invoke()
  self.assertEqual([x[0] for x in self.commands],['checkpoint-app','checkpoint-app-stopped','checkpoint-ack'])
  self.run.verify_preparation_prerequisite.assert_called_once()
  call=self.run.verify_preparation_prerequisite.call_args
  self.assertEqual(call.args,());self.assertEqual(set(call.kwargs),{'check'})
  self.assertTrue(callable(call.kwargs['check']))
  self.run.native_seed_files.assert_called_once_with(self.driver)
  self.assertTrue(self.run.report['batch_checkpoint_verified']);self.assertEqual(limit,self.run.commands.limit)
  self.assertTrue(all(0<x[2]<=10 for x in self.commands));self.assertEqual(self.commands[-1][1],['xcrun','simctl','notify_set_state',OWNED,self.request['name'],'1'])
 def test_running_missing_reader_and_ambiguous_process_reject_before_ack(self):
  old=Path.home()/'Library/Developer/CoreSimulator/Devices'/OWNED/'data/Containers/Bundle/Application'/NONCE/'Tripfolio.app/Tripfolio'
  for text in ('','123 /usr/bin/xcodebuild\n',self.listing+f'42 {self.bundle}/Tripfolio\n',self.listing+f'42 {old} --old-container\n',self.listing+'42 Tripfolio --arg\n','malformed'):
   self.run.report.pop('batch_checkpoint',None);self.listing=text;self.commands.clear();self.run.commands.report['commands'].clear()
   with self.subTest(text=text),self.assertRaises(RuntimeError):self.invoke()
   self.assertNotIn('checkpoint-ack',[x[0] for x in self.commands])
 def test_failed_or_changed_preparation_never_sends_ack(self):
  for failure in ('reader','changed'):
   self.commands.clear();self.run.report.pop('batch_checkpoint',None)
   self.run.verify_preparation_prerequisite.reset_mock(side_effect=True)
   if failure=='reader':self.run.verify_preparation_prerequisite.side_effect=RuntimeError('changed preparation bytes')
   else:self.run.verify_preparation_prerequisite.return_value={**self.preparation_proof,'summary_sha256':'f'*64}
   with self.subTest(failure=failure),self.assertRaises(RuntimeError):self.invoke()
   self.assertEqual(self.commands,[])
 def test_preparation_recheck_uses_active_checkpoint_deadline(self):
  initial=time.monotonic();clock=[initial]
  def verify(*,check):
   check();clock[0]=initial+61;check()
   return copy.deepcopy(self.preparation_proof)
  self.run.verify_preparation_prerequisite.side_effect=verify
  with patch.object(q.time,'monotonic',side_effect=lambda:clock[0]):
   with self.assertRaisesRegex(RuntimeError,'Checkpoint primary/clock changed'):
    self.run.acknowledge_batch_seed(self.driver,self.request,initial+60)
  self.assertEqual(self.commands,[])
  self.assertNotIn('batch_checkpoint_verified',self.run.report)
 def test_wrong_owner_and_unknown_writer_never_start(self):
  for fault in ('device','primary','auxiliary','unknown'):
   r=self.run;old=self.driver.args.device
   if fault=='device':self.driver.args.device=TOKEN
   if fault=='primary':r.xcode.active={}
   if fault=='auxiliary':r.commands.active={99:object()}
   if fault=='unknown':r.xcode.unknown_spawn=True
   with self.subTest(fault=fault),self.assertRaises(RuntimeError):self.invoke()
   self.assertEqual(self.commands,[])
   self.driver.args.device=old;r.xcode.active={123:self.driver.process};r.commands.active={};r.xcode.unknown_spawn=False
 def test_changed_source_or_bytes_withhold_ack_and_restore_limit(self):
  r=self.run;limit=r.commands.limit;r.native_seed_files.side_effect=RuntimeError('changed bytes')
  with self.assertRaisesRegex(RuntimeError,'changed bytes'):self.invoke()
  self.assertEqual(r.commands.limit,limit);self.assertNotIn('checkpoint-ack',[x[0] for x in self.commands])
  r.report.pop('batch_checkpoint');r.commands.report['commands'].clear();self.commands.clear();r.native_seed_files.side_effect=None
  (self.root/'source').write_bytes(b'changed');r.before={'files':{'source':{'bytes':3,'sha256':'a'*64,'executable':False}}}
  with self.assertRaisesRegex(RuntimeError,'Source changed'):self.invoke()
  self.assertNotIn('checkpoint-ack',[x[0] for x in self.commands])
 def test_duplicate_and_mismatched_request_reject(self):
  self.invoke()
  with self.assertRaises(RuntimeError):self.invoke()
  self.request['token']=NONCE
  with self.assertRaises(RuntimeError):self.invoke()
 def test_failed_proof_persistence_sends_no_ack(self):
  self.run.save=Mock(side_effect=OSError('proof write failed'))
  with self.assertRaisesRegex(OSError,'proof write failed'):self.invoke()
  self.assertNotIn('checkpoint-ack',[x[0] for x in self.commands])
  self.assertNotIn('batch_checkpoint_verified',self.run.report)
 def test_expired_checkpoint_never_invokes_rpc(self):
  with self.assertRaises(RuntimeError):self.run.acknowledge_batch_seed(self.driver,self.request,time.monotonic()-1)
  self.assertEqual(self.commands,[])

if __name__=='__main__':unittest.main()
