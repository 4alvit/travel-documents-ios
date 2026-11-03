#!/usr/bin/env python3
"""Offline gates for the explicit SDK 26.2 / runtime 18.5 diagnostic."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("runtime_diagnostic", HERE / "diagnose-batch-runtime.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
q = d.q
ENV = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "GITHUB_EVENT_NAME": "workflow_dispatch",
       "GITHUB_WORKFLOW": "Release qualification", "GITHUB_JOB": "qualify",
       "GITHUB_REPOSITORY": "4alvit/travel-documents-ios", "GITHUB_SHA": "a" * 40,
       "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "QUALIFICATION_PROVIDER_LOG": "1",
       "QUALIFICATION_RUNNER": "macos-15", "QUALIFICATION_RUNNER_ARCH": "ARM64",
       "QUALIFICATION_RUNTIME_CONTROL": "ios18.5", "DEVELOPER_DIR": q.DEVELOPER_DIR}


def runtime_data():
    return {"runtimes": [{"identifier": d.RUNTIME, "version": "18.5", "buildversion": "22F77",
                           "isAvailable": True, "supportedArchitectures": ["arm64", "x86_64"],
                           "supportedDeviceTypes": [{"identifier": d.DEVICE_TYPE}]}]}


def plist_data(**changes):
    return q.plistlib.dumps({"MinimumOSVersion": "17.0", "DTPlatformName": "iphonesimulator",
                            "CFBundleSupportedPlatforms": ["iPhoneSimulator"], **changes})


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.clock = [100.0]
        self.enterContext(patch.object(q.time, "monotonic", side_effect=lambda: self.clock[0]))
        self.enterContext(patch.object(q.os, "uname", return_value=SimpleNamespace(machine="arm64")))

    def hooks(self):
        return patch.multiple(q, toolchain_profile=d.runtime_profile, choose_runtime=d.choose_runtime)

    def make_run(self):
        with self.hooks():
            return d.RuntimeQualification(self.root, "batch", ENV)

    def test_explicit_selection_and_arm_workflow_reject_before_output(self):
        variants = [("biometrics", ENV), ("batch", {**ENV, "QUALIFICATION_RUNTIME_CONTROL": ""}),
                    ("batch", {**ENV, "QUALIFICATION_RUNTIME_CONTROL": "ios26.2"}),
                    ("batch", {**ENV, "QUALIFICATION_PROVIDER_LOG": ""}),
                    ("batch", {**ENV, "TEST_RUNNER_TRIPDOCKET_NATIVE_REOPEN_CONTROL": "1"}),
                    ("batch", {**ENV, "QUALIFICATION_RUNNER": "macos-15-intel",
                               "QUALIFICATION_RUNNER_ARCH": "X64"}),
                    ("batch", {**ENV, "GITHUB_EVENT_NAME": "pull_request"})]
        with self.hooks():
            for mode, env in variants:
                with self.subTest(mode=mode, env=env), self.assertRaises(RuntimeError):
                    d.RuntimeQualification(self.root, mode, env)
                self.assertFalse((self.root / "build").exists())
            with patch.object(q.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
                 self.assertRaises(RuntimeError):
                d.RuntimeQualification(self.root, "batch", ENV)
        with self.assertRaisesRegex(RuntimeError, "hooks"):
            d.RuntimeQualification(self.root, "batch", ENV)
        self.assertFalse((self.root / "build").exists())

    def test_only_runtime_profile_changes_and_native_result_must_match(self):
        original = d.BASE_PROFILE("batch")
        self.assertEqual(d.runtime_profile("batch"), {**original, "runtime_version": "18.5"})
        self.assertEqual(d.BASE_PROFILE("batch"), original)
        self.assertEqual(original["sdk_version"], "26.2")
        self.assertEqual(original["xcode_version"], "Xcode 26.2\nBuild version 17C52")
        with self.assertRaises(RuntimeError): d.runtime_profile("biometrics")
        selection = {"identifier": d.RUNTIME, "version": "18.5", "build": "22F77",
                     "architecture": "arm64", "sdk_version": "26.2", "sdk_matched": False}
        result = {"devicesAndConfigurations": [{"device": {
            "osVersion": "18.5", "osBuildNumber": "22F77", "architecture": "arm64"}}]}
        with self.hooks():
            q.validate_runtime_result("batch", selection, result)
            for key, value in [("osVersion", "26.2"), ("osBuildNumber", "23C54"), ("architecture", "x86_64")]:
                wrong = copy.deepcopy(result); wrong["devicesAndConfigurations"][0]["device"][key] = value
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    q.validate_runtime_result("batch", selection, wrong)
            with self.assertRaises(RuntimeError):
                q.validate_runtime_result("batch", {**selection, "sdk_matched": True}, result)

    def test_exact_available_runtime_and_phone_with_no_fallback(self):
        good = runtime_data()
        self.assertEqual(d.choose_runtime(good, "18.5", "arm64"), (d.RUNTIME, d.DEVICE_TYPE))
        changes = [("identifier", "com.apple.CoreSimulator.SimRuntime.iOS-18-4"),
                   ("version", "26.2"), ("buildversion", "22F76"), ("isAvailable", False),
                   ("supportedArchitectures", ["x86_64"]),
                   ("supportedDeviceTypes", [{"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"}])]
        for key, value in changes:
            data = copy.deepcopy(good); data["runtimes"][0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                d.choose_runtime(data, "18.5", "arm64")
        duplicate = copy.deepcopy(good); duplicate["runtimes"].append(copy.deepcopy(good["runtimes"][0]))
        with self.assertRaises(RuntimeError): d.choose_runtime(duplicate, "18.5", "arm64")
        duplicate = copy.deepcopy(good)
        duplicate["runtimes"][0]["supportedDeviceTypes"] *= 2
        with self.assertRaises(RuntimeError): d.choose_runtime(duplicate, "18.5", "arm64")
        for version, arch in [("26.2", "arm64"), ("18.5", "x86_64")]:
            with self.assertRaises(RuntimeError): d.choose_runtime(good, version, arch)

    def test_inherited_prepare_rejects_wrong_build_before_create(self):
        run = self.make_run()
        run.source = lambda _: {"head": "a" * 40, "tree": "b" * 40,
                                "files": dict.fromkeys(q.BATCH_BUILD_RETAINED + q.BATCH_BUILD_EXCLUDED)}
        run.preflight_schemas = lambda: None
        values = {"xcode": q.XCODE_VERSION, "developer": q.DEVELOPER_DIR,
                  "sdk": "26.2", "architecture": "arm64", "generate-project": ""}
        data = runtime_data(); data["runtimes"][0]["buildversion"] = "wrong"
        values["runtimes"] = json.dumps(data)
        calls = []
        def command(label, argv, seconds=30):
            calls.append(label)
            return values[label]
        run.command = command
        original_clocks = run.started, run.work_deadline, run.cleanup_deadline
        with self.hooks(), patch.dict(q.os.environ, ENV), self.assertRaisesRegex(RuntimeError, "22F77"):
            run.prepare()
        self.assertEqual(calls[-1], "runtimes")
        self.assertNotIn("create", calls)
        self.assertIsNone(run.owned)
        self.assertEqual((run.started, run.work_deadline, run.cleanup_deadline), original_clocks)
        self.assertEqual(run.commands.limit, run.work_deadline)

    def test_product_minimum_and_simulator_platform_are_actual_plist_values(self):
        for minimum in ("15.0", "17.0", "18.5", "18.5.0"):
            self.assertEqual(d.product_compatibility(plist_data(MinimumOSVersion=minimum))["minimum_os_version"], minimum)
        for minimum in ("18.5.1", "18.6", "26.2", "18", "18.5beta", "", True, 18.5):
            with self.subTest(minimum=minimum), self.assertRaises(RuntimeError):
                d.product_compatibility(plist_data(MinimumOSVersion=minimum))
        for changes in ({"DTPlatformName": "iphoneos"}, {"CFBundleSupportedPlatforms": ["iPhoneOS"]},
                        {"CFBundleSupportedPlatforms": ["iPhoneSimulator", "iPhoneOS"]}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                d.product_compatibility(plist_data(**changes))
        with self.assertRaises(RuntimeError): d.product_compatibility(q.plistlib.dumps({}))
        with self.assertRaises(RuntimeError): d.product_compatibility(q.plistlib.dumps([]))

    def make_products(self, run):
        run.shared_products = {}
        for name in sorted(d.PRODUCTS):
            path = self.root / name; path.mkdir(); (path / "Info.plist").write_bytes(plist_data())
            run.shared_products[name] = path
        run.shared_product_identity = {name: q.compiled_identity(path, run.check)
                                       for name, path in run.shared_products.items()}

    def test_shared_super_proof_precedes_bounded_four_product_check(self):
        run = self.make_run()
        calls = []
        def shared(_self, driver):
            calls.append("inherited shared proof")
            self.make_products(_self)
        driver = SimpleNamespace(remaining=lambda: 100)
        with patch.object(d.provider.ProviderLogQualification, "prepare_shared_build", shared):
            run.prepare_shared_build(driver)
        self.assertEqual(calls, ["inherited shared proof"])
        proof = run.report["diagnostic_runtime_control"]["product_compatibility"]
        self.assertEqual(proof["status"], "verified")
        self.assertEqual(proof["before_phase"], "seed")
        self.assertEqual(set(proof["products"]), d.PRODUCTS)
        self.assertEqual(proof["products"]["Tripfolio"]["info_plist_sha256"], hashlib.sha256(plist_data()).hexdigest())
        self.assertEqual((run.work_deadline - run.started, run.cleanup_deadline - run.work_deadline), (2400, 180))

    def test_product_check_rejects_alias_drift_missing_oversize_and_expired_clock(self):
        run = self.make_run(); self.make_products(run)
        driver = SimpleNamespace(remaining=lambda: 100)
        path = run.shared_products["Tripfolio"] / "Info.plist"
        good = path.read_bytes()
        with patch.object(d.provider.ProviderLogQualification, "prepare_shared_build", lambda *_: None):
            for raw in (plist_data(MinimumOSVersion="26.2"), plist_data(Extra="changed"), b"x" * (q.MIB + 1)):
                path.write_bytes(raw)
                with self.subTest(size=len(raw)), self.assertRaises(RuntimeError): run.prepare_shared_build(driver)
            path.write_bytes(good)
            target = self.root / "other.plist"; target.write_bytes(good)
            path.unlink(); path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "link"): run.prepare_shared_build(driver)
            path.unlink(); path.write_bytes(good)
            missing = run.shared_products.pop("TripfolioTests")
            with self.assertRaisesRegex(RuntimeError, "Missing"): run.prepare_shared_build(driver)
            run.shared_products["TripfolioTests"] = missing
            driver.remaining = lambda: 0
            with self.assertRaisesRegex(RuntimeError, "driver deadline"): run.prepare_shared_build(driver)
            driver.remaining = lambda: 100
            self.clock[0] = run.work_deadline
            with self.assertRaisesRegex(RuntimeError, "deadline"): run.prepare_shared_build(driver)
        self.assertEqual(run.report["diagnostic_runtime_control"]["product_compatibility"]["status"], "pending")

    def test_every_saved_receipt_is_diagnostic_and_missing_product_proof_incomplete(self):
        run = self.make_run()
        receipt = json.loads((run.out / "receipt.json").read_text())
        self.assertFalse(receipt["diagnostic_runtime_control"]["release_acceptance"])
        self.assertFalse(receipt["diagnostic_runtime_control"]["sdk_matched"])
        for log_status, product_status, expected in [
            ("captured", "pending", "diagnostic_incomplete"),
            ("failed", "verified", "diagnostic_incomplete"),
            ("captured", "verified", "diagnostic_captured_pending_review")]:
            run.report["status"] = "captured_pending_review"
            run.report["diagnostic_provider_log"]["status"] = log_status
            run.report["diagnostic_runtime_control"]["product_compatibility"]["status"] = product_status
            run.save()
            self.assertEqual(run.report["status"], expected)
        run.report["status"] = "failed"; run.report["errors"] = ["native failure"]
        run.save()
        self.assertEqual(run.report["status"], "failed")
        self.assertEqual(run.report["errors"], ["native failure"])

    def test_native_execution_cleanup_and_provider_capture_are_inherited(self):
        for name in ("prepare", "run_driver", "execute", "cleanup", "capture_provider_log", "command"):
            self.assertIs(getattr(d.RuntimeQualification, name), getattr(d.provider.ProviderLogQualification, name))
        self.assertEqual((d.provider.COMMAND_SECONDS, d.provider.STOP_SECONDS, d.provider.FINALIZER_SECONDS), (30, 8, 120))

    def test_entrypoint_preserves_real_signal_handler_and_restores_hooks(self):
        originals = q.Qualification, q.toolchain_profile, q.choose_runtime
        handlers = {}
        run = SimpleNamespace(interrupted=False, acquiring=False, finalizing_driver=False, cleaning=False)
        def execute(): handlers[signal.SIGTERM](signal.SIGTERM, None)
        run.execute = execute
        with patch.dict(q.os.environ, ENV), patch.object(d.sys, "argv", ["diagnose", "--mode", "batch"]), \
             patch.object(d, "RuntimeQualification", return_value=run), \
             patch.object(q.signal, "signal", side_effect=lambda sig, handler: handlers.update({sig: handler})):
            with self.assertRaises(KeyboardInterrupt): d.main()
        self.assertTrue(run.interrupted)
        self.assertEqual(set(handlers), {signal.SIGTERM, signal.SIGINT})
        self.assertEqual((q.Qualification, q.toolchain_profile, q.choose_runtime), originals)
        run.interrupted = False; run.cleaning = True
        handlers[signal.SIGINT](signal.SIGINT, None)
        self.assertTrue(run.interrupted)

    def test_entrypoint_returns_inherited_status_and_restores_on_exception(self):
        originals = q.Qualification, q.toolchain_profile, q.choose_runtime
        def result():
            self.assertIs(q.toolchain_profile, d.runtime_profile)
            self.assertIs(q.choose_runtime, d.choose_runtime)
            self.assertIs(q.Qualification, d.RuntimeQualification)
            return 1
        with patch.dict(q.os.environ, ENV), patch.object(d.sys, "argv", ["diagnose", "--mode", "batch"]):
            with patch.object(q, "main", side_effect=result): self.assertEqual(d.main(), 1)
            with patch.object(q, "main", side_effect=RuntimeError("original failure")), \
                 self.assertRaisesRegex(RuntimeError, "original failure"): d.main()
        self.assertEqual((q.Qualification, q.toolchain_profile, q.choose_runtime), originals)

    def test_invalid_cli_and_selector_never_enter_original_main(self):
        with patch.object(q, "main") as inherited:
            for argv, value in [(["diagnose", "--mode", "biometrics"], "ios18.5"),
                                (["diagnose", "--mode", "batch", "--other"], "ios18.5"),
                                (["diagnose", "--mode", "batch"], "arbitrary")]:
                with patch.object(d.sys, "argv", argv), patch.dict(q.os.environ, {**ENV, "QUALIFICATION_RUNTIME_CONTROL": value}), \
                     self.assertRaises(RuntimeError): d.main()
            inherited.assert_not_called()
        self.assertFalse((self.root / "build").exists())


if __name__ == "__main__":
    unittest.main()
