#!/usr/bin/env python3
"""Capture native-created-folder import evidence without granting release acceptance."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent
PROVIDER_SHA256 = "84e6059233a6eef106d6165709b96f39abeeca955aa55ae2ae6659769cd1189e"


def verify_provider():
    path = HERE / "diagnose-batch-provider.py"
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or path.resolve() != path
            or metadata.st_size > 2 * 1024**2
            or hashlib.sha256(path.read_bytes()).hexdigest() != PROVIDER_SHA256):
        raise RuntimeError("Native-folder diagnostic provider helper changed")


verify_provider()
spec = importlib.util.spec_from_file_location("folder_diagnostic_provider", HERE / "diagnose-batch-provider.py")
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
verify_provider()
q = provider.q


class FolderQualification(provider.ProviderLogQualification):
    native_folder_control = True
    diagnostic_scope = "Persisted logs for native-created-folder control; mandatory preparation and combined seed/main retained"

    def __init__(self, root, mode, env):
        q.require(mode == "batch" and env.get("QUALIFICATION_NATIVE_FOLDER_CONTROL") == "1",
                  "Select the explicit native-created-folder batch control")
        super().__init__(root, mode, env)

    def prepare_native_folder(self, driver):
        try:
            return super().prepare_native_folder(driver)
        except Exception:
            observation = {"status": "skipped", "release_acceptance": False,
                "scope": "Exact unadopted target after failed native folder invocation; no editor-closure proof"}
            self.report["diagnostic_native_folder_after_failure"] = observation
            probing = False
            try:
                folder = self.report.get("native_folder", {})
                rows = [row for row in self.commands.report["commands"] if row.get("id") == "native-folder-ui"]
                q.require(not (self.interrupted or self.cleaning or self.acquiring or self.finalizing_driver)
                          and self.quiet(), "Interrupted phase or unresolved writer")
                q.require(self.mode == "batch" and self.owned is not None
                          and isinstance(self.baseline, dict) and self.owned not in self.baseline,
                          "No exclusive owned-device context")
                q.require(folder.get("absent_before") is True and folder.get("adopted") is False
                          and type(folder.get("calls")) is int and folder["calls"] == 1
                          and folder.get("case") == q.FOLDER_CASE
                          and folder.get("token") == driver.token
                          and folder.get("destination") == str(driver.native_folder_destination)
                          and folder.get("provider_identity") == list(driver.provider_identity)
                          and self.report.get("native_folder_verified") is not True
                          and driver.fixture_directory is None and driver.fixture_identity is None,
                          "No exact unadopted folder intent")
                q.require(len(rows) == 1 and rows[0].get("outcome") == "failed"
                          and type(rows[0].get("returncode")) is int and rows[0]["returncode"] != 0
                          and rows[0].get("stop", {}).get("group_absent") is True
                          and rows[0].get("stop", {}).get("leader_reaped") is True,
                          "No completed failed native folder invocation")
                self.check()
                q.require(q.time.monotonic() < driver.deadline
                          and q.time.monotonic() + provider.FINALIZER_SECONDS < self.work_deadline,
                          "Insufficient original driver/work budget")
                probing = True
                observation.update(start_seconds=q.time.monotonic() - self.started,
                                   target=str(driver.native_folder_destination),
                                   native_command_finish_seconds=rows[0].get("finish"))
                # This later post-test/inspection observation is not the state at
                # assertion time. Even after AUT termination it cannot prove editor closure.
                try:
                    identity = self.native_folder_leaf(driver)
                    self.check()
                    q.require(q.time.monotonic() < driver.deadline
                              and q.time.monotonic() + provider.FINALIZER_SECONDS < self.work_deadline
                              and self.quiet() and driver.fixture_directory is None
                              and driver.fixture_identity is None, "Observation context or clock changed")
                    observation.update(status="observed_empty_target", identity=list(identity))
                finally:
                    observation["finish_seconds"] = q.time.monotonic() - self.started
            except Exception as error:
                observation.update(status="rejected" if probing else "skipped", reason=repr(error))
            try:
                self.save()
            except Exception as error:
                observation["save_error"] = repr(error)
            raise

    def save(self):
        self.report.setdefault("diagnostic_native_folder", {
            "enabled": True, "release_acceptance": False,
            "scope": "Native-created subfolder; additional folder case plus unchanged mandatory preparation/seed/main cases",
            "folder_creation": "Files UI only; host verifies absent-before and exact empty leaf after",
            "expected_phase_case_counts": [2, 1, 2], "expected_result_bundles": 3,
            "driver_seconds": 1440, "additional_folder_seconds": q.FOLDER_SECONDS,
            "clock": "Initial 1200-second driver plus separate 240-second folder envelope; global 2400 unchanged",
            "provider_sha256": PROVIDER_SHA256,
        })
        super().save()


def main():
    q.require(sys.argv[1:] == ["--mode", "batch"], "Native-folder diagnostic requires --mode batch")
    q.require(os.environ.get("QUALIFICATION_NATIVE_FOLDER_CONTROL") == "1",
              "Select the explicit native-created-folder batch control")
    verify_provider()
    provider.verify_pins(HERE)
    previous = q.Qualification
    q.require(previous is provider.BaseQualification, "Native-folder diagnostic inherited class changed")
    q.Qualification = FolderQualification
    try:
        return q.main()
    finally:
        q.Qualification = previous


if __name__ == "__main__":
    sys.exit(main())
