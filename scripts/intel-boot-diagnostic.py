#!/usr/bin/env python3
"""Branch-only first-boot measurement; never runs or qualifies application tests."""
import hashlib
import importlib.util
import os
from pathlib import Path
import signal
import sys

BRANCH = "refs/heads/diagnostic/intel-boot"
BOOT_SECONDS = 600
PINS = {
    "qualify-release.py": "9e69c7196d0d8aee779e17b8c3c74881ea720380b09fadcf9c451e18c32b8149",
    "batch_checkpoint.py": "2356d89b112f25c8375c34ee087c663890e39a3d57e3a2741602367652b96718",
    "recovery_core.py": "2b20f51cf00d4d4a98a938aaf31cdfc10affe3db0fdace72f136538810e8519a",
    "recovery_process.py": "717e17a3ba6e5f1e4828fb374fad7a073ad251a715b38edd96a5805dff1e28a9",
}


def load_qualifier(root):
    for name, expected in PINS.items():
        path = root / "scripts" / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise RuntimeError("Unsafe diagnostic dependency: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Changed diagnostic dependency: " + name)
    spec = importlib.util.spec_from_file_location("boot_diagnostic_qualifier", root / "scripts/qualify-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def diagnostic_class(q):
    class BootReady(Exception):
        pass

    class BootDiagnostic(q.Qualification):
        def __init__(self, root, env):
            q.require(env.get("GITHUB_REF") == BRANCH and env.get("RUNNER_ARCH") == "X64",
                      "Only the explicit Intel diagnostic branch is allowed")
            super().__init__(root, "batch", env)
            self.boot_observed = self.ready_verified = False
            self.report.update(diagnostic_kind="intel_boot_only", qualification_eligible=False,
                               boot_observation_seconds=BOOT_SECONDS, source_after_verified=False,
                               application_test_invocations=0)
            self.save()

        def command(self, label, argv, seconds=30):
            if label == "boot-ready":
                q.require(seconds == 180 and list(argv) == ["xcrun", "simctl", "bootstatus", self.owned, "-b"],
                          "Unexpected inherited boot command")
                q.require(self.report["toolchain"]["architecture"] == "x86_64"
                          and self.report["runtime_selection"]["build"] == "23C54",
                          "Wrong Intel boot profile")
                result = super().command(label, argv, BOOT_SECONDS)
                self.boot_observed = True
                return result
            return super().command(label, argv, seconds)

        def prepare_files_ui(self):
            # Inherited prepare() reaches this boundary only after bootstatus exits 0.
            self.check()
            q.require(self.boot_observed and not self.ready_verified, "Boot completion not observed exactly once")
            current = self.inventory("boot-diagnostic-ready")
            self.verify_owned(current)
            q.require(current[self.owned]["state"] == "Booted", "Owned device is not Booted")
            self.ready_verified = True
            self.report["boot_ready_inventory"] = current
            self.save()
            raise BootReady()

        def run_driver(self):
            raise RuntimeError("Application tests are forbidden in the boot diagnostic")

        def capture_original_result(self):
            raise RuntimeError("Qualification capture is forbidden in the boot diagnostic")

        def execute(self):
            try:
                self.prepare()
                raise RuntimeError("Missing stop before Files preparation")
            except BootReady:
                pass
            except BaseException as error:
                self.report["errors"].append(repr(error))
            finally:
                try:
                    q.require(not self.commands.active and not self.commands.unknown_spawn
                              and not self.xcode.active and not self.xcode.unknown_spawn,
                              "Source recheck withheld: unresolved process ownership")
                    q.require(hasattr(self, "before"), "Source-before was not captured")
                    q.require(self.source("source-after") == self.before, "Source changed during boot observation")
                    self.report["source_after_verified"] = True
                except BaseException as error:
                    self.report["errors"].append("Source: " + repr(error))
                try:
                    self.cleanup()
                except BaseException as error:
                    self.report["errors"].append("Cleanup: " + repr(error))
                complete = (self.ready_verified and self.report["source_after_verified"]
                            and self.report["cleanup_verified"] and not self.report["errors"])
                self.report["status"] = "boot_observed_cleanup_verified" if complete else "boot_diagnostic_failed"
                self.save()
            return 0 if complete else 1

    return BootDiagnostic


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("The diagnostic takes no options")
    root = Path(__file__).resolve().parents[1]
    q = load_qualifier(root)
    run = diagnostic_class(q)(root, os.environ)

    def interrupt(_signal, _frame):
        run.interrupted = True
        if not (run.acquiring or run.finalizing_driver or run.cleaning):
            raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    return run.execute()


if __name__ == "__main__":
    sys.exit(main())
