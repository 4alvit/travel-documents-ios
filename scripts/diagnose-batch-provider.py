#!/usr/bin/env python3
"""Run the unchanged batch suite with bounded, diagnostic-only provider logs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
PINS = {
    "qualify-release.py": "6469ce2e836145008d9b8c6ae501a68343ecbf9ae0f582254b57adf1bdcaf43c",
    "recovery_process.py": "717e17a3ba6e5f1e4828fb374fad7a073ad251a715b38edd96a5805dff1e28a9",
    "recovery_core.py": "2b20f51cf00d4d4a98a938aaf31cdfc10affe3db0fdace72f136538810e8519a",
    "batch_checkpoint.py": "edbdbec1435e674a3a4367edc4aa2c21aa41d990c9d2e8cb538b92962ac734ac",
    "test-batch-simulator.py": "3413b0b086e63d1bba230fd1dc6c8f7c6ae4f6783aaa9b7daa5e4d4dd4910816",
}
COMMAND_SECONDS = 30
STOP_SECONDS = 8
FINALIZER_SECONDS = 120
PREDICATE = (
    'subsystem CONTAINS[c] "fileprovider" OR '
    'subsystem CONTAINS[c] "documentmanager" OR senderImagePath CONTAINS[c] "FileProvider" OR '
    'senderImagePath CONTAINS[c] "DocumentManager"'
)


def verify_pins(folder):
    for name, digest in PINS.items():
        path = folder / name
        metadata = path.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or path.resolve() != path
                or metadata.st_size > 2 * 1024**2
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise RuntimeError("Provider diagnostic helper changed: " + name)


verify_pins(HERE)
spec = importlib.util.spec_from_file_location("provider_log_qualification", HERE / "qualify-release.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
verify_pins(HERE)
BaseQualification = q.Qualification


def raw_inventory(data):
    """Keep every device field; use the existing parser to reject duplicate IDs."""
    q.device_map(data)
    return {
        "runtimes": sorted(data["devices"]),
        "devices": {
            str(q.uuid.UUID(device["udid"])).upper(): {"runtime": runtime, "device": device}
            for runtime, devices in data["devices"].items() for device in devices
        },
    }


class ProviderLogQualification(BaseQualification):
    def __init__(self, root, mode, env):
        q.require(mode == "batch" and env.get("QUALIFICATION_PROVIDER_LOG") == "1"
                  and not env.get("TEST_RUNNER_TRIPDOCKET_NATIVE_REOPEN_CONTROL"),
                  "Select the explicit normal-batch provider diagnostic")
        profile = q.execution_profile(mode, env, os.uname().machine)
        q.require(profile == {"name": "default", "runner": "macos-15",
                              "runner_architecture": "ARM64", "architecture": "arm64",
                              "work_seconds": 2400, "boot_seconds": 180},
                  "Provider diagnostic requires the unchanged ARM batch profile")
        super().__init__(root, mode, env)

    def save(self):
        diagnostic = self.report.setdefault("diagnostic_provider_log", {
            "enabled": True, "release_acceptance": False, "status": "pending",
            "scope": "Persisted logs only; unchanged normal batch tests and acceptance predicates",
            "window": "last 5m at target command execution; retained info/debug only",
            "helper_sha256": dict(PINS),
        })
        if self.report.get("status") == "captured_pending_review":
            self.report["status"] = ("diagnostic_captured_pending_review"
                                     if diagnostic["status"] == "captured"
                                     else "diagnostic_incomplete")
        super().save()

    def quiet(self):
        return not (self.xcode.active or self.xcode.unknown_spawn
                    or self.commands.active or self.commands.unknown_spawn)

    def command_inventory(self, label):
        records = [row for row in self.commands.report["commands"] if row["id"] == label]
        q.require(len(records) == 1, "Missing or ambiguous inventory command")
        row = records[0]
        q.require(row.get("outcome") == "completed" and row.get("returncode") == 0
                  and row["argv"] == ["xcrun", "simctl", "list", "devices", "--json"],
                  "Inventory command was not completed")
        path = Path(row["logs"]["stdout"])
        q.require(path.parent == self.commands.out, "Inventory log escaped the owned output")
        raw = q.bounded_read(self.out, str(path.relative_to(self.out)),
                             q.processes.PER_LOG, self.check)
        q.require(len(raw) == row["bytes"]["stdout"], "Inventory log byte count changed")
        return json.loads(raw)

    def capture_provider_log(self):
        diagnostic = self.report["diagnostic_provider_log"]
        diagnostic["start_seconds"] = time.monotonic() - self.started
        reason = None
        if self.interrupted or self.cleaning or self.acquiring or self.finalizing_driver:
            reason = "interrupted or another phase is active"
        elif not self.quiet():
            reason = "process ownership unresolved"
        elif self.owned is None or self.baseline is None or self.intent is None:
            reason = "no complete owned-device acquisition"
        elif time.monotonic() + 2 * (COMMAND_SECONDS + STOP_SECONDS) + FINALIZER_SECONDS >= self.work_deadline:
            reason = "insufficient original work for two commands and finalization"
        if reason:
            diagnostic.update(status="skipped", reason=reason)
            return
        self.check()
        baseline_data = self.command_inventory("baseline")
        baseline = raw_inventory(baseline_data)
        q.require(q.device_map(baseline_data) == self.baseline
                  and self.owned not in baseline["devices"], "Raw baseline ownership mismatch")
        if time.monotonic() + 2 * (COMMAND_SECONDS + STOP_SECONDS) + FINALIZER_SECONDS >= self.work_deadline:
            diagnostic.update(status="skipped", reason="baseline read consumed the remaining capture budget")
            return
        self.command("provider-log-inventory", ["xcrun", "simctl", "list", "devices", "--json"],
                     COMMAND_SECONDS)
        data = self.command_inventory("provider-log-inventory")
        self.verify_owned(q.device_map(data))
        current = raw_inventory(data)
        device = current["devices"].pop(self.owned)["device"]
        q.require(device.get("isAvailable") is True and device["state"] == "Booted",
                  "Owned device is not available and Booted")
        q.require(current == baseline, "Foreign raw device inventory changed")
        diagnostic["inventory_verified"] = True
        self.check()
        q.require(self.quiet(), "Writer appeared before provider capture")
        if time.monotonic() + COMMAND_SECONDS + STOP_SECONDS + FINALIZER_SECONDS >= self.work_deadline:
            diagnostic.update(status="skipped", reason="inventory consumed the remaining capture budget")
            return
        diagnostic["target_uuid"] = self.owned
        diagnostic["log_start_unix_seconds"] = time.time()
        self.command("provider-log-show", ["xcrun", "simctl", "spawn", self.owned, "log", "show",
                     "--last", "5m", "--style", "ndjson", "--info", "--debug",
                     "--predicate", PREDICATE], COMMAND_SECONDS)
        diagnostic["log_finish_unix_seconds"] = time.time()
        record = self.commands.report["commands"][-1]
        q.require(record["id"] == "provider-log-show" and record.get("outcome") == "completed",
                  "Missing completed provider log command")
        count = record["bytes"]["stdout"]
        q.require(type(count) is int and 0 <= count <= q.processes.PER_LOG,
                  "Invalid provider log byte count")
        diagnostic.update(status="captured" if count else "empty", stdout_bytes=count,
                          empty_stdout=count == 0, log_command_id="provider-log-show",
                          content_review="Unreviewed bytes; nonempty stdout does not establish provider events or time coverage",
                          limitation="Empty or redacted retained logs do not prove absence of a provider error")
        if not count:
            diagnostic["reason"] = "provider log command returned no retained stdout"

    def cleanup(self):
        diagnostic = self.report["diagnostic_provider_log"]
        try:
            try:
                self.capture_provider_log()
            except BaseException as error:
                # Keep the original native failure first and unmodified. The
                # command receipt retains partial output and stop provenance.
                diagnostic.update(status="failed", error=repr(error))
            finally:
                diagnostic["finish_seconds"] = time.monotonic() - self.started
        finally:
            # Never clear unknown groups or borrow this cleanup clock for logs.
            super().cleanup()
        if self.report.get("cleanup_verified"):
            baseline = raw_inventory(self.command_inventory("baseline"))
            final = raw_inventory(self.command_inventory("after-cleanup"))
            diagnostic["full_raw_baseline_verified"] = False
            q.require(final == baseline, "Final raw device inventory changed")
            diagnostic["full_raw_baseline_verified"] = True


def main():
    q.require(sys.argv[1:] == ["--mode", "batch"], "Provider diagnostic requires --mode batch")
    verify_pins(HERE)
    # Retain q.main's signal registration and interrupted/acquiring/cleaning
    # semantics instead of introducing another outer process or signal layer.
    q.Qualification = ProviderLogQualification
    try:
        return q.main()
    finally:
        q.Qualification = BaseQualification


if __name__ == "__main__":
    sys.exit(main())
