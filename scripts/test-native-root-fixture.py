#!/usr/bin/env python3
"""Exercise native-root admission, byte proofs and teardown without native tools."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_root_base", HERE / "test-qualify-release.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
q, batch = base.q, base.batch
TOKEN = "12345678-1234-4234-8234-123456789abc"
OWNED = base.OWNED


class RootGuards(unittest.TestCase):
    setUp = base.Guards.setUp
    run_object = base.Guards.run_object
    fixture = base.Guards.fixture
    preparation_fixture = base.Guards.preparation_fixture
    prepared_capture = base.Guards.prepared_capture

    def root_fixture(self, *, root=None, before=None, native_root=True, native_seed=True, native_folder=False):
        root = root or self.root
        run = q.Qualification(root, "batch", base.ENV)
        run.owned = OWNED; run.baseline = {}; run.intent = {"name": "owned"}
        home = root / "home"
        self.enterContext(patch.object(Path, "home", return_value=home))
        group = home / "Library/Developer/CoreSimulator/Devices" / OWNED / "data/Containers/Shared/AppGroup" / base.EXISTING
        provider = group / "File Provider Storage"; provider.mkdir(parents=True)
        project = root / "Tripfolio.xcodeproj"; project.mkdir(); (project / "project.pbxproj").write_text("fixture")
        driver = batch.Driver.__new__(batch.Driver)
        driver.args = SimpleNamespace(device=OWNED, native_root=native_root, native_seed=native_seed,
                                      native_folder=native_folder)
        driver.root = root; driver.directory = root / "build/driver"; driver.directory.mkdir()
        driver.token = TOKEN; driver.folder_name = "TripDocket-Batch-QA-" + TOKEN
        driver.fixture_directory = None; driver.fixture_identity = None; driver.native_folder_destination = None
        driver.native_root_provider = None; driver.native_root_group_identity = None
        driver.summary = {}; driver.record = Mock(); driver.save = Mock(); driver.source_snapshot = Mock(return_value={})
        driver.deadline = time.monotonic() + 1200
        inventory = {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-26-2": [
            {"udid": OWNED, "state": "Booted", "isAvailable": True, "name": "owned"}]}}
        driver.command = Mock(side_effect=[json.dumps(inventory).encode(), f"{batch.GROUP}\t{group}\n".encode()])
        if before: before(provider)
        driver.prepare()
        run.report["files_preparation_verified"] = True
        derived = root / "build/QualificationPreparationDerivedData-123-1"; derived.mkdir()
        run.report["files_preparation"] = {"derived_data": str(derived.relative_to(root))}
        return run, driver, provider

    def save_files(self, driver):
        for item in driver.summary["fixtures"]:
            (driver.fixture_directory / item["name"]).write_bytes((driver.directory / "fixtures" / item["name"]).read_bytes())

    def test_real_driver_prepares_empty_root_without_creating_a_folder_or_writing_provider_bytes(self):
        run, driver, provider = self.root_fixture()
        self.assertEqual(list(provider.iterdir()), [])
        self.assertEqual(driver.fixture_directory, provider)
        self.assertEqual(driver.fixture_identity, driver.provider_identity)
        self.assertEqual(driver.summary["fixture_destination_mode"], "native_root")
        manifest = json.loads((driver.directory / "fixture-manifest.json").read_text())
        self.assertEqual(manifest["destination_mode"], "native_root")
        self.assertEqual(manifest["folder"], driver.folder_name)
        self.assertEqual(sorted(x.name for x in (driver.directory / "fixtures").iterdir()),
                         ["synthetic-insurance.pdf", "synthetic-ticket.pdf"])
        run.prepare_native_root(driver)
        self.assertTrue(run.report["native_root"]["verified_empty_before_seed"])
        self.assertNotIn("native_folder_verified", run.report)
        self.assertNotIn("native_folder", run.report)
        with self.assertRaises(RuntimeError): run.prepare_native_root(driver)

    def test_root_preparation_rejects_every_existing_entry_and_invalid_mode(self):
        for fault in ("hidden", "file", "directory", "symlink", "without-seed", "with-folder"):
            root = self.root / fault; root.mkdir()
            def before(provider):
                if fault == "hidden": (provider / ".hidden").write_bytes(b"")
                elif fault == "file": (provider / "file").write_bytes(b"old")
                elif fault == "directory": (provider / "directory").mkdir()
                elif fault == "symlink": (provider / "link").symlink_to(provider.parent)
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                self.root_fixture(root=root, before=before, native_seed=fault != "without-seed",
                                  native_folder=fault == "with-folder")

    def test_root_requires_fresh_exact_device_token_and_preparation_without_writers(self):
        for fault in ("baseline", "other-device", "token", "folder-token", "prep", "mode", "flag", "command", "xcode"):
            root = self.root / fault; root.mkdir(); run, driver, _ = self.root_fixture(root=root)
            if fault == "baseline": run.baseline[OWNED] = {}
            elif fault == "other-device": driver.args.device = base.EXISTING
            elif fault == "token": driver.token = TOKEN.upper()
            elif fault == "folder-token": driver.folder_name = "TripDocket-Batch-QA-" + base.EXISTING
            elif fault == "prep": run.report["files_preparation_verified"] = False
            elif fault == "mode": run.mode = "biometrics"
            elif fault == "flag": driver.args.native_root = False
            elif fault == "command": run.commands.unknown_spawn = True
            else: run.xcode.unknown_spawn = True
            with self.subTest(fault=fault), self.assertRaises(RuntimeError): run.prepare_native_root(driver)
            self.assertNotIn("native_root", run.report)

    def test_root_identity_rejects_replaced_provider_group_and_symlink_ancestor(self):
        for fault in ("provider", "group", "ancestor"):
            root = self.root / fault; root.mkdir(); run, driver, provider = self.root_fixture(root=root)
            if fault == "provider":
                provider.rename(provider.with_name("old-provider")); provider.mkdir()
            elif fault == "group":
                group = provider.parent; old = group.with_name("old-group"); group.rename(old)
                group.mkdir(); provider.mkdir()
            else:
                parent = provider.parent.parent; old = parent.with_name("old-AppGroup"); parent.rename(old)
                parent.symlink_to(old, target_is_directory=True)
            with self.subTest(fault=fault), self.assertRaises(RuntimeError): run.native_seed_files(driver, empty=True)

    def test_exact_two_bytes_and_no_extra_entries_are_required_after_seed_and_main(self):
        for fault in (None, "extra", "hidden", "subdir", "link", "bytes", "source", "oversize", "identity"):
            root = self.root / str(fault); root.mkdir(); run, driver, provider = self.root_fixture(root=root)
            run.prepare_native_root(driver); self.save_files(driver); run.native_seed_files(driver)
            target = provider / "synthetic-ticket.pdf"
            if fault == "extra": (provider / "third.pdf").write_bytes(b"")
            elif fault == "hidden": (provider / ".hidden").write_bytes(b"")
            elif fault == "subdir": target.unlink(); target.mkdir()
            elif fault == "link": target.unlink(); target.symlink_to(driver.directory / "fixtures/synthetic-ticket.pdf")
            elif fault == "bytes": target.write_bytes(b"changed")
            elif fault == "source": (driver.directory / "fixtures/synthetic-ticket.pdf").write_bytes(b"changed")
            elif fault == "oversize": target.write_bytes(b"a" * 1025)
            elif fault == "identity": driver.native_root_group_identity = (0, 0)
            if fault is None: run.native_seed_files(driver)
            else:
                with self.subTest(fault=fault), self.assertRaises((RuntimeError, OSError)):
                    run.native_seed_files(driver)
            self.assertTrue(provider.is_dir())

    def test_empty_scan_rechecks_parent_and_provider_pins(self):
        run, driver, provider = self.root_fixture(); original = q.os.scandir
        def mutate(path):
            driver.native_root_group_identity = (0, 0)
            return original(path)
        with patch.object(q.os, "scandir", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "identity changed"): run.prepare_native_root(driver)
        self.assertNotIn("native_root", run.report)

    def test_root_cleanup_never_removes_provider_or_files_and_default_cleanup_remains_scoped(self):
        run, driver, provider = self.root_fixture(); self.save_files(driver)
        before = {x.name: x.read_bytes() for x in provider.iterdir()}
        with patch.object(batch.shutil, "rmtree", side_effect=AssertionError("Provider root deletion forbidden")):
            driver.remove_fixtures()
        self.assertEqual({x.name: x.read_bytes() for x in provider.iterdir()}, before)
        self.assertEqual(driver.summary["fixture_cleanup"], "native root retained for verified owned Simulator teardown")
        default = self.root / "default"; default.mkdir()
        _, normal, parent = self.root_fixture(root=default, native_root=False, native_seed=False)
        owned = normal.fixture_directory; normal.remove_fixtures()
        self.assertFalse(owned.exists()); self.assertTrue(parent.is_dir())
        self.assertEqual(normal.summary["fixture_cleanup"], "removed only the uniquely created fixture folder")

    def test_seed_uses_same_clock_and_exact_root_flags_then_restores_environment(self):
        run, driver, _ = self.root_fixture(); run.prepare_native_root(driver)
        original_deadline = driver.deadline; original_env = run.commands.ops.env; calls = []
        def command(label, argv, seconds):
            calls.append((label, [str(x) for x in argv], seconds, dict(run.commands.ops.env)))
            self.save_files(driver)
        run.command = command; run.inspect_files_preparation = Mock()
        run.prepare_native_seed(driver)
        self.assertEqual(driver.deadline, original_deadline); self.assertIs(run.commands.ops.env, original_env)
        self.assertEqual(len(calls), 1)
        label, argv, seconds, env = calls[0]
        self.assertEqual((label, seconds), ("native-seed-ui", 300))
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance") + 1], "180")
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_ROOT_UI"], "1")
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_ROOT_TOKEN"], TOKEN)
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_TOKEN"], TOKEN)
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER"], driver.folder_name)
        self.assertNotIn("TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_UI", env)
        self.assertEqual(run.inspect_files_preparation.call_args.kwargs, {"native_seed": True})
        self.assertTrue(run.report["native_seed_verified"])

    def test_seed_failure_keeps_original_error_and_has_no_verified_root_result(self):
        run, driver, provider = self.root_fixture(); run.prepare_native_root(driver)
        original_env = run.commands.ops.env
        run.command = Mock(side_effect=RuntimeError("original native failure"))
        run.inspect_files_preparation = Mock(side_effect=RuntimeError("secondary inspection failure"))
        with self.assertRaisesRegex(RuntimeError, "original native failure"): run.prepare_native_seed(driver)
        self.assertIs(run.commands.ops.env, original_env)
        self.assertNotIn("native_seed_verified", run.report); self.assertTrue(provider.is_dir())
        self.assertIn("secondary inspection failure", run.report["native_seed_inspection_error"])

    def test_root_seed_refuses_insufficient_original_driver_and_outer_budgets(self):
        for fault in ("driver", "outer"):
            root = self.root / fault; root.mkdir(); run, driver, _ = self.root_fixture(root=root)
            run.prepare_native_root(driver)
            if fault == "driver": driver.deadline = time.monotonic() + 900
            else: run.work_deadline = time.monotonic() + 1010
            run.command = Mock(side_effect=AssertionError("No native launch with insufficient budget"))
            with self.subTest(fault=fault), self.assertRaisesRegex(RuntimeError, "Insufficient"):
                run.prepare_native_seed(driver)
            run.command.assert_not_called()
        self.assertEqual(q.MODES["batch"][1], 1200); self.assertEqual(q.WORK_SECONDS["batch"], 2400)

    def test_root_driver_acceptance_requires_post_main_verification_and_deferred_cleanup(self):
        summary, result, tree, cases = self.fixture()
        summary.update(fixture_destination_mode="native_root", native_root_post_main_verified=True,
                       fixture_cleanup="native root retained for verified owned Simulator teardown")
        q.validate_driver("batch", summary, result, tree, cases, OWNED, base.HEAD)
        for fault in ("post-main", "cleanup", "source", "skip", "warning"):
            s, r = copy.deepcopy(summary), copy.deepcopy(result)
            if fault == "post-main": s.pop("native_root_post_main_verified")
            elif fault == "cleanup": s["fixture_cleanup"] = "removed only the uniquely created fixture folder"
            elif fault == "source": s["source_originals_unchanged"] = False
            elif fault == "skip": r.update(skippedTests=1, passedTests=1)
            else: r["runtimeWarnings"] = [{}]
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                q.validate_driver("batch", s, r, tree, cases, OWNED, base.HEAD)

    def root_capture(self):
        run, result = self.prepared_capture()
        # Older folder fixture remains on disk only as a counterexample. Its
        # deliberately missing proof must not be represented as a fourth phase.
        for key in tuple(run.report):
            if key.startswith("native_folder"): del run.report[key]
        run.report["native_root"] = {"verified_empty_before_seed": True, "verified_after_main": True, "device": OWNED}
        run.report["final_inventory"] = {}; run.report["cleanup_verified"] = True
        return run, result

    def test_final_capture_binds_only_actual_three_bundles_after_owned_teardown(self):
        run, result = self.root_capture()
        run.capture_original_result()
        self.assertTrue(run.report["files_preparation_original"]["unchanged_after_cleanup"])
        self.assertTrue(run.report["native_seed_original"]["unchanged_after_cleanup"])
        self.assertNotIn("native_folder_verified", run.report)
        self.assertEqual(run.root / run.report["original_xcresult"]["path"], result)

    def test_final_capture_rejects_missing_post_main_cleanup_and_changed_seed_result(self):
        for fault in ("empty", "after", "device", "baseline", "cleanup", "seed"):
            root = self.root / fault; root.mkdir(); saved = self.root; self.root = root
            try: run, _ = self.root_capture()
            finally: self.root = saved
            if fault == "empty": run.report["native_root"]["verified_empty_before_seed"] = False
            elif fault == "after": run.report["native_root"].pop("verified_after_main")
            elif fault == "device": run.report["native_root"]["device"] = base.EXISTING
            elif fault == "baseline": run.report["final_inventory"] = {OWNED: {}}
            elif fault == "cleanup": run.report["cleanup_verified"] = False
            else: (run.out / "native-seed.xcresult/Data/result").write_bytes(b"modified")
            with self.subTest(fault=fault), self.assertRaises(RuntimeError): run.capture_original_result()
            self.assertNotIn("original_xcresult", run.report)


if __name__ == "__main__": unittest.main(verbosity=2)
