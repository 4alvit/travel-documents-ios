"""Pure controls for the actual evidence adapter; no native processes or signals."""
import copy
import errno
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    module = importlib.util.module_from_spec(spec)
    with patch('subprocess.Popen', side_effect=AssertionError('Real process forbidden')), \
            patch('os.killpg', side_effect=AssertionError('Real signal forbidden')):
        spec.loader.exec_module(module)
    return module


adapter = load('files_failure_tested', 'files_picker_failure.py')
fakes = load('existing_hosted_fakes', 'test-recovery-hosted.py')
SHA = 'a'*40
DEVICE = dict(deviceId='11111111-1111-1111-1111-111111111111', deviceName='Synthetic phone',
              modelName='iPhone', osVersion='26.2', platform='iOS Simulator')
CONFIG = dict(configurationId='1', configurationName='Local StoreKit')
ENV = dict(GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2', GITHUB_SHA=SHA,
           GITHUB_ACTIONS='true', RUNNER_OS='macOS')


def tree(restore='Failed', imported='Failed'):
    return dict(devices=[DEVICE], testPlanConfigurations=[CONFIG], testNodes=[dict(
        nodeType='Test Suite', children=[dict(nodeType='Test Case', nodeIdentifier=case, result=result)
                                       for (case, _), result in zip(adapter.CASES, (restore, imported))])])


def attachments(selected):
    rows = []
    for kind, suffix, ext in [('png', '', 'png'), ('ax', selected.get('ax_suffix', ' — accessibility hierarchy'), 'txt')]:
        rows.append(dict(exportedFileName='synthetic.'+ext, deviceId=DEVICE['deviceId'],
                         configurationName=CONFIG['configurationName'], isAssociatedWithFailure=False,
                         suggestedHumanReadableName=selected['label']+suffix+'_0_'+DEVICE['deviceId']+'.'+ext))
    return [dict(testIdentifier=selected['case'], attachments=rows)]


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        (self.repo/'build').mkdir()
        for target in ('subprocess.Popen', 'os.killpg'):
            guard = patch(target, side_effect=AssertionError('Real process/signal forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        floor = patch.object(adapter.shutil, 'disk_usage', return_value=SimpleNamespace(free=32*1024**3))
        floor.start()
        self.addCleanup(floor.stop)

    def runner(self, ops=None):
        return adapter.Evidence(self.repo, ENV, ops or fakes.Ops())

    def test_restore_priority_unrelated_failure_and_import_fallback(self):
        data = tree()
        data['testNodes'].append(dict(nodeType='Test Case', nodeIdentifier='Other/test()', result='Failed'))
        self.assertEqual(adapter.select_case(data)['case'], adapter.CASES[0][0])
        self.assertEqual(adapter.select_case(tree('Passed'))['case'], adapter.CASES[1][0])
        data = tree()
        data['testNodes'][0]['children'].pop(0)
        self.assertEqual(adapter.select_case(data)['case'], adapter.CASES[1][0])
        with self.assertRaisesRegex(RuntimeError, 'No failed relevant'):
            adapter.select_case(tree('Passed', 'Passed'))
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
            adapter.select_case(tree('Skipped'))

    def test_ambiguous_case_device_config_and_json_rejected(self):
        mutations = [lambda d: d['testNodes'][0]['children'].append(d['testNodes'][0]['children'][0]),
                     lambda d: d['devices'].append(DEVICE),
                     lambda d: d['testPlanConfigurations'].append(CONFIG)]
        for change in mutations:
            data = tree(); change(data)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                adapter.select_case(data)
        with self.assertRaises(RuntimeError):
            adapter.parse('{"devices":[],"devices":[]}')

    def test_exact_pair_from_actual_device_configuration_keepalways(self):
        selected = adapter.select_case(tree())
        pair = adapter.select_pair(attachments(selected), selected)
        self.assertEqual(set(pair), {'png', 'ax'})
        self.assertFalse(pair['png']['isAssociatedWithFailure'])
        self.assertEqual(selected['configuration'], CONFIG)

    def test_wrong_case_pair_names_device_config_duplicates_and_path_rejected(self):
        selected = adapter.select_case(tree())
        changes = [lambda m: m[0].update(testIdentifier=adapter.CASES[1][0]),
                   lambda m: m[0]['attachments'][0].update(deviceId='2'*36),
                   lambda m: m[0]['attachments'][0].update(configurationName='Other'),
                   lambda m: m[0]['attachments'][0].update(exportedFileName='../private.png'),
                   lambda m: m[0]['attachments'][0].update(suggestedHumanReadableName='Wrong.png'),
                   lambda m: m[0]['attachments'].append(dict(m[0]['attachments'][0]))]
        for change in changes:
            data = attachments(selected); change(data)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                adapter.select_pair(data, selected)

    def test_actual_collect_exports_once_and_retains_only_pair_and_receipt(self):
        for relative in adapter.SOURCE_FILES:
            target = self.repo/relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'Synthetic source binding fixture')
        tool = self.repo/'xcresulttool'; tool.write_bytes(b'synthetic never executed')
        bundle = self.repo/'build/Tests-20261028T120000Z.xcresult'; bundle.mkdir()
        (bundle/'Info.plist').write_bytes(b'synthetic bundle')
        data = tree()
        selected = adapter.select_case(data)
        outputs = [SHA+'\n', str(tool)+'\n', json.dumps(data), '']
        ops = fakes.Ops(*[dict(output=[('stdout', text.encode())]) for text in outputs])
        run = self.runner(ops)
        exports = []
        def on_spawn(argv):
            if 'export' in argv:
                exports.append(argv)
                dest = Path(argv[argv.index('--output-path')+1]); dest.mkdir()
                (dest/'manifest.json').write_text(json.dumps(attachments(selected)))
                (dest/'synthetic.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II', 2, 3))
                (dest/'synthetic.txt').write_text('Synthetic Files navigation hierarchy')
                (dest/'unrelated.log').write_text('Must not be published')
        ops.on_spawn = on_spawn
        run.collect()
        self.assertEqual(len(exports), 1)
        self.assertEqual(exports[0][-2:], ['--test-id', adapter.CASES[0][0]])
        self.assertTrue(run.finish())
        self.assertEqual({p.name for p in run.public.iterdir()}, {'failure.png', 'failure-ax.txt', 'evidence.json'})
        receipt = json.loads((run.public/'evidence.json').read_text())
        self.assertTrue(receipt['cases']['files']['input_unchanged'] and receipt['all_owned_groups_closed']
                        and receipt['temporary_cleanup_verified'])
        self.assertFalse(receipt['runtime_acceptance'])
        self.assertNotIn(str(self.repo), (run.public/'evidence.json').read_text())
        self.assertFalse(run.out.exists())
        self.assertEqual([r['requested_cap_seconds'] for r in run.report['commands']], [30, 12, 30, 60])

    def disposable_fixture(self, attempt='2', mutate=None):
        self.fixture_sources()
        tool = self.repo/'xcresulttool'; tool.write_bytes(b'synthetic never executed')
        bundle = self.repo/'build/Tests-20261028T120000Z.xcresult'
        bundle.mkdir(exist_ok=True); (bundle/'Info.plist').write_bytes(b'original immutable result')
        (bundle/'Info.plist').chmod(0o644)
        data = tree('Passed'); selected = adapter.select_case(data)
        ops = fakes.Ops(*[dict(output=[('stdout', text.encode())])
                          for text in (SHA+'\n', str(tool)+'\n', json.dumps(data), '')])
        run = adapter.Evidence(self.repo, dict(ENV, GITHUB_RUN_ATTEMPT=attempt), ops)
        paths = []
        def on_spawn(argv):
            if '--path' not in argv:
                return
            working = Path(argv[argv.index('--path')+1]); paths.append(working)
            self.assertEqual(working, run.working)
            self.assertNotEqual(working, bundle)
            if mutate is not None:
                mutate(bundle, working, argv)
            if 'export' in argv:
                dest = Path(argv[argv.index('--output-path')+1]); dest.mkdir()
                (dest/'manifest.json').write_text(json.dumps(attachments(selected)))
                (dest/'synthetic.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II', 2, 3))
                (dest/'synthetic.txt').write_text('Synthetic failed Import hierarchy')
        ops.on_spawn = on_spawn
        return run, bundle, paths

    def test_actual_cache_creation_uses_copy_preserves_original_and_retains_pair(self):
        def cache(original, working, argv):
            (working/'database.sqlite3').write_bytes(b'bounded synthetic decoder cache')
        run, bundle, paths = self.disposable_fixture(mutate=cache)
        original = adapter.core.tree_manifest(bundle)
        run.collect()
        self.assertEqual(len(paths), 2)
        self.assertEqual(adapter.core.tree_manifest(bundle), original)
        self.assertFalse((bundle/'database.sqlite3').exists())
        self.assertEqual(run.evidence['disposable_input']['changes'][0]['path'], 'database.sqlite3')
        self.assertIsNone(run.evidence['disposable_input']['changes'][0]['before'])
        self.assertTrue(run.finish())
        self.assertEqual({p.name for p in run.public.iterdir()}, {'failure.png','failure-ax.txt','evidence.json'})
        self.assertFalse(run.working.exists())
        self.assertEqual(adapter.core.tree_manifest(bundle), original)

    def test_original_content_mode_deletion_and_noncache_copy_changes_refuse(self):
        changes = [lambda o,w: (o/'Info.plist').write_bytes(b'changed'),
                   lambda o,w: (o/'Info.plist').chmod(0o600),
                   lambda o,w: (o/'Info.plist').unlink(),
                   lambda o,w: (w/'Info.plist').write_bytes(b'changed')]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                run, bundle, paths = self.disposable_fixture(str(10+index),
                    lambda o,w,a: change(o,w) if 'get' in a else None)
                with self.assertRaisesRegex(RuntimeError, 'Input result changed|Non-cache disposable input changed'):
                    run.collect()
                self.assertEqual(len(paths), 1)  # No export after invalid test-tree input.
                self.assertFalse(run.finish())
                self.assertEqual({p.name for p in run.public.iterdir()}, {'evidence.json'})
                self.assertFalse(run.working.exists())

    def test_copy_input_limit_and_original_work_deadline_are_not_renewed(self):
        run, bundle, _ = self.disposable_fixture()
        with patch.object(adapter, 'INPUT', 4), self.assertRaisesRegex(RuntimeError, 'Manifest size cap'):
            run.collect()
        self.assertEqual(len(run.ops.processes), 1)  # Only existing checkout; no native decoder.
        self.assertFalse(run.finish())
        run, bundle, _ = self.disposable_fixture('3')
        copy_tree = adapter.core.Recovery.copy_tree
        def late_copy(owner, source, target, manifest):
            owner.ops.t = adapter.WORK
            return copy_tree(owner, source, target, manifest)
        with patch.object(adapter.core.Recovery, 'copy_tree', side_effect=late_copy), \
                self.assertRaisesRegex(RuntimeError, 'Original evidence deadline'):
            run.collect()
        self.assertEqual((run.limit, run.final_deadline), (100, 120))
        self.assertEqual(len(run.ops.processes), 1)
        self.assertFalse(run.finish())
        self.assertFalse(run.working.exists())

    def test_complete_owned_and_original_output_caps_are_both_enforced(self):
        run = self.runner()
        def size(n): return dict(logical=n, allocated=n, entries=1)
        with patch.object(adapter.core, 'live_sizes', side_effect=[size(100*adapter.MIB),size(1),size(1)]):
            run.checkpoint(force_resources=True)
        with patch.object(adapter.core, 'live_sizes', return_value=size(adapter.OWNED+1)), \
                self.assertRaisesRegex(RuntimeError, 'Evidence owned cap'):
            run.checkpoint(force_resources=True)
        with patch.object(adapter.core, 'live_sizes', side_effect=[size(100*adapter.MIB),size(adapter.OUTPUT),size(1)]), \
                self.assertRaisesRegex(RuntimeError, 'Evidence output cap'):
            run.checkpoint(force_resources=True)

    def fixture_sources(self):
        for relative in adapter.SOURCE_FILES:
            target = self.repo/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'Synthetic source binding fixture')

    def test_checkout_failure_preserves_source_pins_primary_error_exit_and_stderr(self):
        self.fixture_sources()
        stderr = b'irrelevant prefix '*60+b'fatal: synthetic checkout failure\n'
        ops = fakes.Ops(dict(exit=128, output=[('stderr', stderr)]))
        run = self.runner(ops)
        def on_spawn(argv):
            self.assertEqual(set(run.evidence['source_files']), set(adapter.SOURCE_FILES))
            self.assertFalse(run.evidence['checkout_verified'])
        ops.on_spawn = on_spawn
        with self.assertRaisesRegex(RuntimeError, 'checkout failed'):
            run.collect()
        self.assertFalse(run.finish())
        receipt = json.loads((run.public/'evidence.json').read_text())
        row = receipt['commands'][0]
        self.assertEqual(row['returncode'], 128)
        self.assertTrue(row['returncode_observed'])
        self.assertIn('Nonzero command exit: 128', row['errors']['error'])
        self.assertIn('fatal: synthetic checkout failure', row['stderr']['text'])
        self.assertEqual(row['stderr']['retained_tail_bytes'], 512)
        self.assertTrue(row['stderr']['truncated'])
        self.assertEqual(row['stop'], dict(group_absent=True, leader_reaped=True, signals=[]))
        self.assertTrue(receipt['temporary_cleanup_verified'] and receipt['all_owned_groups_closed'])
        self.assertFalse(run.out.exists())
        self.assertLessEqual((run.public/'evidence.json').stat().st_size, 16*1024)

    def test_checkout_allocation_and_original_work_stop_deadline(self):
        ops = fakes.Ops(dict(delay=10, output=[('stdout', b'passed')]), dict(delay=8))
        run = self.runner(ops)
        self.assertEqual(run.command('checkout', ['synthetic'], 30), 'passed')
        self.assertEqual(run.report['commands'][0]['work_deadline'], 22)
        self.assertEqual(run.report['commands'][0]['command_deadline'], 30)
        ops.t = 85
        with self.assertRaisesRegex(RuntimeError, 'checkout failed'):
            run.command('checkout', ['synthetic'], 30)
        row = run.report['commands'][-1]
        self.assertEqual(row['work_deadline'], 92)
        self.assertEqual(row['command_deadline'], 100)
        self.assertLessEqual(ops.t, 100)
        self.assertFalse(run.active)
        self.assertEqual((run.limit, run.final_deadline), (100, 120))
        self.assertIn('Command timeout', row['error'])
        self.assertFalse(run.finish())
        saved = run.evidence['commands'][-1]
        self.assertIsNone(saved['returncode'])
        self.assertFalse(saved['returncode_observed'])
        self.assertEqual(saved['reaped_returncode'], 0)  # Explicit fake stop poll, not command completion.

    def test_failed_stderr_is_only_exact_owned_regular_log(self):
        run = self.runner()
        outside = self.repo/'outside'; outside.write_bytes(b'private unrelated output')
        row = dict(id='checkout', bytes=dict(stderr=outside.stat().st_size), logs=dict(stderr=str(outside)))
        result = run.failed_stderr_tail(row, 1)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('text', result)
        owned = run.out/'1-stderr.log'; owned.symlink_to(outside)
        row['logs']['stderr'] = str(owned)
        result = run.failed_stderr_tail(row, 1)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('text', result)
        run.ops.t = adapter.WORK
        with patch('os.open', side_effect=AssertionError('Late work I/O')):
            self.assertEqual(run.failed_stderr_tail(row, 1)['reason'], 'original work deadline/interruption')

    def test_payment_selection_exact_case_and_its_distinct_ax_suffix(self):
        data = tree()
        data['testNodes'].append(dict(nodeType='Test Case', nodeIdentifier=adapter.PAYMENT_CASES[0][0], result='Failed'))
        selected = adapter.select_cases(data)
        self.assertEqual([r['kind'] for r in selected], ['files', 'payment'])
        self.assertEqual(selected[0]['case'], adapter.CASES[0][0])
        self.assertEqual(selected[1]['ax_suffix'], ' — accessibility')
        self.assertEqual(set(adapter.select_pair(attachments(selected[1]), selected[1])), {'png', 'ax'})
        wrong = attachments(selected[1])
        wrong[0]['attachments'][1]['suggestedHumanReadableName'] = wrong[0]['attachments'][1]['suggestedHumanReadableName'].replace(' — accessibility_', ' — accessibility hierarchy_')
        with self.assertRaisesRegex(RuntimeError, 'Exact failed assertion pair missing'):
            adapter.select_pair(wrong, selected[1])
        data['testNodes'][-1]['result'] = 'Passed'
        self.assertEqual(len(adapter.select_cases(data)), 1)
        data = tree('Passed', 'Passed')
        data['testNodes'].append(dict(nodeType='Test Case', nodeIdentifier=adapter.PAYMENT_CASES[0][0], result='Failed'))
        self.assertEqual([r['kind'] for r in adapter.select_cases(data)], ['payment'])

    def test_two_exact_exports_preserve_first_pair_if_second_fails(self):
        for payment_fails in (False, True):
            with self.subTest(payment_fails=payment_fails):
                # Each synthetic run has its own original immutable scope.
                env = dict(ENV, GITHUB_RUN_ATTEMPT='3' if payment_fails else '2')
                self.fixture_sources()
                tool = self.repo/'xcresulttool'; tool.write_bytes(b'synthetic never executed')
                bundle = self.repo/'build/Tests-20261028T120000Z.xcresult'
                bundle.mkdir(exist_ok=True); (bundle/'Info.plist').write_bytes(b'synthetic bundle')
                data = tree('Passed')
                data['testNodes'].append(dict(nodeType='Test Case', nodeIdentifier=adapter.PAYMENT_CASES[0][0], result='Failed'))
                selected = {r['case']:r for r in adapter.select_cases(data)}
                plans = [dict(output=[('stdout', v.encode())]) for v in (SHA+'\n', str(tool)+'\n', json.dumps(data), '')]
                plans.append(dict(exit=1, output=[('stderr', b'synthetic second export rejected')]) if payment_fails else {})
                ops = fakes.Ops(*plans)
                run = adapter.Evidence(self.repo, env, ops)
                exports = []
                def on_spawn(argv):
                    if 'export' not in argv:
                        return
                    exports.append(argv)
                    if len(exports) == 2 and payment_fails:
                        return
                    item = selected[argv[-1]]
                    dest = Path(argv[argv.index('--output-path')+1]); dest.mkdir()
                    (dest/'manifest.json').write_text(json.dumps(attachments(item)))
                    (dest/'synthetic.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II', 2, 3))
                    (dest/'synthetic.txt').write_text('Synthetic owned failure hierarchy')
                    (dest/'unrelated.log').write_text('Never publish')
                ops.on_spawn = on_spawn
                run.collect()
                self.assertEqual(len(exports), 2)
                self.assertEqual([r[-1] for r in exports], list(selected))
                self.assertEqual(run.finish(), not payment_fails)
                receipt = json.loads((run.public/'evidence.json').read_text())
                self.assertEqual(receipt['cases']['files']['status'], 'complete')
                expected = {'failure.png', 'failure-ax.txt', 'evidence.json'}
                if payment_fails:
                    self.assertEqual(receipt['status'], 'partial')
                    self.assertEqual(receipt['cases']['payment']['failed_stage'], 'payment/export')
                    self.assertIn('synthetic second export rejected', receipt['commands'][-1]['stderr']['text'])
                else:
                    expected.update(['payment-failure.png', 'payment-failure-ax.txt'])
                    self.assertTrue(receipt['cases']['payment']['input_unchanged'])
                self.assertEqual({p.name for p in run.public.iterdir()}, expected)
                self.assertTrue(receipt['all_owned_groups_closed'] and receipt['temporary_cleanup_verified'])
                self.assertLessEqual((run.public/'evidence.json').stat().st_size, 16*1024)

    def test_first_export_failure_withholds_other_case_and_keeps_diagnosis(self):
        self.fixture_sources()
        tool = self.repo/'xcresulttool'; tool.write_bytes(b'synthetic never executed')
        bundle = self.repo/'build/Tests-20261028T120000Z.xcresult'; bundle.mkdir()
        (bundle/'Info.plist').write_bytes(b'synthetic bundle')
        data = tree()
        data['testNodes'].append(dict(nodeType='Test Case', nodeIdentifier=adapter.PAYMENT_CASES[0][0], result='Failed'))
        ops = fakes.Ops(*[dict(output=[('stdout', text.encode())])
                          for text in (SHA+'\n', str(tool)+'\n', json.dumps(data))],
                        dict(exit=7, output=[('stderr', b'synthetic first export failure')]))
        run = self.runner(ops)
        run.collect()
        self.assertEqual(len(ops.processes), 4)
        self.assertEqual(run.evidence['cases']['files']['status'], 'failed')
        self.assertEqual(run.evidence['cases']['payment']['status'], 'not_attempted')
        self.assertFalse(run.finish())
        self.assertEqual(run.evidence['commands'][-1]['returncode'], 7)
        self.assertIn('synthetic first export failure', run.evidence['commands'][-1]['stderr']['text'])
        self.assertTrue(run.evidence['all_owned_groups_closed'])

    def test_stderr_close_error_still_closes_both_and_preserves_primary(self):
        ops = fakes.Ops(dict(exit=7, output=[('stderr', b'synthetic primary failure')]))
        run = self.runner(ops)
        with self.assertRaisesRegex(RuntimeError, 'checkout failed'):
            run.command('checkout', ['synthetic'], 30)
        real_close = os.close
        closed = []
        def close_with_error(fd):
            closed.append(fd)
            real_close(fd)  # Avoid a real leak in the fake error control.
            if len(closed) == 1:
                raise OSError(errno.EIO, 'synthetic close uncertainty')
        with patch.object(adapter.os, 'close', side_effect=close_with_error):
            self.assertFalse(run.finish())
        self.assertGreaterEqual(len(closed), 2)
        self.assertNotEqual(closed[0], closed[1])
        saved = json.loads((run.public/'evidence.json').read_text())
        row = saved['commands'][0]
        self.assertEqual(row['returncode'], 7)
        self.assertIn('Nonzero command exit: 7', row['errors']['error'])
        self.assertFalse(row['stderr']['fd_closure_confirmed'])
        self.assertEqual(row['stderr']['secondary_close_errors'],
                         [dict(descriptor='stderr', error_type='OSError', errno=errno.EIO)])
        self.assertTrue(saved['temporary_cleanup_verified'] and saved['all_owned_groups_closed'])
        self.assertFalse(run.out.exists())

    def test_optional_diagnostics_exception_cannot_replace_primary_or_block_finalization(self):
        ops = fakes.Ops(dict(exit=13))
        run = self.runner(ops)
        with self.assertRaisesRegex(RuntimeError, 'checkout failed'):
            run.command('checkout', ['synthetic'], 30)
        run.evidence.update(failed_stage='checkout', error_type='RuntimeError', error='checkout failed')
        with patch.object(run, 'command_diagnostics', side_effect=RuntimeError('synthetic optional failure')):
            self.assertFalse(run.finish())
        saved = json.loads((run.public/'evidence.json').read_text())
        self.assertEqual(saved['error'], 'checkout failed')
        self.assertEqual(saved['failed_stage'], 'checkout')
        self.assertEqual(saved['commands'][0]['returncode'], 13)
        self.assertIn('Nonzero command exit: 13', saved['commands'][0]['errors']['error'])
        self.assertEqual(saved['secondary_diagnostics_error'], dict(error_type='RuntimeError', errno=None))
        self.assertTrue(saved['temporary_cleanup_verified'] and saved['all_owned_groups_closed'])
        self.assertFalse(run.out.exists())
        self.assertEqual((run.limit, run.final_deadline), (100, 120))

    def test_pending_scan_cannot_spend_command_stop_reserve(self):
        run = self.runner()
        run.report['commands'].append(dict(work_deadline=.1))
        def usage(_):
            run.ops.t = .11
            return SimpleNamespace(free=32*1024**3)
        with patch.object(adapter.shutil, 'disk_usage', side_effect=usage), \
                patch.object(adapter.core, 'live_sizes') as scan:
            with self.assertRaisesRegex(RuntimeError, 'Original command scan deadline'):
                run.checkpoint(force_resources=True)
            scan.assert_not_called()

    def test_actual_command_timeout_closes_owned_group_within_original_cap(self):
        ops = fakes.Ops(dict(delay=23))
        run = self.runner(ops)
        with self.assertRaisesRegex(RuntimeError, 'test-tree failed'):
            run.command('test-tree', ['synthetic'], 30)
        row = run.report['commands'][0]
        self.assertEqual(row['work_deadline'], 22)
        self.assertEqual(row['command_deadline'], 30)
        self.assertLessEqual(ops.t, 30)
        self.assertTrue(row['stop']['group_absent'] and row['stop']['leader_reaped'])
        self.assertFalse(run.active)

    def test_global_clip_and_insufficient_stop_reserve_admit_no_process(self):
        ops = fakes.Ops()
        run = self.runner(ops)
        ops.t = 95
        with self.assertRaisesRegex(RuntimeError, 'Insufficient command/stop budget'):
            run.command('export', ['synthetic'], 60)
        self.assertEqual(ops.processes, [])

    def test_expired_finalization_starts_no_stat_read_write_or_print(self):
        run = self.runner(); run.ops.t = adapter.WHOLE
        with patch.object(adapter.core, 'identity_of', side_effect=AssertionError('Late stat')), \
                patch.object(Path, 'open', side_effect=AssertionError('Late open')), \
                patch.object(Path, 'exists', side_effect=AssertionError('Late stat')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('Late read')), \
                patch('builtins.print', side_effect=AssertionError('Late print')):
            with self.assertRaisesRegex(RuntimeError, 'Original evidence deadline'):
                run.finish()

    def test_same_attempt_scope_and_link_file_rejected(self):
        run = self.runner()
        with self.assertRaises(FileExistsError):
            self.runner()
        outside = self.repo/'private'; outside.write_bytes(b'not an attachment')
        link = run.out/'link'; link.symlink_to(outside)
        with self.assertRaises(OSError):
            run.read(link, adapter.MIB)

    def test_symlink_build_parent_creates_no_evidence_outside_repo(self):
        (self.repo/'build').rmdir()
        outside = self.repo/'outside'; outside.mkdir()
        (self.repo/'build').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved/symlink'):
            self.runner()
        self.assertEqual(list(outside.iterdir()), [])

    def test_interruption_preserves_cleanup_within_original_final_deadline(self):
        run = self.runner(); run.interrupted = True
        self.assertFalse(run.finish())
        self.assertTrue(run.evidence['temporary_cleanup_verified'])

    def test_unknown_process_withholds_cleanup_and_cannot_report_success(self):
        run = self.runner(); run.unknown_spawn = True; run.evidence['status'] = 'complete'
        self.assertFalse(run.finish())
        self.assertTrue(run.out.exists())
        self.assertFalse(run.evidence['all_owned_groups_closed'])
        self.assertFalse(run.evidence['temporary_cleanup_verified'])

    def test_workflow_preserves_original_result_and_full_bundle_upload(self):
        workflow = (HERE.parent/'.github/workflows/ci.yml').read_text()
        original = workflow.split('      - name: Simulator integration and StoreKit tests\n')[1].split('      - name:')[0]
        self.assertIn('id: integration', original)
        self.assertIn('run: bash scripts/test-simulator.sh', original)
        self.assertNotIn('continue-on-error', original)
        self.assertIn("if: ${{ failure() && steps.integration.outcome == 'failure' }}", workflow)
        self.assertIn('path: build/*.xcresult', workflow)
        public = workflow.split('name: TripDocket-files-picker-failure-')[1].split('if-no-files-found')[0]
        self.assertNotIn('scratch', public)
        self.assertNotIn('*', public)
        self.assertEqual(public.count('/public/'), 5)
        self.assertEqual(workflow.count('timeout-minutes: 35'), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
