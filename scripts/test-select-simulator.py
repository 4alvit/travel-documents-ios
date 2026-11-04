#!/usr/bin/env python3
"""Offline selector and real shell-wiring regressions; native tools are stubs."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("selector", HERE / "select-simulator.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
RUNTIME = "com.apple.CoreSimulator.SimRuntime.iOS-26-2"
NEWER = "com.apple.CoreSimulator.SimRuntime.iOS-27-0"
PHONE = "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro"
PAD = "com.apple.CoreSimulator.SimDeviceType.iPad-Pro"
FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"


def fixture():
    runtime = {"identifier": RUNTIME, "version": "26.2", "buildversion": "23C54", "isAvailable": True,
               "supportedArchitectures": ["arm64", "x86_64"], "supportedDeviceTypes": [{"identifier": PHONE}]}
    types = [{"identifier": PHONE, "productFamily": "iPhone"}, {"identifier": PAD, "productFamily": "iPad"}]
    phone = {"udid": FIRST, "name": "iPhone 17 Pro", "deviceTypeIdentifier": PHONE, "isAvailable": True}
    newer = {**runtime, "identifier": NEWER, "version": "27.0"}
    return {"runtimes": [runtime, newer]}, {"devicetypes": types}, {
        "devices": {RUNTIME: [phone], NEWER: [{**phone, "udid": SECOND}]}}


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.runtimes, self.types, self.devices = fixture()

    def select(self, **kwargs):
        return m.select_device(kwargs.get("sdk", "26.2"), kwargs.get("architecture", "arm64"),
                               self.runtimes, self.types, self.devices, kwargs.get("requested"))

    def test_exact_sdk_is_selected_without_newest_runtime_fallback(self):
        self.assertEqual(self.select()["udid"], FIRST)
        self.devices["devices"][RUNTIME] = []
        with self.assertRaises(ValueError): self.select()

    def test_requested_uuid_is_checked_not_silently_replaced(self):
        self.assertEqual(self.select(requested=FIRST)["udid"], FIRST)
        for value in [SECOND, "33333333-3333-4333-8333-333333333333", "invalid"]:
            with self.subTest(value=value), self.assertRaises(ValueError): self.select(requested=value)

    def test_missing_and_unavailable_runtime_fail(self):
        self.runtimes["runtimes"][0]["isAvailable"] = False
        with self.assertRaises(ValueError): self.select()
        self.runtimes["runtimes"].pop(0)
        with self.assertRaises(ValueError): self.select()

    def test_duplicate_matching_runtime_fails_even_if_one_unavailable(self):
        other = copy.deepcopy(self.runtimes["runtimes"][0]); other["isAvailable"] = False
        self.runtimes["runtimes"].append(other)
        with self.assertRaises(ValueError): self.select()

    def test_same_runtime_identifier_with_another_version_is_ambiguous(self):
        self.runtimes["runtimes"][1]["identifier"] = RUNTIME
        with self.assertRaises(ValueError): self.select()

    def test_architecture_and_sdk_are_validated(self):
        for kwargs in [{"sdk": "bad"}, {"sdk": "16.4"}, {"architecture": "unknown"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.select(**kwargs)
        self.runtimes["runtimes"][0]["supportedArchitectures"] = ["x86_64"]
        with self.assertRaises(ValueError): self.select()
        self.assertEqual(self.select(architecture="x86_64")["udid"], FIRST)

    def test_runtime_build_identity_is_required(self):
        del self.runtimes["runtimes"][0]["buildversion"]
        with self.assertRaises(ValueError): self.select()

    def test_only_explicitly_compatible_available_iphone_is_accepted(self):
        for field, value in [("deviceTypeIdentifier", PAD), ("deviceTypeIdentifier", "unknown"), ("isAvailable", False)]:
            with self.subTest(field=field, value=value):
                original = self.devices["devices"][RUNTIME][0][field]
                self.devices["devices"][RUNTIME][0][field] = value
                with self.assertRaises(ValueError): self.select()
                self.devices["devices"][RUNTIME][0][field] = original
        self.runtimes["runtimes"][0]["supportedDeviceTypes"] = []
        with self.assertRaises(ValueError): self.select()

    def test_duplicate_device_and_type_identities_fail(self):
        self.devices["devices"][NEWER][0]["udid"] = FIRST
        with self.assertRaises(ValueError): self.select()
        self.devices = fixture()[2]
        self.types["devicetypes"].append(copy.deepcopy(self.types["devicetypes"][0]))
        with self.assertRaises(ValueError): self.select()

    def test_duplicate_compatibility_entries_fail(self):
        self.runtimes["runtimes"][0]["supportedDeviceTypes"] *= 2
        with self.assertRaises(ValueError): self.select()

    def test_existing_inventory_order_is_preserved_inside_matching_runtime(self):
        second = {**self.devices["devices"][RUNTIME][0], "udid": SECOND}
        self.devices["devices"] = {RUNTIME: [second, self.devices["devices"][RUNTIME][0]]}
        self.assertEqual(self.select()["udid"], SECOND)
        self.assertEqual(self.select(requested=FIRST)["udid"], FIRST)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError): m.decode(b'{"devices":{},"devices":{}}')


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve(); (self.root / "scripts").mkdir(); (self.root / "bin").mkdir()
        for name in ("test-simulator.sh", "select-simulator.py"):
            shutil.copyfile(HERE / name, self.root / "scripts" / name)
        self.input = self.root / "input"; self.input.mkdir()
        for name, value in zip(("runtimes.json", "device-types.json", "devices.json"), fixture()):
            (self.input / name).write_text(json.dumps(value))
        self.output = self.root / "xcode-arguments.json"
        self.env = {**os.environ, "PATH": str(self.root / "bin") + ":" + os.defpath,
                    "FAKE_SIM_INVENTORY": str(self.input), "FAKE_XCODE_ARGS": str(self.output)}
        for name in ("TRIPFOLIO_SIMULATOR_ID", "TEST_RUNNER_TRIPDOCKET_PHONE_TIMING",
                     "TRIPDOCKET_PHONE_TIMING", "RUNNER_ARCH", "GITHUB_ACTIONS"):
            self.env.pop(name, None)
        (self.root / "bin/python3").symlink_to(sys.executable)
        tools = {
            "xcodegen": "pass",
            "uname": "print(os.environ.get('FAKE_ARCH', 'arm64'))",
            "xcodebuild": "Path(os.environ['FAKE_XCODE_ARGS']).write_text(json.dumps(sys.argv[1:])); Path(os.environ['FAKE_XCODE_ARGS'] + '.env').write_text(json.dumps({k:v for k,v in os.environ.items() if 'PHONE_TIMING' in k}))",
            "xcrun": """args = sys.argv[1:]
if args == ['--sdk', 'iphonesimulator', '--show-sdk-version']: print('26.2')
elif args[:2] == ['simctl', 'list']:
    name = {'runtimes':'runtimes.json', 'devicetypes':'device-types.json', 'devices':'devices.json'}[args[2]]
    print((Path(os.environ['FAKE_SIM_INVENTORY']) / name).read_text())
else: raise RuntimeError('Unexpected native command: ' + repr(args))""",
        }
        for name, body in tools.items():
            path = self.root / "bin" / name
            path.write_text("#!" + sys.executable + "\nimport os,sys,json\nfrom pathlib import Path\n" + body + "\n")
            path.chmod(0o755)

    def run_script(self, *args, requested=None):
        env = dict(self.env)
        if requested is not None: env["TRIPFOLIO_SIMULATOR_ID"] = requested
        return subprocess.run(["/bin/bash", str(self.root / "scripts/test-simulator.sh"), *args],
                              env=env, capture_output=True, text=True, timeout=10)

    def test_strict_shell_wiring_and_cohort_limits(self):
        result = self.run_script("--require-sdk-match", "--cohort", "core-purchase")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(self.output.read_text())
        self.assertIn("platform=iOS Simulator,id=" + FIRST, argv)
        self.assertEqual([x for x in argv if x.startswith("-only-testing:")], [
            "-only-testing:TripfolioTests", "-only-testing:TripfolioUITests/PurchaseUITests",
            "-only-testing:TripfolioUITests/TripfolioUITests"])
        for flag, value in [("-default-test-execution-time-allowance", "180"),
                            ("-maximum-test-execution-time-allowance", "480")]:
            self.assertEqual(argv[argv.index(flag) + 1], value)
        source = (HERE.parent / "UITests/PurchaseUITests.swift").read_text()
        helper = source.split("private func verifyPurchaseFailureAlert(", 1)[1].split(
            "private func requirePurchasePostcondition(", 1)[0]
        self.assertIn("executionTimeAllowance = 240", helper)
        self.assertEqual(source.count("executionTimeAllowance ="), 1)
        records = list((self.root / "build/ci-toolchain").glob("simulator-selection.*/selection.json"))
        self.assertEqual(len(records), 1)
        selection = json.loads(records[0].read_text())
        self.assertEqual(selection["udid"], FIRST); self.assertEqual(len(selection["inventory_sha256"]), 5)

    def test_only_guidance_cohort_allows_measured_russian_flow_budget(self):
        for arguments, ceiling in [((), "480"),
                                   (("--cohort", "core-purchase"), "480"),
                                   (("--cohort", "ui-guidance"), "600")]:
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                argv = json.loads(self.output.read_text())
                self.assertEqual(argv[argv.index("-default-test-execution-time-allowance") + 1], "180")
                self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance") + 1], ceiling)
        source = (Path(__file__).resolve().parents[1] / "UITests/PrivacySupportUITests.swift").read_text()
        self.assertIn("executionTimeAllowance = russian && maximumType ? 600 : (hostedPhone ? 720 : 480)", source)
        self.assertEqual(source.count("executionTimeAllowance ="), 1)

    def test_hosted_phone_profile_is_final_invocation_only(self):
        self.env.update(GITHUB_ACTIONS="true", RUNNER_OS="macOS", RUNNER_ARCH="X64",
                        RUNNER_ENVIRONMENT="github-hosted", GITHUB_WORKFLOW="CI",
                        GITHUB_JOB="ui_guidance", FAKE_ARCH="x86_64")
        (self.root / "scripts/prepare-guidance-files.py").write_text(
            "import os\nassert 'TEST_RUNNER_TRIPDOCKET_PHONE_TIMING' not in os.environ\n"
            "assert 'TRIPDOCKET_PHONE_TIMING' not in os.environ\n")
        result = self.run_script("--require-sdk-match", "--prepare-files", "--cohort", "ui-guidance")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(self.output.read_text())
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance") + 1], "720")
        self.assertEqual(argv[argv.index("-default-test-execution-time-allowance") + 1], "180")
        exported = json.loads(Path(str(self.output) + ".env").read_text())
        self.assertEqual(exported, {"TEST_RUNNER_TRIPDOCKET_PHONE_TIMING": "hosted-intel-phone-v1"})
        for args in [(), ("--cohort", "core-purchase"), ("--cohort", "ui-guidance")]:
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(Path(str(self.output) + ".env").read_text()), {})

    def test_hosted_phone_rejects_inherited_tokens_and_crossed_host_before_tools(self):
        for name in ["TEST_RUNNER_TRIPDOCKET_PHONE_TIMING", "TRIPDOCKET_PHONE_TIMING"]:
            for value in ["", "wrong", "hosted-intel-phone-v1"]:
                with self.subTest(name=name, value=value):
                    self.env[name] = value
                    result = self.run_script()
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertFalse(self.output.exists())
                    del self.env[name]
        self.env.update(GITHUB_ACTIONS="true", RUNNER_OS="macOS", RUNNER_ARCH="X64",
                        RUNNER_ENVIRONMENT="github-hosted", GITHUB_WORKFLOW="CI",
                        GITHUB_JOB="ui_guidance", FAKE_ARCH="x86_64")
        for name, wrong in [("RUNNER_OS", "Linux"), ("RUNNER_ENVIRONMENT", "self-hosted"),
                            ("GITHUB_WORKFLOW", "Other"), ("GITHUB_JOB", "recovery"),
                            ("FAKE_ARCH", "arm64")]:
            with self.subTest(name=name):
                old = self.env[name]; self.env[name] = wrong
                result = self.run_script("--require-sdk-match", "--prepare-files", "--cohort", "ui-guidance")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.output.exists())
                self.env[name] = old

    def test_strict_wrong_requested_uuid_prevents_native_test_command(self):
        result = self.run_script("--require-sdk-match", requested=SECOND)
        self.assertNotEqual(result.returncode, 0); self.assertFalse(self.output.exists())

    def test_local_default_and_explicit_override_keep_previous_behavior(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("platform=iOS Simulator,id=" + SECOND, json.loads(self.output.read_text()))
        result = self.run_script("--cohort", "ui-guidance", requested=SECOND)
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(self.output.read_text())
        self.assertIn("platform=iOS Simulator,id=" + SECOND, argv)
        self.assertIn("-skip-testing:TripfolioUITests/PurchaseUITests", argv)
        self.assertFalse((self.root / "build/ci-toolchain").exists())

    def test_selection_cli_never_overwrites_existing_receipt(self):
        for name, value in [("sdk.txt", "26.2"), ("architecture.txt", "arm64")]: (self.input / name).write_text(value)
        command = [sys.executable, "-B", str(HERE / "select-simulator.py"), "--inventory", str(self.input)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.input / "selection.json").read_bytes()
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0); self.assertEqual((self.input / "selection.json").read_bytes(), original)


if __name__ == "__main__": unittest.main(verbosity=2)
