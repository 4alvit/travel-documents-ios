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

    def attempted_case(self, index, start_at=0, preparation_seconds=0, **plan):
        case = ipad.CASES[index]; locale, method, size, _ = case
        driver, world = self.driver(locale=locale, **plan)
        world.t = start_at
        driver.owned = 'synthetic-owned-device'
        driver.products = {'aut':self.root/'Synthetic.app','runner':self.root/'SyntheticRunner.app','xctestrun':self.root/'synthetic.xctestrun'}
        (driver.out/'originals'/(locale+'.xcresult')).mkdir(parents=True)
        actual = driver.command
        def command(argv, label, **kwargs):
            if label == locale+'-test':
                return actual(argv, label, **kwargs)
            if label == locale+'-install':
                world.t += preparation_seconds
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

    def sdk_fixture(self):
        types = {'devicetypes': [
            {'identifier': 'type.ipad-m4', 'name': 'iPad Pro 13-inch M4', 'productFamily': 'iPad'},
            {'identifier': 'type.ipad-m5', 'name': 'iPad Pro 13-inch M5', 'productFamily': 'iPad'},
            {'identifier': 'type.phone', 'name': 'iPhone', 'productFamily': 'iPhone'}]}
        def runtime(version, device):
            return {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-' + version.replace('.', '-'),
                    'version': version, 'buildversion': 'synthetic-build-' + version, 'isAvailable': True,
                    'supportedArchitectures': ['arm64'], 'supportedDeviceTypes': [{'identifier': device}]}
        return {'runtimes': [runtime('18.5', 'type.ipad-m4'), runtime('26.2', 'type.ipad-m5')]}, types

    def test_sdk_pair_uses_exact_sdk_and_only_its_supported_device_types(self):
        runtimes, types = self.sdk_fixture()
        pair = ipad.choose_pair(runtimes, types, 'arm64', '18.5')
        self.assertEqual(pair['os_version'], '18.5')
        self.assertEqual(pair['device_type'], 'type.ipad-m4')
        self.assertEqual(pair['os_build'], 'synthetic-build-18.5')
        self.assertEqual(ipad.choose_pair(runtimes, types, 'arm64', '26.2')['device_type'], 'type.ipad-m5')

    def test_sdk_pair_rejects_ambiguous_match_even_if_one_is_unavailable(self):
        runtimes, types = self.sdk_fixture()
        duplicate = dict(runtimes['runtimes'][0]); duplicate['isAvailable'] = False
        runtimes['runtimes'].append(duplicate)
        with self.assertRaisesRegex(RuntimeError, 'unique exact SDK-matched'):
            ipad.choose_pair(runtimes, types, 'arm64', '18.5')

    def test_sdk_pair_requires_available_architecture_compatible_ipad(self):
        for mutation in ('absent', 'unavailable', 'architecture', 'phone', 'unknown-type', 'duplicate-type', 'malformed-architecture'):
            runtimes, types = self.sdk_fixture(); runtime = runtimes['runtimes'][0]
            if mutation == 'absent': runtimes['runtimes'].pop(0)
            elif mutation == 'unavailable': runtime['isAvailable'] = False
            elif mutation == 'architecture': runtime['supportedArchitectures'] = ['x86_64']
            elif mutation == 'malformed-architecture': runtime['supportedArchitectures'] = 'arm64'
            elif mutation == 'phone': runtime['supportedDeviceTypes'] = [{'identifier': 'type.phone'}]
            elif mutation == 'unknown-type': runtime['supportedDeviceTypes'] = [{'identifier': 'missing'}]
            else: runtime['supportedDeviceTypes'] *= 2
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                ipad.choose_pair(runtimes, types, 'arm64', '18.5')
        for sdk in ('', 'latest', '18.5\n', '../18.5', '16.4', None):
            with self.subTest(sdk=sdk), self.assertRaises(RuntimeError):
                ipad.choose_pair(*self.sdk_fixture(), 'arm64', sdk)

    def test_sdk_raw_output_and_selection_are_retained_during_prepare(self):
        driver, world, reached, error = self.complete_discovery()
        self.assertIsNone(error)
        self.assertEqual(driver.report['simulator_sdk'], {'raw': '26.2\n', 'version': '26.2',
                                                        'selection': 'exact-sdk-matched'})
        self.assertEqual(driver.report['destination']['os_version'], '26.2')
        self.assertEqual(reached.count('create-owned-ipad'), 1)

    def test_invalid_sdk_stops_before_any_simulator_discovery_or_creation(self):
        driver, _ = self.driver(); calls = []
        def command(argv, label, **kwargs):
            calls.append(argv)
            return 0, 'invalid-sdk' if label == 'simulator-sdk-version' else ''
        with patch.object(driver, 'source_snapshot', return_value={'status': '', 'head': 'a' * 40}), \
             patch.object(driver, 'command', side_effect=command):
            with self.assertRaisesRegex(RuntimeError, 'Invalid Simulator SDK version'): driver.prepare()
        self.assertFalse(any('simctl' in argv for argv in calls)); self.assertIsNone(driver.owned)

    def test_ci_ipad_toolchain_is_pinned_without_changing_native_case_allowances(self):
        workflow = (HERE.parent / '.github/workflows/ci.yml').read_text()
        self.assertIn('group: ci-${{ github.workflow }}-${{ github.ref }}-${{ github.sha }}', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        ipad_job = workflow.split('  privacy_ipad:\n', 1)[1].split('  recovery:\n', 1)[0]
        self.assertIn('DEVELOPER_DIR: /Applications/Xcode_26.2.app/Contents/Developer', ipad_job)
        self.assertIn('TRIPDOCKET_IPAD_XCODE_VERSION=$(xcodebuild -version)', ipad_job)
        self.assertIn("test \"$TRIPDOCKET_IPAD_XCODE_VERSION\" = $'Xcode 26.2\\nBuild version 17C52'", ipad_job)
        self.assertEqual([case[3] for case in ipad.CASES], [900, 900])
        self.assertEqual(ipad.WORK_SECONDS, {'en-US': 2100, 'ru-RU': 2100})
        self.assertEqual(ipad.CLEANUP_SECONDS, 180)

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
                work = 2100
                self.assertEqual((driver.work_deadline,driver.final_deadline),(work,work+180))
                self.assertEqual(driver.report['work_seconds'],work)
                self.assertEqual(driver.report['cleanup_reserve_seconds'],180)
                self.assertEqual(world.processes,[])

    def test_observed_RU_remaining357_is_not_admitted_or_spawned(self):
        driver,world=self.driver(locale='ru-RU');world.t=driver.work_deadline-357
        with patch.object(driver,'product_snapshot') as snapshot:
            with self.assertRaisesRegex(RuntimeError,'lacks full case/post-validation budget'):
                driver.run_case(*driver.case)
        snapshot.assert_not_called();self.assertEqual(world.processes,[])
        self.assertEqual(driver.report['cases'][0]['status'],'not_admitted')
        self.assertEqual(driver.report['cases'][0]['admission']['required_seconds'],1487)
        with self.assertRaisesRegex(RuntimeError,'no retry'):driver.run_case(*driver.case)

    def test_full_case_admission_rejects_exact_boundary(self):
        for locale,expected in [('en-US',1487),('ru-RU',1487)]:
            with self.subTest(locale=locale):
                driver,world=self.driver(locale=locale)
                required=ipad.CASE_PREP_SECONDS+driver.case[3]+7+ipad.CASE_POST_SECONDS
                self.assertEqual(required,expected);world.t=driver.work_deadline-required
                with self.assertRaisesRegex(RuntimeError,'no case started'):driver.run_case(*driver.case)
                self.assertEqual(world.processes,[]);self.assertEqual(driver.report['cases'][0]['status'],'not_admitted')

    def test_actual_test_command_rechecks_full_wait_stop_and_post_budget_before_spawn(self):
        for locale,allowance,work in [('en-US',900,2100),('ru-RU',900,2100)]:
            with self.subTest(locale=locale):
                driver,world=self.driver(locale=locale,delay=1)
                world.t=work-allowance-7-ipad.CASE_POST_SECONDS
                with self.assertRaisesRegex(RuntimeError,'no test spawned'):
                    driver.command(['synthetic'],locale+'-test',timeout=allowance,required_after=ipad.CASE_POST_SECONDS)
                self.assertEqual(world.processes,[])
                world.t-=1
                driver.command(['synthetic'],locale+'-test',timeout=allowance,required_after=ipad.CASE_POST_SECONDS)
                self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
                self.assertEqual(self.row(driver)['wait_deadline_monotonic'],world.processes[0].started+allowance)
                self.assertEqual((driver.work_deadline,driver.final_deadline),(work,work+180))

    def test_case_does_not_accept_a_different_locale_or_case(self):
        driver,world=self.driver()
        with self.assertRaisesRegex(RuntimeError,'differs from selected locale'):driver.run_case(*ipad.CASES[1])
        self.assertEqual(driver.report['cases'],[]);self.assertEqual(world.processes,[])

    def test_one_build_selects_only_the_exact_locale_case_and_keeps_its_cap(self):
        for locale in ('en-US','ru-RU'):
            with self.subTest(locale=locale):
                driver,world=self.driver(locale=locale)
                driver.owned='synthetic-owned-device'
                with patch.object(driver,'command') as command,patch.object(driver,'discover_products') as discover, \
                     patch.object(driver,'product_snapshot',return_value={'synthetic':'manifest'}) as snapshot:
                    driver.build_once()
                self.assertEqual(command.call_count,2)
                command.assert_any_call(['xcodegen','generate'],'xcodegen',timeout=120)
                args,kwargs=command.call_args
                self.assertEqual(args[0][:2],['xcodebuild','build-for-testing'])
                self.assertEqual(args[0][args[0].index('-scheme')+1],'Tripfolio-iPad')
                self.assertEqual(args[0][args[0].index('-testPlan')+1],'Tripfolio-iPad')
                self.assertEqual([a for a in args[0] if str(a).startswith('-only-testing:')],
                    ['-only-testing:TripfolioUITests/PrivacySupportUITests/'+driver.case[1]])
                self.assertFalse(any(str(a).startswith('-skip-testing:') for a in args[0]))
                self.assertEqual(kwargs,{'timeout':480,'stream':True})
                discover.assert_called_once_with();snapshot.assert_called_once_with('products-after-build')
                self.assertEqual(world.processes,[])

    def test_progressing_build_can_finish_after_former_cap_without_changing_case_budget(self):
        driver, world = self.driver(locale='ru-RU', delay=400)
        world.t = 201  # Observed H6 pre-build work was about 201 seconds.
        driver.owned = 'synthetic-owned-device'
        actual = driver.command
        def command(argv, label, **kwargs):
            return (0, '') if label == 'xcodegen' else actual(argv, label, **kwargs)
        with patch.object(driver, 'command', side_effect=command), \
             patch.object(driver, 'discover_products') as discover, \
             patch.object(driver, 'product_snapshot', return_value={'synthetic':'manifest'}):
            driver.build_once()
        discover.assert_called_once_with()
        self.assertEqual(len(world.processes), 1)
        self.assertGreater(world.t, 201 + 360)
        self.assertLess(world.t, 201 + 480)
        self.assertFalse(any(call[0].startswith('signal_') for call in world.calls))
        self.assertEqual((driver.work_deadline, driver.final_deadline), (2100, 2280))
        self.assertEqual(driver.case[3], 900)
        self.assertGreater(driver.work_deadline - world.t, 1487)

    def test_extended_build_does_not_admit_case_without_full_remaining_budget(self):
        driver, world = self.driver(locale='ru-RU', delay=420)
        world.t = 201
        driver.owned = 'synthetic-owned-device'
        actual = driver.command
        def command(argv, label, **kwargs):
            return (0, '') if label == 'xcodegen' else actual(argv, label, **kwargs)
        with patch.object(driver, 'command', side_effect=command), \
             patch.object(driver, 'discover_products'), \
             patch.object(driver, 'product_snapshot', return_value={'synthetic':'manifest'}):
            driver.build_once()
        with patch.object(driver, 'product_snapshot') as snapshot:
            with self.assertRaisesRegex(RuntimeError, 'lacks full case/post-validation budget'):
                driver.run_case(*driver.case)
        snapshot.assert_not_called()
        self.assertEqual(len(world.processes), 1)  # Build only: no partial native case.
        self.assertEqual(driver.report['cases'][0]['status'], 'not_admitted')
        self.assertEqual(driver.report['cases'][0]['admission']['required_seconds'], 1487)
        self.assertEqual((driver.work_deadline, driver.final_deadline), (2100, 2280))

    def test_extended_build_still_stops_at_global_work_boundary(self):
        driver, world = self.driver(locale='ru-RU', delay=1000)
        world.t = 1700
        driver.owned = 'synthetic-owned-device'
        actual = driver.command
        def command(argv, label, **kwargs):
            return (0, '') if label == 'xcodegen' else actual(argv, label, **kwargs)
        with patch.object(driver, 'command', side_effect=command), \
             patch.object(driver, 'discover_products') as discover:
            with self.assertRaisesRegex(RuntimeError, 'build-for-testing exceeded its finite timeout'):
                driver.build_once()
        discover.assert_not_called()
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 2093)
        self.assertLessEqual(world.t, 2100)
        self.assertEqual(driver.final_deadline, 2280)
        self.assertEqual(driver.report['cases'], [])
        self.assertTrue(driver.report['process_stops'][-1]['group_absent'])
        self.assertEqual(len(world.processes), 1)

    def post_failure_case(self, locale='en-US', **process_plan):
        driver,world=self.driver(locale=locale,**process_plan);case=driver.case;locale,method,size,_=case
        driver.owned='synthetic-owned-device';driver.products={'aut':self.root/'Synthetic.app','runner':self.root/'SyntheticRunner.app','xctestrun':self.root/'synthetic.xctestrun'}
        actual=driver.command
        def command(argv,label,**kwargs):
            if label==locale+'-test':return actual(argv,label,**kwargs)
            return 0,size if label==locale+'-read-size' else ''
        def installed(label,required=False,product="aut"):
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
        for locale,step,job in [('en-US',40,46),('ru-RU',40,46)]:
            self.assertIn(f'- locale: {locale}\n            step_minutes: {step}\n            job_minutes: {job}',lane)
            work=ipad.WORK_SECONDS[locale]
            self.assertGreater(step*60,work+ipad.CLEANUP_SECONDS)
            self.assertGreater(job,step+3)
        self.assertEqual(lane.count('- locale:'),2)
        self.assertIn('name: iPad privacy and support (${{ matrix.locale }})',lane)
        self.assertIn("run: bash scripts/test-privacy-support-ipad.sh --locale '${{ matrix.locale }}'",lane)
        self.assertIn('name: TripDocket-privacy-ipad-${{ matrix.locale }}-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}',lane)
        self.assertIn('path: build/PrivacySupport-iPad/${{ matrix.locale }}/',lane)
        self.assertIn('timeout-minutes: ${{ matrix.job_minutes }}',lane)
        self.assertIn('timeout-minutes: ${{ matrix.step_minutes }}',lane)
        gate=workflow.split('  gate:',1)[1]
        self.assertIn('if: always()',gate)
        self.assertIn('needs: [validate, ui_guidance, privacy_ipad, recovery]',gate)
        self.assertIn('CORE_PURCHASE_RESULT: ${{ needs.validate.result }}',gate)
        self.assertIn('UI_GUIDANCE_RESULT: ${{ needs.ui_guidance.result }}',gate)
        self.assertIn('test "$CORE_PURCHASE_RESULT" = success',gate)
        self.assertIn('test "$UI_GUIDANCE_RESULT" = success',gate)
        self.assertIn('IPAD_RESULT: ${{ needs.privacy_ipad.result }}',gate)
        self.assertIn('test "$IPAD_RESULT" = success',gate)
        self.assertIn('exec python3 scripts/test-privacy-support-ipad.py "$@"',(HERE/'test-privacy-support-ipad.sh').read_text())

    def installed_fixture(self, product="aut", **plan):
        driver,world=self.driver(**plan)
        driver.owned='synthetic-owned-device'
        (driver.out/'commands').mkdir()
        name='Tripfolio.app' if product=='aut' else 'TripfolioUITests-Runner.app'
        identifier=ipad.BUNDLE_ID if product=='aut' else ipad.RUNNER_BUNDLE_ID
        built=self.root/'built'/name;fresh=self.root/'installed'/name
        for app in (built,fresh):
            app.mkdir(parents=True)
            (app/'Info.plist').write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':identifier}))
            (app/'Tripfolio').write_bytes(b'synthetic identical application bytes')
        driver.products={product:built}
        driver.built={product:ipad.tree_manifest(built,driver.checkpoint)}
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
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
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
        driver,world,_=self.installed_fixture(delay=50);world.t=2060
        with self.assertRaisesRegex(RuntimeError,'exceeded its finite timeout'):
            driver.installed('ru-RU/installed-before',required=True)
        self.assertEqual((self.row(driver)['timeout_seconds'],self.row(driver)['wait_deadline_monotonic']),(60,2093))
        self.assertEqual(world.t,2093);self.assertFalse(driver.active)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
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
        driver,world,_=self.installed_fixture();world.t=2093
        with self.assertRaisesRegex(RuntimeError,'Insufficient command/stop budget'):
            driver.installed('ru-RU/installed-before',required=True)
        self.assertEqual(world.processes,[]);self.assertFalse(driver.active)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        self.assertEqual(world.t,2093);self.assert_finished(driver)

    def test_generated_runner_requires_the_exact_built_bundle_identifier(self):
        driver,world=self.driver()
        products=driver.derived/'Build/Products';products.mkdir(parents=True)
        aut=products/'Tripfolio.app';aut.mkdir()
        runner=products/'TripfolioUITests-Runner.app';runner.mkdir()
        bundle=runner/'PlugIns/TripfolioUITests.xctest';bundle.mkdir(parents=True)
        (aut/'Info.plist').write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':ipad.BUNDLE_ID}))
        info=runner/'Info.plist'
        data={'__xctestrun_metadata__':{'FormatVersion':2},'TestConfigurations':[{'TestTargets':[{
            'BlueprintName':'TripfolioUITests','IsUITestBundle':True,
            'UITargetAppPath':'__TESTROOT__/Tripfolio.app',
            'TestHostPath':'__TESTROOT__/TripfolioUITests-Runner.app',
            'TestBundlePath':'__TESTHOST__/PlugIns/TripfolioUITests.xctest'}]}]}
        (products/'Synthetic.xctestrun').write_bytes(ipad.plistlib.dumps(data))
        with self.assertRaises(FileNotFoundError):driver.discover_products()
        for identifier in [ipad.BUNDLE_ID,'wrong.runner']:
            info.write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':identifier}))
            with self.assertRaisesRegex(RuntimeError,'Wrong runner bundle identifier'):driver.discover_products()
        info.write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':ipad.RUNNER_BUNDLE_ID}))
        driver.discover_products()
        self.assertEqual(driver.products['runner'],runner)
        self.assertEqual(driver.report['product_bundle_identifiers'],
                         {'aut':ipad.BUNDLE_ID,'runner':ipad.RUNNER_BUNDLE_ID})
        data['TestConfigurations'][0]['TestTargets'].append({'BlueprintName':'TripfolioTests'})
        (products/'Synthetic.xctestrun').write_bytes(ipad.plistlib.dumps(data))
        with self.assertRaisesRegex(RuntimeError,'Expected only TripfolioUITests target'):driver.discover_products()
        self.assertEqual(world.processes,[])

    def test_ipad_plan_preserves_options_and_default_scheme_keeps_all_test_targets(self):
        import xml.etree.ElementTree as xml
        default=json.loads((HERE.parent/'Tripfolio.xctestplan').read_text())
        selected=json.loads((HERE.parent/'Tripfolio-iPad.xctestplan').read_text())
        self.assertEqual(selected['defaultOptions'],default['defaultOptions'])
        self.assertEqual(selected['configurations'],default['configurations'])
        self.assertEqual(selected['testTargets'],[target for target in default['testTargets']
            if target['target']['name']=='TripfolioUITests'])
        self.assertEqual(len(selected['testTargets']),1)
        schemes=HERE.parent/'Tripfolio.xcodeproj/xcshareddata/xcschemes'
        for name,targets,plan in [('Tripfolio',{'TripfolioTests','TripfolioUITests'},'Tripfolio.xctestplan'),
                                  ('Tripfolio-iPad',{'TripfolioUITests'},'Tripfolio-iPad.xctestplan')]:
            scheme=xml.parse(schemes/(name+'.xcscheme')).getroot()
            actual={node.attrib['BlueprintName'] for node in scheme.findall('TestAction/Testables/TestableReference/BuildableReference')}
            self.assertEqual(actual,targets)
            defaults=[node.attrib['reference'] for node in scheme.findall('TestAction/TestPlans/TestPlanReference')
                      if node.attrib.get('default')=='YES']
            self.assertEqual(defaults,['container:'+plan])
            self.assertEqual([node.attrib['reference'] for node in scheme.findall('TestAction/TestPlans/TestPlanReference')],
                             ['container:'+plan])

    def test_runner_readback_checks_a_fresh_container_before_and_after(self):
        driver,world,fresh=self.installed_fixture(product='runner')
        first=driver.installed('en-US/runner-installed-before',required=True,product='runner')
        replacement=fresh.parent.parent/'replacement'/fresh.name
        ipad.shutil.copytree(fresh,replacement)
        world.plan['output']=(str(replacement)+'\n').encode()
        after=driver.installed('en-US/runner-installed-after',required=True,product='runner')
        self.assertNotEqual(first['path'],after['path'])
        self.assertTrue(first['matches_built_bytes'] and after['matches_built_bytes'])
        self.assertEqual(after['bundle_id'],ipad.RUNNER_BUNDLE_ID)
        self.assertEqual(len(world.processes),2)
        for row in driver.report['commands']:
            self.assertEqual(row['argv'][4],ipad.RUNNER_BUNDLE_ID)
            self.assertEqual(row['timeout_seconds'],60)

    def test_runner_readback_rejects_missing_wrong_identity_and_changed_bytes(self):
        original=self.root
        for kind,expected in [('missing','Installed runner unavailable'),
                              ('identity','wrong runner bundle identifier'),
                              ('bytes','Installed runner bytes differ')]:
            with self.subTest(kind=kind):
                self.root=original/kind;self.root.mkdir()
                driver,world,fresh=self.installed_fixture(product='runner')
                if kind=='missing':world.plan['exit']=2
                elif kind=='identity':
                    (fresh/'Info.plist').write_bytes(ipad.plistlib.dumps({'CFBundleIdentifier':ipad.BUNDLE_ID}))
                else:(fresh/'Tripfolio').write_bytes(b'changed synthetic runner')
                with self.assertRaisesRegex(RuntimeError,expected):
                    driver.installed('ru-RU/runner-installed-before',required=True,product='runner')
                self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        self.root=original

    def test_one_runner_install_and_both_fresh_readbacks_precede_acceptance(self):
        driver,world=self.driver();locale,method,size,_=driver.case
        driver.owned='synthetic-owned-device'
        driver.products={'aut':self.root/'Synthetic.app','runner':self.root/'SyntheticRunner.app',
                         'xctestrun':self.root/'synthetic.xctestrun'}
        (driver.out/'originals'/(locale+'.xcresult')).mkdir(parents=True)
        events=[]
        def command(argv,label,**kwargs):
            events.append((label,argv,kwargs))
            return 0,size if label==locale+'-read-size' else ''
        def installed(label,**kwargs):
            events.append((label,kwargs));return {'available':True}
        with patch.object(driver,'command',side_effect=command),patch.object(driver,'installed',side_effect=installed), \
             patch.object(driver,'product_snapshot'),patch.object(driver,'parse_case',return_value={'synthetic':'validated'}):
            driver.run_case(*driver.case)
        labels=[event[0] for event in events]
        self.assertEqual(labels,[locale+'-install',locale+'-runner-install',locale+'/installed-before',
            locale+'/runner-installed-before',locale+'-set-size',locale+'-read-size',locale+'-test',
            locale+'/installed-after',locale+'/runner-installed-after'])
        self.assertEqual(events[1][1],['xcrun','simctl','install',driver.owned,driver.products['runner']])
        self.assertEqual(events[1][2]['timeout'],60)
        self.assertEqual(events[3][1],{'required':True,'product':'runner'})
        self.assertEqual(events[-1][1],{'required':True,'product':'runner'})
        case=driver.report['cases'][0]
        self.assertTrue(case['runner_installed_before'] and case['runner_installed_after'])
        self.assertEqual(case['status'],'passed');self.assertEqual(world.processes,[])

    def test_nonzero_single_runner_install_prevents_native_test(self):
        driver,world=self.driver(exit=4);locale,_,_,_=driver.case
        driver.owned='synthetic-owned-device'
        driver.products={'aut':self.root/'Synthetic.app','runner':self.root/'SyntheticRunner.app'}
        actual=driver.command;labels=[]
        def command(argv,label,**kwargs):
            labels.append(label)
            if label==locale+'-runner-install':return actual(argv,label,**kwargs)
            return 0,''
        with patch.object(driver,'command',side_effect=command),patch.object(driver,'product_snapshot'), \
             patch.object(driver,'installed') as installed,patch.object(driver,'parse_case') as parse:
            with self.assertRaisesRegex(RuntimeError,'runner-install failed'):driver.run_case(*driver.case)
        self.assertEqual(labels,[locale+'-install',locale+'-runner-install'])
        installed.assert_not_called();parse.assert_not_called()
        self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        with self.assertRaisesRegex(RuntimeError,'no retry'):driver.run_case(*driver.case)

    def test_missing_runner_after_successful_install_never_launches_test(self):
        driver,world,_=self.installed_fixture(product='runner',exit=2)
        locale,_,size,_=driver.case
        driver.products['aut']=self.root/'Synthetic.app'
        actual=driver.command;labels=[]
        def command(argv,label,**kwargs):
            labels.append(label)
            if label.endswith('-lookup'):return actual(argv,label,**kwargs)
            return 0,size
        actual_installed=driver.installed
        def installed(label,**kwargs):
            if kwargs.get('product')=='runner':return actual_installed(label,**kwargs)
            return {'available':True}
        with patch.object(driver,'command',side_effect=command),patch.object(driver,'product_snapshot'), \
             patch.object(driver,'installed',side_effect=installed),patch.object(driver,'parse_case') as parse:
            with self.assertRaisesRegex(RuntimeError,'Installed runner unavailable'):driver.run_case(*driver.case)
        self.assertEqual(labels,[locale+'-install',locale+'-runner-install',locale+'/runner-installed-before-lookup'])
        self.assertEqual(len(world.processes),1);parse.assert_not_called()
        self.assertNotIn('xcodebuild_exit_code',driver.report['cases'][0])

    def test_runner_after_failure_prevents_success_but_preserves_native_failure(self):
        original=self.root
        for code in [0,65]:
            with self.subTest(code=code):
                self.root=original/str(code);self.root.mkdir()
                driver,world=self.driver();locale,_,size,_=driver.case
                driver.owned='synthetic-owned-device'
                driver.products={'aut':self.root/'Synthetic.app','runner':self.root/'SyntheticRunner.app',
                                 'xctestrun':self.root/'synthetic.xctestrun'}
                def command(argv,label,**kwargs):
                    return (code,'') if label==locale+'-test' else (0,size)
                def installed(label,**kwargs):
                    if label.endswith('/runner-installed-after'):raise RuntimeError('runner readback failed')
                    return {'available':True}
                with patch.object(driver,'command',side_effect=command),patch.object(driver,'product_snapshot'), \
                     patch.object(driver,'installed',side_effect=installed),patch.object(driver,'parse_case') as parse:
                    with self.assertRaisesRegex(RuntimeError,'runner readback failed' if code==0 else 'xcodebuild failed'):
                        driver.run_case(*driver.case)
                parse.assert_not_called();self.assertEqual(driver.report['cases'][0]['status'],'started')
                self.assertEqual(driver.report['cases'][0]['post_validation_errors'][0]['stage'],'runner-installed-after')
        self.root=original

    def test_first_EN_allows_500_seconds_but_still_requires_result_validation(self):
        driver,world,failure,validated=self.attempted_case(0,delay=500)
        self.assertEqual(str(failure),'Synthetic result validation withheld')
        self.assertTrue(validated);self.assertGreaterEqual(world.t,500);self.assertLess(world.t,900)
        row=self.row(driver);self.assertEqual(row['timeout_seconds'],900)
        args=row['argv'];self.assertEqual(args[args.index('-default-test-execution-time-allowance')+1],'180')
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'480')
        self.assertEqual(args[args.index('-parallel-testing-enabled')+1],'NO')
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        self.assert_finished(driver)

    def test_first_EN_timeout_keeps_one_attempt_and_existing_stop_reserve(self):
        driver,world,failure,validated=self.attempted_case(0,delay=float('inf'),ignore_term=True)
        self.assertIn('en-US-test exceeded its finite timeout',str(failure))
        self.assertFalse(validated);self.assertEqual(self.row(driver)['wait_deadline_monotonic'],900)
        self.assertGreaterEqual(world.t,905);self.assertLessEqual(world.t,907)
        self.assertEqual([name for name,_ in world.calls if name.startswith('signal')],['signal_15','signal_9'])
        self.assertEqual(len(driver.report['cases']),1);self.assert_finished(driver)

    def test_EN_recorded_300_second_cold_start_preserves_full_native_ceiling_and_validation(self):
        # The English host waited299.814s before XCTest began, then its old600s
        # cap interrupted active UI work at300.30s. Preserve all480 native seconds
        # plus90s result finalization, not only the observed incomplete UI slice.
        elapsed=299.814+480+90
        self.assertGreater(elapsed,600)
        driver,world,failure,validated=self.attempted_case(
            0,start_at=309.595,preparation_seconds=28.946,delay=elapsed)
        self.assertEqual(str(failure),'Synthetic result validation withheld')
        self.assertTrue(validated)
        self.assertAlmostEqual(world.processes[0].started,338.541)
        self.assertGreaterEqual(world.t,338.541+elapsed)
        self.assertLess(world.t,338.541+900)
        self.assertGreater(driver.work_deadline-world.t,ipad.CASE_POST_SECONDS)
        self.assertEqual(driver.report['cases'][0]['admission']['required_seconds'],1487)
        args=self.row(driver)['argv']
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'480')
        self.assertEqual(args[args.index('-default-test-execution-time-allowance')+1],'180')
        self.assertEqual(args[args.index('-parallel-testing-enabled')+1],'NO')
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        with self.assertRaisesRegex(RuntimeError,'no retry'):driver.run_case(*driver.case)
        self.assertEqual(len(world.processes),1)

    def test_RU_wait_stops_at_900_with_one_attempt_and_same_content_size(self):
        driver,world,failure,validated=self.attempted_case(1,delay=float('inf'))
        self.assertIn('ru-RU-test exceeded its finite timeout',str(failure))
        self.assertFalse(validated);self.assertEqual(world.t,900)
        self.assertEqual(self.row(driver)['timeout_seconds'],900)
        self.assertEqual(driver.report['cases'][0]['system_content_size_expected'],
                         'accessibility-extra-extra-extra-large')
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        self.assert_finished(driver)

    def test_RU_recorded_cold_start_plus_full_XCTest_ceiling_reaches_result_validation(self):
        # Run41321475035: case admission at366.775s, test process at402.804s,
        # then239.082s before XCTest began. Leave the full480s XCTest ceiling
        # and90s for result finalization, not merely the interrupted331s UI slice.
        elapsed=239.082+480+90
        self.assertGreater(elapsed,570)
        driver,world,failure,validated=self.attempted_case(
            1,start_at=366.775,preparation_seconds=36.029,delay=elapsed)
        self.assertEqual(str(failure),'Synthetic result validation withheld')
        self.assertTrue(validated)
        self.assertAlmostEqual(world.processes[0].started,402.804)
        self.assertGreaterEqual(world.t,402.804+elapsed)
        self.assertLess(world.t,402.804+900)
        self.assertGreater(driver.work_deadline-world.t,ipad.CASE_POST_SECONDS)
        self.assertEqual(driver.report['cases'][0]['admission']['required_seconds'],1487)
        args=self.row(driver)['argv']
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'480')
        self.assertEqual(args[args.index('-default-test-execution-time-allowance')+1],'180')
        self.assertEqual(args[args.index('-parallel-testing-enabled')+1],'NO')
        with self.assertRaisesRegex(RuntimeError,'no retry'):driver.run_case(*driver.case)
        self.assertEqual(len(world.processes),1)

    def test_test_success_at_exact_deadline_is_rejected_before_validation(self):
        for index,locale,allowance in [(0,'en-US',900),(1,'ru-RU',900)]:
            with self.subTest(locale=locale):
                driver,world,failure,validated=self.attempted_case(index,delay=allowance)
                self.assertIn(locale+'-test exceeded its finite timeout',str(failure))
                self.assertEqual(world.t,allowance);self.assertFalse(validated)
                self.assertEqual(self.row(driver)['returncode'],0)
                self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)

    def test_RU_long_success_still_requires_post_test_evidence(self):
        driver,error=self.post_failure_case(locale='ru-RU',delay=239.082+480+90)
        self.assertEqual(error,'Synthetic installed-after budget exhausted')
        self.assertEqual(driver.report['cases'][0]['status'],'started')
        self.assertEqual(driver.report['cases'][0]['xcodebuild_exit_code'],0)

    def test_RU_ordinary_command_is_clipped_by_its_absolute_work_deadline(self):
        driver,world=self.driver(locale='ru-RU',delay=float('inf'));world.t=2000
        with self.assertRaisesRegex(RuntimeError,'finite timeout'):
            driver.command(['synthetic'],'bounded-tail',timeout=900)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'],2093)
        self.assertEqual(world.t,2093)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        self.assertEqual(len(world.processes),1);self.assertFalse(driver.active)
        self.assert_finished(driver)

    def test_RU_cleanup_retains_180_seconds_and_does_not_renew_work(self):
        driver,world=self.driver(locale='ru-RU');world.t=2100
        with self.assertRaisesRegex(RuntimeError,'Work deadline expired'):driver.checkpoint()
        driver.cleanup()
        self.assertTrue(driver.report['cleanup']['verified'])
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        world.t=2279.999;driver.checkpoint()
        world.t=2280
        with self.assertRaisesRegex(RuntimeError,'Cleanup deadline expired'):driver.checkpoint()
        self.assertEqual(world.processes,[])

    def test_discovery_300_allows_70_seconds_and_other_default_stays_30(self):
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
            return 0, '26.2\n' if label == 'simulator-sdk-version' else ('arm64' if label == 'architecture' else '')
        with patch.object(driver, 'source_snapshot', return_value={'status':'', 'head':'a'*40}), \
             patch.object(driver, 'json_command', side_effect=json_command), \
             patch.object(driver, 'command', side_effect=command):
            with self.assertRaisesRegex(RuntimeError, 'No unique exact SDK-matched'): driver.prepare()
        self.assertEqual(self.row(driver)['timeout_seconds'], 300)
        self.assertGreaterEqual(world.t, 70)
        self.assertLess(world.t, 120)
        self.assertEqual(len(world.processes), 1); self.assertFalse(driver.active)
        world.plan['delay'] = 0
        driver.command(['synthetic'], 'default')
        self.assertEqual(self.row(driver)['timeout_seconds'], 30)
        self.assertEqual((driver.work_deadline, driver.final_deadline), (2100, 2280))
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
            return 0, '26.2\n' if label == 'simulator-sdk-version' else ('arm64' if label == 'architecture' else '')
        with patch.object(driver, 'source_snapshot', return_value={'status':'', 'head':'a'*40}), \
             patch.object(driver, 'json_command', side_effect=json_command), \
             patch.object(driver, 'command', side_effect=command), \
             patch.object(ipad, 'choose_pair', wraps=ipad.choose_pair) as choose:
            with self.assertRaises((RuntimeError, json.JSONDecodeError)) as failure:
                driver.prepare()
        self.assertIsNone(driver.owned); self.assertIsNone(driver.intent)
        self.assertEqual(driver.report['cases'], [])
        work=2100
        self.assertEqual((driver.work_deadline, driver.final_deadline), (work, work+180))
        self.assert_finished(driver)
        return failure.exception, reached, choose.called

    def test_initial_runtime_exact_293_completion_is_rejected_before_selection(self):
        driver, world = self.driver(delay=293, output=b'{"runtimes": []}')
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('finite timeout', str(failure))
        self.assertEqual(world.t, 293); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertFalse(driver.active)
        self.assertEqual(self.row(driver)['returncode'], 0)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 293)

    def test_initial_runtime_phase_timeout_one_child_and_existing_7_stop(self):
        driver, world = self.driver(delay=float('inf'), ignore_term=True)
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('finite timeout', str(failure)); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertEqual(len(world.processes), 1)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 293)
        self.assertGreaterEqual(world.t, 298); self.assertLessEqual(world.t, 300)
        self.assertEqual(driver.report['process_stops'][0]['deadline_monotonic'], 300)
        self.assertEqual([n for n, _ in world.calls if n.startswith('signal')], ['signal_15', 'signal_9'])
        self.assertFalse(driver.active)

    def test_initial_runtime_wait_clips_to_work_minus_7_without_spending_cleanup(self):
        driver, world = self.driver(delay=float('inf'), ignore_term=True); world.t = 2030
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('finite timeout', str(failure)); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertEqual(len(world.processes), 1)
        self.assertEqual(self.row(driver)['timeout_seconds'], 300)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 2093)
        self.assertEqual(driver.report['process_stops'][0]['deadline_monotonic'], 2100)
        self.assertLessEqual(world.t, 2100); self.assertFalse(driver.active)

    def test_initial_runtime_exact_clipped_deadline_is_not_inventory_success(self):
        driver, world = self.driver(delay=63, output=b'{"runtimes": []}'); world.t = 2030
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('finite timeout', str(failure))
        self.assertEqual(world.t, 2093); self.assertFalse(selected)
        self.assertEqual(reached, ['runtimes']); self.assertFalse(driver.active)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 2093)

    def test_initial_runtime_exact_7_remaining_never_spawns(self):
        driver, world = self.driver(); world.t = 2093
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('Insufficient command/stop budget', str(failure))
        self.assertEqual(reached, ['runtimes']); self.assertFalse(selected)
        self.assertEqual(world.processes, []); self.assertFalse(driver.active)

    def test_initial_runtime_late_parse_is_rejected_before_device_inventory(self):
        driver, world = self.driver(delay=70, output=b'{"runtimes": []}')
        actual = driver.json_command
        def delayed_parse(*args, **kwargs):
            value = actual(*args, **kwargs)
            world.t = 300
            return value
        with patch.object(driver, 'json_command', side_effect=delayed_parse):
            failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('Discovery deadline expired', str(failure))
        self.assertFalse(selected); self.assertEqual(reached, ['runtimes'])
        self.assertFalse(driver.active)

    def test_initial_runtime_slow_invalid_json_is_not_success(self):
        driver, world = self.driver(delay=70, output=b'not-json')
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIsInstance(failure, json.JSONDecodeError)
        self.assertFalse(selected); self.assertEqual(reached, ['runtimes'])
        self.assertFalse(driver.active); self.assertLess(world.t, 120)

    def test_initial_runtime_longer_wait_reduces_later_case_budget(self):
        driver, world = self.driver(locale='ru-RU',delay=289, output=b'{"runtimes": []}')
        failure, reached, selected = self.initial_runtime(driver)
        self.assertIn('No unique exact SDK-matched', str(failure)); self.assertTrue(selected)
        self.assertEqual(reached, ['runtimes', 'device-types'])
        self.assertGreaterEqual(world.t, 289); self.assertLess(world.t, 290)
        # Fixed synthetic intervening work; no native preparation is claimed.
        world.t += 600
        with self.assertRaisesRegex(RuntimeError, 'no case started'):
            driver.run_case(*driver.case)
        self.assertEqual([case[3] for case in ipad.CASES], [900, 900])
        self.assertEqual(driver.report['cases'][0]['status'],'not_admitted')
        self.assertEqual((driver.work_deadline, driver.final_deadline), (2100, 2280))
        self.assertEqual(len(world.processes), 1); self.assertFalse(driver.active)
        self.assert_finished(driver)

    def complete_discovery(self, costs=None, after_read=None, selection_time=0, intent_time=0, start_at=0, parse_time=0):
        driver,world=self.driver();world.t=start_at
        owned='11111111-2222-4333-8444-555555555555'
        dtype='synthetic.iPad';runtime='com.apple.CoreSimulator.SimRuntime.iOS-26-2'
        runtime_data={'runtimes':[{'identifier':runtime,'version':'26.2','isAvailable':True,
            'supportedArchitectures':['arm64'],'supportedDeviceTypes':[{'identifier':dtype}]}]}
        type_data={'devicetypes':[{'identifier':dtype,'productFamily':'iPad','name':'iPad Pro 13-inch'}]}
        reached=[];actual_command=driver.command;actual_json=driver.json_command
        actual_choose=ipad.choose_pair;actual_write=driver.write
        actual_loads=json.loads
        def loads(text,*args,**kwargs):
            value=actual_loads(text,*args,**kwargs)
            if '"runtimes":' in text:world.t+=parse_time
            return value
        def command(argv,label,**kwargs):
            if label in ['runtimes','device-types','architecture','devices-before','create-owned-ipad','devices-created']:
                reached.append(label)
                outputs={'runtimes':json.dumps(runtime_data),'device-types':json.dumps(type_data),
                    'architecture':'arm64','devices-before':json.dumps({'devices':{runtime:[]}}),
                    'create-owned-ipad':owned}
                if label=='devices-created':
                    output=json.dumps({'devices':{runtime:[{'udid':owned,'name':driver.intent['name'],
                        'deviceTypeIdentifier':dtype}]}})
                else:output=outputs[label]
                world.plan.update(delay=(costs or {}).get(label,0),output=output.encode())
                return actual_command(argv,label,**kwargs)
            if label in ['boot','bootstatus']:reached.append(label)
            return 0, '26.2\n' if label == 'simulator-sdk-version' else ''
        def json_command(argv,label,**kwargs):
            value=actual_json(argv,label,**kwargs)
            world.t+=(after_read or {}).get(label,0)
            return value
        def choose(*args):
            value=actual_choose(*args);world.t+=selection_time;return value
        def write(name,value):
            actual_write(name,value)
            if name=='ownership.json' and value['owned_uuid'] is None:world.t+=intent_time
        error=None
        with patch.object(driver,'source_snapshot',return_value={'status':'','head':'a'*40}), \
             patch.object(driver,'command',side_effect=command), patch.object(driver,'json_command',side_effect=json_command), \
             patch.object(ipad,'choose_pair',side_effect=choose), patch.object(driver,'write',side_effect=write), \
             patch.object(ipad.json,'loads',side_effect=loads), patch('builtins.print'):
            try:driver.prepare()
            except RuntimeError as failure:error=failure
        self.assertIsNone(driver.discovery_deadline)
        self.assertEqual((driver.work_deadline,driver.final_deadline),(2100,2280))
        return driver,world,reached,error

    def test_complete_discovery_near_boundary_has_one_deadline_and_fixed_global_origin(self):
        driver,world,reached,error=self.complete_discovery(start_at=17,costs={
            'runtimes':270,'device-types':5,'architecture':1,'devices-before':5,
            'create-owned-ipad':5,'devices-created':5})
        self.assertIsNone(error);self.assertEqual(driver.report['discovery']['status'],'passed')
        self.assertGreaterEqual(world.t,308);self.assertLess(world.t,310)
        self.assertEqual(driver.report['discovery']['deadline_monotonic'],317)
        self.assertEqual({r['phase_deadline_monotonic'] for r in driver.report['commands']},{317})
        self.assertEqual(reached[-2:],['boot','bootstatus']);self.assertEqual(len(world.processes),6)
        self.assertTrue(all(r['wait_deadline_monotonic']<=310 for r in driver.report['commands']))
        self.assertIsNotNone(driver.owned)

    def test_discovery_shared_remaining_budget_clips_later_inventory_and_stops_before_create(self):
        driver,world,reached,error=self.complete_discovery(costs={
            'runtimes':260,'device-types':20,'architecture':5,'devices-before':15})
        self.assertIn('finite timeout',str(error));self.assertEqual(world.t,293)
        self.assertEqual(reached,['runtimes','device-types','architecture','devices-before'])
        self.assertIsNone(driver.owned);self.assertIsNone(driver.intent)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'],293)
        self.assertTrue(all(s['deadline_monotonic']<=300 for s in driver.report['process_stops']))

    def test_discovery_parse_and_selection_cannot_admit_next_query_after_expiry(self):
        original=self.root
        for stage in ['runtimes','device-types','devices-before','selection','intent']:
            with self.subTest(stage=stage):
                self.root=original/stage;self.root.mkdir()
                kwargs={'after_read':{stage:300}} if stage not in ['selection','intent'] else {
                    'selection_time' if stage=='selection' else 'intent_time':300}
                driver,world,reached,error=self.complete_discovery(**kwargs)
                self.assertIn('Discovery deadline expired',str(error))
                self.assertNotIn('create-owned-ipad',reached);self.assertIsNone(driver.owned)
                self.assertEqual(driver.report['discovery']['status'],'failed')
                if stage=='runtimes':self.assertEqual(reached,['runtimes'])
                if stage=='device-types':self.assertEqual(reached,['runtimes','device-types'])
                if stage=='selection':self.assertNotIn('devices-before',reached)
        self.root=original

    def test_late_created_identity_is_not_accepted_and_preserves_owned_cleanup_identity(self):
        driver,world,reached,error=self.complete_discovery(after_read={'devices-created':300})
        self.assertIn('Discovery deadline expired',str(error));self.assertNotIn('boot',reached)
        self.assertEqual(driver.owned,'11111111-2222-4333-8444-555555555555')
        self.assertEqual(driver.report['discovery']['status'],'failed')

    def test_actual_JSON_parse_reaching_query_deadline_cannot_admit_next_inventory(self):
        driver,world,reached,error=self.complete_discovery(parse_time=293)
        self.assertIn('Discovery inventory parsing reached its wait deadline',str(error))
        self.assertEqual(reached,['runtimes']);self.assertEqual(world.t,293)
        self.assertIsNone(driver.owned);self.assertIsNone(driver.intent)

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
        driver, world = self.driver(); world.t = 2093
        with self.assertRaisesRegex(RuntimeError, 'Insufficient'): driver.command(['synthetic'], 'edge')
        self.assertEqual(world.processes, []); self.assertNotIn('owned_process_group', self.row(driver))
        self.assert_finished(driver)

    def test_receipt_time_before_spawn_cannot_consume_stop_reserve(self):
        driver, world = self.driver(); world.t = 2092
        original = driver.save
        def slow_save():
            original(); world.t += 1
        with patch.object(driver, 'save', side_effect=slow_save):
            with self.assertRaisesRegex(RuntimeError, 'Insufficient'): driver.command(['synthetic'], 'slow-save')
        self.assertEqual(world.processes, []); self.assert_finished(driver)

    def test_just_more_than_7_and_timeout_plus_7_preserve_global_reserve(self):
        driver, world = self.driver(delay=float('inf'))
        world.t = 2092.99
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'tiny', timeout=60)
        self.assertAlmostEqual(world.t, 2093)
        self.assertLessEqual(world.t, driver.work_deadline); self.assertFalse(driver.active)
        world.t = 2033
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'):
            driver.command(['synthetic'], 'full', timeout=60)
        self.assertEqual(world.t, 2093); self.assertEqual(len(world.processes), 2)
        self.assertEqual(self.row(driver)['wait_deadline_monotonic'], 2093)

    def test_deadline_between_TERM_and_KILL_withholds_later_operations(self):
        driver, world = self.driver(delay=float('inf'), ignore_all=True, signal_seconds=7)
        world.t = 2092
        with self.assertRaisesRegex(RuntimeError, 'finite timeout'): driver.command(['synthetic'], 'deadline')
        self.assertEqual(world.t, 2100); self.assertTrue(driver.active)
        self.assertIn('stop deadline', self.row(driver)['stop_error'])
        self.assertEqual(world.calls[-1], ('signal_15', 2093))
        self.assertFalse(any(name == 'signal_9' for name, _ in world.calls))
        self.assert_finished(driver)

    def test_cleanup_final_deadline_allows_no_probe_or_signal(self):
        driver, world = self.driver(delay=float('inf'), probe_error=PermissionError(errno.EPERM, 'denied'))
        with self.assertRaises(RuntimeError): driver.command(['synthetic'], 'hold')
        before = list(world.calls); world.t = 2280
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
