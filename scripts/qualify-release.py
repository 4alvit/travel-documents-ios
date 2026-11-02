#!/usr/bin/env python3
"""Capture hosted batch/biometric evidence; independent review remains required."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

HERE = Path(__file__).resolve().parent
MODES = {"batch": ("test-batch-simulator.py", 1200),
         "biometrics": ("test-privacy-simulator.py", 1200)}
WORK_SECONDS = {"batch": 1800, "biometrics": 2400}
CLEANUP_SECONDS = 180
APP_ID = "com.4alvit.tripfolio"
RUNNER_ID = APP_ID + ".uitests.xctrunner"
MIB = 1024 * 1024
DEVELOPER_DIR = "/Applications/Xcode_26.2.app/Contents/Developer"
XCODE_VERSION = "Xcode 26.2\nBuild version 17C52"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


processes = load_module(HERE / "recovery_process.py", "qualification_processes")


def context(mode, env):
    require(mode in MODES, "Select exactly batch or biometrics")
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("RUNNER_OS") == "macOS",
            "Qualification requires the hosted macOS workflow")
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and env.get("GITHUB_WORKFLOW") == "Release qualification"
            and env.get("GITHUB_JOB") == "qualify", "Unexpected workflow context")
    require(env.get("GITHUB_REPOSITORY") == "4alvit/travel-documents-ios", "Unexpected repository")
    require(re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")), "Missing exact source SHA")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(re.fullmatch(r"[1-9][0-9]*", env.get(key, "")), "Invalid run identity")
    return {key: env[key] for key in ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID",
                                     "GITHUB_RUN_ATTEMPT", "GITHUB_EVENT_NAME", "GITHUB_WORKFLOW")}


def device_map(data):
    require(isinstance(data, dict) and isinstance(data.get("devices"), dict), "Invalid inventory")
    result = {}
    for runtime, devices in data["devices"].items():
        require(isinstance(devices, list), "Invalid runtime devices")
        for device in devices:
            identifier = str(uuid.UUID(device["udid"])).upper()
            require(identifier not in result, "Duplicate device UUID")
            result[identifier] = {"runtime": runtime, "name": device["name"],
                                  "type": device.get("deviceTypeIdentifier"), "state": device["state"]}
    return result


def choose_runtime(data, sdk, architecture):
    require(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", sdk), "Invalid SDK version")
    matches = [r for r in data.get("runtimes", []) if r.get("version") == sdk
               and r.get("isAvailable") is True
               and r.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
               and architecture in r.get("supportedArchitectures", [])]
    require(len(matches) == 1, "No unique SDK-matched available runtime")
    phones = [d["identifier"] for d in matches[0].get("supportedDeviceTypes", [])
              if d.get("identifier", "").startswith("com.apple.CoreSimulator.SimDeviceType.iPhone-")]
    require(phones and len(phones) == len(set(phones)), "No unambiguous compatible iPhone")
    preferred = "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"
    return matches[0]["identifier"], preferred if preferred in phones else sorted(phones)[-1]


def tree_manifest(root, check):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "Invalid product root")
    result, total = {}, 0
    def visit(path, relative):
        nonlocal total
        check()
        require(len(result) < 10000, "Product entry cap exceeded")
        before = path.lstat()
        if stat.S_ISDIR(before.st_mode):
            result[relative] = {"kind": "directory"}
            for child in sorted(path.iterdir()):
                visit(child, relative + "/" + child.name)
        elif stat.S_ISLNK(before.st_mode):
            result[relative] = {"kind": "link", "target": os.readlink(path)}
        else:
            require(stat.S_ISREG(before.st_mode), "Unexpected product entry")
            total += before.st_size
            require(total <= 256 * 1024 * 1024, "Product byte cap exceeded")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    check(); digest.update(chunk)
            result[relative] = {"kind": "file", "bytes": before.st_size, "sha256": digest.hexdigest()}
        after = path.lstat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode),
                "Product changed while capturing identity")
    visit(root, ".")
    return result


def bounded_read(root, relative, maximum, check):
    """Read one pinned regular file; never follow a library path component."""
    parts = relative.split("/")
    require(1 <= len(parts) <= 8 and all(p and p not in (".", "..") and "\\" not in p
                                      for p in parts), "Invalid snapshot relative path")
    opened, pins = [], []
    try:
        check()
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(fd)
        root_stat = os.fstat(fd)
        require((root_stat.st_dev, root_stat.st_ino) == (root.lstat().st_dev, root.lstat().st_ino),
                "Snapshot root identity changed")
        for index, name in enumerate(parts):
            check()
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            directory = index < len(parts) - 1
            require(stat.S_ISDIR(before.st_mode) if directory else stat.S_ISREG(before.st_mode),
                    "Snapshot contains a link or unsupported entry")
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                            | (os.O_DIRECTORY if directory else 0), dir_fd=fd)
            opened.append(child)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)
            require(identity(before) == identity(os.fstat(child)), "Snapshot entry changed during open")
            pins.append((fd, name, child, identity(before))); fd = child
        require(0 < before.st_size <= maximum, "Snapshot file exceeds byte limit")
        chunks, size = [], 0
        while True:
            check(); chunk = os.read(fd, min(MIB, maximum + 1 - size))
            if not chunk: break
            chunks.append(chunk); size += len(chunk)
            require(size <= maximum, "Snapshot file grew beyond byte limit")
        require(size == before.st_size, "Snapshot file size changed")
        for parent, name, child, pin in pins:
            check()
            require(identity(os.fstat(child)) == pin
                    and identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == pin,
                    "Snapshot entry identity changed")
        require((root.lstat().st_dev, root.lstat().st_ino) == (root_stat.st_dev, root_stat.st_ino),
                "Snapshot root identity changed")
        return b"".join(chunks)
    finally:
        for fd in reversed(opened): os.close(fd)


# Exact producer documentation captured from Xcode 26.2 build 17C52.
# The summary document is malformed/stale; its identity is not runtime evidence.
SCHEMA_DOCUMENTS = {
    "summary": "caebdac65d3702246017a340212ddf224723bb24db65631c47ff08bf140a5e66",
    "tests": "e2ab685a13f16c60c44bec331e90c85973f0e3cc1fcd9669ddee541fc1ad3609",
}


def toolchain_profile(mode):
    require(mode in MODES, "Select exactly batch or biometrics")
    if mode == "batch":
        return {"developer_dir": "/Applications/Xcode_16.4.app/Contents/Developer",
                "xcode_version": "Xcode 16.4\nBuild version 16F6", "sdk_version": "18.5",
                "xcresulttool_version": "xcresulttool version 23714, format version 3.53 (current)",
                "schema_documents": None}
    return {"developer_dir": DEVELOPER_DIR, "xcode_version": XCODE_VERSION, "sdk_version": "26.2",
            "xcresulttool_version": None, "schema_documents": dict(SCHEMA_DOCUMENTS)}


def validate_schemas(summary, tests, mode="biometrics"):
    """Recognize exact pinned-toolchain docs without loosening any JSON parser."""
    documents = toolchain_profile(mode)["schema_documents"]
    require(documents is not None, "Pinned batch producer does not support schema documentation")
    for kind, raw in (("summary", summary), ("tests", tests)):
        require(isinstance(raw, bytes) and 0 < len(raw) <= MIB, "Invalid schema documentation bytes")
        require(hashlib.sha256(raw).hexdigest() == documents[kind],
                "Unrecognized " + kind + " schema documentation for pinned Xcode")
    return {"selection": "pinned-toolchain-default", "documentation_verified": True,
            "runtime_evidence": "Independent pinned-reader review must provide explicit warnings, failures, counts, cases and device identity"}


def validate_driver(mode, summary, result, tree, expected_cases, owned, head):
    require(summary.get("status") == "passed" and not summary.get("error")
            and summary.get("xcodebuild_returncode") == 0, "Driver did not pass")
    require(summary.get("device") == owned, "Driver device changed")
    expected = {"totalTestCount": len(expected_cases), "passedTests": len(expected_cases),
                "failedTests": 0, "skippedTests": 0, "expectedFailures": 0}
    require(result.get("result") == "Passed" and all(type(result.get(k)) is int
            and result[k] == v for k, v in expected.items()), "Incomplete or skipped result")
    require(result.get("testFailures") == [], "XCTest reported failures or omitted their evidence")
    require("runtimeWarnings" not in result or result["runtimeWarnings"] == [],
            "XCTest reported runtime warnings or invalid warning evidence")
    pending, cases = list(tree.get("testNodes", [])), []
    while pending:
        node = pending.pop()
        require(node.get("nodeType") != "Runtime Warning", "XCTest test tree reported a runtime warning")
        pending.extend(node.get("children", []))
        if node.get("nodeType") == "Test Case":
            require(node.get("result") == "Passed", "A selected case did not pass")
            cases.append(node.get("nodeIdentifier"))
    require(sorted(cases) == sorted(expected_cases), "Wrong, duplicate, or missing test case")
    require([(d.get("deviceId", "").upper(), d.get("platform")) for d in tree.get("devices", [])]
            == [(owned, "iOS Simulator")], "Result device mismatch")
    configurations = result.get("devicesAndConfigurations", [])
    require(len(configurations) == 1 and configurations[0].get("device", {}).get("deviceId", "").upper() == owned,
            "Result configuration mismatch")
    before, after = summary.get("source_before"), summary.get("source_after")
    require(isinstance(before, dict) and before == after and before.get("head") == head,
            "Driver source identity changed")
    require(not before.get("dirty") and not before.get("status")
            and not before.get("status_porcelain_v1_z"), "Driver source was dirty")
    if mode == "batch":
        require(summary.get("source_originals_unchanged") is True and summary.get("fixture_cleanup")
                == "removed only the uniquely created fixture folder", "Batch originals/cleanup unverified")
    else:
        require(summary.get("selected_method") is None and all(summary.get("requests", {}).get(k, 0) > 0
                for k in ("match", "nomatch")), "Full biometric sequence missing")


class Commands(processes.Smoke):
    def __init__(self, owner, name):
        self.owner = owner
        self.out = owner.out / name; self.out.mkdir()
        self.ops = processes.RealOps(dict(os.environ), str(owner.root))
        self.t0 = owner.started; self.limit = owner.work_deadline
        self.write_deadline = owner.cleanup_deadline + 10
        self.active = {}; self.absent_groups = set(); self.unknown_spawn = False; self.log_total = 0
        self.report = {"commands": [], "errors": []}
        owner.report[name] = self.report

    def checkpoint(self, **_):
        self.owner.check()
        require(time.monotonic() < self.limit, "Command phase expired")


class Qualification:
    def __init__(self, root, mode, env):
        self.job = context(mode, env); self.root = Path(root).resolve(); self.mode = mode
        self.started = time.monotonic(); self.work_deadline = self.started + WORK_SECONDS[mode]
        self.cleanup_deadline = self.work_deadline + CLEANUP_SECONDS
        self.cleaning = self.interrupted = self.acquiring = self.finalizing_driver = False
        self.owned = self.intent = self.baseline = None; self.driver_calls = 0
        self.out = self.root / "build" / ("ReleaseQualification-" + mode + "-" + self.job["GITHUB_RUN_ID"]
                                         + "-" + self.job["GITHUB_RUN_ATTEMPT"])
        require(not self.out.parent.is_symlink() and (not self.out.parent.exists()
                or self.out.parent.resolve() == self.out.parent), "Unsafe build output parent")
        self.out.mkdir(parents=True, exist_ok=False)
        self.report = {"status": "running", "mode": mode, "job": self.job,
                       "limits": {"work_seconds": WORK_SECONDS[mode], "cleanup_seconds": CLEANUP_SECONDS},
                       "errors": [], "cleanup_verified": False}
        self.commands = Commands(self, "commands"); self.xcode = Commands(self, "xcode-process")
        self.save()

    def save(self):
        require(time.monotonic() < self.cleanup_deadline + 10, "Receipt deadline expired")
        self.report["elapsed_seconds"] = time.monotonic() - self.started
        (self.out / "receipt.json").write_text(json.dumps(self.report, indent=2) + "\n")

    def check(self):
        require(self.cleaning or not self.interrupted, "Qualification interrupted")
        require(time.monotonic() < (self.cleanup_deadline if self.cleaning else self.work_deadline),
                "Qualification deadline expired")

    def command(self, label, argv, seconds=30):
        require(not self.xcode.unknown_spawn, "Unresolved xcodebuild spawn")
        return self.commands.command(label, [str(v) for v in argv], seconds + 8)

    def inventory(self, label):
        return device_map(json.loads(self.command(label, ["xcrun", "simctl", "list", "devices", "--json"],
                                                  30 if self.cleaning else 120)))

    def source(self, label):
        head = self.command(label + "-head", ["git", "rev-parse", "HEAD"]).strip()
        require(head == self.job["GITHUB_SHA"], "Checkout differs from dispatched commit")
        require(not self.command(label + "-status", ["git", "status", "--porcelain=v1", "--untracked-files=all"]),
                "Qualification source must be clean")
        tree = self.command(label + "-tree", ["git", "rev-parse", "HEAD^{tree}"]).strip()
        names = self.command(label + "-files", ["git", "ls-files", "-z"]).split("\0")
        files = {}
        for name in filter(None, names):
            self.check(); path = self.root / name; metadata = path.lstat()
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_size < 128 * 1024 * 1024,
                    "Unsupported source entry")
            files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "bytes": metadata.st_size, "executable": bool(metadata.st_mode & 0o111)}
        value = {"head": head, "tree": tree, "files": files}
        (self.out / (label + ".json")).write_text(json.dumps(value, indent=2) + "\n")
        return value

    def preflight_schemas(self):
        profile = toolchain_profile(self.mode)
        if profile["schema_documents"] is None:
            # Xcode 16.4 has no test-results --schema API. Pin the real reader
            # version; only independent 27.1 review can finish qualification.
            raw = self.command("xcresulttool-version", ["xcrun", "xcresulttool", "version"])
            require(raw.strip() == profile["xcresulttool_version"], "Unexpected batch xcresulttool version")
            name = "xcresulttool-version.txt"
            (self.out / name).write_bytes(raw.encode())
            self.report["xcresult_schema"] = {
                "status": "unsupported_by_producer", "selection": "pinned-toolchain-default",
                "xcresulttool_version": raw.strip(), "version_file": name,
                "version_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "runtime_evidence": "Independent pinned-reader review must provide explicit warnings, failures, counts, cases and device identity"}
            self.save()
            return
        schemas, hashes = {}, {}
        for kind in ("summary", "tests"):
            raw = self.command("xcresult-schema-" + kind,
                               ["xcrun", "xcresulttool", "get", "test-results", kind,
                                "--schema"]).encode()
            schemas[kind] = raw
            (self.out / ("xcresult-schema-" + kind + ".json")).write_bytes(raw)
            hashes[kind] = hashlib.sha256(raw).hexdigest()
        self.report["xcresult_schema"] = {**validate_schemas(schemas["summary"], schemas["tests"], self.mode),
                                          "sha256": hashes}
        self.save()

    def prepare(self):
        self.before = self.source("source-before")
        self.report["source"] = {"commit": self.before["head"], "tree": self.before["tree"]}
        toolchain = {}
        for name, argv in (("xcode", ["xcodebuild", "-version"]), ("developer", ["xcode-select", "-p"]),
                           ("sdk", ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"]),
                           ("architecture", ["uname", "-m"])):
            toolchain[name] = self.command(name, argv).strip()
        toolchain["developer_environment"] = os.environ.get("DEVELOPER_DIR")
        self.report["toolchain"] = toolchain
        profile = toolchain_profile(self.mode)
        require(toolchain["developer_environment"] == profile["developer_dir"]
                and toolchain["xcode"] == profile["xcode_version"]
                and toolchain["sdk"] == profile["sdk_version"],
                "Qualification requires its mode's pinned Xcode, developer directory and SDK")
        self.preflight_schemas()
        self.command("generate-project", ["xcodegen", "generate"], 120)
        original = self.commands.limit
        self.commands.limit = min(original, time.monotonic() + 300)
        try:
            runtimes = json.loads(self.command("runtimes", ["xcrun", "simctl", "list", "runtimes", "--json"], 150))
            runtime, dtype = choose_runtime(runtimes, "26.2" if self.mode == "batch" else toolchain["sdk"], toolchain["architecture"])
            self.baseline = self.inventory("baseline")
            self.intent = {"name": "TripDocket-Qualification-" + str(uuid.uuid4()), "runtime": runtime, "type": dtype}
            require(all(d["name"] != self.intent["name"] for d in self.baseline.values()), "Device name collision")
            self.report.update(baseline=self.baseline, create_intent=self.intent); self.save()
            self.acquiring = True
            created = self.command("create", ["xcrun", "simctl", "create", self.intent["name"], dtype, runtime], 60).strip()
            self.owned = str(uuid.UUID(created)).upper()
            require(self.owned not in self.baseline, "Create returned an existing device")
            self.report["owned_uuid"] = self.owned; self.save()
            self.acquiring = False
            self.verify_owned(self.inventory("created"))
        finally:
            self.acquiring = False; self.commands.limit = original
        self.command("boot", ["xcrun", "simctl", "boot", self.owned], 60)
        self.command("boot-ready", ["xcrun", "simctl", "bootstatus", self.owned, "-b"], 180)
        if self.mode == "batch":
            self.command("files-launch", ["xcrun", "simctl", "launch", self.owned, "com.apple.DocumentsApp"], 120)
            # One launch only; readiness observation never replays an action.
            listing = self.command("files-group", ["xcrun", "simctl", "get_app_container", self.owned,
                                                    "com.apple.DocumentsApp", "groups"], 60)
            groups = [line.split("\t")[1] for line in listing.splitlines()
                      if line.startswith("group.com.apple.FileProvider.LocalStorage\t") and len(line.split("\t")) == 2]
            require(len(groups) == 1, "Files local group ambiguous")
            provider = self.container_path(groups[0], "Shared", "AppGroup") / "File Provider Storage"
            end = min(self.work_deadline, time.monotonic() + 30)
            while not provider.exists():
                self.check(); require(time.monotonic() < end, "Files provider not ready"); time.sleep(0.1)
            require(provider.is_dir() and not provider.is_symlink(), "Invalid Files provider")

    def verify_owned(self, devices):
        require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline,
                "No exclusive device ownership")
        require(self.owned in devices and all(devices[self.owned][key] == self.intent[key]
                for key in ("runtime", "name", "type")), "Owned device identity changed")

    def container_path(self, value, *kind):
        path = Path(value)
        prefix = Path.home() / "Library/Developer/CoreSimulator/Devices" / self.owned / "data/Containers"
        prefix = prefix.joinpath(*kind)
        require(path.is_absolute() and path.resolve(strict=True) == path and path.is_dir(), "Invalid container")
        relative = path.relative_to(prefix)
        require(len(relative.parts) == (2 if kind == ("Bundle", "Application") else 1),
                "Unexpected container path depth")
        require(str(uuid.UUID(relative.parts[0])).upper() == relative.parts[0], "Invalid container UUID")
        if kind == ("Bundle", "Application"):
            require(relative.parts[1].endswith(".app"), "Invalid application container")
        return path

    def facade(self):
        # Private dependency injection into this one imported module, never the
        # interpreter's subprocess module. The original driver owns test logic.
        def run(argv, *, cwd, timeout=30, text=False, **kwargs):
            require(Path(cwd).resolve() == self.root, "Driver changed working directory")
            output = self.command("driver-command-" + str(len(self.commands.report["commands"])), argv, min(timeout, 30))
            return subprocess.CompletedProcess(argv, 0, output if text else output.encode(), "" if text else b"")
        def popen(argv, **kwargs):
            require(self.driver_calls == 0 and argv[0] == "xcodebuild"
                    and kwargs.get("start_new_session") is True and Path(kwargs["cwd"]).resolve() == self.root,
                    "Driver may launch exactly one owned xcodebuild")
            require("platform=iOS Simulator,id=" + self.owned in argv,
                    "Driver selected another destination")
            self.check(); self.driver_calls += 1
            record = {"id": "driver-xcodebuild", "argv": argv, "start": time.monotonic() - self.started}
            self.xcode.report["commands"].append(record); self.save()
            self.acquiring = True; self.xcode.unknown_spawn = True
            try:
                child = subprocess.Popen(argv, **kwargs)
                require(child.pid > 0, "Invalid child PID")
                self.xcode.active[child.pid] = child; record["pgid"] = child.pid
                self.xcode.unknown_spawn = False
            finally:
                self.acquiring = False
            self.save(); self.check()
            return child
        return SimpleNamespace(run=run, Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT,
                               TimeoutExpired=subprocess.TimeoutExpired)

    def run_driver(self):
        filename, timeout = MODES[self.mode]
        require(time.monotonic() + timeout + 120 < self.work_deadline, "Insufficient full driver/postcheck budget")
        module = load_module(HERE / filename, "qualification_" + self.mode)
        module.subprocess = self.facade()
        args = SimpleNamespace(device=self.owned, timeout=timeout, only_test=None)
        driver = module.Driver(args); failure = None
        self.report["driver_directory"] = str(driver.directory.relative_to(self.root))
        try:
            driver.prepare()
            require(time.monotonic() + timeout + 8 < self.work_deadline,
                    "Insufficient full test and owned-stop budget after driver preparation")
            driver.run_test() if self.mode == "batch" else driver.run_tests()
        except BaseException as error:
            failure = error
        finally:
            self.finalizing_driver = True
            # The concrete Popen object was registered at acquisition, even if
            # an interrupt arrived before the original driver assigned it.
            for child in list(self.xcode.active.values()):
                record = self.xcode.report["commands"][-1]
                try:
                    self.xcode.stop(child, min(self.cleanup_deadline, time.monotonic() + 8),
                                    record)
                    for stream in (child.stdout, child.stderr):
                        if stream is not None: stream.close()
                    record.update(returncode=child.returncode, outcome="stopped",
                                  finish=time.monotonic() - self.started)
                except BaseException as error:
                    record.update(error=repr(error), outcome="failed")
                    failure = failure or error
            if not self.xcode.active and not self.xcode.unknown_spawn:
                try:
                    if self.mode == "batch":
                        driver.verify_fixtures(); driver.remove_fixtures()
                        driver.summary["source_after"] = driver.source_snapshot()
                    else:
                        driver.restore(); driver.verify_provenance()
                except BaseException as error:
                    failure = failure or error
            driver.summary.update(status="failed" if failure else "passed", error=str(failure) if failure else None,
                                  finished_at=module.timestamp())
            driver.save() if self.mode == "batch" else driver.write_summary()
            driver.actions.close()
            if self.mode == "biometrics": driver.log.close()
            self.finalizing_driver = False
        result = None
        if (driver.directory / "xcresult-summary.json").exists():
            try:
                result = json.loads(bounded_read(driver.directory, "xcresult-summary.json", 16 * MIB, self.check))
                self.report["xcresult_issues"] = {
                    "runtimeWarnings": result["runtimeWarnings"] if "runtimeWarnings" in result else "not_reported",
                    "runtimeWarnings_reported": "runtimeWarnings" in result,
                    "testFailures": result.get("testFailures"),
                }
                self.save()
            except BaseException as error:
                failure = failure or error
        if failure: raise failure
        require(self.driver_calls == 1, "Driver did not launch exactly once")
        require(result is not None, "Missing xcresult summary")
        expected = [module.CASE] if self.mode == "batch" else ["PrivacyTransitionUITests/" + name + "()" for name in module.EXPECTED_METHODS]
        tree = json.loads(bounded_read(driver.directory, "xcresult-tests.json", 16 * MIB, self.check))
        validate_driver(self.mode, driver.summary, result, tree, expected, self.owned, self.job["GITHUB_SHA"])
        self.products(driver)
        if self.mode == "batch": self.batch_snapshot(driver)
        self.report["driver_capture_verified"] = True
        self.report["selected_cases"] = expected

    def products(self, driver):
        derived = driver.directory / "DerivedData" if self.mode == "batch" else self.root / "build/DerivedData"
        directory = derived / "Build/Products/Debug-iphonesimulator"
        runners = list(directory.glob("*-Runner.app")); require(len(runners) == 1, "Ambiguous built test runner")
        manifests = {}
        for identifier, built in ((APP_ID, directory / "Tripfolio.app"), (RUNNER_ID, runners[0])):
            built_manifest = tree_manifest(built, self.check)
            require(plistlib.loads((built / "Info.plist").read_bytes()).get("CFBundleIdentifier") == identifier,
                    "Wrong built bundle identifier")
            value = self.command("installed-" + identifier, ["xcrun", "simctl", "get_app_container", self.owned, identifier, "app"], 60).strip()
            installed = self.container_path(value, "Bundle", "Application")
            installed_manifest = tree_manifest(installed, self.check)
            require(built_manifest == installed_manifest, "Installed product differs from the built bytes")
            manifests[identifier] = {"built": built_manifest, "installed": installed_manifest, "equal": True}
        (self.out / "products.json").write_text(json.dumps(manifests, indent=2) + "\n")
        self.report["products_verified"] = True

    def batch_snapshot(self, driver):
        value = self.command("batch-library-container", ["xcrun", "simctl", "get_app_container",
                             self.owned, APP_ID, "data"], 60).strip()
        container = self.container_path(value, "Data", "Application")
        base = "Library/Application Support/TripfolioUITesting/"
        pointer_bytes = bounded_read(container, base + "active.json", 1024, self.check)
        pointer = json.loads(pointer_bytes)
        generation = pointer.get("generation")
        require(type(pointer.get("formatVersion")) is int and pointer["formatVersion"] == 1
                and isinstance(generation, str) and str(uuid.UUID(generation)) == generation,
                "Invalid active synthetic-library generation")
        catalog_path = base + generation + "/catalog.json"
        catalog_bytes = bounded_read(container, catalog_path, 2 * MIB, self.check)
        catalog = json.loads(catalog_bytes)
        require(type(catalog.get("schemaVersion")) is int and catalog["schemaVersion"] == 1,
                "Unsupported catalog schema")
        ids = {}
        for kind in ("trips", "travelers", "documents"):
            rows = catalog.get(kind)
            require(isinstance(rows, list) and len(rows) <= 1000, "Catalog item limit exceeded")
            ids[kind] = [str(uuid.UUID(row["id"])) for row in rows]
            require(len(ids[kind]) == len(set(ids[kind])), "Duplicate catalog IDs")
        documents, total, names = catalog["documents"], 0, set()
        for document, identifier in zip(documents, ids["documents"]):
            count, name = document.get("byteCount"), document.get("storedFilename")
            require(type(count) is int and 0 < count <= 16 * MIB, "Document byte limit exceeded")
            total += count; require(total <= 64 * MIB, "Library byte limit exceeded")
            require(name in [identifier + "." + suffix for suffix in ("pdf", "jpg", "png")]
                    and name not in names, "Invalid or duplicate stored filename")
            names.add(name)
            require(re.fullmatch(r"[0-9a-f]{64}", document.get("sha256", "")), "Invalid catalog digest")
            require(str(uuid.UUID(document["tripID"])) in ids["trips"] and
                    (document.get("travelerID") is None or str(uuid.UUID(document["travelerID"])) in ids["travelers"]),
                    "Broken catalog reference")
        fixtures = driver.summary.get("fixtures", [])
        require(len(fixtures) == 2 and {f["name"] for f in fixtures}
                == {"synthetic-ticket.pdf", "synthetic-insurance.pdf"}, "Unexpected source fixtures")
        fixture_map = {f["name"]: f for f in fixtures}
        copies = self.out / "BatchLibrary"; copies.mkdir()
        manifest = {"generation": generation, "originals": [], "fixture_matches": [],
                    "other_originals": "Verified against final catalog only; no pre-run snapshot"}
        for document in documents:
            name = document["storedFilename"]
            data = bounded_read(container, base + generation + "/" + name, 16 * MIB, self.check)
            digest = hashlib.sha256(data).hexdigest()
            require(len(data) == document["byteCount"] and digest == document["sha256"],
                    "Saved original differs from catalog bytes/hash")
            entry = {"document_id": document["id"], "original_filename": document["originalFilename"],
                     "file": name, "bytes": len(data), "sha256": digest}
            fixture = fixture_map.get(document["originalFilename"])
            if fixture:
                source = bounded_read(driver.directory, "fixtures/" + fixture["name"], 16 * MIB, self.check)
                require(source == data and fixture["bytes"] == len(source)
                        and fixture["sha256"] == digest, "Imported fixture bytes/hash changed")
                manifest["fixture_matches"].append({**entry, "fixture": fixture["name"], "equal": True})
            (copies / name).write_bytes(data); manifest["originals"].append(entry)
        require(sorted(row["fixture"] for row in manifest["fixture_matches"]) == sorted(fixture_map),
                "Each source fixture must match exactly one saved original")
        require(bounded_read(container, base + "active.json", 1024, self.check) == pointer_bytes
                and bounded_read(container, catalog_path, 2 * MIB, self.check) == catalog_bytes,
                "Library generation changed during snapshot")
        for name, data in (("active.json", pointer_bytes), ("catalog.json", catalog_bytes)):
            (copies / name).write_bytes(data)
            manifest[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        encoded = (json.dumps(manifest, indent=2) + "\n").encode()
        (copies / "manifest.json").write_bytes(encoded)
        self.report["batch_snapshot"] = {"verified": True, "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
                                          "fixture_matches": manifest["fixture_matches"], "total_original_bytes": total}

    def cleanup(self):
        self.cleaning = True; self.commands.limit = self.cleanup_deadline
        require(not self.xcode.active and not self.xcode.unknown_spawn
                and not self.commands.active and not self.commands.unknown_spawn, "Unresolved process ownership; device cleanup withheld")
        if self.baseline is None: return
        current = self.inventory("before-cleanup")
        if self.owned is None and self.intent:
            matches = [key for key, value in current.items() if key not in self.baseline
                       and all(value[k] == self.intent[k] for k in ("name", "runtime", "type"))]
            require(len(matches) <= 1, "Ambiguous interrupted device acquisition")
            if matches: self.owned = matches[0]; self.report["owned_uuid"] = self.owned
        if self.owned:
            self.verify_owned(current)
            if current[self.owned]["state"] != "Shutdown":
                try:
                    self.command("shutdown", ["xcrun", "simctl", "shutdown", self.owned], 60)
                except Exception as error:
                    # A timed-out RPC does not establish the device's final state.
                    # Retain the failure even if a fresh observation permits cleanup.
                    self.report["errors"].append("Cleanup shutdown: " + repr(error))
                    require(not self.xcode.active and not self.xcode.unknown_spawn
                            and not self.commands.active and not self.commands.unknown_spawn,
                            "Unresolved process ownership after shutdown; device cleanup withheld")
                    self.check()
                    current = self.inventory("after-shutdown-error")
                    self.report["shutdown_failure_inventory"] = current
                    if self.owned in current:
                        self.verify_owned(current)
                        require(current[self.owned]["state"] == "Shutdown",
                                "Owned device is not confirmed shut down; deletion withheld")
                    else:
                        require(current == self.baseline, "Baseline changed after shutdown failure")
            if self.owned in current:
                self.command("delete", ["xcrun", "simctl", "delete", self.owned], 60)
        final = self.inventory("after-cleanup")
        self.report["final_inventory"] = final
        require(final == self.baseline, "Baseline device inventory changed")
        self.report["cleanup_verified"] = True

    def capture_original_result(self):
        require(self.report["cleanup_verified"] and not self.xcode.active and not self.xcode.unknown_spawn
                and not self.commands.active and not self.commands.unknown_spawn,
                "Original result capture requires complete owned cleanup")
        result = self.root / self.report["driver_directory"] / "Tests.xcresult"
        require(result.is_relative_to(self.root / "build") and result.resolve(strict=True) == result,
                "Invalid original result path")
        # Reuse the bounded product traversal (256 MiB, 10,000 entries), after
        # every owned writer/device is gone. The original bundle is never edited.
        manifest = tree_manifest(result, self.check)
        require(all(entry["kind"] in ("file", "directory") for entry in manifest.values()),
                "Original result contains unsupported links")
        require(manifest.get("./Info.plist", {}).get("kind") == "file"
                and manifest.get("./Data", {}).get("kind") == "directory", "Incomplete original result bundle")
        encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.check()
        name = "xcresult-original-manifest.json"
        (self.out / name).write_bytes(encoded)
        self.check()
        self.report["original_xcresult"] = {
            "path": str(result.relative_to(self.root)), "manifest": name,
            "manifest_sha256": hashlib.sha256(encoded).hexdigest(), "entries": len(manifest),
        }

    def execute(self):
        try:
            self.prepare(); self.run_driver()
            require(self.source("source-after") == self.before, "Source changed during qualification")
        except BaseException as error:
            self.report["errors"].append(repr(error))
        finally:
            try: self.cleanup()
            except BaseException as error: self.report["errors"].append("Cleanup: " + repr(error))
            capture_ready = (not self.report["errors"] and self.report.get("driver_capture_verified")
                             and self.report.get("products_verified") and self.report["cleanup_verified"]
                             and (self.mode != "batch" or self.report.get("batch_snapshot", {}).get("verified")))
            if capture_ready:
                try: self.capture_original_result()
                except BaseException as error: self.report["errors"].append("Original result capture: " + repr(error))
            self.report["status"] = ("captured_pending_review" if capture_ready and not self.report["errors"]
                                     and self.report.get("original_xcresult") else "failed")
            self.save()
        return 0 if self.report["status"] == "captured_pending_review" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--mode", choices=MODES)
    selection.add_argument("--validate-schemas", nargs=2, metavar=("SUMMARY", "TESTS"))
    parser.add_argument("--schema-mode", choices=MODES,
                        help="Producer mode for --validate-schemas (default: biometrics / Xcode 26.2)")
    args = parser.parse_args()
    if args.schema_mode is not None and not args.validate_schemas:
        parser.error("--schema-mode requires --validate-schemas")
    if args.validate_schemas:
        documents = []
        for name in args.validate_schemas:
            path = Path(name).absolute()
            documents.append(bounded_read(path.parent, path.name, MIB, lambda: None))
        validate_schemas(*documents, mode=args.schema_mode or "biometrics")
        return 0
    run = Qualification(HERE.parent, args.mode, os.environ)
    def interrupt(_signal, _frame):
        run.interrupted = True
        if not (run.acquiring or run.finalizing_driver or run.cleaning): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt); signal.signal(signal.SIGINT, interrupt)
    return run.execute()


if __name__ == "__main__":
    sys.exit(main())
