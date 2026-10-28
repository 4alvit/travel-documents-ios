"""Injected driver regressions. Never start a native child or send a real signal."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ipad_driver', HERE/'test-privacy-support-ipad.py')
ipad = importlib.util.module_from_spec(spec)
with patch('subprocess.Popen') as spawn, patch('os.killpg') as kill:
    spec.loader.exec_module(ipad)
    spawn.assert_not_called(); kill.assert_not_called()


class Process:
    def __init__(self, world, plan):
        self.world, self.plan = world, plan
        self.pid, self.started = 101 + len(world.processes), world.t
        self.returncode, self.dead, self.polls = None, False, 0

    def poll(self):
        self.polls += 1
        self.world.calls.append(('poll', self.world.t))
        error = self.plan.get('poll_errors', {}).get(self.polls)
        if error:
            raise error
        if self.dead or self.world.t - self.started >= self.plan.get('delay', 0):
            self.returncode = -15 if self.dead else self.plan.get('exit', 0)
        return self.returncode


class World:
    def __init__(self, **plan):
        self.t, self.plan, self.processes, self.calls = 0., plan, [], []
        self.on_spawn, self.on_probe = None, None
        self.probes = 0

    def clock(self):
        return self.t

    def sleep(self, seconds):
        assert seconds >= 0
        self.t += seconds

    def spawn(self, argv, **kwargs):
        assert kwargs['start_new_session'] is True
        self.calls.append(('spawn', self.t))
        process = Process(self, self.plan)
        self.processes.append(process)
        kwargs['stdout'].write(self.plan.get('output', b'')); kwargs['stdout'].flush()
        if self.on_spawn:
            self.on_spawn()
        return process

    def killpg(self, pid, sig):
        self.calls.append(('probe' if sig == 0 else 'signal_' + str(int(sig)), self.t))
        process = next(p for p in self.processes if p.pid == pid)
        if sig == 0:
            self.probes += 1
            if self.on_probe:
                self.on_probe()
            if self.probes in self.plan.get('probe_errors', {}):
                raise self.plan['probe_errors'][self.probes]
            if self.plan.get('probe_error'):
                raise self.plan['probe_error']
            if process.dead or process.returncode is not None and not self.plan.get('lingering'):
                raise ProcessLookupError(errno.ESRCH, 'gone')
        else:
            if self.plan.get('signal_error'):
                raise self.plan['signal_error']
            if self.plan.get('signal_esrch'):
                process.dead = True
                raise ProcessLookupError(errno.ESRCH, 'gone during signal')
            if not self.plan.get('ignore_all') and (sig == signal.SIGKILL or not self.plan.get('ignore_term')):
                process.dead = True
            self.t += self.plan.get('signal_seconds', 0)


class DriverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='trip-ipad-injected-')
        self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.guards = []
        for name in ['subprocess.Popen', 'os.killpg', 'os.kill', 'os.system']:
            guard = patch(name, side_effect=AssertionError('NO NATIVE EXECUTION'))
            self.guards.append(guard.start()); self.addCleanup(guard.stop)

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def driver(self, locale="en-US", **plan):
        world = World(**plan)
        for name, value in [('time.monotonic', world.clock), ('time.sleep', world.sleep),
                            ('subprocess.Popen', world.spawn), ('os.killpg', world.killpg)]:
            injected = patch(name, side_effect=value)
            injected.start(); self.addCleanup(injected.stop)
        return ipad.Driver(self.root, locale), world

    def row(self, driver):
        return driver.report['commands'][-1]

    def assert_finished(self, driver):
        row = self.row(driver)
        self.assertIn('finish', row)
        stored = json.loads((driver.out/'run-summary.json').read_text())
        self.assertEqual(stored['commands'][-1], row)

    def attempted_case(self, index, **plan):
        case = ipad.CASES[index]; locale, method, size, _ = case
        driver, world = self.driver(locale=locale, **plan)
        driver.owned = 'synthetic-owned-device'
        driver.products = {'aut':self.root/'Synthetic.app','xctestrun':self.root/'synthetic.xctestrun'}
        (driver.out/'originals'/(locale+'.xcresult')).mkdir(parents=True)
        actual = driver.command
        def command(argv, label, **kwargs):
            if label == locale+'-test':
                return actual(argv, label, **kwargs)
            return 0, size if label == locale+'-read-size' else ''
        with patch.object(driver,'command',side_effect=command), \
             patch.object(driver,'product_snapshot'), \
             patch.object(driver,'installed',return_value={'available':True}), \
             patch.object(driver,'parse_case',side_effect=RuntimeError('Synthetic result validation withheld')) as validate:
            with self.assertRaises(RuntimeError) as failure:driver.run_case(*case)
        self.assertEqual(len(world.processes),1)
        self.assertFalse(driver.active)
        self.assertEqual(driver.report['cases'][0]['status'],'started')
        self.assertEqual(self.row(driver)['argv'][-1],
            '-only-testing:TripfolioUITests/PrivacySupportUITests/'+method)
        return driver,world,failure.exception,validate.called

    def test_selected_locale_is_required_and_invalid_locale_creates_no_output(self):
        with self.assertRaises(TypeError): ipad.Driver(self.root)
        with self.assertRaisesRegex(RuntimeError, 'Exactly one supported locale'): ipad.Driver(self.root, 'all')
        self.assertFalse((self.root/'build').exists())

    def test_fresh_locale_driver_runs_exactly_one_case_and_requires_its_success(self):
        for locale in ('en-US', 'ru-RU'):
            with self.subTest(locale=locale):
                driver, world = self.driver(locale=locale)
                def passed(*case):
                    self.assertEqual(case, driver.case)
                    driver.report['cases'].append(dict(locale=case[0],method=case[1],status='passed'))
                def cleanup(): driver.report['cleanup']['verified']=True
                with patch('signal.signal'), patch.object(driver,'prepare'), patch.object(driver,'build_once'), \
                     patch.object(driver,'run_case',side_effect=passed) as case_run, \
                     patch.object(driver,'cleanup',side_effect=cleanup), patch.object(driver,'final_evidence'), patch('builtins.print'):
                    self.assertEqual(driver.run(),0)
                case_run.assert_called_once_with(*driver.case)
                self.assertEqual(driver.report['selected_locale'],locale)
                self.assertEqual(driver.report['expected_case_count'],1)
                self.assertEqual(driver.out,self.root.resolve()/'build/PrivacySupport-iPad'/locale)
                self.assertEqual(driver.derived,self.root.resolve()/('build/PrivacySupport-iPad-DerivedData-'+locale))
                self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))
                self.assertEqual(world.processes,[])

    def test_observed_RU_remaining357_is_not_admitted_or_spawned(self):
        driver,world=self.driver(locale='ru-RU');world.t=1076.561
        with patch.object(driver,'product_snapshot') as snapshot:
            with self.assertRaisesRegex(RuntimeError,'lacks full case/post-validation budget'):
                driver.run_case(*driver.case)
        snapshot.assert_not_called();self.assertEqual(world.processes,[])
        self.assertEqual(driver.report['cases'][0]['status'],'not_admitted')
        self.assertEqual(driver.report['cases'][0]['admission']['required_seconds'],956)
        with self.assertRaisesRegex(RuntimeError,'no retry'):driver.run_case(*driver.case)

    def test_full_case_admission_rejects_exact_boundary(self):
        driver,world=self.driver()
        required=ipad.CASE_PREP_SECONDS+driver.case[3]+7+ipad.CASE_POST_SECONDS
        self.assertEqual(required,986);world.t=1440-required
        with self.assertRaisesRegex(RuntimeError,'no case started'):driver.run_case(*driver.case)
        self.assertEqual(world.processes,[]);self.assertEqual(driver.report['cases'][0]['status'],'not_admitted')

    def test_actual_test_command_rechecks_full_wait_stop_and_post_budget_before_spawn(self):
        driver,world=self.driver(delay=1)
        world.t=1440-570-7-ipad.CASE_POST_SECONDS
        with self.assertRaisesRegex(RuntimeError,'no test spawned'):
            driver.command(['synthetic'],'ru-RU-test',timeout=570,required_after=ipad.CASE_POST_SECONDS)
        self.assertEqual(world.processes,[])
        world.t-=1
        driver.command(['synthetic'],'ru-RU-test',timeout=570,required_after=ipad.CASE_POST_SECONDS)
        self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'],world.processes[0].started+570)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))

    def test_case_does_not_accept_a_different_locale_or_case(self):
        driver,world=self.driver()
        with self.assertRaisesRegex(RuntimeError,'differs from selected locale'):driver.run_case(*ipad.CASES[1])
        self.assertEqual(driver.report['cases'],[]);self.assertEqual(world.processes,[])

    def post_failure_case(self, **process_plan):
        driver,world=self.driver(**process_plan);case=driver.case;locale,method,size,_=case
        driver.owned='synthetic-owned-device';driver.products={'aut':self.root/'Synthetic.app','xctestrun':self.root/'synthetic.xctestrun'}
        actual=driver.command
        def command(argv,label,**kwargs):
            if label==locale+'-test':return actual(argv,label,**kwargs)
            return 0,size if label==locale+'-read-size' else ''
        def installed(label,required=False):
            if label.endswith('/installed-after'):raise RuntimeError('Synthetic installed-after budget exhausted')
            return {'available':True}
        with patch.object(driver,'command',side_effect=command), patch.object(driver,'product_snapshot'), \
             patch.object(driver,'installed',side_effect=installed), patch.object(driver,'parse_case') as parse:
            with self.assertRaises(RuntimeError) as raised:driver.run_case(*case)
        parse.assert_not_called();self.assertFalse(driver.active)
        self.assertEqual(len(world.processes),1)
        self.assertEqual(driver.report['cases'][0]['post_validation_errors'],[
            {'stage':'installed-after','error':"RuntimeError('Synthetic installed-after budget exhausted')"}])
        return driver,str(raised.exception)

    def test_timeout_primary_survives_secondary_post_lookup_error(self):
        driver,error=self.post_failure_case(delay=float('inf'))
        self.assertIn('en-US-test exceeded its finite timeout',error)
        self.assertIn('finite timeout',driver.report['cases'][0]['primary_error'])
        self.assertEqual(driver.report['cases'][0]['status'],'started')

    def test_nonzero_primary_survives_secondary_post_lookup_error(self):
        driver,error=self.post_failure_case(exit=65)
        self.assertIn('xcodebuild failed',error)
        self.assertEqual(driver.report['cases'][0]['xcodebuild_exit_code'],65)

    def test_success_cannot_override_mandatory_post_validation_failure(self):
        driver,error=self.post_failure_case(exit=0)
        self.assertEqual(error,'Synthetic installed-after budget exhausted')
        self.assertEqual(driver.report['cases'][0]['status'],'started')

    def test_ci_fixed_two_locale_matrix_serializes_ipads_and_gates_both(self):
        workflow=(HERE.parent/'.github/workflows/ci.yml').read_text()
        lane=workflow.split('  privacy_ipad:',1)[1].split('  recovery:',1)[0]
        self.assertIn('fail-fast: false',lane);self.assertIn('max-parallel: 1',lane)
        self.assertIn('locale: [en-US, ru-RU]',lane)
        self.assertIn('name: iPad privacy and support (${{ matrix.locale }})',lane)
        self.assertIn("run: bash scripts/test-privacy-support-ipad.sh --locale '${{ matrix.locale }}'",lane)
        self.assertIn('name: TripDocket-privacy-ipad-${{ matrix.locale }}-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}',lane)
        self.assertIn('path: build/PrivacySupport-iPad/${{ matrix.locale }}/',lane)
        self.assertIn('timeout-minutes: 35',lane);self.assertIn('timeout-minutes: 29',lane)
        gate=workflow.split('  gate:',1)[1]
        self.assertIn('if: always()',gate);self.assertIn('needs: [validate, privacy_ipad, recovery]',gate)
        self.assertIn('IPAD_RESULT: ${{ needs.privacy_ipad.result }}',gate)
        self.assertIn('test "$IPAD_RESULT" = success',gate)
        self.assertIn('exec python3 scripts/test-privacy-support-ipad.py "$@"',(HERE/'test-privacy-support-ipad.sh').read_text())

    def installed_fixture(self, **plan):
        driver,world=self.driver(**plan)
        driver.owned='synthetic-owned-device'
        (driver.out/'commands').mkdir()
        built=self.root/'built/Tripfolio.app';fresh=self.root/'installed/Tripfolio.app'
        for app in (built,fresh):
            app.mkdir(parents=True)
            (app/'Info.plist').write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':ipad.BUNDLE_ID}))
            (app/'Tripfolio').write_bytes(b'synthetic identical application bytes')
        driver.products={'aut':built}
        driver.built={'aut':ipad.tree_manifest(built,driver.checkpoint)}
        world.plan['output']=(str(fresh)+'\n').encode()
        return driver,world,fresh

    def test_installed_lookup60_allows45_seconds_and_keeps_exact_fresh_byte_checks(self):
        driver,world,fresh=self.installed_fixture(delay=45)
        result=driver.installed('ru-RU/installed-before',required=True)
        self.assertTrue(result['available'] and result['matches_built_bytes'])
        self.assertEqual(result['path'],str(fresh))
        row=self.row(driver)
        self.assertEqual(row['argv'],['xcrun','simctl','get_app_container',driver.owned,ipad.BUNDLE_ID,'app'])
        self.assertEqual((row['timeout_seconds'],row['wait_deadline_monotonic']),(60,60))
        self.assertGreaterEqual(world.t,45);self.assertLess(world.t,60)
        self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        self.assertEqual(driver.report['cases'],[])
        self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))
        self.assert_finished(driver)

    def test_installed_lookup60_applies_only_to_the_existing_four_lookup_calls(self):
        driver,world,_=self.installed_fixture()
        for label in ['en-US/installed-before','en-US/installed-after','ru-RU/installed-before','ru-RU/installed-after']:
            self.assertTrue(driver.installed(label,required=True)['available'])
            self.assertEqual(self.row(driver)['timeout_seconds'],60)
            self.assertEqual(self.row(driver)['label'],label+'-lookup')
        driver.command(['synthetic'],'unrelated-default')
        self.assertEqual(self.row(driver)['timeout_seconds'],30)
        self.assertEqual(len(world.processes),5)

    def test_installed_lookup60_timeout_keeps_original_stop_and_no_retry(self):
        driver,world,_=self.installed_fixture(delay=float('inf'),ignore_term=True)
        with self.assertRaisesRegex(RuntimeError,'ru-RU/installed-before-lookup exceeded its finite timeout'):
            driver.installed('ru-RU/installed-before',required=True)
        row=self.row(driver);self.assertEqual(row['wait_deadline_monotonic'],60)
        self.assertGreaterEqual(world.t,65);self.assertLessEqual(world.t,67)
        self.assertEqual([name for name,_ in world.calls if name.startswith('signal')],['signal_15','signal_9'])
        self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        self.assertFalse((driver.out/'ru-RU/installed-before.json').exists())
        self.assertEqual(driver.report['cases'],[]);self.assert_finished(driver)

    def test_installed_lookup60_is_clipped_to_global_work_and_preserves_cleanup(self):
        driver,world,_=self.installed_fixture(delay=50);world.t=1400
        with self.assertRaisesRegex(RuntimeError,'exceeded its finite timeout'):
            driver.installed('ru-RU/installed-before',required=True)
        self.assertEqual((self.row(driver)['timeout_seconds'],self.row(driver)['wait_deadline_monotonic']),(60,1433))
        self.assertEqual(world.t,1433);self.assertFalse(driver.active)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))
        self.assertEqual(len(world.processes),1);self.assert_finished(driver)

    def test_installed_lookup60_still_rejects_wrong_bundle_or_changed_bytes(self):
        original=self.root
        for kind in ['bundle','bytes']:
            with self.subTest(kind=kind):
                self.root=original/kind;self.root.mkdir()
                driver,world,fresh=self.installed_fixture(delay=45)
                if kind=='bundle':
                    (fresh/'Info.plist').write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':'wrong.synthetic.bundle'}))
                else:(fresh/'Tripfolio').write_bytes(b'changed synthetic application')
                expected='wrong AUT bundle identifier' if kind=='bundle' else 'Installed AUT bytes differ'
                with self.assertRaisesRegex(RuntimeError,expected):driver.installed('ru-RU/installed-before',required=True)
                self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        self.root=original

    def test_installed_lookup60_still_rejects_nonzero_and_invalid_path(self):
        original=self.root
        for kind in ['nonzero','path']:
            with self.subTest(kind=kind):
                self.root=original/kind;self.root.mkdir()
                driver,world,_=self.installed_fixture()
                if kind=='nonzero':world.plan['exit']=3
                else:world.plan['output']=b'relative/Tripfolio.app'
                expected='Installed AUT unavailable' if kind=='nonzero' else 'Invalid fresh AUT container path'
                with self.assertRaisesRegex(RuntimeError,expected):driver.installed('ru-RU/installed-before',required=True)
                self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
                self.assertEqual(driver.report['cases'],[])
        self.root=original

    def test_installed_lookup60_with_only_stop_reserve_never_spawns(self):
        driver,world,_=self.installed_fixture();world.t=1433
        with self.assertRaisesRegex(RuntimeError,'Insufficient command/stop budget'):
            driver.installed('ru-RU/installed-before',required=True)
        self.assertEqual(world.processes,[]);self.assertFalse(driver.active)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))
        self.assertEqual(world.t,1433);self.assert_finished(driver)

    def test_first_EN_allows_500_seconds_but_still_requires_result_validation(self):
        driver,world,failure,validated=self.attempted_case(0,delay=500)
        self.assertEqual(str(failure),'Synthetic result validation withheld')
        self.assertTrue(validated);self.assertGreaterEqual(world.t,500);self.assertLess(world.t,600)
        row=self.row(driver);self.assertEqual(row['timeout_seconds'],600)
        args=row['argv'];self.assertEqual(args[args.index('-default-test-execution-time-allowance')+1],'180')
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'480')
        self.assertEqual(args[args.index('-parallel-testing-enabled')+1],'NO')
        self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))
        self.assert_finished(driver)

    def test_first_EN_timeout_keeps_one_attempt_and_existing_stop_reserve(self):
        driver,world,failure,validated=self.attempted_case(0,delay=float('inf'),ignore_term=True)
        self.assertIn('en-US-test exceeded its finite timeout',str(failure))
        self.assertFalse(validated);self.assertEqual(self.row(driver)['wait_deadline_monotonic'],600)
        self.assertGreaterEqual(world.t,605);self.assertLessEqual(world.t,607)
        self.assertEqual([name for name,_ in world.calls if name.startswith('signal')],['signal_15','signal_9'])
        self.assertEqual(len(driver.report['cases']),1);self.assert_finished(driver)

    def test_RU_wait_remains_570_and_does_not_inherit_EN_allowance(self):
        driver,world,failure,validated=self.attempted_case(1,delay=float('inf'))
        self.assertIn('ru-RU-test exceeded its finite timeout',str(failure))
        self.assertFalse(validated);self.assertEqual(world.t,570)
        self.assertEqual(self.row(driver)['timeout_seconds'],570)
        self.assertEqual(driver.report['cases'][0]['system_content_size_expected'],
                         'accessibility-extra-extra-extra-large')
        self.assert_finished(driver)

    def test_long_first_wait_leaves_RU_clipped_by_original_global_deadline(self):
        driver,world=self.driver(delay=599);world.t=358
        driver.command(['synthetic'],'en-US-test',timeout=ipad.CASES[0][3])
        after_EN=world.t;self.assertGreaterEqual(after_EN,957);self.assertLess(after_EN,958)
        world.plan['delay']=float('inf')
        with self.assertRaisesRegex(RuntimeError,'finite timeout'):
            driver.command(['synthetic'],'ru-RU-test',timeout=ipad.CASES[1][3])
        self.assertEqual(self.row(driver)['timeout_seconds'],570)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'],1433)
        self.assertEqual(world.t,1433);self.assertLess(world.t-after_EN,570)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(1440,1620))
        self.assertEqual(len(world.processes),2);self.assertFalse(driver.active)
        self.assert_finished(driver)

    def test_runtime_120_allows_70_seconds_and_other_default_stays_30(self):
        driver, world = self.driver(delay=70, output=b'{"runtimes": []}')
        # Real prepare() passes the timeout to real json_command()/command().
        # Stop at pair selection before any simulator creation is possible.
        actual = driver.json_command
        def json_command(argv, label, timeout=30):
            if label == 'runtimes':
                return actual(argv, label, timeout)
            self.assertEqual((label, timeout), ('device-types', 30))
            return {'devicetypes': []}
        actual_command = driver.command
        def command(argv, label, **kwargs):
            if label == 'runtimes':
                return actual_command(argv, label, **kwargs)
            return 0, 'arm64' if label == 'architecture' else ''
        with patch.object(driver, 'source_snapshot', return_value={'status':'', 'head':'a'*40}), \
             patch.object(driver, 'json_command', side_effect=json_command), \
             patch.object(driver, 'command', side_effect=command):
            with self.assertRaisesRegex(RuntimeError, 'No explicitly compatible'): driver.prepare()
        self.assertEqual(self.row(driver)['timeout_seconds'], 120)
        self.assertGreaterEqual(world.t, 70)
        self.assertLess(world.t, 120)
        self.assertEqual(len(world.processes), 1); self.assertFalse(driver.active)
        world.plan['delay'] = 0
        driver.command(['synthetic'], 'default')
        self.assertEqual(self.row(driver)['timeout_seconds'], 30)
        self.assertEqual((driver.work_deadline, driver.final_deadline), (1440, 1620))
        self.assert_finished(driver)

    def initial_runtime(self, driver):
        # Exercise real prepare -> json_command -> command -> stop for inventory.
        # Other preparatory commands are inert; no device can be acquired.
        actual_json, actual_command = driver.json_command, driver.command
        reached = []
        def json_command(argv, label, timeout=30):
            reached.append(label)
            if label == 'runtimes':
                return actual_json(argv, label, timeout)
            self.assertEqual((label, timeout), ('device-types', 30))
            return {'devicetypes': []}
        def command(argv, label, **kwargs):
            if label == 'runtimes':
                return actual_command(argv, label, **kwargs)
            return 0, 'arm64' if label == 'architecture' else ''
        with patch.object(driver, 'source_snapshot', return_value={'status':'', 'head':'a'*40}), \
             patch.object(driver, 'json_command', side_effect=json_command), \
             patch.object(driver, 'command', side_effect=command), \
             patch.object(ipad, 'choose_pair', wraps=ipad.choose_pair) as choose:
            with self.assertRaises((RuntimeError, json.JSONDecodeError)) as failure:
                driver.prepare()
        self.assertIsNone(driver.owned); self.assertIsNone(driver.intent)
        self.assertEqual(driver.report['cases'], [])
        self.assertEqual((driver.work_deadline, driver.final_deadline), (1440, 1620))
        self.assert_finished(driver)
        return failure.exception, reached, choose.called

    def test_initial_runtime_exact_120_completion_is_rejected_before_selection(self):
        driver, world = self.driver(delay=120, output=b'{"runtimes": []}')
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('Initial runtime inventory wait deadline reached', str(failure))
        self.assertEqual(world.t, 120); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertFalse(driver.active)
        self.assertEqual(self.row(driver)['returncode'], 0)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 120)

    def test_initial_runtime_120_timeout_one_child_and_existing_7_stop(self):
        driver, world = self.driver(delay=float('inf'), ignore_term=True)
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('finite timeout', str(failure)); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertEqual(len(world.processes), 1)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 120)
        self.assertGreaterEqual(world.t, 125); self.assertLessEqual(world.t, 127)
        self.assertEqual(driver.report['process_stops'][0]['deadline_monotonic'], 127)
        self.assertEqual([n for n, _ in world.calls if n.startswith('signal')], ['signal_15', 'signal_9'])
        self.assertFalse(driver.active)

    def test_initial_runtime_wait_clips_to_work_minus_7_without_spending_cleanup(self):
        driver, world = self.driver(delay=float('inf'), ignore_term=True); world.t = 1370
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('finite timeout', str(failure)); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertEqual(len(world.processes), 1)
        self.assertEqual(self.row(driver)['timeout_seconds'], 120)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 1433)
        self.assertEqual(driver.report['process_stops'][0]['deadline_monotonic'], 1440)
        self.assertLessEqual(world.t, 1440); self.assertFalse(driver.active)

    def test_initial_runtime_exact_clipped_deadline_is_not_inventory_success(self):
        driver, world = self.driver(delay=63, output=b'{"runtimes": []}'); world.t = 1370
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('Initial runtime inventory wait deadline reached', str(failure))
        self.assertEqual(world.t, 1433); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertFalse(driver.active)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 1433)

    def test_initial_runtime_exact_7_remaining_never_spawns(self):
        driver, world = self.driver(); world.t = 1433
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('Insufficient command/stop budget', str(failure))
        self.assertEqual(reached, ['runtimes']); self.assertFalse(selected)
        self.assertEqual(world.processes, []); self.assertFalse(driver.active)

    def test_initial_runtime_late_parse_is_rejected_before_device_inventory(self):
        driver, world = self.driver(delay=70, output=b'{"runtimes": []}')
        actual = driver.json_command
        def delayed_parse(*args, **kwargs):
            value = actual(*args, **kwargs)
            world.t = 120
            return value
        with patch.object(driver, 'json_command', side_effect=delayed_parse):
            failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('Initial runtime inventory wait deadline reached', str(failure))
        self.assertFalse(selected); self.assertEqual(reached, ['runtimes'])
        self.assertFalse(driver.active)

    def test_initial_runtime_slow_invalid_json_is_not_success(self):
        driver, world = self.driver(delay=70, output=b'not-json')
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIsInstance(failure, json.JSONDecodeError)
        self.assertFalse(selected); self.assertEqual(reached, ['runtimes'])
        self.assertFalse(driver.active); self.assertLess(world.t, 120)

    def test_initial_runtime_longer_wait_reduces_later_case_budget(self):
        driver, world = self.driver(delay=119, output=b'{"runtimes": []}')
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('No explicitly compatible', str(failure)); self.assertTrue(selected)
        self.assertEqual(reached, ['runtimes', 'device-types'])
        self.assertGreaterEqual(world.t, 119); self.assertLess(world.t, 120)
        # Fixed synthetic intervening work; no native preparation is claimed.
        world.t += 400
        world.plan['delay'] = 599
        driver.command(['synthetic'], 'en-US-test', timeout=ipad.CASES[0][3])
        after_EN = world.t
        world.plan['delay'] = float('inf')
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'ru-RU-test', timeout=ipad.CASES[1][3])
        self.assertEqual([case[3] for case in ipad.CASES], [600, 570])
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 1433)
        self.assertLess(world.t - after_EN, 316)
        self.assertEqual((driver.work_deadline, driver.final_deadline), (1440, 1620))
        self.assertEqual(len(world.processes), 3); self.assertFalse(driver.active)
        self.assert_finished(driver)

    def test_timeout_and_probe_EPERM_keep_primary_and_allow_owned_cleanup(self):
        error = PermissionError(errno.EPERM, 'probe denied')
        driver, world = self.driver(delay=float('inf'), probe_error=error)
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'timeout')
        row = self.row(driver); self.assertIn('PermissionError', row['stop_error'])
        stop = driver.report['process_stops'][0]
        self.assertEqual(stop['observations']['group_probe']['errno'], errno.EPERM)
        self.assertEqual(stop['observations']['group_probe']['exception_type'], 'PermissionError')
        self.assertEqual(len(driver.active), 1); self.assert_finished(driver)
        world.plan.pop('probe_error')
        driver.cleanup()
        self.assertTrue(driver.report['cleanup']['verified']); self.assertFalse(driver.active)
        self.assertEqual(len(world.processes), 1)
        self.assertEqual(len(driver.report['process_stops']), 2)
        self.assertIn('PermissionError', self.row(driver)['stop_error'])

    def test_stop_poll_EPERM_and_signal_EPERM_have_distinct_operations(self):
        driver, world = self.driver(poll_errors={2: PermissionError(errno.EPERM, 'poll denied')})
        with self.assertRaises(PermissionError): driver.command(['synthetic'], 'poll', check=False)
        obs = driver.report['process_stops'][0]['observations']
        self.assertEqual(list(obs), ['poll']); self.assertEqual(obs['poll']['errno'], errno.EPERM)
        self.assert_finished(driver); self.assertTrue(driver.active)
        world.plan.pop('poll_errors'); world.plan['delay'] = float('inf')
        world.plan['signal_error'] = PermissionError(errno.EPERM, 'signal denied')
        process = world.processes[0]; process.returncode = None
        with self.assertRaises(PermissionError): driver.stop(process)
        obs = driver.report['process_stops'][-1]['observations']
        self.assertEqual(obs['signal_15']['errno'], errno.EPERM)
        self.assertNotIn('signal_9', obs)

    def test_timeout_then_TERM_then_probe_EPERM_cleanup_does_not_signal_again(self):
        driver, world = self.driver(delay=float('inf'), probe_errors={2:PermissionError(errno.EPERM, 'after TERM')})
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'after-term')
        stop = driver.report['process_stops'][0]
        self.assertEqual(stop['signals'], [15])
        self.assertEqual(stop['observations']['signal_15']['outcome'], 'returned')
        self.assertEqual(stop['observations']['group_probe']['errno'], errno.EPERM)
        self.assertEqual(stop['observations']['group_probe']['calls'], 2)
        self.assertNotIn('signal_9', stop['observations'])
        self.assertTrue(driver.active); self.assert_finished(driver)
        driver.cleanup()
        self.assertFalse(driver.active); self.assertTrue(driver.report['cleanup']['verified'])
        self.assertEqual([name for name, _ in world.calls if name.startswith('signal')], ['signal_15'])
        self.assertEqual(len(world.processes), 1)
        self.assertIn('finite timeout', self.row(driver)['error'])
        self.assertIn('after TERM', self.row(driver)['stop_error'])

    def test_unknown_ProcessLookupError_is_not_absence(self):
        driver, world = self.driver(probe_error=ProcessLookupError('unknown'))
        with self.assertRaises(ProcessLookupError): driver.command(['synthetic'], 'unknown')
        self.assertTrue(driver.active); self.assertFalse(driver.confirmed_absent_groups)
        self.assert_finished(driver)

    def test_signal_ESRCH_is_recorded_as_exception_without_fake_delivery(self):
        driver, world = self.driver(delay=float('inf'), signal_esrch=True)
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'): driver.command(['synthetic'], 'esrch')
        stop = driver.report['process_stops'][0]
        self.assertEqual(stop['signals'], [])
        self.assertEqual(stop['observations']['signal_15']['errno'], errno.ESRCH)
        self.assertTrue(stop['group_absent']); self.assertFalse(driver.active)
        self.assertEqual(stop['observations']['group_probe']['calls'], 1)

    def test_deferred_cancel_during_spawn_registers_and_stops_one_child(self):
        driver, world = self.driver(delay=float('inf'))
        world.on_spawn = lambda: driver.signal(signal.SIGTERM, None)
        with self.assertRaisesRegex(InterruptedError, 'Deferred signal'):
            driver.command(['synthetic'], 'cancel')
        self.assertEqual(len(world.processes), 1); self.assertFalse(driver.active)
        self.assert_finished(driver); self.assertFalse(driver.registering_process)

    def test_cancel_before_spawn_withholds_child_and_finishes_metadata(self):
        driver, world = self.driver()
        save = driver.save
        first = True
        def cancelled_save():
            nonlocal first
            save()
            if first:
                first = False
                driver.signal(signal.SIGINT, None)
        with patch.object(driver, 'save', side_effect=cancelled_save):
            with self.assertRaises(InterruptedError): driver.command(['synthetic'], 'cancel-before-spawn')
        self.assertEqual(world.processes, [])
        self.assertNotIn('owned_process_group', self.row(driver)); self.assert_finished(driver)

    def test_cancellation_remains_primary_when_stop_fails(self):
        driver, world = self.driver(delay=float('inf'), probe_error=PermissionError(errno.EPERM, 'denied'))
        world.on_spawn = lambda: driver.signal(signal.SIGINT, None)
        with self.assertRaises(InterruptedError): driver.command(['synthetic'], 'cancel-stop')
        self.assertIn('PermissionError', self.row(driver)['stop_error'])
        self.assertEqual(len(world.processes), 1); self.assertTrue(driver.active)
        self.assert_finished(driver)

    def test_primary_poll_failure_survives_secondary_stop_and_receipt_errors(self):
        primary = OSError(errno.EIO, 'command poll')
        driver, world = self.driver(poll_errors={1:primary, 2:PermissionError(errno.EPERM, 'stop poll')})
        original = driver.save
        count = 0
        def save():
            nonlocal count
            count += 1
            if count >= 3:
                raise OSError(errno.ENOSPC, 'receipt full')
            original()
        with patch.object(driver, 'save', side_effect=save):
            with self.assertRaises(OSError) as result: driver.command(['synthetic'], 'double')
        self.assertIs(result.exception, primary)
        row = self.row(driver)
        self.assertIn('finish', row); self.assertIn('returncode', row)
        self.assertIn('stop_error', row); self.assertIn('finalization_error', row)
        self.assertIn('finalization_error', driver.report['process_stops'][0])
        self.assertTrue(driver.active)

    def test_remaining_exactly_7_refuses_spawn_and_finishes_metadata(self):
        driver, world = self.driver(); world.t = 1433
        with self.assertRaisesRegex(RuntimeError, 'Insufficient'): driver.command(['synthetic'], 'edge')
        self.assertEqual(world.processes, []); self.assertNotIn('owned_process_group', self.row(driver))
        self.assert_finished(driver)

    def test_receipt_time_before_spawn_cannot_consume_stop_reserve(self):
        driver, world = self.driver(); world.t = 1432
        original = driver.save
        def slow_save():
            original(); world.t += 1
        with patch.object(driver, 'save', side_effect=slow_save):
            with self.assertRaisesRegex(RuntimeError, 'Insufficient'): driver.command(['synthetic'], 'slow-save')
        self.assertEqual(world.processes, []); self.assert_finished(driver)

    def test_just_more_than_7_and_timeout_plus_7_preserve_global_reserve(self):
        driver, world = self.driver(delay=float('inf'))
        world.t = 1432.99
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'tiny', timeout=60)
        self.assertAlmostEqual(world.t, 1433)
        self.assertLessEqual(world.t, driver.work_deadline); self.assertFalse(driver.active)
        world.t = 1373
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'full', timeout=60)
        self.assertEqual(world.t, 1433); self.assertEqual(len(world.processes), 2)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 1433)

    def test_deadline_between_TERM_and_KILL_withholds_later_operations(self):
        driver, world = self.driver(delay=float('inf'), ignore_all=True, signal_seconds=7)
        world.t = 1432
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'): driver.command(['synthetic'], 'deadline')
        self.assertEqual(world.t, 1440); self.assertTrue(driver.active)
        self.assertIn('stop deadline', self.row(driver)['stop_error'])
        self.assertEqual(world.calls[-1], ('signal_15', 1433))
        self.assertFalse(any(name == 'signal_9' for name, _ in world.calls))
        self.assert_finished(driver)

    def test_cleanup_final_deadline_allows_no_probe_or_signal(self):
        driver, world = self.driver(delay=float('inf'), probe_error=PermissionError(errno.EPERM, 'denied'))
        with self.assertRaises(RuntimeError): driver.command(['synthetic'], 'hold')
        before = list(world.calls); world.t = 1620
        with self.assertRaisesRegex(RuntimeError, 'cleanup could not be confirmed'): driver.cleanup()
        self.assertEqual(world.calls, before); self.assertTrue(driver.active)
        self.assertFalse(driver.report['cleanup']['verified'])

    def test_terminal_success_is_cached_even_next_to_deadline(self):
        driver, world = self.driver()
        world.on_probe = lambda: setattr(world, 't', 6.999)
        driver.command(['synthetic'], 'near-deadline')
        stop = driver.report['process_stops'][0]
        self.assertEqual(stop['observations']['poll']['calls'], 1)
        self.assertEqual(stop['observations']['group_probe']['calls'], 1)
        self.assertFalse(driver.active); self.assert_finished(driver)

    def test_many_stop_polls_use_four_fixed_slots_and_no_extra_saves(self):
        driver, world = self.driver(delay=float('inf'), ignore_term=True)
        with patch.object(driver, 'save', wraps=driver.save) as save:
            with self.assertRaisesRegex(RuntimeError, 'finite timeout'): driver.command(['synthetic'], 'long-stop')
        stop = driver.report['process_stops'][0]; obs = stop['observations']
        self.assertEqual(set(obs), {'poll','group_probe','signal_15','signal_9'})
        self.assertGreater(obs['poll']['calls'], 100)
        self.assertLess(len(json.dumps(obs)), 2000); self.assertEqual(save.call_count, 4)
        self.assertEqual([name for name, _ in world.calls if name.startswith('signal')], ['signal_15','signal_9'])
        self.assertFalse(driver.active); self.assert_finished(driver)
        for slot in obs.values():
            self.assertGreaterEqual(slot['last_finish'], slot['last_start'])

    def test_unowned_handle_has_no_observations_or_syscalls(self):
        driver, world = self.driver()
        process = Process(world, {})
        with self.assertRaisesRegex(RuntimeError, 'unowned'): driver.stop(process)
        self.assertEqual(world.calls, []); self.assertNotIn('process_stops', driver.report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
