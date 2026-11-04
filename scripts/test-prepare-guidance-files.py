#!/usr/bin/env python3
"""Non-native regressions for the actual Files bootstrap and shell boundary."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
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
        with patch.object(Path, "home", return_value=home): runner = Fake(directory, CI)
        runner.architecture = architecture
        runner.home = home; runner.calls = []; runner.fail = None; runner.transform = lambda _, result: result
        runner.runtimes = runtimes; runner.types = types; runner.devices = devices; runner.group = group
        runner.summary = {"result": "Passed", "totalTestCount": 1, "passedTests": 1, "failedTests": 0,
            "skippedTests": 0, "expectedFailures": 0, "testFailures": [], "devicesAndConfigurations": [{"device": {
                "deviceId": s.FIRST, "platform": "iOS Simulator", "osVersion": "26.2", "osBuildNumber": "23C54", "architecture": architecture}}]}
        runner.tree = {"testNodes": [{"nodeType": "Test Case", "nodeIdentifier": m.PREPARE_CASE, "result": "Passed"}],
                       "devices": [{"deviceId": s.FIRST, "platform": "iOS Simulator"}]}
        clock = Clock(); runner.ops = clock; runner.t0 = clock.now(); runner.limit = clock.now() + m.WORK
        runner.cleanup_deadline = runner.limit + m.STOP; runner.write_deadline = runner.cleanup_deadline + m.WRITE
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
        self.assertLess(command_seconds, m.PREPARE_COMMAND_SECONDS - 8)
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
        runner = self.make(); original = runner.out.stat().st_ino
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
        self.assertIn("    timeout-minutes: 65\n", guidance)
        self.assertIn("        timeout-minutes: 45\n", integration)
        core = text.split("  validate:\n", 1)[1].split("  ui_guidance:\n", 1)[0]
        core_integration = core.split("      - name: Simulator integration and StoreKit tests\n", 1)[1].split(
            "      - name:", 1)[0]
        self.assertEqual([line for line in core.splitlines()
                          if line.startswith("    timeout-minutes:")], ["    timeout-minutes: 75"])
        self.assertEqual([line for line in core_integration.splitlines()
                          if line.startswith("        timeout-minutes:")], ["        timeout-minutes: 35"])
        # Planning envelope: 60s selection, bounded bootstrap including final
        # receipts, 24m previously observed guidance, 80s remaining margin.
        self.assertEqual(60 + m.WORK + m.STOP + m.WRITE + 24 * 60 + 80, 45 * 60)
        self.assertEqual(2 + 3 + 45 + 5 + 3 + 3 + 2 + 2, 65)
        self.assertEqual(guidance.count("        timeout-minutes: 3\n"), 3)
        self.assertEqual(guidance.count("        timeout-minutes: 2\n"), 2)

    def test_workflow_retains_nested_receipt_and_uses_explicit_flag(self):
        text = (HERE.parent / ".github/workflows/ci.yml").read_text()
        self.assertIn("bash scripts/test-simulator.sh --require-sdk-match --prepare-files --cohort ui-guidance", text)
        self.assertIn("build/ci-toolchain/simulator-selection.*/", text)


if __name__ == "__main__": unittest.main(verbosity=2)
