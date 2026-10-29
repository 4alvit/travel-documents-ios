#!/usr/bin/env python3
"""Opt-in real Files / local StoreKit batch UI test on one already booted UUID.

Run xcodegen generate first. This driver creates only synthetic PDFs in its own
unique Files folder, runs one test once, and removes only that folder afterward.
It neither boots simulators nor changes Apple accounts. Authentication is bypassed
by this functional UI test; its result is not privacy or rendered-PDF proof.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid


TEST = "TripfolioUITests/BatchImportUITests/testRealFilesBatchRequiresEveryReviewAndPreservesOriginals"
CASE = TEST.split("/", 1)[1] + "()"
GROUP = "group.com.apple.FileProvider.LocalStorage"


def device_uuid(value):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise argparse.ArgumentTypeError("Use an exact simulator UUID, not a name or 'booted'")
    return str(uuid.UUID(value)).upper()


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def pdf(title):
    """Small complete one-page PDF, with byte-accurate stream and xref lengths."""
    lines = [title, "TripDocket batch UI QA", "SYNTHETIC - NOT VALID FOR TRAVEL", "No personal data"]
    stream = "BT /F1 20 Tf 54 730 Td "
    for index, text in enumerate(lines):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream += ("0 -36 Td " if index else "") + f"({escaped}) Tj "
    content = (stream + "ET\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream",
    ]
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(result)


class Driver:
    def __init__(self, args):
        self.args = args
        self.root = Path(__file__).resolve().parent.parent
        self.deadline = time.monotonic() + args.timeout
        self.token = str(uuid.uuid4())
        self.folder_name = "TripDocket-Batch-QA-" + self.token
        self.directory = self.root / "build" / ("BatchSimulator-" + self.token)
        self.directory.mkdir(parents=True, mode=0o700)
        self.actions = (self.directory / "actions.jsonl").open("w", encoding="utf-8", buffering=1)
        self.process = None
        self.fixture_directory = None
        self.fixture_identity = None
        self.provider_identity = None
        self.summary = {"status": "running", "started_at": timestamp(), "device": args.device,
                        "folder": self.folder_name, "test": TEST, "timeout_seconds": args.timeout,
                        "result_bundle": str(self.directory / "Tests.xcresult"),
                        "limits": "Rendered PDF pixels and saved-library byte identity require independent review; this is not an authentication test."}
        self.save()

    def save(self):
        (self.directory / "summary.json").write_text(json.dumps(self.summary, indent=2) + "\n", encoding="utf-8")

    def record(self, action, **values):
        self.actions.write(json.dumps({"at": timestamp(), "action": action, **values}) + "\n")

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("The overall driver timeout expired")
        return remaining

    def command(self, *command):
        self.record("command", argv=list(command))
        result = subprocess.run(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=min(30, self.remaining()), check=False)
        self.record("command_result", returncode=result.returncode,
                    stdout=result.stdout.decode("utf-8", "replace"), stderr=result.stderr.decode("utf-8", "replace"))
        if result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}): {command[0]} {command[1:]}")
        return result.stdout

    def source_snapshot(self):
        head = self.command("git", "rev-parse", "HEAD").decode().strip()
        status = self.command("git", "status", "--porcelain=v1", "-z", "--untracked-files=all").decode("utf-8", "surrogateescape")
        names = self.command("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        files = []
        for name in sorted(set(filter(None, names.split(b"\0")))):
            path = self.root / os.fsdecode(name)
            if not path.exists() and not path.is_symlink():
                files.append({"path": os.fsdecode(name), "deleted": True})
                continue
            metadata = path.lstat()
            digest = hashlib.sha256()
            if stat.S_ISLNK(metadata.st_mode):
                digest.update(os.fsencode(os.readlink(path)))
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 128 * 1024 * 1024:
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        self.remaining()
                        digest.update(chunk)
            else:
                raise RuntimeError(f"Unsupported or oversized source candidate entry: {name!r}")
            files.append({"path": os.fsdecode(name), "mode": metadata.st_mode,
                          "bytes": metadata.st_size, "sha256": digest.hexdigest()})
        snapshot = {"head": head, "status": status, "files": files}
        snapshot["sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return snapshot

    def prepare(self):
        inventory = json.loads(self.command("xcrun", "simctl", "list", "devices", "available", "--json"))
        matches = [(runtime, device) for runtime, devices in inventory["devices"].items() for device in devices
                   if device.get("udid", "").upper() == self.args.device]
        if len(matches) != 1:
            raise RuntimeError("The exact device UUID must identify one available simulator")
        runtime, device = matches[0]
        if ".iOS-" not in runtime or device.get("state") != "Booted" or not device.get("isAvailable"):
            raise RuntimeError("The requested device must already be an available, booted iOS simulator")
        self.summary.update({"runtime": runtime, "device_name": device.get("name")})
        if not (self.root / "Tripfolio.xcodeproj/project.pbxproj").is_file():
            raise RuntimeError("Run xcodegen generate before this driver")
        self.summary["source_before"] = self.source_snapshot()
        self.save()

        # Resolve exactly this application's exact shared group; never search
        # another device or fall back to a guessed AppGroup directory.
        output = self.command("xcrun", "simctl", "get_app_container", self.args.device,
                              "com.apple.DocumentsApp", "groups").decode()
        groups = []
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) != 2 or not all(fields):
                raise RuntimeError("Files returned a malformed shared-group listing")
            if fields[0] == GROUP:
                groups.append(fields[1])
        if len(groups) != 1:
            raise RuntimeError("Files must expose exactly one matching local-storage group")
        group = Path(groups[0])
        expected = (self.args.device, "data", "Containers", "Shared", "AppGroup")
        if (not group.is_absolute() or not group.is_dir() or group.is_symlink()
                or tuple(group.parts[-6:-1]) != expected
                or not re.fullmatch(r"[0-9a-fA-F-]{36}", group.name)):
            raise RuntimeError("Files returned an unexpected local-storage group path for this UUID")
        provider = group / "File Provider Storage"
        if not provider.is_dir() or provider.is_symlink():
            raise RuntimeError("The exact Files group has no existing File Provider Storage directory")
        self.provider_identity = (provider.stat().st_dev, provider.stat().st_ino)
        owned = provider / self.folder_name
        owned.mkdir(mode=0o700)  # No exist_ok: an existing folder is never adopted.
        self.fixture_directory = owned
        self.fixture_identity = (owned.stat().st_dev, owned.stat().st_ino)
        copies = self.directory / "fixtures"
        copies.mkdir(mode=0o700)
        fixtures = []
        for name, title in [("synthetic-ticket.pdf", "SYNTHETIC TICKET"),
                            ("synthetic-insurance.pdf", "SYNTHETIC INSURANCE")]:
            data = pdf(title)
            (copies / name).write_bytes(data)
            with (owned / name).open("xb") as destination:
                destination.write(data)
            fixtures.append({"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                             "retained_copy": str(copies / name)})
        self.summary.update({"fixture_directory": str(owned), "group_identifier": GROUP, "fixtures": fixtures})
        (self.directory / "fixture-manifest.json").write_text(json.dumps({
            "device": self.args.device, "folder": self.folder_name, "directory": str(owned),
            "group_identifier": GROUP, "fixtures": fixtures,
        }, indent=2) + "\n", encoding="utf-8")
        self.record("seeded_owned_folder", path=str(owned), fixtures=fixtures)
        self.save()

    def run_test(self):
        command = ["xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio",
                   "-configuration", "Debug", "-destination", f"platform=iOS Simulator,id={self.args.device}",
                   "-destination-timeout", "30", "-parallel-testing-enabled", "NO",
                   "-maximum-concurrent-test-simulator-destinations", "1", "-collect-test-diagnostics", "never",
                   "-default-test-execution-time-allowance", "300", "-maximum-test-execution-time-allowance", "300",
                   "-derivedDataPath", str(self.directory / "DerivedData"),
                   "-resultBundlePath", self.summary["result_bundle"], "-only-testing:" + TEST,
                   "CODE_SIGNING_ALLOWED=NO", "test"]
        overrides = {"TEST_RUNNER_TRIPDOCKET_BATCH_UI": "1",
                     "TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER": self.folder_name,
                     "TEST_RUNNER_NSUnbufferedIO": "YES", "NSUnbufferedIO": "YES"}
        self.summary.update({"command": command, "environment_overrides": overrides})
        self.save()
        self.record("xcodebuild_started", argv=command, environment_overrides=overrides)
        print(f"One batch test; follow {self.directory / 'xcodebuild.log'}", flush=True)
        with (self.directory / "xcodebuild.log").open("wb") as log:
            self.process = subprocess.Popen(command, cwd=self.root, env={**os.environ, **overrides},
                                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.summary["xcodebuild_returncode"] = self.process.wait(timeout=self.remaining())
        self.save()
        self.validate_result()
        if self.summary["xcodebuild_returncode"] != 0:
            raise RuntimeError("xcodebuild failed despite the reported test result")

    def validate_result(self):
        results = {}
        for kind in ["summary", "tests"]:
            data = self.command("xcrun", "xcresulttool", "get", "test-results", kind,
                                "--schema-version", "0.4.0", "--path", self.summary["result_bundle"], "--compact")
            (self.directory / f"xcresult-{kind}.json").write_bytes(data)
            results[kind] = json.loads(data)
        summary, tree = results["summary"], results["tests"]
        expected_counts = {"totalTestCount": 1, "passedTests": 1, "failedTests": 0,
                           "skippedTests": 0, "expectedFailures": 0}
        self.summary["test_counts"] = {key: summary.get(key) for key in expected_counts}
        cases, nodes = [], list(tree["testNodes"])
        while nodes:
            node = nodes.pop()
            nodes.extend(node.get("children", []))
            if node.get("nodeType") == "Test Case":
                cases.append({"identifier": node.get("nodeIdentifier"), "result": node.get("result")})
        self.summary["test_cases"] = cases
        devices = [{"id": device.get("deviceId", "").upper(), "platform": device.get("platform")}
                   for device in tree["devices"]]
        self.summary["result_devices"] = devices
        self.save()
        if (summary.get("result") != "Passed" or any(type(summary.get(key)) is not int or summary[key] != value
                for key, value in expected_counts.items())
                or cases != [{"identifier": CASE, "result": "Passed"}]):
            raise RuntimeError("xcresult must contain exactly the selected case: 1 passed, 0 failed, 0 skipped")
        if devices != [{"id": self.args.device, "platform": "iOS Simulator"}]:
            raise RuntimeError("xcresult did not run on exactly the requested device UUID")
        configurations = summary.get("devicesAndConfigurations", [])
        if (len(configurations) != 1
                or configurations[0].get("device", {}).get("deviceId", "").upper() != self.args.device):
            raise RuntimeError("xcresult summary has an unexpected device configuration")

    def stop_process(self):
        if self.process is None:
            return
        # Descendants can outlive the leader or ignore TERM. Always finish the
        # same private group created with start_new_session=True (PID = PGID).
        process_group = self.process.pid
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.process.wait(timeout=5)
        self.record("xcodebuild_stopped", process_group=process_group, returncode=self.process.returncode)

    def verify_fixtures(self):
        fixtures = self.summary.get("fixtures")
        if not fixtures:
            return
        self.summary["source_originals_unchanged"] = False
        for fixture in fixtures:
            path = self.fixture_directory / fixture["name"]
            if (path.is_symlink() or not path.is_file() or path.stat().st_size != fixture["bytes"]
                    or hashlib.sha256(path.read_bytes()).hexdigest() != fixture["sha256"]):
                raise RuntimeError(f"The original Files fixture changed or disappeared: {fixture['name']}")
        self.summary["source_originals_unchanged"] = True
        self.record("verified_source_originals_unchanged", files=[fixture["name"] for fixture in fixtures])

    def remove_fixtures(self):
        owned = self.fixture_directory
        if owned is None:
            return
        parent = owned.parent
        if (parent.is_symlink() or owned.is_symlink()
                or (parent.stat().st_dev, parent.stat().st_ino) != self.provider_identity
                or (owned.stat().st_dev, owned.stat().st_ino) != self.fixture_identity):
            raise RuntimeError("Owned fixture folder identity changed; refusing unsafe cleanup")
        shutil.rmtree(owned)
        self.summary["fixture_cleanup"] = "removed only the uniquely created fixture folder"
        self.record("removed_owned_folder", path=str(owned))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, type=device_uuid, help="Exact UUID of an already booted iOS simulator")
    parser.add_argument("--timeout", type=int, default=1200, help="Overall timeout in seconds, 60–3600 (default: 1200)")
    args = parser.parse_args()
    if not 60 <= args.timeout <= 3600:
        parser.error("--timeout must be between 60 and 3600 seconds")
    driver = Driver(args)
    print(f"Batch test artifacts: {driver.directory}", flush=True)
    failure, interrupted = None, False

    def interrupt(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        driver.prepare()
        driver.run_test()
    except KeyboardInterrupt:
        failure, interrupted = "Interrupted", True
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for cleanup in [driver.stop_process, driver.verify_fixtures, driver.remove_fixtures]:
            try:
                cleanup()
            except Exception as error:
                failure = (failure + "; " if failure else "") + f"Cleanup failed: {error}"
        if "source_before" in driver.summary:
            try:
                driver.summary["source_after"] = driver.source_snapshot()
                if driver.summary["source_after"] != driver.summary["source_before"]:
                    raise RuntimeError("Source changed during the run; the result cannot be attributed to one candidate")
            except Exception as error:
                driver.summary["source_after_error"] = str(error)
                if failure is None:
                    failure = str(error)
        driver.summary.update({"status": "failed" if failure else "passed", "finished_at": timestamp(), "error": failure})
        driver.save()
        driver.actions.close()
    print(f"Batch test {'failed: ' + failure if failure else 'passed'}", flush=True)
    print(f"Summary: {driver.directory / 'summary.json'}", flush=True)
    return 130 if interrupted else (1 if failure else 0)


if __name__ == "__main__":
    sys.exit(main())
