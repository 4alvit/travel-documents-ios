#!/usr/bin/env python3
"""Offline ownership, deadline and classification guards for provider logging."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("provider_diagnostic", HERE / "diagnose-batch-provider.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
q = d.q
OWNED = "11111111-1111-4111-8111-111111111111"
FOREIGN = "22222222-2222-4222-8222-222222222222"
RUNTIME = "com.apple.CoreSimulator.SimRuntime.iOS-26-2"
ENV = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "GITHUB_EVENT_NAME": "workflow_dispatch",
       "GITHUB_WORKFLOW": "Release qualification", "GITHUB_JOB": "qualify",
       "GITHUB_REPOSITORY": "4alvit/travel-documents-ios", "GITHUB_SHA": "a" * 40,
       "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "QUALIFICATION_PROVIDER_LOG": "1",
       "QUALIFICATION_RUNNER": "macos-15", "QUALIFICATION_RUNNER_ARCH": "ARM64"}


def device(identifier, name):
    return {"udid": identifier, "name": name, "deviceTypeIdentifier": "iPhone16Pro",
            "state": "Booted", "isAvailable": True, "lastUsedAt": "unchanged",
            "dataPath": "/synthetic/" + identifier}


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.clock = [100.0]
        self.enterContext(patch.object(d.time, "monotonic", side_effect=lambda: self.clock[0]))
        self.enterContext(patch.object(q.os, "uname", return_value=SimpleNamespace(machine="arm64")))
        self.baseline = {"devices": {RUNTIME: [device(FOREIGN, "existing")]}}
        self.current = copy.deepcopy(self.baseline)
        self.current["devices"][RUNTIME].append(device(OWNED, "owned"))
        self.calls = []
        self.on_command = lambda *_: None
        self.log_stdout = '{"eventMessage":"synthetic provider event"}\n'

    def make_run(self):
        run = d.ProviderLogQualification(self.root, "batch", ENV)
        run.owned = OWNED
        run.baseline = q.device_map(self.baseline)
        run.intent = {"runtime": RUNTIME, "name": "owned", "type": "iPhone16Pro"}

        def command(label, argv, cap):
            self.calls.append((label, argv, cap, run.cleaning, run.commands.limit))
            self.on_command(label, run)
            if label == "shutdown":
                self.current["devices"][RUNTIME][-1]["state"] = "Shutdown"
            elif label == "delete":
                self.current["devices"][RUNTIME] = [row for row in self.current["devices"][RUNTIME]
                                                    if row["udid"] != OWNED]
            output = json.dumps(self.baseline if label == "baseline" else self.current)
            if label == "provider-log-show":
                output = self.log_stdout
            path = run.commands.out / (str(len(run.commands.report["commands"]) + 1) + "-stdout.log")
            path.write_text(output)
            run.commands.report["commands"].append({"id": label, "argv": argv, "outcome": "completed",
                "returncode": 0, "logs": {"stdout": str(path)}, "bytes": {"stdout": len(output.encode())}})
            return output

        run.commands.command = command
        command("baseline", ["xcrun", "simctl", "list", "devices", "--json"], 128)
        self.calls.clear()
        return run

    def diagnostic_calls(self):
        return [row for row in self.calls if row[0].startswith("provider-log-")]

    def test_explicit_arm_context_fails_before_output(self):
        variants = [("batch", {**ENV, "QUALIFICATION_PROVIDER_LOG": ""}),
                    ("biometrics", ENV),
                    ("batch", {**ENV, "TEST_RUNNER_TRIPDOCKET_NATIVE_REOPEN_CONTROL": "1"}),
                    ("batch", {**ENV, "QUALIFICATION_RUNNER": "macos-15-intel",
                               "QUALIFICATION_RUNNER_ARCH": "X64"}),
                    ("batch", {**ENV, "GITHUB_EVENT_NAME": "pull_request"})]
        for mode, env in variants:
            with self.subTest(mode=mode, env=env), self.assertRaises(RuntimeError):
                d.ProviderLogQualification(self.root, mode, env)
            self.assertFalse((self.root / "build").exists())
        with patch.object(q.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
             self.assertRaisesRegex(RuntimeError, "ARM batch"):
            d.ProviderLogQualification(self.root, "batch", {**ENV, "QUALIFICATION_RUNNER": "macos-15-intel",
                                                           "QUALIFICATION_RUNNER_ARCH": "X64"})
        self.assertFalse((self.root / "build").exists())

    def test_two_bounded_commands_precede_unchanged_cleanup_and_keep_raw_baseline(self):
        run = self.make_run()
        clocks = run.started, run.work_deadline, run.cleanup_deadline
        run.cleanup()
        calls = self.diagnostic_calls()
        self.assertEqual([row[0] for row in calls], ["provider-log-inventory", "provider-log-show"])
        self.assertEqual(calls[0][1], ["xcrun", "simctl", "list", "devices", "--json"])
        self.assertEqual(calls[1][1], ["xcrun", "simctl", "spawn", OWNED, "log", "show", "--last", "5m",
            "--style", "ndjson", "--info", "--debug", "--predicate", d.PREDICATE])
        self.assertTrue(all(row[2:] == (38, False, clocks[1]) for row in calls))
        self.assertEqual([row[0] for row in self.calls[2:]], ["before-cleanup", "shutdown", "delete", "after-cleanup"])
        self.assertEqual((run.started, run.work_deadline, run.cleanup_deadline), clocks)
        self.assertTrue(run.report["cleanup_verified"])
        self.assertTrue(run.report["diagnostic_provider_log"]["full_raw_baseline_verified"])
        self.assertEqual(run.report["diagnostic_provider_log"]["stdout_bytes"], len(self.log_stdout.encode()))
        self.assertFalse(run.report["diagnostic_provider_log"]["empty_stdout"])
        self.assertEqual(run.report["diagnostic_provider_log"]["window"],
                         "last 5m at target command execution; retained info/debug only")
        self.assertEqual((q.processes.PER_LOG, q.processes.ALL_LOG), (16 * 1024**2, 64 * 1024**2))

    def test_predicate_keeps_provider_metadata_without_process_only_traffic(self):
        clauses = []
        for clause in d.PREDICATE.split(" OR "):
            match = re.fullmatch(r'(subsystem|senderImagePath) CONTAINS\[c\] "([^"]+)"', clause)
            self.assertIsNotNone(match, clause)
            clauses.append(match.groups())
        self.assertEqual(clauses, [("subsystem", "fileprovider"), ("subsystem", "documentmanager"),
                                   ("senderImagePath", "FileProvider"), ("senderImagePath", "DocumentManager")])
        cases = [
            ({"subsystem": "com.apple.FileProvider"}, True),
            ({"subsystem": "com.apple.DocumentManager"}, True),
            ({"subsystem": "com.apple.Foundation", "senderImagePath": "/Frameworks/FILEPROVIDER.framework/FileProvider"}, True),
            ({"subsystem": "com.apple.Foundation", "senderImagePath": "/Frameworks/DocumentManager.framework/DocumentManager"}, True),
            ({"process": "fileproviderd", "subsystem": "com.apple.apsd",
              "senderImagePath": "/PrivateFrameworks/ApplePushService.framework/ApplePushService"}, False),
            ({"process": "com.apple.DocumentManager.Service", "subsystem": "com.apple.UIKit",
              "senderImagePath": "/Frameworks/UIKitCore.framework/UIKitCore"}, False),
            ({"subsystem": "com.apple.unrelated"}, False),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(any(value.casefold() in row.get(field, "").casefold()
                                     for field, value in clauses), expected)

    def test_empty_retained_log_is_explicitly_incomplete_and_still_cleans_up(self):
        run = self.make_run()
        self.log_stdout = ""
        run.cleanup()
        diagnostic = run.report["diagnostic_provider_log"]
        self.assertEqual(diagnostic["status"], "empty")
        self.assertEqual(diagnostic["stdout_bytes"], 0)
        self.assertTrue(diagnostic["empty_stdout"])
        self.assertIn("no retained stdout", diagnostic["reason"])
        self.assertTrue(run.report["cleanup_verified"])
        self.assertTrue(diagnostic["full_raw_baseline_verified"])
        run.report["status"] = "captured_pending_review"
        run.save()
        self.assertEqual(run.report["status"], "diagnostic_incomplete")

    def test_strict_initial_admission_never_spawns_at_or_below_196(self):
        run = self.make_run()
        for remaining in (195.0, 196.0):
            self.clock[0] = run.work_deadline - remaining
            run.capture_provider_log()
            self.assertEqual(self.diagnostic_calls(), [])
            self.assertEqual(run.report["diagnostic_provider_log"]["status"], "skipped")
        self.clock[0] = run.work_deadline - 196.01
        run.capture_provider_log()
        self.assertEqual(len(self.diagnostic_calls()), 2)

    def test_elapsed_inventory_and_baseline_read_cannot_renew_admission(self):
        run = self.make_run()
        self.clock[0] = run.work_deadline - 200
        self.on_command = lambda label, _: self.clock.__setitem__(0, run.work_deadline - 158) if label == "provider-log-inventory" else None
        run.capture_provider_log()
        self.assertEqual([row[0] for row in self.diagnostic_calls()], ["provider-log-inventory"])
        self.assertEqual(run.report["diagnostic_provider_log"]["status"], "skipped")
        self.calls.clear()
        self.clock[0] = run.work_deadline - 200
        original = run.command_inventory
        def slow_read(label):
            value = original(label)
            self.clock[0] = run.work_deadline - 196
            return value
        with patch.object(run, "command_inventory", side_effect=slow_read):
            run.capture_provider_log()
        self.assertEqual(self.diagnostic_calls(), [])

    def test_identity_availability_and_full_foreign_fields_are_required(self):
        run = self.make_run()
        good = copy.deepcopy(self.current)
        changes = [(OWNED, "name", "other"), (OWNED, "state", "Shutdown"),
                   (OWNED, "isAvailable", False), (FOREIGN, "lastUsedAt", "changed")]
        for identifier, key, value in changes:
            self.current = copy.deepcopy(good)
            next(row for row in self.current["devices"][RUNTIME] if row["udid"] == identifier)[key] = value
            self.calls.clear()
            run.commands.report["commands"] = run.commands.report["commands"][:1]
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                run.capture_provider_log()
            self.assertEqual([row[0] for row in self.diagnostic_calls()], ["provider-log-inventory"])
        self.current = good
        run.baseline[OWNED] = run.baseline[FOREIGN]
        self.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "baseline ownership"):
            run.capture_provider_log()
        self.assertEqual(self.diagnostic_calls(), [])

    def test_missing_acquisition_interrupt_and_active_phases_skip_capture(self):
        run = self.make_run()
        for attribute, value in [("owned", None), ("intent", None), ("baseline", None),
                                 ("interrupted", True), ("cleaning", True),
                                 ("acquiring", True), ("finalizing_driver", True)]:
            with self.subTest(attribute=attribute), patch.object(run, attribute, value):
                run.capture_provider_log()
            self.assertEqual(self.diagnostic_calls(), [])

    def test_unresolved_process_ownership_is_not_cleared_for_cleanup(self):
        run = self.make_run()
        for owner, attribute, value in [(run.commands, "unknown_spawn", True),
                                        (run.xcode, "active", {123: object()})]:
            with patch.object(owner, attribute, value), self.assertRaisesRegex(RuntimeError, "cleanup withheld"):
                run.cleanup()
            self.assertEqual(getattr(owner, attribute), False if attribute == "unknown_spawn" else {})
            self.assertEqual(self.calls, [])
            run.cleaning = False
            run.commands.limit = run.work_deadline

    def test_capture_errors_preserve_first_failure_and_always_cleanup(self):
        for failure in (RuntimeError("timeout"), RuntimeError("unsupported log syntax"),
                        RuntimeError("Output cap exceeded"), KeyboardInterrupt()):
            with self.subTest(failure=repr(failure)):
                # Each diagnostic gets a fresh output, just as the real entrypoint requires.
                self.root = Path(self.temp.name) / str(len(list(Path(self.temp.name).iterdir())))
                self.root.mkdir()
                self.current = copy.deepcopy(self.baseline)
                self.current["devices"][RUNTIME].append(device(OWNED, "owned"))
                run = self.make_run()
                run.report["errors"] = ["original native failure"]
                def fail(label, current_run):
                    if label == "provider-log-show":
                        if isinstance(failure, KeyboardInterrupt): current_run.interrupted = True
                        raise failure
                self.on_command = fail
                run.cleanup()
                self.assertEqual(run.report["errors"], ["original native failure"])
                self.assertEqual(run.report["diagnostic_provider_log"]["status"], "failed")
                self.assertEqual(sum(row[0] == "before-cleanup" for row in self.calls), 1)
                self.assertTrue(run.report["cleanup_verified"])
                self.calls.clear()
                self.on_command = lambda *_: None

    def test_late_unresolved_log_group_withholds_device_mutation(self):
        run = self.make_run()
        def fail(label, current_run):
            if label == "provider-log-show":
                current_run.commands.unknown_spawn = True
                raise RuntimeError("spawn unresolved")
        self.on_command = fail
        with self.assertRaisesRegex(RuntimeError, "cleanup withheld"):
            run.cleanup()
        self.assertTrue(run.commands.unknown_spawn)
        self.assertEqual(len(self.calls), 2)

    def test_final_raw_baseline_catches_fields_reduced_cleanup_omits(self):
        run = self.make_run()
        def mutate(label, _):
            if label == "delete": self.current["devices"][RUNTIME][0]["lastUsedAt"] = "drift"
        self.on_command = mutate
        with self.assertRaisesRegex(RuntimeError, "Final raw device"):
            run.cleanup()
        self.assertFalse(run.report["diagnostic_provider_log"]["full_raw_baseline_verified"])
        duplicate = copy.deepcopy(self.baseline)
        duplicate["devices"][RUNTIME].append(copy.deepcopy(duplicate["devices"][RUNTIME][0]))
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            d.raw_inventory(duplicate)

    def test_inventory_input_requires_exact_completed_bounded_regular_log(self):
        run = self.make_run()
        row = run.commands.report["commands"][0]
        good = copy.deepcopy(row)
        for key, value in [("outcome", "failed"), ("argv", ["other"]),
                           ("bytes", {"stdout": 1}), ("logs", {"stdout": "/tmp/foreign"})]:
            row.clear(); row.update(copy.deepcopy(good)); row[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): run.command_inventory("baseline")
        row.clear(); row.update(good)
        path = Path(row["logs"]["stdout"])
        target = self.root / "other"; target.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "link"):
            run.command_inventory("baseline")

    def test_every_saved_result_is_diagnostic_and_incomplete_is_not_success(self):
        run = self.make_run()
        initial = json.loads((run.out / "receipt.json").read_text())
        self.assertFalse(initial["diagnostic_provider_log"]["release_acceptance"])
        for log_status, expected in [("captured", "diagnostic_captured_pending_review"),
                                     ("failed", "diagnostic_incomplete"), ("skipped", "diagnostic_incomplete")]:
            run.report["status"] = "captured_pending_review"
            run.report["diagnostic_provider_log"]["status"] = log_status
            run.save()
            self.assertEqual(json.loads((run.out / "receipt.json").read_text())["status"], expected)
        run.report["status"] = "failed"; run.save()
        self.assertEqual(run.report["status"], "failed")

    def test_inherited_execute_keeps_native_original_capture_before_diagnostic_classification(self):
        run = self.make_run()
        run.before = {"head": "a" * 40}
        run.prepare = lambda: None
        run.source = lambda _: run.before
        def driver():
            run.report.update(driver_capture_verified=True, products_verified=True,
                batch_snapshot={"verified": True}, files_preparation_verified=True,
                batch_checkpoint_verified=True, combined_batch={"result_bundles": 2})
        run.run_driver = driver
        captured = []
        def original():
            captured.append(True); run.report["original_xcresult"] = {"verified": True}
        run.capture_original_result = original
        self.assertEqual(run.execute(), 0)
        self.assertEqual(captured, [True])
        self.assertEqual(run.report["status"], "diagnostic_captured_pending_review")
        self.assertIs(d.ProviderLogQualification.execute, d.BaseQualification.execute)
        self.assertIs(d.ProviderLogQualification.run_driver, d.BaseQualification.run_driver)
        self.assertIs(d.ProviderLogQualification.prepare, d.BaseQualification.prepare)

    def test_real_main_signal_handler_remains_effective_and_binding_is_restored(self):
        handlers = {}
        run = SimpleNamespace(interrupted=False, acquiring=False, finalizing_driver=False, cleaning=False)
        def execute():
            handlers[signal.SIGTERM](signal.SIGTERM, None)
        run.execute = execute
        with patch.object(d.sys, "argv", ["diagnose", "--mode", "batch"]), \
             patch.object(d, "ProviderLogQualification", return_value=run), \
             patch.object(q.signal, "signal", side_effect=lambda sig, handler: handlers.update({sig: handler})):
            with self.assertRaises(KeyboardInterrupt): d.main()
        self.assertTrue(run.interrupted)
        self.assertEqual(set(handlers), {signal.SIGTERM, signal.SIGINT})
        self.assertIs(q.Qualification, d.BaseQualification)
        run.interrupted = False; run.cleaning = True
        handlers[signal.SIGINT](signal.SIGINT, None)
        self.assertTrue(run.interrupted)

    def test_pins_and_workflow_keep_the_diagnostic_isolated(self):
        for name, digest in d.PINS.items():
            self.assertEqual(hashlib.sha256((HERE / name).read_bytes()).hexdigest(), digest)
        workflow = (HERE.parent / ".github/workflows/release-qualification.yml").read_text()
        self.assertIn('QUALIFICATION_PROVIDER_LOG: "1"', workflow)
        if 'QUALIFICATION_RUNTIME_CONTROL:' in workflow:
            self.assertIn('QUALIFICATION_RUNTIME_CONTROL: "ios18.5"', workflow)
            self.assertIn('run: python3 -B scripts/diagnose-batch-runtime.py --mode "$QUALIFICATION_MODE"', workflow)
            self.assertIn('name: TripDocket-diagnostic-runtime-185-', workflow)
            self.assertIn('python3 -B scripts/test-runtime-diagnostic.py', workflow)
        else:
            self.assertIn('run: python3 -B scripts/diagnose-batch-provider.py --mode "$QUALIFICATION_MODE"', workflow)
            self.assertIn('name: TripDocket-diagnostic-provider-log-', workflow)
        self.assertIn('python3 -B scripts/test-provider-log-diagnostic.py', workflow)
        self.assertIn('if: always()', workflow)
        self.assertNotIn('TEST_RUNNER_TRIPDOCKET_NATIVE_REOPEN_CONTROL:', workflow)
        with patch.object(d.sys, "argv", ["diagnose", "--mode", "biometrics"]), self.assertRaises(RuntimeError):
            d.main()


if __name__ == "__main__":
    unittest.main()
