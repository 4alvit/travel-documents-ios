"""Scheduler plus extracted production boundaries; fake OS only."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tests_adapters import World, adapters
from tests_runner import runner, parent_env


class Integration(unittest.TestCase):
    def exercise(self, first_mode='success', cleanup_error=False):
        with ExitStack() as stack:
            for obj, name in [(subprocess, 'Popen'), (os, 'killpg'), (os, 'getpgid'),
                              (os, 'getsid'), (signal, 'signal'), (signal, 'setitimer'),
                              (runner.resource, 'setrlimit')]:
                stack.enter_context(patch.object(obj, name, side_effect=AssertionError('LIVE_OPERATION_FORBIDDEN')))
            temp = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
            worlds, reports = [], []
            def invoke(boundary, env, directory, deadline):
                world = World(first_mode if not worlds else 'success', cleanup_error=cleanup_error if not worlds else False)
                worlds.append(world)
                with patch.object(adapters, 'libraries', return_value=world.lib()):
                    return adapters.run_probe(boundary, env, directory, deadline)
            rows, stopped = runner.run_schedule(parent_env(), temp, 1000, invoke,
                                                lambda rows, stop: reports.append(json.dumps(rows)), clock=lambda:0)
            for public in reports:
                self.assertNotIn('PRIVATE_SENTINEL', public)
                self.assertNotIn(str(temp), public)
                self.assertNotIn('/toy/private-home', public)
            return rows, stopped, worlds

    def test_all_ten_real_adapters_with_fake_os_cross_schema_and_directory_contracts(self):
        rows, stopped, worlds = self.exercise()
        self.assertFalse(stopped, rows)
        self.assertEqual(len(worlds), 10)
        self.assertTrue(all(r['status']=='OBSERVED' and r['observation']['outcome']=='success' for r in rows))
        self.assertEqual([w.argv for w in worlds], [adapters.ARGV[r['boundary']] for r in rows])

    def test_clean_timeout_advances_predeclared_cohort(self):
        rows, stopped, worlds = self.exercise('timeout')
        self.assertFalse(stopped, rows)
        self.assertEqual(rows[0]['observation']['outcome'], 'timeout')
        self.assertEqual(len(worlds),10)

    def test_cleanup_failure_withholds_every_later_actual_adapter(self):
        rows, stopped, worlds = self.exercise('timeout', cleanup_error=True)
        self.assertTrue(stopped)
        self.assertEqual(len(worlds),1)
        self.assertTrue(all(r['status']=='NOT_RUN' for r in rows[1:]))

    def test_output_limit_stops_all_later_actual_adapters(self):
        rows, stopped, worlds = self.exercise('censor')
        self.assertTrue(stopped)
        self.assertTrue(rows[0]['observation']['output_censored'])
        self.assertEqual(len(worlds),1)
