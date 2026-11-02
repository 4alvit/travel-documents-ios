"""Offline checks of the branch-only wrapper; no Simulator or subprocess starts."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("INTEL_BOOT_TEST_SOURCE", str(ROOT)))
spec = importlib.util.spec_from_file_location("boot_wrapper", ROOT / "scripts/intel-boot-diagnostic.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
q = m.load_qualifier(SOURCE)


class FakeBase:
    def __init__(self, root, mode, env):
        self.mode = mode
        self.owned = "11111111-1111-4111-8111-111111111111"
        self.calls = []
        self.commands = SimpleNamespace(active={}, unknown_spawn=False)
        self.xcode = SimpleNamespace(active={}, unknown_spawn=False)
        self.report = {"errors": [], "cleanup_verified": False,
                       "toolchain": {"architecture": "x86_64"},
                       "runtime_selection": {"build": "23C54"}}
        self.fail_boot = self.fail_cleanup = self.changed_source = self.missing_boundary = False
        self.state = "Booted"

    def save(self):
        self.calls.append("save")

    def check(self):
        self.calls.append("check")

    def command(self, label, argv, seconds=30):
        self.calls.append((label, list(argv), seconds))
        if self.fail_boot and label == "boot-ready":
            self.commands.active[42] = object()
            raise RuntimeError("Command timeout")
        return ""

    def prepare(self):
        self.before = {"source": "same"}
        self.command("boot", ["xcrun", "simctl", "boot", self.owned], 60)
        self.command("boot-ready", ["xcrun", "simctl", "bootstatus", self.owned, "-b"], 180)
        if not self.missing_boundary:
            self.prepare_files_ui()
        self.calls.append("would_start_files_actions")

    def inventory(self, label):
        self.calls.append(label)
        return {self.owned: {"state": self.state}}

    def verify_owned(self, current):
        self.calls.append("verify_owned")
        q.require(self.owned in current, "Wrong owned device")

    def source(self, label):
        self.calls.append(label)
        return {"source": "changed" if self.changed_source else "same"}

    def cleanup(self):
        self.calls.append("cleanup")
        q.require(not self.commands.active and not self.commands.unknown_spawn,
                  "Unresolved process ownership; device cleanup withheld")
        q.require(not self.fail_cleanup, "Baseline device inventory changed")
        self.report["cleanup_verified"] = True


class DiagnosticTests(unittest.TestCase):
    def make(self, **env):
        cls = m.diagnostic_class(SimpleNamespace(Qualification=FakeBase, require=q.require))
        return cls(ROOT, {"GITHUB_REF": m.BRANCH, "RUNNER_ARCH": "X64", **env})

    def test_only_explicit_branch_and_architecture(self):
        for changes in ({"GITHUB_REF": "refs/heads/main"}, {"RUNNER_ARCH": "ARM64"}):
            with self.assertRaisesRegex(RuntimeError, "explicit Intel"):
                self.make(**changes)

    def test_success_stops_before_files_and_never_claims_qualification(self):
        run = self.make()
        self.assertEqual(run.execute(), 0)
        self.assertNotIn("would_start_files_actions", run.calls)
        self.assertEqual(run.report["status"], "boot_observed_cleanup_verified")
        self.assertFalse(run.report["qualification_eligible"])
        self.assertEqual(run.report["application_test_invocations"], 0)
        self.assertTrue(run.report["source_after_verified"])
        self.assertLess(run.calls.index("source-after"), run.calls.index("cleanup"))

    def test_only_boot_observation_allocation_changes(self):
        run = self.make()
        run.execute()
        commands = [entry for entry in run.calls if isinstance(entry, tuple)]
        self.assertEqual([entry[0::2] for entry in commands], [("boot", 60), ("boot-ready", 600)])
        for args in [(["xcrun", "simctl", "bootstatus", "other", "-b"], 180),
                     (["xcrun", "simctl", "bootstatus", run.owned, "-b"], 181)]:
            with self.assertRaisesRegex(RuntimeError, "Unexpected inherited boot"):
                run.command("boot-ready", *args)

    def test_timeout_does_not_turn_into_pass_or_unsafe_source_command(self):
        run = self.make(); run.fail_boot = True
        self.assertEqual(run.execute(), 1)
        self.assertNotIn("source-after", run.calls)
        self.assertIn("cleanup", run.calls)
        self.assertFalse(run.report["cleanup_verified"])
        self.assertFalse(run.ready_verified)
        self.assertTrue(any("Command timeout" in x for x in run.report["errors"]))

    def test_cleanup_or_source_failure_retained(self):
        for key in ("fail_cleanup", "changed_source"):
            run = self.make(); setattr(run, key, True)
            self.assertEqual(run.execute(), 1)
            self.assertEqual(run.report["status"], "boot_diagnostic_failed")
            self.assertTrue(run.report["errors"])

    def test_booted_state_and_successful_command_required(self):
        run = self.make()
        with self.assertRaisesRegex(RuntimeError, "completion not observed"):
            run.prepare_files_ui()
        run.state = "Booting"
        self.assertEqual(run.execute(), 1)
        self.assertFalse(run.ready_verified)

    def test_runtime_and_actual_host_architecture_remain_exact(self):
        for key, value in (("toolchain", {"architecture": "arm64"}),
                           ("runtime_selection", {"build": "23C53"})):
            run = self.make(); run.report[key] = value
            self.assertEqual(run.execute(), 1)
            self.assertTrue(any("Wrong Intel boot profile" in x for x in run.report["errors"]))

    def test_driver_and_capture_are_forbidden(self):
        run = self.make()
        for operation in (run.run_driver, run.capture_original_result):
            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                operation()

    def test_missing_sentinel_cannot_be_success(self):
        run = self.make(); run.missing_boundary = True
        self.assertEqual(run.execute(), 1)
        self.assertTrue(any("Missing stop" in x for x in run.report["errors"]))

    def test_real_ownership_and_global_budgets_are_inherited(self):
        cls = m.diagnostic_class(q)
        self.assertIs(cls.prepare, q.Qualification.prepare)
        self.assertIs(cls.cleanup, q.Qualification.cleanup)
        self.assertIs(cls.check, q.Qualification.check)
        self.assertIs(cls.inventory, q.Qualification.inventory)
        self.assertIs(cls.verify_owned, q.Qualification.verify_owned)
        self.assertIs(cls.source, q.Qualification.source)
        self.assertEqual(q.WORK_SECONDS["batch"], 2400)
        self.assertEqual(q.CLEANUP_SECONDS, 180)


if __name__ == "__main__":
    unittest.main(verbosity=2)
