#!/usr/bin/env python3
"""Offline checks for the bounded metadata probe; no native command executes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('probe-xcode-toolchain.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Clock:
    def __init__(self, plans):
        self.now, self.plans, self.processes, self.signals = 285, iter(plans), [], []

    def spawn(self, argv, stdout, stderr, start_new_session):
        assert start_new_session
        plan = next(self.plans)
        process = Process(self, plan)
        stdout.write(plan.get('output', b'captured metadata'))
        stdout.flush()
        self.processes.append(process)
        return process

    def sleep(self, seconds):
        self.now += seconds

    def killpg(self, pid, sig):
        process = next(p for p in self.processes if p.pid == pid)
        process.poll()
        if not process.group:
            raise ProcessLookupError()
        if sig:
            self.signals.append((pid, sig, self.now))
            if process.plan.get('signal_error'):
                raise PermissionError('synthetic signal failure')
            if sig == signal.SIGKILL or not process.plan.get('ignore_term'):
                process.returncode, process.group = -sig, False


class Process:
    def __init__(self, clock, plan):
        self.clock, self.plan, self.start = clock, plan, clock.now
        self.pid, self.returncode, self.group = len(clock.processes) + 100, None, True

    def poll(self):
        if self.returncode is None and self.clock.now >= self.start + self.plan.get('delay', 0):
            self.returncode = self.plan.get('exit', 0)
            self.group = self.plan.get('orphan', False)
        return self.returncode


class ProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(probe.subprocess, 'Popen', side_effect=AssertionError('Unexpected native command')).start()
        patch.object(probe.os, 'killpg', side_effect=AssertionError('Unexpected native signal')).start()

    def clock(self, plans):
        clock = Clock(plans)
        patch.object(probe.time, 'monotonic', side_effect=lambda: clock.now).start()
        patch.object(probe.time, 'sleep', side_effect=clock.sleep).start()
        patch.object(probe.subprocess, 'Popen', side_effect=clock.spawn).start()
        patch.object(probe.os, 'killpg', side_effect=clock.killpg).start()
        return clock

    def test_commands_share_deadline_and_timeout_kills_reaps_without_retry(self):
        clock = self.clock([{'delay': 6}, {'delay': float('inf'), 'ignore_term': True}])
        report = {'start': 0, 'commands': []}
        with self.assertRaisesRegex(RuntimeError, 'Shared probe work deadline'):
            for name in ('first', 'second', 'never'):
                probe.command(name, ['read-only', name], self.output, 300, report)
        self.assertEqual([r['id'] for r in report['commands']], ['first', 'second'])
        self.assertEqual(len(clock.processes), 2)
        self.assertEqual([s[1] for s in clock.signals], [signal.SIGTERM, signal.SIGKILL])
        self.assertTrue(all(s[2] < 300 for s in clock.signals))
        self.assertTrue(report['commands'][-1]['group_closed'])
        self.assertLess(clock.now, 300)
        self.assertEqual((self.output / 'second-stdout.txt').read_bytes(), b'captured metadata')

    def test_stop_reserve_only_starts_no_process(self):
        clock = self.clock([])
        clock.now = 292
        report = {'start': 0, 'commands': []}
        with self.assertRaisesRegex(RuntimeError, 'Shared probe budget exhausted'):
            probe.command('late', ['read-only'], self.output, 300, report)
        self.assertEqual(clock.processes, [])
        self.assertEqual(report['commands'][0]['streams'], {})

    def test_cleanup_error_keeps_primary_timeout(self):
        self.clock([{'delay': float('inf'), 'signal_error': True}])
        report = {'start': 0, 'commands': []}
        with self.assertRaisesRegex(RuntimeError, 'Shared probe work deadline'):
            probe.command('timeout', ['read-only'], self.output, 300, report)
        row = report['commands'][0]
        self.assertIn('synthetic signal failure', row['cleanup_error'])
        self.assertIn('Shared probe work deadline', row['error'])
        self.assertNotIn('group_closed', row)

    def test_nonzero_or_surviving_descendants_never_count_as_success(self):
        for number, plan in enumerate(({'exit': 65}, {'orphan': True})):
            with self.subTest(plan=plan):
                clock = self.clock([plan])
                report = {'start': 0, 'commands': []}
                with self.assertRaisesRegex(RuntimeError, 'failed or left descendants'):
                    probe.command(str(number), ['read-only'], self.output, 300, report)
                self.assertTrue(report['commands'][0]['group_closed'])
                self.assertEqual(len(clock.processes), 1)

    def test_metadata_parsing_keeps_raw_schemas_and_rejects_bad_runtime_or_toolchain(self):
        values = {'source': 'a' * 40, 'developer': probe.DEVELOPER,
                  'xcode': 'Xcode 26.5\nBuild version 17F42', 'sdk': '26.5',
                  'swift': 'Apple Swift version 6.3 (synthetic)',
                  'runtimes': '{"runtimes": []}', 'device-types': '{"devicetypes": []}',
                  'summary-schema': '{known-malformed-document', 'tests-schema': '{"type": "object"}'}
        for name, text in values.items():
            (self.output / (name + '-stdout.txt')).write_text(text)
        report = {'environment': {'GITHUB_SHA': 'a' * 40}, 'release_acceptance': False}
        probe.parse_metadata(self.output, report)
        self.assertFalse(report['schema_json']['summary-schema']['valid_json'])
        self.assertTrue(report['schema_json']['tests-schema']['valid_json'])
        self.assertFalse(report['release_acceptance'])
        self.assertEqual((self.output / 'summary-schema-stdout.txt').read_text(), values['summary-schema'])
        for name, text in [('runtimes', '{"runtimes": {}}'), ('runtimes', 'invalid-json'), ('sdk', '26.4')]:
            with self.subTest(name=name, text=text):
                path = self.output / (name + '-stdout.txt')
                original = path.read_text()
                path.write_text(text)
                with self.assertRaises((RuntimeError, json.JSONDecodeError)):
                    probe.parse_metadata(self.output, report)
                path.write_text(original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
