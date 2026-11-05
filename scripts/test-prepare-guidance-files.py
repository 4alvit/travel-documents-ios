#!/usr/bin/env python3
"""Non-native regressions for the actual Files bootstrap and shell boundary."""
import copy
import errno
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


m = load("guidance_files", "prepare-guidance-files.py")
s = load("selector_tests", "test-select-simulator.py")
CI = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "RUNNER_ENVIRONMENT": "github-hosted",
      "GITHUB_WORKFLOW": "CI", "GITHUB_JOB": "ui_guidance"}


class Clock:
    def __init__(self): self.value = 1.; self.env = dict(CI)
    def now(self): return self.value
    def sleep(self, seconds): self.value += seconds


class Fake(m.Bootstrap):
    def command(self, label, argv, cap):
        self.checkpoint(); self.calls.append((label, argv, cap))
        if label == self.fail: raise RuntimeError("Injected command failure")
        if label == "prepare-ui":
            self.devices["devices"][s.RUNTIME][0]["state"] = "Booted"
            self.prep_env = dict(self.ops.env)
            result = self.out / "prepare.xcresult"; result.mkdir(); (result / "Data").mkdir()
            (result / "Info.plist").write_bytes(b"synthetic-result")
        if label == "post-preparation-bootstatus":
            self.devices["devices"][s.RUNTIME][0]["state"] = "Booted"
        result = {"xcode": "Xcode 26.2\nBuild version 17C52\n", "sdk": "26.2\n", "architecture": self.architecture + "\n",
                  "runtimes": self.runtimes, "types": self.types, "devices-before": self.devices,
                  "devices-booted": self.devices, "devices-after-warm-boot": self.devices,
                  "devices-final": self.devices, "post-preparation-bootstatus": "",
                  "prepare-ui": "",
                  "prepare-summary": self.summary, "prepare-tests": self.tree,
                  "files-group": m.GROUP + "\t" + str(self.group) + "\n"}[label]
        result = self.transform(label, copy.deepcopy(result))
        return json.dumps(result) if isinstance(result, dict) else result


class BootstrapTests(unittest.TestCase):
    def make(self, state="Shutdown", architecture="arm64"):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve(); home = root / "home"; home.mkdir()
        directory = root / "selection"; directory.mkdir()
        data = home / "Library/Developer/CoreSimulator/Devices" / s.FIRST / "data"; data.mkdir(parents=True)
        group = data / "Containers/Shared/AppGroup/33333333-3333-4333-8333-333333333333"
        group.mkdir(parents=True); (group / "File Provider Storage").mkdir()
        runtimes, types, devices = s.fixture()
        devices["devices"][s.RUNTIME][0].update(state=state, dataPath=str(data))
        devices["devices"][s.NEWER][0]["state"] = "Shutdown"
        raw = {"sdk.txt": b"26.2\n", "architecture.txt": (architecture + "\n").encode(), "runtimes.json": json.dumps(runtimes).encode(),
               "device-types.json": json.dumps(types).encode(), "devices.json": json.dumps(devices).encode()}
        for name, value in raw.items(): (directory / name).write_bytes(value)
        selected = m.selector.select_device("26.2", architecture, runtimes, types, devices)
        selected["inventory_sha256"] = {name: m.digest(value) for name, value in raw.items()}
        (directory / "selection.json").write_text(json.dumps(selected))
        with patch.object(Path, "home", return_value=home), \
                patch.object(m.os, "uname", return_value=SimpleNamespace(machine=architecture)), \
                patch.object(m.time, "monotonic", return_value=1.):
            runner = Fake(directory, CI)
        runner.architecture = architecture
        runner.home = home; runner.calls = []; runner.fail = None; runner.transform = lambda _, result: result
        runner.runtimes = runtimes; runner.types = types; runner.devices = devices; runner.group = group
        runner.summary = {"result": "Passed", "totalTestCount": 1, "passedTests": 1, "failedTests": 0,
            "skippedTests": 0, "expectedFailures": 0, "testFailures": [], "devicesAndConfigurations": [{"device": {
                "deviceId": s.FIRST, "platform": "iOS Simulator", "osVersion": "26.2", "osBuildNumber": "23C54", "architecture": architecture}}]}
        runner.tree = {"testNodes": [{"nodeType": "Test Case", "nodeIdentifier": m.PREPARE_CASE, "result": "Passed"}],
                       "devices": [{"deviceId": s.FIRST, "platform": "iOS Simulator"}]}
        runner.ops = Clock()
        return runner

    def run_bootstrap(self, runner):
        with patch.object(Path, "home", return_value=runner.home): return runner.execute()

    def test_actual_prepare_owns_selected_startup_once_and_preserves_provider(self):
        runner = self.make(); (runner.group / "File Provider Storage/sentinel").write_text("unchanged")
        self.assertEqual(self.run_bootstrap(runner), 0, runner.report)
        labels = [call[0] for call in runner.calls]
        self.assertEqual(labels, ["xcode", "sdk", "architecture", "runtimes", "types", "devices-before",
                                 "prepare-ui", "prepare-summary", "prepare-tests", "devices-booted", "files-group", "devices-final"])
        for label, argv, _ in runner.calls:
            if label == "files-group": self.assertEqual(argv[3], s.FIRST)
            self.assertFalse(set(argv) & {"boot", "bootstatus", "delete", "erase", "shutdown", "terminate", "spawn"})
        self.assertEqual((runner.group / "File Provider Storage/sentinel").read_text(), "unchanged")
        self.assertTrue(runner.report["final_inventory_verified"])
        self.assertEqual(runner.report["status"], "provider_ready")
        self.assertEqual(runner.report["host_cleanup"], {"active_groups": [], "unknown_spawn": False})

    def test_intel_bootstrap_preserves_selected_architecture_and_provider(self):
        runner = self.make(architecture="x86_64")
        sentinel = runner.group / "File Provider Storage/sentinel"
        sentinel.write_text("unchanged")
        self.assertEqual(self.run_bootstrap(runner), 0, runner.report)
        self.assertEqual(runner.report["status"], "provider_ready")
        self.assertEqual(runner.report["selected"]["architecture"], "x86_64")
        self.assertEqual((runner.directory / "architecture.txt").read_text(), "x86_64\n")
        self.assertTrue(runner.report["final_inventory_verified"])
        self.assertTrue(runner.report["original_result"]["unchanged_after_reader"])
        self.assertEqual(sentinel.read_text(), "unchanged")
        self.assertEqual(sum(call[0] == "prepare-ui" for call in runner.calls), 1)
        self.assertFalse(runner.report["post_preparation_warm_boot"])

    def test_crossed_live_architecture_fails_before_native_preparation(self):
        for selected, live in [("x86_64", "arm64"), ("arm64", "x86_64")]:
            with self.subTest(selected=selected, live=live):
                runner = self.make(architecture=selected)
                runner.transform = lambda label, value: live + "\n" if label == "architecture" else value
                self.assertEqual(self.run_bootstrap(runner), 1)
                self.assertIn("Live toolchain differs from selection", " ".join(runner.report["errors"]))
                labels = [call[0] for call in runner.calls]
                self.assertNotIn("prepare-ui", labels)
                self.assertNotIn("files-group", labels)

    def test_crossed_result_architecture_fails_before_provider_acceptance(self):
        for selected, result in [("x86_64", "arm64"), ("arm64", "x86_64")]:
            with self.subTest(selected=selected, result=result):
                runner = self.make(architecture=selected)
                runner.summary["devicesAndConfigurations"][0]["device"]["architecture"] = result
                self.assertEqual(self.run_bootstrap(runner), 1)
                self.assertIn("Preparation runtime identity mismatch", " ".join(runner.report["errors"]))
                labels = [call[0] for call in runner.calls]
                self.assertEqual(labels.count("prepare-ui"), 1)
                self.assertNotIn("files-group", labels)
                self.assertFalse(runner.report.get("final_inventory_verified", False))

    def test_already_booted_is_not_booted_again(self):
        runner = self.make("Booted"); self.assertEqual(self.run_bootstrap(runner), 0)
        self.assertNotIn("boot", [call[0] for call in runner.calls])
        self.assertNotIn("bootstatus", [call[0] for call in runner.calls])
        self.assertEqual(sum(call[0] == "prepare-ui" for call in runner.calls), 1)
        self.assertFalse(runner.report["post_preparation_warm_boot"])
        self.assertEqual(runner.report["post_boot_state"], "Booted")

    def test_successful_preparation_returned_to_shutdown_gets_one_exact_warm_boot(self):
        runner = self.make()
        def transform(label, value):
            if label == "devices-booted": value["devices"][s.RUNTIME][0]["state"] = "Shutdown"
            return value
        runner.transform = transform
        self.assertEqual(self.run_bootstrap(runner), 0, runner.report)
        warm = [call for call in runner.calls if call[0] == "post-preparation-bootstatus"]
        self.assertEqual(warm, [("post-preparation-bootstatus", ["xcrun", "simctl", "bootstatus", s.FIRST, "-b"], 180)])
        labels = [call[0] for call in runner.calls]
        self.assertLess(labels.index("prepare-tests"), labels.index("post-preparation-bootstatus"))
        self.assertLess(labels.index("post-preparation-bootstatus"), labels.index("devices-after-warm-boot"))
        self.assertLess(labels.index("devices-after-warm-boot"), labels.index("files-group"))
        self.assertEqual(runner.report["post_preparation_state"], "Shutdown")
        self.assertTrue(runner.report["post_preparation_warm_boot"])
        self.assertEqual(runner.report["post_boot_state"], "Booted")
        self.assertTrue(runner.report["final_inventory_verified"])

    def test_warm_boot_failures_and_changed_post_boot_identity_stop_before_provider(self):
        for fault in ("command", "inventory", "shutdown", "booting", "identity", "path", "root"):
            with self.subTest(fault=fault):
                runner = self.make()
                if fault == "command": runner.fail = "post-preparation-bootstatus"
                if fault == "inventory": runner.fail = "devices-after-warm-boot"
                def transform(label, value):
                    if label == "devices-booted": value["devices"][s.RUNTIME][0]["state"] = "Shutdown"
                    if label == "devices-after-warm-boot":
                        row = value["devices"][s.RUNTIME][0]
                        if fault == "shutdown": row["state"] = "Shutdown"
                        elif fault == "booting": row["state"] = "Booting"
                        elif fault == "identity": row["name"] = "changed"
                        elif fault == "path": row["dataPath"] = "/tmp/foreign"
                        elif fault == "root":
                            root = Path(row["dataPath"])
                            root.rename(root.with_name("previous-data")); root.mkdir()
                    return value
                runner.transform = transform
                self.assertEqual(self.run_bootstrap(runner), 1)
                labels = [call[0] for call in runner.calls]
                self.assertEqual(labels.count("post-preparation-bootstatus"), 1)
                self.assertNotIn("files-group", labels)
                self.assertFalse(runner.report.get("final_inventory_verified", False))

    def test_live_identity_state_and_toolchain_changes_fail_before_launch(self):
        variants = [("devices-before", lambda d: d["devices"][s.RUNTIME][0].update(state="Booting")),
                    ("devices-before", lambda d: d["devices"][s.RUNTIME][0].update(isAvailable=False)),
                    ("devices-before", lambda d: d["devices"][s.RUNTIME].append(copy.deepcopy(d["devices"][s.RUNTIME][0]))),
                    ("devices-before", lambda d: d["devices"].pop(s.RUNTIME)),
                    ("devices-before", lambda d: d["devices"][s.RUNTIME][0].update(dataPath="/tmp/another-device")),
                    ("runtimes", lambda d: d["runtimes"][0].update(buildversion="changed")),
                    ("runtimes", lambda d: d["runtimes"][0].update(supportedArchitectures=["x86_64"]))]
        for label, mutation in variants:
            with self.subTest(label=label, mutation=mutation):
                runner = self.make()
                def transform(current, value):
                    if current == label: mutation(value)
                    return value
                runner.transform = transform
                self.assertEqual(self.run_bootstrap(runner), 1)
                self.assertNotIn("prepare-ui", [call[0] for call in runner.calls])
        for label in ["xcode", "sdk", "architecture"]:
            runner = self.make(); runner.transform = lambda current, value: "wrong" if current == label else value
            self.assertEqual(self.run_bootstrap(runner), 1)

    def test_post_preparation_identity_state_and_data_root_still_gate_provider(self):
        for fault in ("state", "identity", "root"):
            with self.subTest(fault=fault):
                runner = self.make()
                def transform(label, value):
                    if label == "devices-booted":
                        value["devices"][s.RUNTIME][0]["state"] = "Shutdown"
                        if fault == "state": value["devices"][s.RUNTIME][0]["state"] = "Booting"
                        elif fault == "identity": value["devices"][s.RUNTIME][0]["name"] = "changed"
                        else:
                            root = Path(value["devices"][s.RUNTIME][0]["dataPath"])
                            root.rename(root.with_name("previous-data")); root.mkdir()
                    return value
                runner.transform = transform
                self.assertEqual(self.run_bootstrap(runner), 1)
                labels = [call[0] for call in runner.calls]
                self.assertEqual(labels.count("prepare-ui"), 1)
                self.assertIn("prepare-tests", labels)
                self.assertNotIn("post-preparation-bootstatus", labels)
                self.assertNotIn("files-group", labels)
                self.assertFalse(runner.report.get("final_inventory_verified", False))

    def test_final_other_device_or_target_change_rejects_readiness(self):
        for runtime, field, value in [(s.NEWER, "state", "Booted"), (s.RUNTIME, "state", "Shutdown"),
                                      (s.RUNTIME, "name", "renamed")]:
            runner = self.make()
            def transform(label, result):
                if label == "devices-final": result["devices"][runtime][0][field] = value
                return result
            runner.transform = transform
            self.assertEqual(self.run_bootstrap(runner), 1)
            self.assertEqual(runner.report["status"], "failed")

    def test_failed_command_is_not_retried_and_receipt_survives(self):
        for label in ["prepare-ui", "devices-booted", "files-group", "devices-final"]:
            runner = self.make(); runner.fail = label
            self.assertEqual(self.run_bootstrap(runner), 1)
            self.assertEqual(sum(call[0] == label for call in runner.calls), 1)
            self.assertEqual(json.loads((runner.out / "receipt.json").read_text())["status"], "failed")

    def test_preparation_failure_prevents_provider_acceptance(self):
        runner = self.make(); runner.summary["failedTests"] = 1
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertNotIn("files-group", [call[0] for call in runner.calls])
        self.assertNotIn("post-preparation-bootstatus", [call[0] for call in runner.calls])

    def test_group_response_has_no_ambiguous_or_foreign_fallback(self):
        for text in ["", m.GROUP + "\t/tmp/foreign\n", m.GROUP + "\tbad\textra\n"]:
            runner = self.make(); runner.transform = lambda label, value: text if label == "files-group" else value
            self.assertEqual(self.run_bootstrap(runner), 1)
        runner = self.make(); runner.transform = lambda label, value: value * 2 if label == "files-group" else value
        self.assertEqual(self.run_bootstrap(runner), 1)

    def test_provider_absence_has_finite_observation_no_creation_or_relaunch(self):
        runner = self.make(); provider = runner.group / "File Provider Storage"; provider.rmdir()
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertFalse(provider.exists()); self.assertGreater(runner.report["provider"]["absent_observations"], 0)
        self.assertLessEqual(runner.ops.now() - runner.t0, 31)
        self.assertEqual(sum(call[0] == "prepare-ui" for call in runner.calls), 1)

    def test_preparation_selection_limits_environment_and_original_bytes(self):
        runner = self.make(); before_env = runner.ops.env
        self.assertEqual(self.run_bootstrap(runner), 0, runner.report)
        _, argv, cap = next(call for call in runner.calls if call[0] == "prepare-ui")
        self.assertEqual(cap, 960)
        self.assertEqual((m.WORK, m.STOP, m.WRITE), (1080, 30, 10))
        self.assertEqual(runner.limit - runner.t0, 1080)
        self.assertEqual([v for v in argv if v.startswith("-only-testing:")], ["-only-testing:TripfolioUITests/" + m.PREPARE_CASE.removesuffix("()")])
        self.assertEqual(argv[argv.index("-destination") + 1], "platform=iOS Simulator,id=" + s.FIRST)
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance") + 1], "180")
        self.assertEqual(argv[argv.index("-default-test-execution-time-allowance") + 1], "180")
        self.assertEqual(argv[argv.index("-derivedDataPath") + 1], str(HERE.parent / "build/DerivedData"))
        self.assertFalse(any(value.startswith("COMPILER_INDEX_STORE_ENABLE=") for value in argv))
        self.assertEqual(runner.prep_env["TEST_RUNNER_TRIPDOCKET_RECOVERY_PHASE"], "prepare")
        self.assertIs(runner.ops.env, before_env)
        self.assertTrue(runner.report["original_result"]["unchanged_after_reader"])
        self.assertEqual((runner.out / "prepare.xcresult/Info.plist").read_bytes(), b"synthetic-result")
        self.assertEqual(runner.result_manifest(runner.out / "prepare.xcresult"),
                         runner.result_manifest(runner.out / "prepare-inspection.xcresult"))
        self.assertEqual(runner.report["preparation_result"]["runtimeWarnings"], "not_reported")
        self.assertEqual(runner.report["preparation_result"]["independent_warning_and_pixel_review"], "pending")
        runner = self.make(); before_env = runner.ops.env; runner.fail = "prepare-ui"
        self.assertEqual(self.run_bootstrap(runner), 1); self.assertIs(runner.ops.env, before_env)

    def test_cold_start_model_preserves_case_and_fixed_postprocessing_deadline(self):
        runner = self.make()
        # Model the observed startup plus the full existing case allowance and
        # completion margin. This is not a measured native performance claim.
        command_seconds = 711 + m.recovery.PREPARE_CASE_SECONDS + 30
        self.assertLess(command_seconds, runner.execution_profile["prepare_command_seconds"] - 8)
        def transform(label, value):
            runner.ops.value += {"prepare-ui": command_seconds, "prepare-summary": 20,
                                 "prepare-tests": 20, "devices-booted": 20,
                                 "files-group": 20, "devices-final": 20}.get(label, 0)
            return value
        runner.transform = transform
        self.assertEqual(self.run_bootstrap(runner), 0, runner.report)
        self.assertEqual(runner.limit - runner.t0, 1080)
        self.assertEqual(runner.cleanup_deadline - runner.limit, 30)
        self.assertEqual(runner.write_deadline - runner.cleanup_deadline, 10)
        self.assertEqual(sum(call[0] == "prepare-ui" for call in runner.calls), 1)

    def test_slow_preparation_does_not_extend_postprocessing_work_deadline(self):
        runner = self.make()
        def transform(label, value):
            runner.ops.value += {"prepare-ui": 950, "prepare-summary": 60,
                                 "prepare-tests": 60, "devices-booted": 11}.get(label, 0)
            return value
        runner.transform = transform
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertEqual(runner.report["status"], "failed")
        self.assertFalse(runner.report.get("final_inventory_verified", False))
        self.assertNotIn("files-group", [call[0] for call in runner.calls])
        self.assertEqual(sum(call[0] == "prepare-ui" for call in runner.calls), 1)
        self.assertEqual(runner.limit - runner.t0, 1080)

    def test_exact_preparation_case_warnings_and_device_contract(self):
        runner = self.make()
        variants = [lambda a,b: a.update(skippedTests=1), lambda a,b: a.pop("testFailures"),
            lambda a,b: a.update(runtimeWarnings=["warning"]), lambda a,b: a.update(runtimeWarnings=None),
            lambda a,b: b["testNodes"].append(copy.deepcopy(b["testNodes"][0])),
            lambda a,b: b["testNodes"][0].update(nodeIdentifier="other"),
            lambda a,b: b["testNodes"].append({"nodeType":"Runtime Warning"}),
            lambda a,b: b["devices"][0].update(deviceId=s.SECOND),
            lambda a,b: a["devicesAndConfigurations"][0]["device"].update(osBuildNumber="wrong")]
        for mutate in variants:
            summary, tree = copy.deepcopy(runner.summary), copy.deepcopy(runner.tree); mutate(summary, tree)
            with self.assertRaises((RuntimeError, ValueError)): m.validate_preparation(summary, tree, runner.selected)

    def test_result_symlink_or_reader_mutation_rejected(self):
        for failure in ["symlink", "mutate"]:
            runner = self.make()
            def transform(label, value):
                if label == "prepare-ui" and failure == "symlink":
                    (runner.out / "prepare.xcresult/Data/link").symlink_to(runner.home)
                if label == "prepare-tests" and failure == "mutate":
                    (runner.out / "prepare.xcresult/Info.plist").write_bytes(b"changed")
                return value
            runner.transform = transform
            self.assertEqual(self.run_bootstrap(runner), 1)
            self.assertNotIn("files-group", [call[0] for call in runner.calls])

    def test_provider_or_group_symlink_rejected(self):
        for name in ["provider", "group"]:
            runner = self.make(); provider = runner.group / "File Provider Storage"
            if name == "provider":
                provider.rmdir(); provider.symlink_to(runner.home, target_is_directory=True)
            else:
                old = runner.group.with_name("old"); runner.group.rename(old); runner.group.symlink_to(old, target_is_directory=True)
            self.assertEqual(self.run_bootstrap(runner), 1)

    def test_tampered_inputs_and_existing_output_never_overwritten(self):
        for architecture in ("arm64", "x86_64"):
            with self.subTest(architecture=architecture):
                runner = self.make(architecture=architecture)
                original = runner.out.stat().st_ino
                with patch.object(m.os, "uname", return_value=SimpleNamespace(machine=architecture)):
                    with self.assertRaises(FileExistsError): m.Bootstrap(runner.directory, CI)
                self.assertEqual(runner.out.stat().st_ino, original)
                (runner.directory / "sdk.txt").write_text("27.0")
                with self.assertRaises(RuntimeError): m.read_selection(runner.directory)

    def test_forged_selection_and_late_input_mutation_fail(self):
        runner = self.make(); path = runner.directory / "selection.json"
        original = path.read_text(); value = json.loads(original); value["runtime_build"] = "forged"
        path.write_text(json.dumps(value))
        with self.assertRaises(RuntimeError): m.read_selection(runner.directory)
        path.write_text(original)
        def transform(label, result):
            if label == "devices-final": (runner.directory / "sdk.txt").write_text("27.0")
            return result
        runner.transform = transform
        self.assertEqual(self.run_bootstrap(runner), 1)

    def test_provider_ancestor_replacement_during_wait_fails(self):
        runner = self.make(); (runner.group / "File Provider Storage").rmdir()
        def replace(_):
            old = runner.group.with_name("replaced"); runner.group.rename(old); runner.group.mkdir()
        runner.ops.sleep = replace
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertIn("Pinned provider ancestry changed", " ".join(runner.report["errors"]))

    def test_hosted_context_required_and_interruption_is_failure(self):
        runner = self.make()
        for field in CI:
            env = dict(CI); env.pop(field)
            with self.assertRaises(RuntimeError): m.Bootstrap(runner.directory, env)
        runner.interrupted = True
        self.assertEqual(self.run_bootstrap(runner), 1); self.assertEqual(runner.calls, [])

    def test_global_deadline_prevents_further_actions(self):
        runner = self.make()
        def transform(label, result):
            if label == "devices-before": runner.ops.value = runner.limit
            return result
        runner.transform = transform
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertNotIn("prepare-ui", [call[0] for call in runner.calls])


class ShellBoundary(s.ShellTests):
    # Inherited native tools are stubs; extend the actual shell path without booting anything.
    def test_bootstrap_is_explicit_and_failure_prevents_xcodebuild(self):
        self.env["GITHUB_ACTIONS"] = "true"
        helper = self.root / "scripts/prepare-guidance-files.py"
        helper.write_text("import sys\nfrom pathlib import Path\np=Path(sys.argv[2]); assert (p/'selection.json').is_file()\nraise SystemExit(17)\n")
        result = self.run_script("--require-sdk-match", "--prepare-files", "--cohort", "ui-guidance")
        self.assertEqual(result.returncode, 17, result.stderr); self.assertFalse(self.output.exists())

    def test_bootstrap_rejects_local_or_wrong_cohort_before_native_tools(self):
        for args in [("--prepare-files",), ("--require-sdk-match", "--prepare-files", "--cohort", "core-purchase"),
                     ("--require-sdk-match", "--prepare-files", "--cohort", "ui-guidance")]:
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 2, result.stderr); self.assertFalse(self.output.exists())

    def test_workflow_budget_preserves_guidance_and_external_reserves(self):
        text = (HERE.parent / ".github/workflows/ci.yml").read_text()
        guidance = text.split("  ui_guidance:\n", 1)[1].split("  privacy_ipad:\n", 1)[0]
        integration = guidance.split("      - name: Simulator integration and StoreKit tests\n", 1)[1]
        self.assertIn("    timeout-minutes: 128\n", guidance)
        self.assertIn("        timeout-minutes: 108\n", integration)
        core = text.split("  validate:\n", 1)[1].split("  ui_guidance:\n", 1)[0]
        core_integration = core.split("      - name: Simulator integration and StoreKit tests\n", 1)[1].split(
            "      - name:", 1)[0]
        self.assertEqual([line for line in core.splitlines()
                          if line.startswith("    timeout-minutes:")], ["    timeout-minutes: 85"])
        self.assertEqual([line for line in core_integration.splitlines()
                          if line.startswith("        timeout-minutes:")], ["        timeout-minutes: 45"])
        # The full Intel bootstrap and all nine nominal case ceilings fit with
        # an explicit600s other-work allocation and20s rounding. Arm is unchanged.
        self.assertEqual(m.WORK + m.STOP + m.WRITE, 1120)
        native_cases = [360, 360, 360, 180, 180, 120, 240, 1080, 1500]
        self.assertEqual(sum(native_cases), 4380)
        self.assertEqual(m.EXECUTION_PROFILES["x86_64"]["work_seconds"]
                         + m.STOP + m.WRITE + sum(native_cases) + 600 + 20, 108 * 60)
        self.assertEqual(2 + 3 + 108 + 5 + 3 + 3 + 2 + 2, 128)
        self.assertEqual(guidance.count("        timeout-minutes: 3\n"), 3)
        self.assertEqual(guidance.count("        timeout-minutes: 2\n"), 2)

    def test_workflow_retains_nested_receipt_and_uses_explicit_flag(self):
        text = (HERE.parent / ".github/workflows/ci.yml").read_text()
        self.assertIn("bash scripts/test-simulator.sh --require-sdk-match --prepare-files --cohort ui-guidance", text)
        self.assertIn("build/ci-toolchain/simulator-selection.*/", text)


class OwnedBootOps(Clock):
    """Fake OS boundary; the actual Bootstrap command/stop/finalizer still run."""
    def __init__(self, duration, absent_after=None, permanent_eperm=False):
        super().__init__()
        self.duration = duration
        self.absent_after = duration if absent_after is None else absent_after
        self.permanent_eperm = permanent_eperm
        self.processes = []; self.probes = 0; self.signals = []; self.closes = 0
        self.after_poll = None; self.after_probe = None; self.read_once = False

    def spawn(self, argv):
        child = SimpleNamespace(pid=101, returncode=None, started=self.now(), argv=argv)
        def poll():
            if self.now() - child.started >= self.duration:
                child.returncode = 0
            if self.after_poll: self.after_poll(child)
            return child.returncode
        child.poll = poll
        self.processes.append(child)
        return child

    def prepare(self, child): pass

    def read(self, child):
        if self.read_once: return []
        self.read_once = True
        # Terminal-looking text is deliberately not proof of process closure.
        return [("stdout", b"isTerminal=YES\nFinished\n")]

    def absent(self, child):
        self.probes += 1
        if self.after_probe: self.after_probe(child)
        if self.permanent_eperm or (self.probes == 1 and child.returncode is None):
            raise PermissionError(errno.EPERM, "synthetic group probe")
        return self.now() - child.started >= self.absent_after

    def send(self, child, signal):
        self.signals.append(signal)
        raise AssertionError("No repeated signal is allowed in this fixture")

    def close(self, child): self.closes += 1


class OwnedPreparationOps(OwnedBootOps):
    """Only the child process is synthetic; preparation and command policy run."""
    def __init__(self, duration, returncode=0):
        super().__init__(duration)
        self.expected_returncode = returncode

    def spawn(self, argv):
        child = super().spawn(argv)
        self.spawn_env = dict(self.env)
        poll = child.poll
        def completed():
            result = poll()
            if result == 0: child.returncode = self.expected_returncode
            return child.returncode
        child.poll = completed
        return child

    def absent(self, child):
        self.probes += 1
        return child.returncode is not None

    def send(self, child, signal):
        self.signals.append(signal)
        child.returncode = -signal


class PreparationCommandTests(unittest.TestCase):
    make = BootstrapTests.make

    def preparation_runner(self, architecture="x86_64", duration=1000, returncode=0):
        runner = self.make(architecture=architecture)
        ops = OwnedPreparationOps(duration, returncode); runner.ops = ops
        runner.command = lambda label, argv, cap: m.Bootstrap.command(runner, label, argv, cap)
        # Parsing is a separate tested boundary. This stub records whether the
        # real preparation path reaches it; it cannot grant provider readiness.
        inspections = []
        runner.inspect_preparation = lambda: inspections.append(True)
        return runner, ops, inspections

    def test_actual_preparation_uses_intel_margin_and_arm_baseline(self):
        for arch, cap, passes in [("x86_64", 1080, True), ("arm64", 960, False)]:
            with self.subTest(architecture=arch):
                runner, ops, inspections = self.preparation_runner(arch)
                before = ops.env
                if passes: m.Bootstrap.prepare_ui(runner)
                else:
                    with self.assertRaisesRegex(RuntimeError, "prepare-ui failed"):
                        m.Bootstrap.prepare_ui(runner)
                row = runner.report["commands"][0]
                self.assertEqual(row["requested_cap_seconds"], cap)
                self.assertEqual(row["work_deadline"], cap - 8)
                self.assertEqual(row["outcome"], "completed" if passes else "failed")
                argv = ops.processes[0].argv
                for flag in ["-default-test-execution-time-allowance", "-maximum-test-execution-time-allowance"]:
                    self.assertEqual(argv[argv.index(flag) + 1], "300" if arch == "x86_64" else "180")
                self.assertEqual([a for a in argv if a.startswith("-only-testing:")],
                                 ["-only-testing:TripfolioUITests/" + m.PREPARE_CASE.removesuffix("()")])
                self.assertEqual(len(ops.processes), 1); self.assertEqual(runner.preparation_calls, 1)
                self.assertEqual(inspections, [True]); self.assertIs(ops.env, before)
                self.assertFalse(runner.active); self.assertEqual(runner.report["status"], "running")

    def test_native_prepare_profile_and_cli_are_paired_and_environment_restored(self):
        for arch, native in [("arm64", 180), ("x86_64", 300)]:
            for returncode in (0, 65):
                with self.subTest(architecture=arch, returncode=returncode):
                    runner, ops, _ = self.preparation_runner(arch, duration=100, returncode=returncode)
                    previous = ops.env
                    previous["TEST_RUNNER_UNRELATED"] = "retained"
                    if returncode:
                        with self.assertRaisesRegex(RuntimeError, "prepare-ui failed"):
                            m.Bootstrap.prepare_ui(runner)
                    else:
                        m.Bootstrap.prepare_ui(runner)
                    self.assertIs(ops.env, previous)
                    self.assertNotIn("TEST_RUNNER_TRIPDOCKET_RECOVERY_EXECUTION_PROFILE", previous)
                    self.assertEqual(ops.spawn_env["TEST_RUNNER_UNRELATED"], "retained")
                    self.assertEqual(ops.spawn_env.get("TEST_RUNNER_TRIPDOCKET_RECOVERY_EXECUTION_PROFILE"),
                                     "hosted-intel-v1" if arch == "x86_64" else None)
                    self.assertNotIn("TEST_RUNNER_TRIPDOCKET_RECOVERY_CREATE_FOLDER", ops.spawn_env)
                    argv = ops.processes[0].argv
                    for flag in ["-default-test-execution-time-allowance", "-maximum-test-execution-time-allowance"]:
                        self.assertEqual(argv[argv.index(flag) + 1], str(native))
                    self.assertEqual(len(ops.processes), 1)
                    self.assertFalse(runner.active)

    def test_old_intel_preparation_cap_causally_rejects_delayed_completion(self):
        old = {**m.EXECUTION_PROFILES["x86_64"], "prepare_command_seconds": 960}
        with patch.object(m, "EXECUTION_PROFILES", {
                **m.EXECUTION_PROFILES, "x86_64": m.MappingProxyType(old)}):
            runner, ops, _ = self.preparation_runner()
        with self.assertRaisesRegex(RuntimeError, "prepare-ui failed"):
            m.Bootstrap.prepare_ui(runner)
        self.assertEqual(runner.report["commands"][0]["requested_cap_seconds"], 960)
        self.assertEqual(runner.limit - runner.t0, 1440)
        self.assertEqual(len(ops.processes), 1); self.assertFalse(runner.active)

    def test_late_and_nonzero_preparation_remain_failed(self):
        for duration, returncode in [(1081, 0), (1000, 1)]:
            with self.subTest(duration=duration, returncode=returncode):
                runner, ops, inspections = self.preparation_runner(duration=duration, returncode=returncode)
                with self.assertRaisesRegex(RuntimeError, "prepare-ui failed"):
                    m.Bootstrap.prepare_ui(runner)
                self.assertEqual(runner.report["commands"][0]["outcome"], "failed")
                self.assertEqual(len(ops.processes), 1); self.assertEqual(inspections, [True])
                self.assertFalse(runner.active); self.assertNotIn("preparation_result", runner.report)

    def test_original_work_deadline_clips_preparation_without_reset(self):
        runner, ops, _ = self.preparation_runner()
        ops.value = runner.limit - 100
        deadlines = (runner.t0, runner.limit, runner.cleanup_deadline, runner.write_deadline)
        with self.assertRaisesRegex(RuntimeError, "prepare-ui failed"):
            m.Bootstrap.prepare_ui(runner)
        row = runner.report["commands"][0]
        self.assertEqual((row["requested_cap_seconds"], row["command_deadline"], row["work_deadline"]),
                         (1080, 1440, 1432))
        self.assertEqual((runner.t0, runner.limit, runner.cleanup_deadline, runner.write_deadline), deadlines)
        self.assertFalse(runner.active); self.assertEqual(len(ops.processes), 1)

    def test_completed_command_still_requires_native_result_inspection(self):
        runner, ops, _ = self.preparation_runner()
        runner.inspect_preparation = lambda: m.Bootstrap.inspect_preparation(runner)
        with self.assertRaises(FileNotFoundError):
            m.Bootstrap.prepare_ui(runner)
        self.assertEqual(runner.report["commands"][0]["outcome"], "completed")
        self.assertIn("preparation_inspection_error", runner.report)
        self.assertNotIn("preparation_result", runner.report)
        self.assertEqual(runner.report["status"], "running")
        self.assertFalse(runner.active); self.assertEqual(len(ops.processes), 1)


class BootstrapLifecycleTests(unittest.TestCase):
    make = BootstrapTests.make
    run_bootstrap = BootstrapTests.run_bootstrap

    def boot_runner(self, architecture="arm64", duration=200, **options):
        runner = self.make(architecture=architecture)
        ops = OwnedBootOps(duration, **options); runner.ops = ops
        runner.prepare = lambda: m.Bootstrap.command(
            runner, "post-preparation-bootstatus",
            ["xcrun", "simctl", "bootstatus", runner.selected["udid"], "-b"],
            runner.execution_profile["warm_boot_seconds"])
        return runner, ops

    def test_constructor_selects_immutable_profile_before_original_deadlines(self):
        for arch, work, boot, prepare in [("arm64", 1080, 180, 960), ("x86_64", 1440, 300, 1080)]:
            with self.subTest(arch=arch):
                runner = self.make(architecture=arch)
                self.assertEqual((runner.t0, runner.limit, runner.cleanup_deadline, runner.write_deadline),
                                 (1., 1. + work, 31. + work, 41. + work))
                self.assertEqual(runner.execution_profile["warm_boot_seconds"], boot)
                self.assertEqual(runner.execution_profile["prepare_command_seconds"], prepare)
                self.assertEqual(runner.execution_profile["prepare_case_seconds"], 300 if arch == "x86_64" else 180)
                self.assertEqual(runner.report["execution_profile"], dict(runner.execution_profile))
                self.assertEqual(runner.report["limits"]["work_seconds"], work)
                selected = runner.execution_profile
                with self.assertRaises(TypeError): selected["work_seconds"] = 1
                with self.assertRaises(TypeError): selected["prepare_command_seconds"] = 1
                with self.assertRaises(TypeError): selected["prepare_case_seconds"] = 1
                with self.assertRaises(AttributeError): runner.execution_profile = {}
                with self.assertRaises(AttributeError): del runner.execution_profile
                self.assertIs(runner.execution_profile, selected)

    def test_unknown_or_crossed_host_rejected_before_output_creation(self):
        for selected, host in [("arm64", "x86_64"), ("x86_64", "arm64"), ("arm64", "unknown")]:
            runner = self.make(architecture=selected); runner.out.rmdir()
            with patch.object(Path, "home", return_value=runner.home), \
                    patch.object(m.os, "uname", return_value=SimpleNamespace(machine=host)):
                with self.assertRaisesRegex(RuntimeError, "architectures differ"):
                    m.Bootstrap(runner.directory, CI)
            self.assertFalse(runner.out.exists())

    def test_actual_boot_command_uses_intel_margin_and_arm_baseline(self):
        for arch, expected, cap in [("x86_64", 0, 300), ("arm64", 1, 180)]:
            runner, ops = self.boot_runner(arch)
            self.assertEqual(self.run_bootstrap(runner), expected)
            row = runner.report["commands"][0]
            self.assertEqual(row["requested_cap_seconds"], cap)
            self.assertEqual(len(ops.processes), 1); self.assertEqual(ops.signals, [])
            if expected:
                self.assertEqual(row["post_stop_observation"]["status"], "confirmed")
                self.assertEqual(runner.report["status"], "failed")

    def test_complete_prepare_routes_selected_warm_boot_cap(self):
        for arch, cap in [("arm64", 180), ("x86_64", 300)]:
            runner = self.make(architecture=arch)
            def transform(label, value):
                if label == "devices-booted": value["devices"][s.RUNTIME][0]["state"] = "Shutdown"
                return value
            runner.transform = transform
            self.assertEqual(self.run_bootstrap(runner), 0)
            self.assertEqual([call[2] for call in runner.calls
                              if call[0] == "post-preparation-bootstatus"], [cap])

    def test_old_intel_boot_cap_causally_rejects_delayed_completion(self):
        old = {**m.EXECUTION_PROFILES["x86_64"], "warm_boot_seconds": 180}
        with patch.object(m, "EXECUTION_PROFILES", {
                **m.EXECUTION_PROFILES, "x86_64": m.MappingProxyType(old)}):
            runner, ops = self.boot_runner("x86_64", duration=200)
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertEqual(runner.limit - runner.t0, 1440)
        self.assertEqual(runner.report["commands"][0]["requested_cap_seconds"], 180)
        self.assertEqual(runner.report["commands"][0]["post_stop_observation"]["status"], "confirmed")
        self.assertEqual(ops.signals, [])

    def test_late_intel_completion_never_changes_failed_command(self):
        runner, ops = self.boot_runner("x86_64", duration=301)
        self.assertEqual(self.run_bootstrap(runner), 1)
        row = runner.report["commands"][0]
        self.assertIn("Command timeout", row["error"])
        self.assertEqual(row["outcome"], "failed")
        self.assertEqual(row["stop"]["signals"], [])
        self.assertFalse(row["stop"]["leader_reaped"])
        self.assertFalse(row["stop"]["group_absent"])
        self.assertIn("PermissionError", row["stop_error"])
        self.assertEqual(row["post_stop_observation"]["status"], "confirmed")
        self.assertEqual(runner.report["host_cleanup"]["active_groups"], [])
        self.assertTrue(runner.report["errors"]); self.assertEqual(ops.signals, [])
        self.assertEqual(ops.closes, 1)

    def test_original_work_deadline_clips_larger_intel_boot_cap(self):
        runner, ops = self.boot_runner("x86_64", duration=200)
        ops.value = runner.limit - 20
        deadline = runner.cleanup_deadline
        self.assertEqual(self.run_bootstrap(runner), 1)
        row = runner.report["commands"][0]
        self.assertEqual(row["command_deadline"], 1440)
        self.assertEqual(row["work_deadline"], 1432)
        self.assertEqual(runner.cleanup_deadline, deadline)
        self.assertEqual(row["post_stop_observation"]["status"], "unconfirmed")
        self.assertEqual(runner.report["host_cleanup"]["active_groups"], [101])

    def test_permanent_unknown_or_only_one_confirmation_retains_active(self):
        for duration, absence, denied in [(200, 200, True), (200, float("inf"), False),
                                           (float("inf"), 200, False)]:
            with self.subTest(duration=duration, absence=absence, denied=denied):
                runner, ops = self.boot_runner(duration=duration, absent_after=absence,
                                               permanent_eperm=denied)
                self.assertEqual(self.run_bootstrap(runner), 1)
                row = runner.report["commands"][0]
                self.assertEqual(row["post_stop_observation"]["status"], "unconfirmed")
                self.assertEqual(runner.report["host_cleanup"]["active_groups"], [101])
                self.assertEqual(ops.signals, [])

    def test_late_positive_poll_or_probe_cannot_confirm_cleanup(self):
        for boundary in ["poll", "probe"]:
            runner, ops = self.boot_runner()
            def late(child):
                if runner.report["commands"][0].get("post_stop_observation"):
                    ops.value = runner.cleanup_deadline + 1
                    child.returncode = 0
            if boundary == "poll": ops.after_poll = late
            else: ops.after_probe = late
            self.assertEqual(self.run_bootstrap(runner), 1)
            self.assertEqual(runner.report["host_cleanup"]["active_groups"], [101])
            self.assertEqual(runner.report["commands"][0]["post_stop_observation"]["status"], "unconfirmed")

    def test_reap_and_absence_must_be_fresh_in_same_iteration(self):
        runner, ops = self.boot_runner()
        original = ops.absent
        def alternate(child):
            if runner.report["commands"][0].get("post_stop_observation"):
                return child.returncode is None
            return original(child)
        ops.absent = alternate
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertEqual(runner.report["host_cleanup"]["active_groups"], [101])
        self.assertEqual(runner.report["commands"][0]["post_stop_observation"]["status"], "unconfirmed")
        self.assertEqual(ops.signals, [])

    def test_ineligible_or_ambiguous_child_is_not_observed_again(self):
        for fault in ["pid", "record", "extra", "unknown", "signals", "errno", "argv", "id"]:
            with self.subTest(fault=fault):
                runner, ops = self.boot_runner()
                original = m.Bootstrap.observe_failed_warm_boot
                probe_counts = []
                def mutate(self, child, row):
                    if fault == "pid": child.pid = 102
                    elif fault == "record": self.report["commands"].append(dict(row))
                    elif fault == "extra": self.active[102] = SimpleNamespace(pid=102)
                    elif fault == "unknown": self.unknown_spawn = True
                    elif fault == "signals": row["stop"]["signals"] = [15]
                    elif fault == "errno": row["process_observations"]["stop.group_probe"]["errno"] = errno.EIO
                    elif fault == "argv": row["argv"] = ["wrong"]
                    elif fault == "id": row["id"] = "other"
                    before = ops.probes
                    original(self, child, row)
                    probe_counts.append((before, ops.probes))
                with patch.object(m.Bootstrap, "observe_failed_warm_boot", mutate):
                    self.assertEqual(self.run_bootstrap(runner), 1)
                self.assertTrue(all(before == after for before, after in probe_counts))
                self.assertIn(101, runner.active)
                self.assertEqual(ops.signals, [])

    def test_identity_change_during_observation_never_removes_replacement(self):
        runner, ops = self.boot_runner()
        replacement = SimpleNamespace(pid=101)
        def replace(child):
            if runner.report["commands"][0].get("post_stop_observation"):
                runner.active[101] = replacement
        ops.after_poll = replace
        self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertIs(runner.active[101], replacement)
        self.assertIn("ownership changed", runner.report["commands"][0]["post_stop_observation"]["error"])
        self.assertEqual(ops.signals, [])

    def test_other_probe_error_retains_failure_and_no_second_observation(self):
        runner, ops = self.boot_runner()
        def fail(child):
            if runner.report["commands"][0].get("post_stop_observation"):
                raise OSError(errno.EIO, "synthetic probe")
        ops.after_probe = fail
        self.assertEqual(self.run_bootstrap(runner), 1)
        row = runner.report["commands"][0]; count = ops.probes
        m.Bootstrap.observe_failed_warm_boot(runner, ops.processes[0], row)
        self.assertEqual(ops.probes, count)
        self.assertEqual(runner.report["host_cleanup"]["active_groups"], [101])
        self.assertEqual(ops.signals, [])

    def test_observation_is_causal_but_never_accepts_terminal_text(self):
        runner, ops = self.boot_runner()
        with patch.object(m.Bootstrap, "observe_failed_warm_boot", return_value=None):
            self.assertEqual(self.run_bootstrap(runner), 1)
        self.assertEqual(runner.report["host_cleanup"]["active_groups"], [101])
        self.assertIn("Finished", (runner.out / "1-stdout.log").read_text())
        self.assertIsNone(ops.processes[0].returncode)


class BootstrapControlTests(unittest.TestCase):
    make = BootstrapTests.make
    run_bootstrap = BootstrapTests.run_bootstrap
    boot_runner = BootstrapLifecycleTests.boot_runner
    controls = (KeyboardInterrupt, SystemExit, GeneratorExit)

    def test_owned_warm_boot_controls_propagate_with_failed_receipt(self):
        for kind in self.controls:
            for boundary in ("poll", "probe", "sleep"):
                with self.subTest(kind=kind.__name__, boundary=boundary):
                    runner, ops = self.boot_runner("x86_64", duration=301)
                    abort = kind("synthetic control"); original = {}
                    deadlines = (runner.limit, runner.cleanup_deadline, runner.write_deadline)
                    def interrupt(*_):
                        row = runner.report["commands"][0]
                        if "post_stop_observation" in row:
                            original.update({key: copy.deepcopy(row[key])
                                             for key in ("error", "outcome", "stop", "stop_error")})
                            raise abort
                    if boundary == "poll": ops.after_poll = interrupt
                    elif boundary == "probe": ops.after_probe = interrupt
                    else:
                        sleep = ops.sleep
                        def interrupt_sleep(seconds):
                            interrupt(); sleep(seconds)
                        ops.sleep = interrupt_sleep
                    with self.assertRaises(kind) as caught:
                        self.run_bootstrap(runner)
                    self.assertIs(caught.exception, abort)
                    row = runner.report["commands"][0]
                    self.assertEqual({key: row[key] for key in original}, original)
                    self.assertEqual(row["post_stop_observation"]["status"], "unconfirmed")
                    self.assertIn("finish", row["post_stop_observation"])
                    self.assertEqual(runner.report["status"], "failed")
                    self.assertEqual(runner.report["host_cleanup"],
                                     {"active_groups": [101], "unknown_spawn": False})
                    saved = json.loads((runner.out / "receipt.json").read_text())
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(saved["commands"][0], row)
                    self.assertEqual(saved["host_cleanup"], runner.report["host_cleanup"])
                    self.assertTrue(any(repr(abort) in error for error in saved["errors"]))
                    self.assertEqual((runner.limit, runner.cleanup_deadline, runner.write_deadline), deadlines)
                    self.assertEqual(len(ops.processes), 1); self.assertEqual(len(saved["commands"]), 1)
                    self.assertEqual(ops.signals, []); self.assertEqual(ops.closes, 1)
                    self.assertIs(runner.active[101], ops.processes[0])

    def test_direct_prepare_control_propagates_after_final_accounting(self):
        for kind in self.controls:
            with self.subTest(kind=kind.__name__):
                runner = self.make(); abort = kind("synthetic prepare control")
                with patch.object(runner, "prepare", side_effect=abort):
                    with self.assertRaises(kind) as caught:
                        self.run_bootstrap(runner)
                self.assertIs(caught.exception, abort)
                saved = json.loads((runner.out / "receipt.json").read_text())
                self.assertEqual(saved["status"], "failed")
                self.assertEqual(saved["host_cleanup"], {"active_groups": [], "unknown_spawn": False})
                self.assertEqual(runner.calls, [])

    def test_cleanup_stop_control_propagates_without_removing_owned_child(self):
        for kind in self.controls:
            with self.subTest(kind=kind.__name__):
                runner = self.make(); child = SimpleNamespace(pid=101)
                row = {"id": "synthetic-owned-command", "pgid": 101}
                runner.active[101] = child; runner.report["commands"].append(row)
                abort = kind("synthetic stop control")
                with patch.object(runner, "prepare", side_effect=RuntimeError("synthetic prior failure")), \
                        patch.object(runner, "stop", side_effect=abort) as stop:
                    with self.assertRaises(kind) as caught:
                        self.run_bootstrap(runner)
                self.assertIs(caught.exception, abort)
                stop.assert_called_once_with(child, runner.cleanup_deadline, row)
                self.assertIs(runner.active[101], child)
                saved = json.loads((runner.out / "receipt.json").read_text())
                self.assertEqual(saved["status"], "failed")
                self.assertEqual(saved["host_cleanup"]["active_groups"], [101])
                self.assertTrue(any("synthetic prior failure" in error for error in saved["errors"]))
                self.assertTrue(any(repr(abort) in error for error in saved["errors"]))

    def test_prepare_ui_control_restores_environment_without_inspection(self):
        for kind in self.controls:
            with self.subTest(kind=kind.__name__):
                runner = self.make(); environment = runner.ops.env
                abort = kind("synthetic preparation command control")
                with patch.object(runner, "command", side_effect=abort) as command, \
                        patch.object(runner, "inspect_preparation") as inspect:
                    with self.assertRaises(kind) as caught:
                        runner.prepare_ui()
                self.assertIs(caught.exception, abort); self.assertIs(runner.ops.env, environment)
                command.assert_called_once(); inspect.assert_not_called()
                self.assertEqual(runner.preparation_calls, 1)

    def test_inspection_control_is_not_replaced_by_earlier_command_failure(self):
        for kind in self.controls:
            with self.subTest(kind=kind.__name__):
                runner = self.make(); environment = runner.ops.env
                abort = kind("synthetic inspection control")
                with patch.object(runner, "command", side_effect=RuntimeError("synthetic command failure")), \
                        patch.object(runner, "inspect_preparation", side_effect=abort) as inspect:
                    with self.assertRaises(kind) as caught:
                        runner.prepare_ui()
                self.assertIs(caught.exception, abort); self.assertIs(runner.ops.env, environment)
                inspect.assert_called_once()

    def test_receipt_failure_cannot_replace_pending_control_or_reset_deadline(self):
        for kind in self.controls:
            for failure in ("io", "deadline"):
                with self.subTest(kind=kind.__name__, failure=failure):
                    runner = self.make(); abort = kind("synthetic pending control")
                    deadline = runner.write_deadline; save = runner.save; calls = []
                    def failing_save():
                        calls.append(runner.ops.now())
                        if len(calls) == 2:
                            if failure == "io": raise OSError(errno.EIO, "synthetic receipt failure")
                            runner.ops.value = deadline
                        save()
                    with patch.object(runner, "prepare", side_effect=abort), \
                            patch.object(runner, "save", side_effect=failing_save):
                        with self.assertRaises(kind) as caught:
                            self.run_bootstrap(runner)
                    self.assertIs(caught.exception, abort); self.assertEqual(len(calls), 2)
                    self.assertEqual(runner.write_deadline, deadline)
                    self.assertEqual(runner.report["status"], "failed")
                    self.assertEqual(runner.report["host_cleanup"], {"active_groups": [], "unknown_spawn": False})
                    self.assertTrue(any("Final receipt: " in error for error in runner.report["errors"]))
                    # Only the initial receipt is on disk; a failed write is never claimed as final evidence.
                    self.assertEqual(json.loads((runner.out / "receipt.json").read_text())["status"], "running")


if __name__ == "__main__": unittest.main(verbosity=2)
