#!/usr/bin/env python3
"""Drive real simulated Face ID for PrivacyTransitionUITests on one booted UUID.

The tests must wait for the system authentication prompt, then write and flush
one line: TRIPDOCKET_BIOMETRIC_REQUEST match (or nomatch). No app authentication
state is injected. This is a test-only use of private Apple simulator events,
verified in iOS 27.0 (24A434); other runtimes require separate verification.
Run xcodegen generate first so the shared project includes the current tests.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid


ENROLLMENT = "com.apple.BiometricKit.enrollmentChanged"
EVENTS = {
    "match": "com.apple.BiometricKit_Sim.pearl.match",
    "nomatch": "com.apple.BiometricKit_Sim.pearl.nomatch",
}
MARKER = "TRIPDOCKET_BIOMETRIC_REQUEST"
MARKER_PATTERN = re.compile(r"(?:^|\s)TRIPDOCKET_BIOMETRIC_REQUEST (match|nomatch)\s*$")
EXPECTED_METHODS = (
    "testFailedAndCancelledAuthenticationKeepDocumentsPrivate",
    "testOriginalPreviewIsPrivateAcrossBackgroundAndReturn",
    "testExportShareIsPrivateAcrossBackgroundAndReturn",
    "testEditDraftIsPrivateAcrossBackgroundAndReturn",
    "testUnsavedDocumentDraftSurvivesBackgroundAfterAuthentication",
    "testMaximumTypeUnlockIsReachablePortraitAndLandscapeWithoutAuthenticationSuccess",
)


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def device_uuid(value):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise argparse.ArgumentTypeError("--device requires an exact simulator UUID; aliases are not accepted")
    return str(uuid.UUID(value)).upper()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, type=device_uuid, help="Exact UUID of an already booted iOS simulator")
    parser.add_argument("--timeout", type=int, default=1200, metavar="SECONDS", help="Whole xcodebuild timeout (default: 1200)")
    parser.add_argument("--only-test", metavar="METHOD", help="One test method within PrivacyTransitionUITests only")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.only_test and not re.fullmatch(r"test[A-Za-z0-9_]+", args.only_test):
        parser.error("--only-test must be a test method name, without a target, class, or slash")
    if args.only_test and args.only_test not in EXPECTED_METHODS:
        parser.error("--only-test must name a current PrivacyTransitionUITests method")
    return args


class DriverError(RuntimeError):
    pass


def result_manifest(tree):
    """Read every test case, including duplicates and tests outside our suite."""
    if not isinstance(tree, dict) or not isinstance(tree.get("testNodes"), list) or not isinstance(tree.get("devices"), list):
        raise DriverError("Cannot validate xcresult test tree")
    cases = []
    pending = list(tree["testNodes"])
    while pending:
        node = pending.pop()
        if not isinstance(node, dict) or not isinstance(node.get("children", []), list):
            raise DriverError("Cannot validate xcresult test node")
        pending.extend(node.get("children", []))
        if node.get("nodeType") == "Test Case":
            if not isinstance(node.get("nodeIdentifier"), str):
                raise DriverError("xcresult test case has no identifier")
            cases.append({"identifier": node["nodeIdentifier"], "result": node.get("result")})
    devices = []
    for device in tree["devices"]:
        if not isinstance(device, dict) or not isinstance(device.get("deviceId"), str):
            raise DriverError("xcresult test tree has no device identifier")
        devices.append({"identifier": device["deviceId"].upper(), "platform": device.get("platform")})
    return sorted(cases, key=lambda case: case["identifier"]), devices


def source_provenance(root):
    """Fingerprint the Git candidate without copying source content to logs."""
    def git(*arguments):
        result = subprocess.run(["git", *arguments], cwd=root, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30, check=False)
        if result.returncode:
            raise DriverError("Cannot capture source provenance: " + result.stderr.decode("utf-8", "replace").strip())
        return result.stdout

    def state():
        return (
            git("rev-parse", "HEAD").decode("ascii").strip(),
            git("status", "--porcelain=v1", "-z", "--untracked-files=all"),
            git("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--binary", "--full-index", "--no-renames", "HEAD", "--"),
            git("ls-files", "--others", "--exclude-standard", "-z"),
        )

    before = state()
    untracked = []
    for raw_path in sorted(path for path in before[3].split(b"\0") if path):
        relative = os.fsdecode(raw_path)
        path = root / relative
        metadata = path.lstat()
        digest = hashlib.sha256()
        if stat.S_ISLNK(metadata.st_mode):
            content = os.fsencode(os.readlink(path))
            digest.update(content)
            size = len(content)
        elif stat.S_ISREG(metadata.st_mode):
            if metadata.st_size > 128 * 1024 * 1024:
                raise DriverError(f"Untracked file is too large for bounded provenance capture: {relative}")
            size = metadata.st_size
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise DriverError(f"Unsupported untracked entry in source candidate: {relative}")
        untracked.append({"path": relative, "mode": oct(stat.S_IMODE(metadata.st_mode)),
                          "kind": "symlink" if stat.S_ISLNK(metadata.st_mode) else "file",
                          "bytes": size, "sha256": digest.hexdigest()})
    if before != state():
        raise DriverError("Source tree changed while capturing provenance; retry with a stable candidate")
    manifest = json.dumps(untracked, sort_keys=True, separators=(",", ":")).encode("utf-8")
    diff_digest = hashlib.sha256()
    # Length framing makes this combined digest unambiguous. It includes every
    # non-ignored untracked file, including this driver and newly added tests.
    for data in [before[2], manifest]:
        diff_digest.update(len(data).to_bytes(8, "big"))
        diff_digest.update(data)
    provenance = {
        "head": before[0], "dirty": bool(before[1]),
        "status_porcelain_v1_z": before[1].decode("utf-8", "surrogateescape"),
        "tracked_diff_sha256": hashlib.sha256(before[2]).hexdigest(),
        "candidate_diff_sha256": diff_digest.hexdigest(), "untracked_files": untracked,
    }
    canonical = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
    provenance["candidate_sha256"] = hashlib.sha256(canonical).hexdigest()
    return provenance


class Driver:
    def __init__(self, args):
        self.args = args
        self.root = Path(__file__).resolve().parent.parent
        run_name = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.directory = self.root / "build" / f"PrivacySimulator-{run_name}-{uuid.uuid4().hex[:8]}"
        self.directory.mkdir(parents=True, mode=0o700)
        self.log = (self.directory / "xcodebuild.log").open("w", encoding="utf-8", buffering=1)
        self.actions = (self.directory / "actions.jsonl").open("w", encoding="utf-8", buffering=1)
        self.process = None
        self.requests = {"match": 0, "nomatch": 0}
        self.original_enrollment = None
        self.enrollment_changed = False
        self.provenance = None
        methods = [args.only_test] if args.only_test else EXPECTED_METHODS
        self.expected_cases = sorted(f"PrivacyTransitionUITests/{method}()" for method in methods)
        self.summary = {
            "status": "running", "started_at": timestamp(), "device": args.device,
            "directory": str(self.directory), "result_bundle": str(self.directory / "Tests.xcresult"),
            "requests": self.requests,
            "selected_test_class": "TripfolioUITests/PrivacyTransitionUITests",
            "selected_method": args.only_test,
            "expected_test_cases": self.expected_cases,
        }
        self.write_summary()

    def record(self, action, **fields):
        entry = {"timestamp": timestamp(), "monotonic_seconds": time.monotonic(), "action": action, **fields}
        self.actions.write(json.dumps(entry, sort_keys=True) + "\n")
        self.actions.flush()

    def write_summary(self):
        path = self.directory / "summary.json"
        path.write_text(json.dumps(self.summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def command(self, action, command):
        self.record(action + "_started", command=command)
        try:
            result = subprocess.run(command, cwd=self.root, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            self.record(action, returncode=None, error=str(error))
            raise DriverError(f"{action}: {error}") from error
        self.record(action, returncode=result.returncode, output=result.stdout)
        if result.returncode:
            raise DriverError(f"{action} failed ({result.returncode}): {result.stdout.strip()}")
        return result.stdout

    def simctl(self, action, verb, *values):
        return self.command(action, ["xcrun", "simctl", verb, self.args.device, *values])

    def prepare(self):
        self.provenance = source_provenance(self.root)
        self.summary["source_before"] = self.provenance
        self.record("source_before", provenance=self.provenance)
        self.write_summary()
        output = self.command("list_devices", ["xcrun", "simctl", "list", "devices", "available", "--json"])
        try:
            devices = json.loads(output)["devices"]
            matches = [(runtime, device) for runtime, items in devices.items() for device in items
                       if device.get("udid", "").upper() == self.args.device]
        except (ValueError, KeyError, AttributeError, TypeError) as error:
            raise DriverError("Cannot validate simctl device inventory") from error
        if len(matches) != 1:
            raise DriverError("Requested UUID is not one available simulator")
        runtime, device = matches[0]
        if ".iOS-" not in runtime or not device.get("isAvailable") or device.get("state") != "Booted":
            raise DriverError("Requested UUID must be an available, already booted iOS simulator")
        self.summary["runtime"] = runtime
        self.summary["device_name"] = device.get("name")
        self.record("validated_device", runtime=runtime, device=device)
        if not (self.root / "Tripfolio.xcodeproj" / "project.pbxproj").is_file():
            raise DriverError("Generate Tripfolio.xcodeproj with xcodegen before running this driver")

        # Fail before changing enrollment if the installed CLI's output cannot
        # be parsed safely. The original state is restored even after test errors.
        state = self.simctl("read_enrollment", "notify_get_state", ENROLLMENT).strip()
        if not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", state):
            raise DriverError(f"Cannot safely parse original enrollment state: {state!r}")
        self.original_enrollment = int(state, 16 if state.lower().startswith("0x") else 10)
        self.enrollment_changed = True  # Restore even if the set command fails ambiguously.
        self.simctl("enroll_state", "notify_set_state", ENROLLMENT, "1")
        self.simctl("enroll_post", "notify_post", ENROLLMENT)

    def run_tests(self):
        test_selection = "TripfolioUITests/PrivacyTransitionUITests"
        if self.args.only_test:
            test_selection += "/" + self.args.only_test
        command = [
            "xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio",
            "-configuration", "Debug", "-destination", f"platform=iOS Simulator,id={self.args.device}",
            "-destination-timeout", "30", "-parallel-testing-enabled", "NO",
            "-maximum-concurrent-test-simulator-destinations", "1", "-collect-test-diagnostics", "never",
            "-default-test-execution-time-allowance", "120", "-maximum-test-execution-time-allowance", "180",
            "-derivedDataPath", str(self.root / "build" / "DerivedData"),
            "-resultBundlePath", self.summary["result_bundle"],
            "-only-testing:" + test_selection, "CODE_SIGNING_ALLOWED=NO", "test",
        ]
        environment = os.environ.copy()
        environment.update({"TEST_RUNNER_TRIPDOCKET_BIOMETRIC_DRIVER": "1", "NSUnbufferedIO": "YES",
                            "TEST_RUNNER_NSUnbufferedIO": "YES"})
        self.record("xcodebuild_started", command=command)
        self.process = subprocess.Popen(command, cwd=self.root, env=environment, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, start_new_session=True)
        lines = queue.Queue()

        def read_output():
            try:
                for line in self.process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        deadline = time.monotonic() + self.args.timeout
        while True:
            if time.monotonic() >= deadline:
                raise DriverError(f"xcodebuild exceeded {self.args.timeout} seconds")
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                break
            self.log.write(line)
            sys.stdout.write(line)
            sys.stdout.flush()
            if MARKER in line:
                match = MARKER_PATTERN.search(line)
                if match is None or line.count(MARKER) != 1:
                    raise DriverError(f"Malformed biometric request: {line.strip()}")
                event = match.group(1)
                self.requests[event] += 1
                self.record("biometric_request", event=event, ordinal=sum(self.requests.values()))
                # One command for this one marker. Never retry a potentially
                # delivered match: a retry could authenticate a later prompt.
                self.simctl("biometric_" + event, "notify_post", EVENTS[event])
        remaining = max(0.01, deadline - time.monotonic())
        try:
            returncode = self.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise DriverError("xcodebuild did not exit after closing its output") from error
        self.record("xcodebuild", returncode=returncode)
        self.summary["xcodebuild_returncode"] = returncode
        if returncode:
            raise DriverError(f"xcodebuild failed with exit code {returncode}")
        self.validate_result()
        if sum(self.requests.values()) == 0:
            raise DriverError("No biometric request was handled; an empty or skipped run is not a pass")

    def validate_result(self):
        output = self.command("xcresult_summary", [
            "xcrun", "xcresulttool", "get", "test-results", "summary", "--schema-version", "0.4.0",
            "--path", self.summary["result_bundle"], "--compact",
        ])
        try:
            result = json.loads(output)
            keys = ["totalTestCount", "passedTests", "failedTests", "skippedTests", "expectedFailures"]
            if any(type(result.get(key)) is not int or result[key] < 0 for key in keys):
                raise ValueError("missing or invalid test counts")
        except (ValueError, TypeError, AttributeError) as error:
            raise DriverError("Cannot validate xcresult test summary") from error
        (self.directory / "xcresult-summary.json").write_text(output + "\n", encoding="utf-8")
        self.summary["test_counts"] = {key: result[key] for key in keys}
        self.summary["test_result"] = result.get("result")
        # Keep counts even if the detailed manifest or device check fails.
        self.write_summary()
        tree_output = self.command("xcresult_tests", [
            "xcrun", "xcresulttool", "get", "test-results", "tests", "--schema-version", "0.4.0",
            "--path", self.summary["result_bundle"], "--compact",
        ])
        (self.directory / "xcresult-tests.json").write_text(tree_output + "\n", encoding="utf-8")
        try:
            cases, devices = result_manifest(json.loads(tree_output))
        except (ValueError, TypeError) as error:
            raise DriverError("Cannot parse xcresult test tree") from error
        self.summary["observed_test_cases"] = cases
        self.summary["observed_devices"] = devices
        self.write_summary()
        identifiers = [case["identifier"] for case in cases]
        if identifiers != self.expected_cases or result["totalTestCount"] != len(self.expected_cases):
            raise DriverError("xcresult test cases do not exactly match the requested manifest")
        if any(case["result"] != "Passed" for case in cases):
            raise DriverError("xcresult contains a requested test case that did not pass")
        expected_device = [{"identifier": self.args.device, "platform": "iOS Simulator"}]
        if devices != expected_device:
            raise DriverError("xcresult test device does not exactly match the requested simulator UUID")
        configurations = result.get("devicesAndConfigurations")
        if (not isinstance(configurations, list) or len(configurations) != 1
                or not isinstance(configurations[0], dict)
                or not isinstance(configurations[0].get("device"), dict)
                or configurations[0]["device"].get("deviceId", "").upper() != self.args.device):
            raise DriverError("xcresult summary device does not exactly match the requested simulator UUID")
        if (result.get("result") != "Passed" or result["totalTestCount"] <= 0
                or result["passedTests"] != result["totalTestCount"]
                or any(result[key] != 0 for key in ["failedTests", "skippedTests", "expectedFailures"])):
            raise DriverError("xcresult is not a complete pass: " + json.dumps(self.summary["test_counts"], sort_keys=True))

    def verify_provenance(self):
        if self.provenance is None:
            return
        after = source_provenance(self.root)
        self.summary["source_after"] = after
        self.record("source_after", provenance=after)
        if after != self.provenance:
            raise DriverError("Source candidate changed during the run; evidence cannot be attributed to one candidate")

    def stop_tests(self):
        if self.process is None:
            return
        # Only the process group created by this driver, never other Xcode jobs.
        # Descendants can outlive their leader, so leader exit is not proof that
        # this private group is gone. Popen(start_new_session=True) makes PID=PGID.
        process_group = self.process.pid
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.process.wait(timeout=10)
        self.record("xcodebuild_stopped", returncode=self.process.returncode)

    def restore(self):
        if self.enrollment_changed:
            self.simctl("restore_enrollment_state", "notify_set_state", ENROLLMENT, str(self.original_enrollment))
            self.simctl("restore_enrollment_post", "notify_post", ENROLLMENT)


def main():
    args = arguments()
    driver = Driver(args)
    print(f"Privacy test artifacts: {driver.directory}", flush=True)
    failure = None
    interrupted = False

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        driver.prepare()
        driver.run_tests()
    except KeyboardInterrupt:
        failure = "Interrupted"
        interrupted = True
    except Exception as error:
        failure = str(error)
    finally:
        # A second interrupt must not prevent bounded child cleanup/restoration.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for cleanup in [driver.stop_tests, driver.restore, driver.verify_provenance]:
            try:
                cleanup()
            except Exception as error:
                failure = (failure + "; " if failure else "") + f"Cleanup failed: {error}"
        driver.summary.update({"status": "failed" if failure else "passed", "finished_at": timestamp(),
                               "error": failure})
        driver.write_summary()
        driver.log.close()
        driver.actions.close()
    if failure:
        print(f"Privacy test driver failed: {failure}", file=sys.stderr, flush=True)
    print(f"Privacy test summary: {driver.directory / 'summary.json'}", flush=True)
    return 130 if interrupted else (1 if failure else 0)


if __name__ == "__main__":
    sys.exit(main())
