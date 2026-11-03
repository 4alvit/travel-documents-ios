#!/usr/bin/env python3
"""Offline regressions for the explicit native-created-folder diagnostic."""
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch


HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = load("folder_qualification_fixtures", "test-qualify-release.py")
drivers = load("folder_driver_fixtures", "test-batch-driver.py")
control = load("native_folder_control", "diagnose-batch-folder.py")
q = fixtures.q
ENV = {**fixtures.ENV, "QUALIFICATION_PROVIDER_LOG": "1", "QUALIFICATION_NATIVE_FOLDER_CONTROL": "1"}
SETTING = "EXCLUDED_SOURCE_FILE_NAMES=First.swift Second.swift"


class FolderControlTests(unittest.TestCase):
    def fixture_owner(self, kind=fixtures.Guards):
        owner = kind()
        owner.setUp()
        self.addCleanup(owner.doCleanups)
        return owner

    def combined_fixture(self):
        owner = self.fixture_owner()
        run, driver = owner.seed_fixture()
        owner.preparation_fixture(run)
        run.inspect_files_preparation()
        run.native_folder_control = True
        driver.args = SimpleNamespace(native_folder=True, native_root=False, combined_batch=True)
        run.report["native_folder"] = {"adopted": True, "empty_after": True}
        return run, driver

    def capture_fixture(self):
        owner = self.fixture_owner()
        run, original = owner.prepared_capture()
        run.native_folder_control = True
        run.report.pop("native_root")
        owner.preparation_fixture(run, native_folder=True)
        run.inspect_files_preparation(native_folder=True)
        run.report.update(native_folder_verified=True, native_folder={
            "adopted": True, "empty_after": True, "verified_after_main": True,
            "provider_identity": [10, 20],
            "cleanup": {"leaf_absent": True, "provider_identity": [10, 20]}},
            cleanup_verified=True)
        run.report["combined_batch"].update(result_bundles=3, destination_mode="native_folder")
        return run, original

    def test_explicit_context_rejects_before_output_or_dispatch(self):
        variants = [("biometrics", ENV), ("batch", {**ENV, "QUALIFICATION_NATIVE_FOLDER_CONTROL": ""}),
                    ("batch", {**ENV, "QUALIFICATION_PROVIDER_LOG": ""}),
                    ("batch", {**ENV, "TEST_RUNNER_TRIPDOCKET_NATIVE_REOPEN_CONTROL": "1"}),
                    ("batch", {**ENV, "GITHUB_EVENT_NAME": "pull_request"})]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(control.q.os, "uname", return_value=SimpleNamespace(machine="arm64")):
            root = Path(directory)
            for mode, env in variants:
                with self.subTest(mode=mode, env=env), self.assertRaises(RuntimeError):
                    control.FolderQualification(root, mode, env)
                self.assertEqual(list(root.iterdir()), [])
        for argv, env in ((["diagnose-batch-folder.py", "--mode", "biometrics"], ENV),
                          (["diagnose-batch-folder.py", "--mode", "batch"], {})):
            with patch.object(control.sys, "argv", argv), patch.dict(os.environ, env, clear=True), \
                 patch.object(control.q, "main") as main, self.assertRaises(RuntimeError):
                control.main()
            main.assert_not_called()

    def test_wrapper_restores_original_class_on_return_error_and_interrupt(self):
        original = control.q.Qualification
        self.assertIs(original, control.provider.BaseQualification)
        for outcome in (7, RuntimeError("original error"), KeyboardInterrupt("original interrupt")):
            def invoke():
                self.assertIs(control.q.Qualification, control.FolderQualification)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
            with patch.object(control.sys, "argv", ["diagnose-batch-folder.py", "--mode", "batch"]), \
                 patch.dict(os.environ, ENV, clear=True), patch.object(control.q, "main", side_effect=invoke):
                if isinstance(outcome, BaseException):
                    with self.assertRaises(type(outcome)) as caught:
                        control.main()
                    self.assertIs(caught.exception, outcome)
                else:
                    self.assertEqual(control.main(), outcome)
            self.assertIs(control.q.Qualification, original)
        with patch.object(control.q, "Qualification", object()), \
             patch.object(control.sys, "argv", ["diagnose-batch-folder.py", "--mode", "batch"]), \
             patch.dict(os.environ, ENV, clear=True), patch.object(control.q, "main") as main, \
             self.assertRaisesRegex(RuntimeError, "inherited class"):
            control.main()
        main.assert_not_called()

    def test_diagnostic_receipt_never_grants_release_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(control.q.os, "uname", return_value=SimpleNamespace(machine="arm64")), \
             patch.object(control.q.time, "monotonic", return_value=1000.0):
            run = control.FolderQualification(directory, "batch", ENV)
            clocks = run.started, run.work_deadline, run.cleanup_deadline
            self.assertEqual(run.work_deadline - run.started, 2400)
            self.assertEqual(run.cleanup_deadline - run.work_deadline, 180)
            run.report["diagnostic_provider_log"]["status"] = "captured"
            run.report["status"] = "captured_pending_review"
            run.save()
            self.assertEqual(run.report["status"], "diagnostic_captured_pending_review")
            self.assertEqual((run.started, run.work_deadline, run.cleanup_deadline), clocks)
            proof = run.report["diagnostic_native_folder"]
            self.assertIs(proof["release_acceptance"], False)
            self.assertEqual(proof["expected_phase_case_counts"], [2, 1, 2])
            self.assertEqual(proof["expected_result_bundles"], 3)
            self.assertEqual(proof["driver_seconds"], 1440)
            self.assertEqual(proof["additional_folder_seconds"], 240)

    def test_added_folder_envelope_is_allocated_once_after_actual_preparation(self):
        owner = self.fixture_owner()
        run = owner.run_object()
        original = run.started, run.work_deadline, run.cleanup_deadline
        self.assertEqual(q.MODES["batch"][1], 1200)
        for folder, seconds in ((False, 1200), (True, 1440)):
            run.native_folder_control = folder
            constructor = Mock(side_effect=LookupError("stop before any native work"))
            module = SimpleNamespace(Driver=constructor)
            boundary = run.work_deadline - seconds - 120
            with self.subTest(folder=folder), patch.object(q, "load_module", return_value=module) as loader:
                with patch.object(q.time, "monotonic", return_value=boundary):
                    with self.assertRaisesRegex(RuntimeError, "full driver/postcheck budget"):
                        run.run_driver()
                loader.assert_not_called()
                constructor.assert_not_called()
                with patch.object(q.time, "monotonic", return_value=boundary - 0.001):
                    with self.assertRaisesRegex(LookupError, "stop before any native work"):
                        run.run_driver()
                constructor.assert_called_once()
                args = constructor.call_args.args[0]
                self.assertEqual(args.timeout, seconds)
                self.assertEqual(args.native_folder, folder)
                self.assertEqual(args.native_root, not folder)
                self.assertEqual((run.started, run.work_deadline, run.cleanup_deadline), original)

    def test_native_folder_forwards_setting_and_adopts_only_after_native_return(self):
        owner = self.fixture_owner()
        run, driver = owner.folder_fixture()
        run.build_settings = (SETTING,)
        clocks = run.started, run.work_deadline, run.cleanup_deadline, driver.deadline
        previous = run.commands.ops.env
        calls = []
        def command(label, argv, seconds):
            self.assertIsNone(driver.fixture_directory)
            self.assertFalse(driver.native_folder_destination.exists())
            calls.append((label, argv, seconds, dict(run.commands.ops.env)))
            driver.native_folder_destination.mkdir()
        run.command = command
        run.inspect_files_preparation = Mock()
        run.prepare_native_folder(driver)
        self.assertEqual(len(calls), 1)
        label, argv, seconds, env = calls[0]
        self.assertEqual((label, seconds), ("native-folder-ui", 240))
        self.assertEqual(argv.count(SETTING), 1)
        self.assertEqual(argv[-2:], [SETTING, "test"])
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance") + 1], "180")
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_TOKEN"], driver.token)
        source_token = env["TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN"]
        self.assertEqual(source_token, str(uuid.UUID(source_token)))
        self.assertEqual(source_token, run.report["native_folder"]["source_token"])
        self.assertNotIn(source_token, (driver.token, run.report["files_preparation"]["fixture_token"]))
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER"], driver.folder_name)
        recorded = run.report["native_folder"]["environment_overrides"]
        self.assertEqual(set(recorded), {"TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_UI",
            "TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_TOKEN", "TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN",
            "TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER", "TEST_RUNNER_NSUnbufferedIO", "NSUnbufferedIO"})
        self.assertEqual(recorded, {key: env[key] for key in recorded})
        self.assertNotIn("TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_UI", env)
        self.assertIs(run.commands.ops.env, previous)
        self.assertEqual((run.started, run.work_deadline, run.cleanup_deadline, driver.deadline), clocks)
        self.assertEqual(driver.fixture_directory, driver.native_folder_destination)
        self.assertEqual(run.report["native_folder"]["leaf_identity"], list(driver.fixture_identity))
        self.assertTrue(run.report["native_folder"]["adopted"])
        self.assertTrue(run.report["native_folder"]["empty_after"])
        run.inspect_files_preparation.assert_called_once_with(native_folder=True)

    def test_folder_and_shared_admission_keep_original_clock_reserves(self):
        owner = self.fixture_owner()
        run, driver = owner.folder_fixture()
        # An exactly representable clock keeps the equality boundary independent
        # of floating-point cancellation in the host's current uptime.
        now = 1000.0
        driver.deadline = now + 1148
        run.command = Mock()
        with patch.object(q.time, "monotonic", return_value=now), self.assertRaisesRegex(RuntimeError, "budget"):
            run.prepare_native_folder(driver)
        run.command.assert_not_called()
        self.assertNotIn("native_folder", run.report)
        shared = self.fixture_owner(fixtures.SharedBuildGuards)
        shared.run.native_folder_control = True
        shared.run.report["native_folder_verified"] = True
        shared.driver.args = SimpleNamespace(native_root=False, native_folder=True, combined_batch=True)
        shared.driver.remaining = lambda: 1098
        with self.assertRaisesRegex(RuntimeError, "budget"):
            shared.run.prepare_shared_build(shared.driver)
        self.assertEqual(shared.calls, [])

    def test_combined_folder_requires_exclusive_destination_and_empty_adoption(self):
        faults = ("both", "neither", "unselected", "unverified", "unadopted", "nonempty", "no-preparation")
        for fault in faults:
            run, driver = self.combined_fixture()
            if fault == "both": driver.args.native_root = True
            elif fault == "neither": driver.args.native_folder = False
            elif fault == "unselected": run.native_folder_control = False
            elif fault == "unverified": run.report["native_folder_verified"] = False
            elif fault == "unadopted": run.report["native_folder"]["adopted"] = False
            elif fault == "nonempty": run.report["native_folder"]["empty_after"] = False
            else: run.report["files_preparation_verified"] = False
            with self.subTest(fault=fault), self.assertRaisesRegex(RuntimeError, "verified owned destination"):
                run.prepare_combined_batch(driver)
            self.assertNotIn("combined_batch", run.report)
            self.assertFalse(hasattr(driver, "checkpoint_callback"))

    def test_combined_setup_keeps_exact_cases_and_unrenewed_budgets(self):
        run, driver = self.combined_fixture()
        clocks = run.started, run.work_deadline, run.cleanup_deadline, driver.deadline
        run.prepare_combined_batch(driver)
        proof = run.report["combined_batch"]
        self.assertEqual(proof["cases"], list(q.checkpoint.CASES))
        self.assertEqual(proof["preparation_cases"], list(q.checkpoint.PREPARATION_CASES))
        self.assertEqual((proof["result_bundles"], proof["destination_mode"]), (3, "native_folder"))
        self.assertEqual([proof[key] for key in ("driver_seconds", "seed_case_seconds",
                         "seed_observed_envelope_seconds", "main_case_seconds", "checkpoint_seconds")],
                         [1440, 180, 300, 600, 60])
        self.assertEqual((run.started, run.work_deadline, run.cleanup_deadline, driver.deadline), clocks)
        self.assertTrue(callable(driver.checkpoint_callback))
        self.assertIs(driver.combined_protocol, q.checkpoint)

    def test_shared_query_forwards_actual_settings_to_adopted_folder_driver(self):
        owner = self.fixture_owner(fixtures.SharedBuildGuards)
        owner.run.native_folder_control = True
        owner.run.report["native_folder_verified"] = True
        owner.driver.args = SimpleNamespace(native_root=False, native_folder=True, combined_batch=True)
        owner.run.build_settings = (SETTING,)
        for item in owner.settings:
            item["buildSettings"]["EXCLUDED_SOURCE_FILE_NAMES"] = SETTING.split("=", 1)[1]
        owner.run.prepare_shared_build(owner.driver)
        argv = owner.calls[0][1]
        self.assertEqual(argv.count(SETTING), 1)
        self.assertEqual(argv[argv.index("-destination") + 1], "generic/platform=iOS Simulator")
        self.assertIs(owner.driver.qualified_build_settings, owner.run.build_settings)
        self.assertEqual(owner.driver.qualified_build, owner.derived)

    def driver_fixture(self):
        owner = self.fixture_owner(drivers.BatchDriverTests)
        run = owner.focused_fixture()
        run.args.native_root = False
        run.args.native_folder = True
        run.native_folder_destination = run.root / "native-created"
        run.fixture_directory = run.native_folder_destination
        run.fixture_identity = (10, 30)
        return run

    def test_actual_combined_driver_forwards_folder_and_settings_in_one_invocation(self):
        run = self.driver_fixture()
        with patch.object(drivers.driver.subprocess, "Popen") as spawn, patch("builtins.print"):
            run.run_test()
        spawn.assert_called_once()
        argv = spawn.call_args.args[0]
        self.assertEqual(argv.count(SETTING), 1)
        self.assertEqual(argv[-1], "test-without-building")
        self.assertEqual(argv[argv.index("-derivedDataPath") + 1], str(run.qualified_build))
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance") + 1], "600")
        self.assertEqual(run.summary["command"], argv)
        env = run.summary["environment_overrides"]
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_TOKEN"], run.token)
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_TOKEN"], run.token)
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_COMBINED_BATCH_UI"], "1")
        self.assertNotIn("TEST_RUNNER_TRIPDOCKET_NATIVE_ROOT_UI", env)
        self.assertEqual(run.combined_protocol.monitor.call_args.args[2], 1200)
        run.native_root_identity.assert_not_called()

    def test_driver_rejects_ambiguous_or_unadopted_folder_before_spawn(self):
        for fault in ("both", "neither", "no-leaf", "wrong-leaf", "no-checkpoint"):
            run = self.driver_fixture()
            if fault == "both": run.args.native_root = True
            elif fault == "neither": run.args.native_folder = False
            elif fault == "no-leaf": run.fixture_identity = None
            elif fault == "wrong-leaf": run.fixture_directory = run.root / "other"
            else: run.checkpoint_callback = None
            with self.subTest(fault=fault), patch.object(drivers.driver.subprocess, "Popen") as spawn, \
                 self.assertRaises(RuntimeError):
                run.run_test()
            spawn.assert_not_called()

    def test_successful_folder_execute_captures_three_original_bundles(self):
        run, original = self.capture_fixture()
        before = q.tree_manifest(original, run.check)
        self.assertEqual(run.execute(), 0)
        self.assertEqual(run.report["status"], "captured_pending_review")
        self.assertIn("original_xcresult", run.report)
        self.assertTrue(run.report["files_preparation_original"]["unchanged_after_cleanup"])
        self.assertTrue(run.report["native_folder_original"]["unchanged_after_cleanup"])
        self.assertFalse((run.out / "native-seed.xcresult").exists())
        self.assertEqual(q.tree_manifest(original, run.check), before)

    def test_capture_rejects_missing_post_main_cleanup_checkpoint_or_extra_seed_proof(self):
        faults = ("missing-folder", "no-post-main", "no-cleanup", "changed-provider", "no-checkpoint",
                  "wrong-count", "wrong-mode", "extra-seed-proof", "extra-seed-bundle", "changed-original")
        for fault in faults:
            run, _ = self.capture_fixture()
            if fault == "missing-folder": run.report.pop("native_folder_original")
            elif fault == "no-post-main": run.report["native_folder"].pop("verified_after_main")
            elif fault == "no-cleanup": run.report["native_folder"].pop("cleanup")
            elif fault == "changed-provider": run.report["native_folder"]["cleanup"]["provider_identity"] = [10, 21]
            elif fault == "no-checkpoint": run.report["batch_checkpoint_verified"] = False
            elif fault == "wrong-count": run.report["combined_batch"]["result_bundles"] = 2
            elif fault == "wrong-mode": run.report["combined_batch"]["destination_mode"] = "native_root"
            elif fault == "extra-seed-proof": run.report["native_seed_verified"] = True
            elif fault == "extra-seed-bundle": (run.out / "native-seed.xcresult").mkdir()
            else: (run.out / "native-folder.xcresult/Data/result").write_bytes(b"changed")
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                run.capture_original_result()
            self.assertNotIn("original_xcresult", run.report)

    def test_folder_cleanup_removes_only_adopted_leaf_and_confirms_parent(self):
        run = self.driver_fixture()
        parent = run.root / "provider"
        parent.mkdir()
        leaf = parent / "owned"
        leaf.mkdir()
        (leaf / "synthetic.pdf").write_bytes(b"synthetic")
        sibling = parent / "foreign"
        sibling.mkdir()
        run.fixture_directory = leaf
        run.fixture_identity = (leaf.stat().st_dev, leaf.stat().st_ino)
        run.provider_identity = (parent.stat().st_dev, parent.stat().st_ino)
        run.remove_fixtures()
        self.assertFalse(leaf.exists())
        self.assertTrue(sibling.is_dir())
        self.assertEqual(run.summary["native_folder_cleanup"],
                         {"leaf_absent": True, "provider_identity": list(run.provider_identity)})


if __name__ == "__main__":
    unittest.main()
