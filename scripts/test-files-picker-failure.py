"""Pure controls for the actual evidence adapter; no native processes or signals."""
import copy
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
    for kind, suffix, ext in [('png', '', 'png'), ('ax', ' — accessibility hierarchy', 'txt')]:
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
        for relative in ('scripts/files_picker_failure.py', 'scripts/recovery_core.py', 'scripts/recovery_process.py',
                         'scripts/test-simulator.sh', 'UITests/AccessibilityUITests.swift', '.github/workflows/ci.yml'):
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
        self.assertTrue(receipt['input_unchanged'] and receipt['all_owned_groups_closed']
                        and receipt['temporary_cleanup_verified'])
        self.assertFalse(receipt['runtime_acceptance'])
        self.assertNotIn(str(self.repo), (run.public/'evidence.json').read_text())
        self.assertFalse(run.out.exists())
        self.assertEqual([r['requested_cap_seconds'] for r in run.report['commands']], [12, 12, 30, 60])

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
        self.assertEqual(public.count('/public/'), 3)
        self.assertEqual(workflow.count('timeout-minutes: 35'), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
