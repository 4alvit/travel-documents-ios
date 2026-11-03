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
WORK_SECONDS = {"batch": 2400, "biometrics": 2400}
CLEANUP_SECONDS = 180
PREPARE_CASE = "BatchImportUITests/testRecoveryPrepareFilesProvider()"
# Includes build and runner startup; a retained run spent about 532s before
# its unchanged 180s case started. The original outer/driver budgets still apply.
PREPARE_SECONDS = 780
SEED_CASE = "BatchImportUITests/testNativeSaveSeedsBothSyntheticOriginals()"
SEED_SECONDS = 300
SEED_CASE_SECONDS = 180
FOLDER_CASE = "BatchImportUITests/testNativeCreateOwnedFilesFolder()"
FOLDER_SECONDS = 240
FOLDER_CASE_SECONDS = 180
APP_ID = "com.4alvit.tripfolio"
RUNNER_ID = APP_ID + ".uitests.xctrunner"
MIB = 1024 * 1024
DEVELOPER_DIR = "/Applications/Xcode_26.2.app/Contents/Developer"
XCODE_VERSION = "Xcode 26.2\nBuild version 17C52"
INTEL_RUNTIME_BUILD = "23C54"

# Complete source files, never extracted test bodies. LocalizationTests remains
# included because its basename is shared with a TravelCore package test.
BATCH_BUILD_RETAINED = (
    "AppTests/LocalizationTests.swift", "AppTests/PlatformTests.swift",
    "AppTests/StoreKitTestBootstrap.swift", "UITests/BatchImportUITests.swift",
)
BATCH_BUILD_EXCLUDED = (
    "AppTests/AppModelTests.swift", "AppTests/BatchCopiedSelectionTests.swift",
    "AppTests/BatchDocumentPickerTests.swift", "AppTests/BatchExternalSelectionTests.swift",
    "AppTests/BatchImportTests.swift", "AppTests/BatchPickerRequestTests.swift",
    "AppTests/ExternalReadCoordinationTests.swift", "AppTests/NotificationSystemTests.swift",
    "AppTests/PrivacySupportTests.swift", "AppTests/ReminderLifecycleTests.swift",
    "UITests/AccessibilityUITests.swift", "UITests/LocalizationUITests.swift",
    "UITests/PrivacySupportUITests.swift", "UITests/PrivacyTransitionUITests.swift",
    "UITests/PurchaseUITests.swift", "UITests/TripfolioUITests.swift",
)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checkpoint = load_module(HERE / "batch_checkpoint.py", "qualification_batch_checkpoint")
processes = load_module(HERE / "recovery_process.py", "qualification_processes")
recovery = load_module(HERE / "recovery_core.py", "qualification_recovery_validation")


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


def execution_profile(mode, env, architecture):
    """Select the explicit runner profile before allocating its work deadline."""
    require(mode in MODES, "Select exactly batch or biometrics")
    runner = env.get("QUALIFICATION_RUNNER")
    runner_arch = env.get("QUALIFICATION_RUNNER_ARCH")
    require((runner, runner_arch, architecture) in (
        ("macos-15", "ARM64", "arm64"), ("macos-15-intel", "X64", "x86_64")),
        "Qualification runner label or host architecture mismatch")
    intel_batch = mode == "batch" and runner == "macos-15-intel"
    return {"name": "intel-batch" if intel_batch else "default", "runner": runner,
            "runner_architecture": runner_arch, "architecture": architecture,
            "work_seconds": 3000 if intel_batch else WORK_SECONDS[mode],
            "boot_seconds": 600 if intel_batch else 180}

def focused_build_selection(mode, profile, files):
    """Bind batch-only literal exclusions to the verified runner and source set."""
    if mode == "biometrics" and profile["name"] == "default":
        return None
    identity = tuple(profile.get(key) for key in ("name", "runner", "runner_architecture", "architecture"))
    require(mode == "batch" and identity in (
        ("default", "macos-15", "ARM64", "arm64"),
        ("intel-batch", "macos-15-intel", "X64", "x86_64")),
        "Focused build requires a verified batch profile")
    require(isinstance(files, dict), "Focused build requires captured source files")
    expected = set(BATCH_BUILD_RETAINED + BATCH_BUILD_EXCLUDED)
    actual = {name for name in files if name.startswith(("AppTests/", "UITests/"))}
    require(actual == expected, "Focused build test source set changed")
    names = sorted(Path(name).name for name in BATCH_BUILD_EXCLUDED)
    require(len(names) == len(set(names)) and all(re.fullmatch(r"[A-Za-z0-9_]+\.swift", name) for name in names),
            "Focused build exclusions must be unique literal Swift basenames")
    require({name for name in files if Path(name).name in names} == set(BATCH_BUILD_EXCLUDED),
            "Focused build exclusion collides with another source or resource")
    return {"retained_sources": list(BATCH_BUILD_RETAINED), "excluded_sources": list(BATCH_BUILD_EXCLUDED),
            "build_settings": ["EXCLUDED_SOURCE_FILE_NAMES=" + " ".join(names)]}


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


def choose_runtime(data, version, architecture):
    require(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version), "Invalid runtime version")
    matches = [r for r in data.get("runtimes", []) if r.get("version") == version
               and r.get("isAvailable") is True
               and r.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
               and architecture in r.get("supportedArchitectures", [])]
    require(len(matches) == 1, "No unique pinned available runtime")
    require(sum(item.get("identifier") == matches[0]["identifier"] for item in data["runtimes"]) == 1,
            "Selected runtime identifier appears more than once")
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


def compiled_identity(path, check):
    """Bounded bytes plus modes, with no traversal through product symlinks."""
    content = tree_manifest(path, check)
    modes = {}
    for relative, entry in content.items():
        check()
        require(len(Path(relative).parts) <= 32, "Compiled product depth exceeded")
        value = (path / relative).lstat()
        modes[relative] = stat.S_IMODE(value.st_mode)
        require((entry["kind"] == "directory" and stat.S_ISDIR(value.st_mode))
                or (entry["kind"] == "file" and stat.S_ISREG(value.st_mode))
                or (entry["kind"] == "link" and stat.S_ISLNK(value.st_mode)),
                "Compiled product kind changed")
    require(tree_manifest(path, check) == content, "Compiled product changed during mode capture")
    return {"content": content, "modes": modes}


def shared_product_paths(raw, derived, build_settings=()):
    """Use the producer's actual target paths; never select a guessed output."""
    require(len(raw.encode()) <= MIB, "Build settings output too large")
    values = json.loads(raw)
    require(isinstance(values, list) and len(values) <= 16, "Invalid build settings targets")
    expected = {"Tripfolio": APP_ID, "TripfolioTests": APP_ID + ".tests",
                "TripfolioUITests": APP_ID + ".uitests"}
    result = {}; symroot = None
    for target, identifier in expected.items():
        matches = [item for item in values if isinstance(item, dict) and item.get("target") == target]
        require(len(matches) == 1, "Missing or ambiguous compiled target: " + target)
        settings = matches[0].get("buildSettings")
        require(isinstance(settings, dict) and settings.get("CONFIGURATION") == "Debug"
                and settings.get("PLATFORM_NAME") == "iphonesimulator"
                and settings.get("PRODUCT_BUNDLE_IDENTIFIER") == identifier,
                "Unexpected compiled target identity")
        if build_settings:
            require(settings.get("EXCLUDED_SOURCE_FILE_NAMES", "").split() == build_settings[0].split("=", 1)[1].split()
                    and not settings.get("INCLUDED_SOURCE_FILE_NAMES", "").strip(),
                    "Compiled target exclusion settings differ from the qualified build")
        paths = {}
        for key in ("SYMROOT", "BUILT_PRODUCTS_DIR", "TARGET_BUILD_DIR"):
            value = settings.get(key)
            require(isinstance(value, str), "Missing compiled target path")
            path = Path(value)
            require(path.is_absolute() and path.is_dir() and path.resolve(strict=True) == path,
                    "Invalid compiled target path")
            require(path.is_relative_to(derived) and path != derived, "Compiled target escaped owned build")
            paths[key] = path
        require(symroot is None or symroot == paths["SYMROOT"], "Compiled targets have different SYMROOTs")
        symroot = paths["SYMROOT"]
        require(paths["TARGET_BUILD_DIR"].is_relative_to(symroot)
                and paths["BUILT_PRODUCTS_DIR"].is_relative_to(symroot), "Target is outside compiled SYMROOT")
        name = settings.get("FULL_PRODUCT_NAME")
        require(isinstance(name, str) and name and Path(name).name == name and name not in (".", ".."),
                "Invalid compiled target name")
        path = paths["TARGET_BUILD_DIR"] / name
        require(path.is_dir() and not path.is_symlink() and path.resolve(strict=True) == path,
                "Compiled target is missing or indirect")
        require(plistlib.loads(bounded_read(path, "Info.plist", MIB, lambda: None)).get("CFBundleIdentifier") == identifier,
                "Compiled target plist identity differs")
        result[target] = path
    require(len(set(result.values())) == 3, "Compiled targets alias each other")
    require(result["TripfolioTests"].is_relative_to(result["Tripfolio"]), "Hosted test is outside its app")
    runners = [p for p in result["TripfolioUITests"].parents if p.suffix == ".app"]
    require(len(runners) == 1 and runners[0].is_relative_to(derived)
            and runners[0].resolve(strict=True) == runners[0], "Ambiguous shared UI runner")
    require(plistlib.loads(bounded_read(runners[0], "Info.plist", MIB, lambda: None)).get("CFBundleIdentifier") == RUNNER_ID,
            "Wrong shared runner identity")
    # The enclosing runner owns XCTest runtime frameworks outside its .xctest.
    result["TripfolioUITestsRunner"] = runners[0]
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
    return {"developer_dir": DEVELOPER_DIR, "xcode_version": XCODE_VERSION, "sdk_version": "26.2",
            "runtime_version": "26.2",
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
        cleanup = ("native root retained for verified owned Simulator teardown"
                   if summary.get("fixture_destination_mode") == "native_root"
                   else "removed only the uniquely created fixture folder")
        require(summary.get("source_originals_unchanged") is True and summary.get("fixture_cleanup") == cleanup,
                "Batch originals/cleanup unverified")
        if summary.get("fixture_destination_mode") == "native_root":
            require(summary.get("native_root_post_main_verified") is True,
                    "Native root originals not verified after main flow")
    else:
        require(summary.get("selected_method") is None and all(summary.get("requests", {}).get(k, 0) > 0
                for k in ("match", "nomatch")), "Full biometric sequence missing")


def validate_runtime_result(mode, selection, result):
    profile = toolchain_profile(mode)
    require(isinstance(selection, dict) and set(selection) == {
        "identifier", "version", "build", "architecture", "sdk_version", "sdk_matched"
    }, "Missing runtime selection evidence")
    require(selection["version"] == profile["runtime_version"]
            and selection["sdk_version"] == profile["sdk_version"]
            and selection["sdk_matched"] is (profile["runtime_version"] == profile["sdk_version"])
            and isinstance(selection["identifier"], str)
            and selection["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
            and isinstance(selection["build"], str) and 0 < len(selection["build"]) <= 100
            and selection["architecture"] in ("arm64", "x86_64"), "Wrong runtime selection evidence")
    if selection["architecture"] == "x86_64":
        require(selection["build"] == INTEL_RUNTIME_BUILD, "Intel qualification requires runtime build 23C54")
    configurations = result.get("devicesAndConfigurations", [])
    require(len(configurations) == 1, "Wrong runtime result configuration")
    device = configurations[0].get("device", {})
    require(device.get("osVersion") == selection["version"]
            and device.get("osBuildNumber") == selection["build"]
            and device.get("architecture") == selection["architecture"], "Native result runtime differs from selection")


def validate_batch_order(raw, recorded):
    driver = load_module(HERE / "test-batch-simulator.py", "qualification_batch_order")
    observed = driver.execution_order(raw)
    require(recorded == observed, "Batch execution order differs from original log")
    return observed


def validate_files_preparation(summary, tree, owned, selection, expected_case=PREPARE_CASE):
    require(expected_case in (PREPARE_CASE, SEED_CASE, FOLDER_CASE), "Unexpected preparation case")
    require(isinstance(summary, dict) and isinstance(tree, dict), "Invalid Files preparation result")
    nodes = tree.get("testNodes")
    require(isinstance(nodes, list), "Missing Files preparation cases")
    pending, count = [(node, 0) for node in nodes], 0
    while pending:
        node, depth = pending.pop(); count += 1
        require(isinstance(node, dict) and count <= 10000 and depth <= 100,
                "Files preparation tree bounds exceeded")
        require(node.get("nodeType") != "Runtime Warning", "Files preparation runtime warning")
        children = node.get("children", [])
        require(isinstance(children, list), "Invalid Files preparation children")
        pending.extend((child, depth + 1) for child in children)
    recovery.validate_result(summary, tree, expected_case, owned)
    require(summary.get("testFailures") == [], "Files preparation failures missing or nonempty")
    require("runtimeWarnings" not in summary or summary["runtimeWarnings"] == [],
            "Files preparation runtime warnings")
    validate_runtime_result("batch", selection, summary)
    require(summary["devicesAndConfigurations"][0]["device"].get("platform") == "iOS Simulator",
            "Files preparation requires Simulator result")


def validate_preparation_pair(summary, tree, owned, selection):
    """Require both real first-invocation cases, retaining explicit issue evidence."""
    require(isinstance(summary, dict) and isinstance(tree, dict), "Invalid hosted/Files preparation result")
    expected = {"totalTestCount": 2, "passedTests": 2, "failedTests": 0,
                "skippedTests": 0, "expectedFailures": 0}
    require(summary.get("result") == "Passed" and all(type(summary.get(key)) is int
            and summary[key] == value for key, value in expected.items()), "Unexpected preparation pair counts")
    pending = [(node, 0) for node in tree.get("testNodes", [])]; cases = []; count = 0
    while pending:
        node, depth = pending.pop(); count += 1
        require(isinstance(node, dict) and count <= 10000 and depth <= 100,
                "Preparation pair tree bounds exceeded")
        require(node.get("nodeType") != "Runtime Warning", "Preparation pair runtime warning")
        children = node.get("children", [])
        require(isinstance(children, list), "Invalid preparation pair children")
        pending.extend((child, depth + 1) for child in children)
        if node.get("nodeType") == "Test Case": cases.append((node.get("nodeIdentifier"), node.get("result")))
    require(sorted(cases) == sorted((case, "Passed") for case in checkpoint.PREPARATION_CASES),
            "Wrong, duplicated, failed or missing preparation pair case")
    require([(d.get("deviceId", "").upper(), d.get("platform")) for d in tree.get("devices", [])]
            == [(owned, "iOS Simulator")], "Preparation pair device mismatch")
    require(summary.get("testFailures") == [], "Preparation pair failures missing or nonempty")
    require("runtimeWarnings" not in summary or summary["runtimeWarnings"] == [],
            "Preparation pair runtime warnings")
    validate_runtime_result("batch", selection, summary)
    device = summary["devicesAndConfigurations"][0]["device"]
    require(device.get("deviceId", "").upper() == owned and device.get("platform") == "iOS Simulator",
            "Preparation pair configuration mismatch")


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
    native_folder_control = False

    def __init__(self, root, mode, env):
        self.job = context(mode, env); self.root = Path(root).resolve(); self.mode = mode
        reopen_control = env.get("TEST_RUNNER_TRIPDOCKET_NATIVE_REOPEN_CONTROL", "")
        require(reopen_control in ("", "1") and (not reopen_control or mode == "batch"),
                "Invalid native reopen diagnostic selection")
        self.native_reopen_control = reopen_control == "1"
        self.started = time.monotonic()
        self.profile = execution_profile(mode, env, os.uname().machine)
        self.work_deadline = self.started + self.profile["work_seconds"]
        self.cleanup_deadline = self.work_deadline + CLEANUP_SECONDS
        self.cleaning = self.interrupted = self.acquiring = self.finalizing_driver = False
        self.owned = self.intent = self.baseline = None; self.driver_calls = self.preparation_calls = 0
        self.build_settings = ()
        self.out = self.root / "build" / ("ReleaseQualification-" + mode + "-" + self.job["GITHUB_RUN_ID"]
                                         + "-" + self.job["GITHUB_RUN_ATTEMPT"])
        require(not self.out.parent.is_symlink() and (not self.out.parent.exists()
                or self.out.parent.resolve() == self.out.parent), "Unsafe build output parent")
        self.out.mkdir(parents=True, exist_ok=False)
        self.report = {"status": "running", "mode": mode, "job": self.job,
                       "execution_profile": self.profile,
                       "limits": {"work_seconds": self.profile["work_seconds"], "cleanup_seconds": CLEANUP_SECONDS},
                       "errors": [], "cleanup_verified": False}
        if self.native_reopen_control:
            self.report["diagnostic_native_reopen"] = {
                "enabled": True, "release_acceptance": False,
                "transport": "copy",
                "seed_export": "single-presentation-two-files",
                "scope": "Same AUT process exports and reopens both originals before the unchanged main relaunch"}
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
        require(toolchain["architecture"] == self.profile["architecture"],
                "Captured host architecture differs from qualification profile")
        profile = toolchain_profile(self.mode)
        require(toolchain["developer_environment"] == profile["developer_dir"]
                and toolchain["xcode"] == profile["xcode_version"]
                and toolchain["sdk"] == profile["sdk_version"],
                "Qualification requires its mode's pinned Xcode, developer directory and SDK")
        selection = focused_build_selection(self.mode, self.profile, self.before.get("files"))
        if selection is not None:
            self.build_settings = tuple(selection["build_settings"])
            self.report["focused_build"] = selection
            self.save()
        self.preflight_schemas()
        self.command("generate-project", ["xcodegen", "generate"], 120)
        original = self.commands.limit
        self.commands.limit = min(original, time.monotonic() + 300)
        try:
            runtimes = json.loads(self.command("runtimes", ["xcrun", "simctl", "list", "runtimes", "--json"], 150))
            runtime, dtype = choose_runtime(runtimes, profile["runtime_version"], toolchain["architecture"])
            selected = next(item for item in runtimes["runtimes"]
                            if item["identifier"] == runtime and item.get("version") == profile["runtime_version"])
            require(isinstance(selected.get("buildversion"), str) and selected["buildversion"],
                    "Selected runtime is missing its observed build")
            if toolchain["architecture"] == "x86_64":
                require(selected["buildversion"] == INTEL_RUNTIME_BUILD,
                        "Intel qualification requires runtime build 23C54")
            self.report["runtime_selection"] = {
                "identifier": runtime, "version": selected["version"], "build": selected["buildversion"],
                "architecture": toolchain["architecture"], "sdk_version": toolchain["sdk"],
                "sdk_matched": selected["version"] == toolchain["sdk"],
            }
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
        self.command("boot-ready", ["xcrun", "simctl", "bootstatus", self.owned, "-b"], self.profile["boot_seconds"])
        if self.mode == "batch":
            self.prepare_files_ui()
            # The separate real UI case initializes the provider. These reads
            # neither replay its actions nor create a provider directory.
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

    def preparation_manifest(self, path, check=None):
        check = self.check if check is None else check
        check()
        manifest = recovery.tree_manifest(path, check, max_bytes=256 * MIB)
        check()
        require(len(manifest) <= 10000 and manifest.get("Info.plist", {}).get("kind") == "file"
                and manifest.get("Data", {}).get("kind") == "directory",
                "Incomplete or oversized Files preparation result")
        return manifest

    def inspect_files_preparation(self, native_seed=False, native_folder=False):
        require(not (native_seed and native_folder), "Ambiguous preparation phase")
        prefix = "native-folder" if native_folder else "native-seed" if native_seed else "files-prepare"
        key = "native_folder" if native_folder else "native_seed" if native_seed else "files_preparation"
        expected_case = FOLDER_CASE if native_folder else SEED_CASE if native_seed else PREPARE_CASE
        original = self.out / (prefix + ".xcresult")
        manifest = self.preparation_manifest(original)
        raw = recovery.encoded(manifest)
        (self.out / (prefix + "-original-manifest.json")).write_bytes(raw)
        self.report[key + "_original"] = {
            "path": prefix + ".xcresult", "manifest": prefix + "-original-manifest.json",
            "sha256": hashlib.sha256(raw).hexdigest(), "entries": len(manifest),
        }
        self.save()
        copy = self.out / (prefix + "-inspection.xcresult"); copy.mkdir()
        for relative, item in manifest.items():
            self.check(); target = copy / relative
            if item["kind"] == "directory": target.mkdir()
            else:
                fd = os.open(original / relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as source, target.open("xb") as destination:
                    count = 0
                    while chunk := source.read(MIB):
                        self.check(); count += len(chunk)
                        require(count <= item["bytes"], "Files preparation result grew during copy")
                        destination.write(chunk)
                target.chmod(item["mode"])
        for relative, item in reversed(list(manifest.items())):
            if item["kind"] == "directory": (copy / relative).chmod(item["mode"])
        require(self.preparation_manifest(copy) == manifest and self.preparation_manifest(original) == manifest,
                "Files preparation result changed while copying")
        try:
            parsed = {}
            for kind in ("summary", "tests"):
                self.command(prefix + "-" + kind,
                    ["xcrun", "xcresulttool", "get", "test-results", kind, "--path", copy, "--compact"], 60)
                name = Path(self.commands.report["commands"][-1]["logs"]["stdout"]).name
                raw = bounded_read(self.commands.out, name, 16 * MIB, self.check)
                (self.out / (prefix + "-" + kind + ".json")).write_bytes(raw)
                parsed[kind] = json.loads(raw)
            if native_seed or native_folder:
                validate_files_preparation(parsed["summary"], parsed["tests"], self.owned,
                                           self.report.get("runtime_selection"), expected_case)
                cases = [expected_case]
            else:
                validate_preparation_pair(parsed["summary"], parsed["tests"], self.owned,
                                          self.report.get("runtime_selection"))
                cases = list(checkpoint.PREPARATION_CASES)
                self.report["files_preparation_order"] = checkpoint.preparation_order(self.preparation_log())
            self.report[key + "_result"] = {
                "functional_status": "passed", "cases": cases,
                "runtimeWarnings": parsed["summary"].get("runtimeWarnings", "not_reported"),
                "runtimeWarnings_reported": "runtimeWarnings" in parsed["summary"],
                "independent_warning_and_pixel_review": "pending",
            }
        finally:
            require(self.preparation_manifest(original) == manifest,
                    "Original Files preparation result mutated during reading")
            self.report[key + "_original"]["unchanged_after_reader"] = True

    def preparation_log(self, check=None):
        check = self.check if check is None else check
        check()
        rows = [row for row in self.commands.report["commands"] if row.get("id") == "files-prepare-ui"]
        require(len(rows) == 1 and rows[0].get("returncode") == 0, "First preparation command did not pass exactly once")
        row = rows[0]; argv = row.get("argv", [])
        require([arg for arg in argv if arg.startswith("-only-testing:")]
                == ["-only-testing:" + case for case in checkpoint.PREPARATION_TESTS],
                "Wrong first preparation selectors")
        for flag, value in (("-default-test-execution-time-allowance", "300"),
                            ("-maximum-test-execution-time-allowance", "600"),
                            ("-destination", "platform=iOS Simulator,id=" + self.owned)):
            require(argv.count(flag) == 1 and argv.index(flag) + 1 < len(argv)
                    and argv[argv.index(flag) + 1] == value, "Wrong first preparation bounds or destination")
        path = Path(row.get("logs", {}).get("stdout", ""))
        require(path.parent == self.commands.out and re.fullmatch(r"[1-9][0-9]*-stdout\.log", path.name),
                "Invalid first preparation log reference")
        return bounded_read(self.commands.out, path.name, 16 * MIB, check)

    def verify_preparation_prerequisite(self, check=None):
        """Recheck durable first-bundle evidence before UI launch, ACK and capture."""
        check = self.check if check is None else check
        check()
        require(self.report.get("files_preparation_verified") is True
                and self.report.get("files_preparation_result", {}).get("functional_status") == "passed"
                and self.report.get("files_preparation_result", {}).get("cases") == list(checkpoint.PREPARATION_CASES),
                "Missing verified hosted/Files preparation pair")
        proof = self.report.get("files_preparation_original", {})
        require(proof.get("path") == "files-prepare.xcresult"
                and proof.get("manifest") == "files-prepare-original-manifest.json"
                and proof.get("unchanged_after_reader") is True, "Missing original preparation pair proof")
        raw = bounded_read(self.out, proof["manifest"], 16 * MIB, check)
        require(hashlib.sha256(raw).hexdigest() == proof.get("sha256")
                and self.preparation_manifest(self.out / proof["path"], check=check) == json.loads(raw),
                "Original preparation pair changed")
        check()
        parsed = {}; hashes = {}
        for kind in ("summary", "tests"):
            raw = bounded_read(self.out, "files-prepare-" + kind + ".json", 16 * MIB, check)
            check()
            parsed[kind] = json.loads(raw); hashes[kind + "_sha256"] = hashlib.sha256(raw).hexdigest()
            check()
        validate_preparation_pair(parsed["summary"], parsed["tests"], self.owned,
                                  self.report.get("runtime_selection"))
        check()
        raw_log = self.preparation_log(check=check)
        check()
        order = checkpoint.preparation_order(raw_log)
        check()
        require(order == self.report.get("files_preparation_order"), "First preparation order or bytes changed")
        return {"order": order, "original_manifest_sha256": proof["sha256"], **hashes}

    def prepare_files_ui(self):
        require(self.mode == "batch" and self.preparation_calls == 0, "Files preparation may run once in batch mode")
        require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline
                and self.intent is not None, "Files preparation requires an owned device")
        require(not self.commands.active and not self.commands.unknown_spawn
                and not self.xcode.active and not self.xcode.unknown_spawn,
                "Files preparation writer ownership unresolved")
        phase_seconds = 1200 if self.profile["name"] == "intel-batch" else PREPARE_SECONDS
        require(time.monotonic() + phase_seconds + MODES["batch"][1] + 120 < self.work_deadline,
                "Insufficient Files preparation and full driver budget")
        self.preparation_calls += 1
        # This owned preparation build supplies the verified seed/main products.
        # Intel reserves 720s overhead plus the existing 300s/180s native cases.
        # Other profiles retain 780s; the original global deadline is unchanged.
        # Keep compiler intermediates outside the evidence upload glob.
        derived = self.root / "build" / ("QualificationPreparationDerivedData-" + self.job["GITHUB_RUN_ID"]
                                          + "-" + self.job["GITHUB_RUN_ATTEMPT"])
        require(not derived.exists() and not derived.is_symlink(), "Files preparation output already exists")
        preparation_token = str(uuid.uuid4())
        folder = "TripDocket-Batch-Prepare-" + preparation_token
        self.report["files_preparation"] = {"calls": self.preparation_calls, "cases": list(checkpoint.PREPARATION_CASES),
            "hosted_case_seconds": 300,
            "phase_seconds": phase_seconds, "case_seconds": recovery.PREPARE_CASE_SECONDS, "absent_folder_probe": folder,
            "fixture_token": preparation_token, "ingress": "direct-native-export-no-save",
            "derived_data": str(derived.relative_to(self.root)), "shared_build": False}
        argv = ["xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio", "-configuration", "Debug",
            "-destination", "platform=iOS Simulator,id=" + self.owned, "-destination-timeout", "30",
            "-parallel-testing-enabled", "NO", "-maximum-concurrent-test-simulator-destinations", "1",
            "-collect-test-diagnostics", "never", "-default-test-execution-time-allowance", "300",
            "-maximum-test-execution-time-allowance", "600", "-derivedDataPath", derived,
            "-resultBundlePath", self.out / "files-prepare.xcresult",
            *("-only-testing:" + case for case in checkpoint.PREPARATION_TESTS), "CODE_SIGNING_ALLOWED=NO", *self.build_settings, "test"]
        previous = self.commands.ops.env
        self.commands.ops.env = {**previous, "TEST_RUNNER_TRIPDOCKET_BATCH_PREPARE_UI": "1",
            "TEST_RUNNER_TRIPDOCKET_BATCH_PREPARE_TOKEN": preparation_token,
            "TEST_RUNNER_NSUnbufferedIO": "YES", "NSUnbufferedIO": "YES"}
        failure = None
        try:
            self.command("files-prepare-ui", argv, phase_seconds)
        except BaseException as error:
            failure = error
        finally:
            self.commands.ops.env = previous
        try:
            require(not self.commands.active and not self.commands.unknown_spawn
                    and not self.xcode.active and not self.xcode.unknown_spawn,
                    "Files preparation writer ownership unresolved")
            self.inspect_files_preparation()
        except BaseException as error:
            self.report["files_preparation_inspection_error"] = repr(error)
            if failure is None: failure = error
        if failure is not None: raise failure
        self.report["files_preparation_verified"] = True
        self.save()

    def verify_owned(self, devices):
        require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline,
                "No exclusive device ownership")
        require(self.owned in devices and all(devices[self.owned][key] == self.intent[key]
                for key in ("runtime", "name", "type")), "Owned device identity changed")

    def native_folder_leaf(self, driver, *, absent=False):
        """Check only the exact intended leaf below its pinned provider."""
        owned = driver.native_folder_destination
        require(owned is not None and driver.fixture_directory is None
                and str(uuid.UUID(driver.token)) == driver.token
                and owned.name == driver.folder_name == "TripDocket-Batch-QA-" + driver.token,
                "Invalid native folder intent")
        provider = owned.parent
        self.container_path(str(provider.parent), "Shared", "AppGroup")
        require(provider.name == "File Provider Storage", "Invalid native folder provider")
        with_fd = os.open(provider, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            def provider_matches():
                current = provider.lstat()
                opened = os.fstat(with_fd)
                return stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == driver.provider_identity \
                    and (opened.st_dev, opened.st_ino) == driver.provider_identity
            require(provider_matches(), "Native folder provider identity changed")
            try:
                entry = os.stat(owned.name, dir_fd=with_fd, follow_symlinks=False)
            except FileNotFoundError:
                require(absent, "Native folder was not created")
                require(provider_matches(), "Native folder provider changed during absence check")
                return None
            require(not absent, "Native folder intent already exists")
            require(stat.S_ISDIR(entry.st_mode), "Native folder is not a regular directory")
            leaf = os.open(owned.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=with_fd)
            try:
                opened = os.fstat(leaf)
                identity = (entry.st_dev, entry.st_ino)
                require((opened.st_dev, opened.st_ino) == identity, "Native folder changed while opening")
                with os.scandir(leaf) as entries:
                    require(next(entries, None) is None, "Native folder is not empty")
                current = os.stat(owned.name, dir_fd=with_fd, follow_symlinks=False)
                require(stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == identity
                        and provider_matches(), "Native folder identity changed during verification")
                return identity
            finally:
                os.close(leaf)
        finally:
            os.close(with_fd)

    def prepare_native_folder(self, driver):
        require(self.mode == "batch" and "native_folder" not in self.report
                and self.report.get("files_preparation_verified") is True,
                "Native folder requires one verified Files preparation")
        require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline,
                "Native folder requires exclusive device ownership")
        require(not self.commands.active and not self.commands.unknown_spawn
                and not self.xcode.active and not self.xcode.unknown_spawn, "Native folder writer unresolved")
        require(driver.remaining() > FOLDER_SECONDS + SEED_SECONDS + 600 + 8
                and time.monotonic() + FOLDER_SECONDS + SEED_SECONDS + 600 + 120 < self.work_deadline,
                "Insufficient native folder, seed and main driver budget")
        self.native_folder_leaf(driver, absent=True)
        derived = self.root / self.report["files_preparation"]["derived_data"]
        expected = self.root / "build" / ("QualificationPreparationDerivedData-" + self.job["GITHUB_RUN_ID"]
                                          + "-" + self.job["GITHUB_RUN_ATTEMPT"])
        require(derived == expected and derived.is_dir() and derived.resolve(strict=True) == derived,
                "Invalid shared native folder build")
        preparation_token = self.report["files_preparation"].get("fixture_token")
        require(isinstance(preparation_token, str)
                and str(uuid.UUID(preparation_token)) == preparation_token
                and preparation_token != driver.token,
                "Native folder requires a distinct canonical first preparation token")
        source_token = str(uuid.uuid4())
        require(source_token not in (preparation_token, driver.token),
                "Native folder source token collided with another phase")
        overrides = {"TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_UI": "1",
                     "TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_TOKEN": driver.token,
                     "TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN": source_token,
                     "TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER": driver.folder_name,
                     "TEST_RUNNER_NSUnbufferedIO": "YES", "NSUnbufferedIO": "YES"}
        self.report["native_folder"] = {"calls": 1, "case": FOLDER_CASE, "phase_seconds": FOLDER_SECONDS,
            "case_seconds": FOLDER_CASE_SECONDS, "token": driver.token, "source_token": source_token,
            "absent_before": True, "environment_overrides": dict(overrides),
            "destination": str(driver.native_folder_destination), "provider_identity": list(driver.provider_identity),
            "ingress": "native New Folder", "adopted": False,
            "driver_deadline": driver.deadline - self.started, "driver_remaining_before": driver.remaining(),
            "partial_leaf_cleanup": "unadopted leaf retained for exclusive owned Simulator teardown"}
        self.save()
        argv = ["xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio", "-configuration", "Debug",
            "-destination", "platform=iOS Simulator,id=" + self.owned, "-destination-timeout", "30",
            "-parallel-testing-enabled", "NO", "-maximum-concurrent-test-simulator-destinations", "1",
            "-collect-test-diagnostics", "never", "-default-test-execution-time-allowance", str(FOLDER_CASE_SECONDS),
            "-maximum-test-execution-time-allowance", str(FOLDER_CASE_SECONDS), "-derivedDataPath", derived,
            "-resultBundlePath", self.out / "native-folder.xcresult",
            "-only-testing:TripfolioUITests/" + FOLDER_CASE.removesuffix("()"), "CODE_SIGNING_ALLOWED=NO",
            *self.build_settings, "test"]
        previous = self.commands.ops.env
        self.commands.ops.env = {**previous, **overrides}
        failure = None
        try:
            self.command("native-folder-ui", argv, min(FOLDER_SECONDS, driver.remaining()))
        except BaseException as error:
            failure = error
        finally:
            self.commands.ops.env = previous
            self.report["native_folder"]["driver_remaining_after"] = max(0, driver.deadline - time.monotonic())
        try:
            require(not self.commands.active and not self.commands.unknown_spawn
                    and not self.xcode.active and not self.xcode.unknown_spawn, "Native folder writer unresolved")
            self.inspect_files_preparation(native_folder=True)
            if failure is None:
                identity = self.native_folder_leaf(driver)
                driver.fixture_identity = identity
                driver.fixture_directory = driver.native_folder_destination
                self.report["native_folder"].update(adopted=True, empty_after=True, leaf_identity=list(identity))
        except BaseException as error:
            self.report["native_folder_inspection_error"] = repr(error)
            if failure is None: failure = error
        if failure is not None: raise failure
        self.report["native_folder_verified"] = True
        driver.record("native_created_empty_owned_folder", path=str(driver.fixture_directory))
        self.save()

    def native_seed_files(self, driver, *, empty=False):
        """Verify the exclusive destination; never create provider file bytes."""
        preparation = self.report.get("files_preparation", {})
        token = preparation.get("fixture_token")
        require(isinstance(token, str) and str(uuid.UUID(token)) == token and token != driver.token
                and preparation.get("absent_folder_probe") == "TripDocket-Batch-Prepare-" + token
                and preparation.get("ingress") == "direct-native-export-no-save",
                "Native seed requires a distinct recorded direct preparation token")
        owned = driver.fixture_directory
        root_mode = getattr(getattr(driver, "args", None), "native_root", False)
        require(owned is not None and str(uuid.UUID(driver.token)) == driver.token
                and driver.folder_name == "TripDocket-Batch-QA-" + driver.token,
                "Invalid native seed destination")
        if root_mode:
            require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline
                    and driver.args.device == self.owned and getattr(driver.args, "native_seed", False)
                    and not getattr(driver.args, "native_folder", False)
                    and owned == driver.native_root_provider, "Native root lacks exclusive device ownership")
            driver.native_root_identity()
            provider = owned
        else:
            require(owned.name == "TripDocket-Batch-QA-" + driver.token, "Invalid native seed folder")
            provider = owned.parent
        self.container_path(str(provider.parent), "Shared", "AppGroup")
        def identity(path):
            value = path.lstat()
            require(stat.S_ISDIR(value.st_mode), "Native seed parent is not a regular directory")
            return value.st_dev, value.st_ino
        require(provider.name == "File Provider Storage"
                and identity(provider) == driver.provider_identity
                and identity(owned) == driver.fixture_identity,
                "Native seed directory identity changed")
        names = []
        with os.scandir(owned) as entries:
            for entry in entries:
                self.check(); names.append(entry.name)
                require(len(names) <= 2, "Unexpected native seed destination entries")
        fixtures = driver.summary["fixtures"]
        require(len(fixtures) == 2 and {entry["name"] for entry in fixtures}
                == {"synthetic-ticket.pdf", "synthetic-insurance.pdf"}, "Unexpected native seed fixtures")
        require(set(names) == (set() if empty else {entry["name"] for entry in fixtures}),
                "Native seed destination must contain the exact expected files")
        for entry in fixtures:
            source = bounded_read(driver.directory, "fixtures/" + entry["name"], 1024, self.check)
            require(len(source) == entry["bytes"] and hashlib.sha256(source).hexdigest() == entry["sha256"],
                    "Native seed retained source changed")
            if not empty:
                require(bounded_read(owned, entry["name"], 1024, self.check) == source,
                        "Native Save to Files changed original bytes")
        require(identity(provider) == driver.provider_identity and identity(owned) == driver.fixture_identity,
                "Native seed directory changed during verification")
        if root_mode: driver.native_root_identity()

    def prepare_native_root(self, driver):
        """Pin a truly empty provider root on this qualification's new device."""
        require(self.mode == "batch" and "native_root" not in self.report
                and getattr(getattr(driver, "args", None), "native_root", False) is True
                and self.report.get("files_preparation_verified") is True,
                "Native root requires one verified Files preparation")
        require(not self.commands.active and not self.commands.unknown_spawn
                and not self.xcode.active and not self.xcode.unknown_spawn, "Native root writer unresolved")
        self.native_seed_files(driver, empty=True)
        self.report["native_root"] = {"verified_empty_before_seed": True,
            "device": self.owned, "provider": str(driver.fixture_directory),
            "provider_identity": list(driver.provider_identity),
            "group_identity": list(driver.native_root_group_identity),
            "cleanup": "deferred to exclusive owned Simulator teardown"}
        self.save()

    def prepare_shared_build(self, driver):
        require(self.mode == "batch"
                and (getattr(driver.args, "native_root", False)
                     or (self.native_folder_control and getattr(driver.args, "native_folder", False)
                         and self.report.get("native_folder_verified") is True))
                and self.report.get("files_preparation_verified") is True
                and not hasattr(self, "shared_products"), "Shared build requires one owned preparation")
        # Combined mode removes one invocation; five settings/container RPCs
        # surround it. The checkpoint is inside the unchanged main600 allowance.
        admission = (SEED_SECONDS + 600 + 5 * 38 + 8 if getattr(driver.args, "combined_batch", False)
                     else SEED_SECONDS + 600 + 7 * 38 + 8)
        require(driver.remaining() > admission,
                "Insufficient shared-build observation and native budget")
        derived = self.root / self.report["files_preparation"]["derived_data"]
        expected = self.root / "build" / ("QualificationPreparationDerivedData-" + self.job["GITHUB_RUN_ID"]
                                          + "-" + self.job["GITHUB_RUN_ATTEMPT"])
        require(derived == expected and derived.is_dir() and derived.resolve(strict=True) == derived,
                "Invalid shared preparation build")
        self.require_no_build_writer()
        # This query reads target metadata; it does not run tests or need a live device.
        # Actual preparation and test invocations still target the owned Simulator.
        argv = ["xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio", "-configuration", "Debug",
                "-destination", "generic/platform=iOS Simulator", "-derivedDataPath", derived,
                "CODE_SIGNING_ALLOWED=NO", *self.build_settings, "-showBuildSettings", "-json", "build-for-testing"]
        raw = self.shared_build_command(driver, "shared-build-settings", argv)
        self.shared_products = shared_product_paths(raw, derived, self.build_settings)
        (self.out / "shared-build-settings.json").write_text(raw)
        self.report["shared_build"] = {"derived_data": str(derived.relative_to(self.root)),
            "action": "test-without-building", "settings_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "products": {key: str(path.relative_to(self.root)) for key, path in self.shared_products.items()},
            "observations": {}}
        self.shared_derived_identity = (derived.stat().st_dev, derived.stat().st_ino)
        driver.qualified_build = derived
        driver.qualified_build_settings = self.build_settings
        driver.summary["qualified_build"] = self.report["shared_build"]["derived_data"]
        self.observe_shared_build(driver, "before_seed")

    def shared_build_command(self, driver, label, argv):
        seconds = min(30, driver.remaining() - 8)
        require(seconds > 0, "No bounded shared-build command budget")
        return self.command(label, argv, seconds)

    def require_no_build_writer(self):
        require(not self.commands.active and not self.commands.unknown_spawn
                and not self.xcode.active and not self.xcode.unknown_spawn, "Shared build writer unresolved")

    def observe_shared_build(self, driver, label):
        require(label in ("before_seed", "after_seed", "after_main", "final_after_failure")
                and label not in self.report["shared_build"]["observations"], "Invalid shared build observation")
        self.require_no_build_writer()
        def check():
            self.check()
            require(driver.remaining() > 0, "Shared build observation exceeded driver deadline")
        check()
        derived = driver.qualified_build
        require(derived.resolve(strict=True) == derived
                and (derived.stat().st_dev, derived.stat().st_ino) == self.shared_derived_identity,
                "Shared derived data identity changed")
        for path in self.shared_products.values():
            require(path.resolve(strict=True) == path and path.is_relative_to(derived), "Shared product path changed")
        products = {key: compiled_identity(path, check) for key, path in self.shared_products.items()}
        if hasattr(self, "shared_product_identity"):
            require(products == self.shared_product_identity, "Compiled products changed between phases")
        else:
            self.shared_product_identity = products
        installed = {}
        for kind in ("app", "data"):
            value = self.shared_build_command(driver, "shared-" + label + "-" + kind,
                ["xcrun", "simctl", "get_app_container", self.owned, APP_ID, kind]).strip()
            path = self.container_path(value, "Bundle" if kind == "app" else "Data", "Application")
            check(); info = path.lstat()
            installed[kind] = {"path": str(path), "identity": [info.st_dev, info.st_ino],
                               "mode": stat.S_IMODE(info.st_mode)}
            if kind == "app":
                identity = compiled_identity(path, check)
                require(identity["content"] == products["Tripfolio"]["content"],
                        "Installed app differs from shared compiled bytes")
                installed[kind]["manifest"] = identity
        record = {"products": products, "installed": installed,
                  "data_note": "Location only; synthetic library content intentionally changes during tests."}
        name = "shared-build-" + label + ".json"
        raw = json.dumps(record, sort_keys=True, indent=2) + "\n"
        (self.out / name).write_text(raw)
        self.report["shared_build"]["observations"][label] = {"path": name,
            "sha256": hashlib.sha256(raw.encode()).hexdigest()}
        self.save()

    def prepare_combined_batch(self, driver):
        folder = self.native_folder_control
        destination_verified = (
            getattr(driver.args, "native_folder", False)
            and not getattr(driver.args, "native_root", False)
            and self.report.get("native_folder_verified") is True
            and self.report.get("native_folder", {}).get("adopted") is True
            and self.report.get("native_folder", {}).get("empty_after") is True
        ) if folder else (
            getattr(driver.args, "native_root", False)
            and not getattr(driver.args, "native_folder", False)
            and self.report.get("native_root", {}).get("verified_empty_before_seed") is True
        )
        require(self.mode == "batch" and getattr(driver.args, "combined_batch", False)
                and "combined_batch" not in self.report and self.report.get("files_preparation_verified") is True
                and destination_verified,
                "Combined batch requires verified owned destination and preparation")
        self.require_no_build_writer()
        require(getattr(driver, "qualified_build", None)
                    == self.root / self.report.get("files_preparation", {}).get("derived_data", "")
                and "before_seed" in self.report.get("shared_build", {}).get("observations", {}),
                "Combined batch lacks verified shared products")
        require(driver.remaining() > SEED_SECONDS + 600 + 8,
                "Insufficient combined seed and main budget")
        def check():
            self.check()
            require(driver.remaining() > 0, "Original driver deadline expired during preparation verification")
        prerequisite = self.verify_preparation_prerequisite(check=check)
        self.native_seed_files(driver, empty=True)
        driver.combined_protocol = checkpoint
        driver.checkpoint_session = str(uuid.uuid4()).upper()
        driver.checkpoint_callback = lambda request, deadline: self.acknowledge_batch_seed(driver, request, deadline)
        self.report["combined_batch"] = {"session": driver.checkpoint_session, "token": driver.token,
            "cases": list(checkpoint.CASES), "preparation_cases": list(checkpoint.PREPARATION_CASES),
            "preparation_prerequisite": prerequisite, "result_bundles": 3 if folder else 2,
            "destination_mode": "native_folder" if folder else "native_root",
            "driver_deadline": driver.deadline - self.started, "driver_seconds": self.driver_budget(),
            "seed_case_seconds": 180, "seed_observed_envelope_seconds": 300,
            "seed_envelope_boundary": "combined invocation start to observed seed PASS",
            "main_case_seconds": 600, "checkpoint_seconds": 60,
            "checkpoint_position": "main entry after observed seed PASS and deferred AUT termination"}
        self.save()

    def acknowledge_batch_seed(self, driver, request, deadline):
        """One scoped auxiliary RPC group at a time while the owned primary waits."""
        primary = driver.process
        expected = {"session": driver.checkpoint_session, "token": driver.token,
                    "nonce": checkpoint.upper_uuid(request.get("nonce")), "line": request.get("line"),
                    "name": checkpoint.CHANNEL + "." + driver.checkpoint_session + "." + request.get("nonce"), "state": 1}
        require(request == expected and type(request["line"]) is int and request["line"] > 0,
                "Wrong checkpoint identity")
        require("batch_checkpoint" not in self.report and self.driver_calls == 1
                and driver.args.device == self.owned and self.owned not in self.baseline
                and driver.summary.get("combined_batch") is True,
                "Checkpoint is not exclusive or is repeated")
        end = min(deadline, driver.deadline, self.work_deadline)
        previous_limit = self.commands.limit
        def active():
            self.check()
            require(time.monotonic() < end and self.xcode.active == {primary.pid: primary}
                    and primary.poll() is None and not self.xcode.unknown_spawn
                    and not self.commands.unknown_spawn, "Checkpoint primary/clock changed")
        def idle():
            active(); require(not self.commands.active, "Checkpoint auxiliary writer unresolved")
        def command(label, argv):
            idle()
            seconds = min(10, end - time.monotonic() - 8)
            require(seconds > 0, "Insufficient checkpoint RPC stop reserve")
            raw = self.command(label, argv, seconds)
            idle(); return raw
        idle()
        prerequisite = self.verify_preparation_prerequisite(check=active)
        require(prerequisite == self.report.get("combined_batch", {}).get("preparation_prerequisite"),
                "Preparation prerequisite changed before checkpoint")
        self.report["batch_checkpoint"] = {"request": request, "status": "verifying",
            "preparation_prerequisite": prerequisite,
            "start": time.monotonic() - self.started, "deadline": end - self.started}
        self.commands.limit = min(previous_limit, end)
        try:
            # Query only the owned AUT. A producer PASS is insufficient by itself:
            # require its exact current executable absent from a complete ps output.
            raw = command("checkpoint-app", ["xcrun", "simctl", "get_app_container", self.owned, APP_ID, "app"])
            bundle = self.container_path(raw.strip(), "Bundle", "Application")
            require(bundle.name == "Tripfolio.app", "Wrong checkpoint app bundle")
            executable = bundle / "Tripfolio"
            require(stat.S_ISREG(executable.lstat().st_mode) and executable.resolve(strict=True) == executable,
                    "Invalid checkpoint app executable")
            listing = command("checkpoint-app-stopped", ["/bin/ps", "-axww", "-o", "pid=,command="])
            rows = [row for row in self.commands.report["commands"] if row["id"] == "checkpoint-app-stopped"]
            require(len(rows) == 1 and rows[0]["returncode"] == 0, "Unbound checkpoint process listing")
            reader = rows[0]["pgid"]; reader_seen = False
            owned_apps = Path.home() / "Library/Developer/CoreSimulator/Devices" / self.owned / "data/Containers/Bundle/Application"
            owned_executable = re.compile(re.escape(str(owned_apps))
                + r"/[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}/Tripfolio\.app/Tripfolio(?: |$)")
            require(listing.strip(), "Empty process listing")
            for line in listing.splitlines():
                active(); match = re.fullmatch(r"\s*([0-9]+)\s+(.*)", line)
                require(match is not None, "Malformed process listing")
                pid, cmd = int(match[1]), match[2]
                if pid == reader:
                    require(cmd.startswith("/bin/ps ") or cmd.startswith("ps "), "Wrong process reader")
                    reader_seen = True
                require(cmd != str(executable) and not cmd.startswith(str(executable) + " ")
                        and owned_executable.match(cmd) is None
                        and cmd != "Tripfolio" and not cmd.startswith("Tripfolio "), "AUT still running or ambiguous")
            require(reader_seen, "Process listing omitted its own reader")
            self.native_seed_files(driver)
            for name, identity in self.before["files"].items():
                active(); file = self.root / name; metadata = file.lstat()
                raw = bounded_read(self.root, name, 128 * MIB, active)
                require({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                         "executable": bool(metadata.st_mode & 0o111)} == identity,
                        "Source changed before seed ACK")
            idle()
            proof = self.report["batch_checkpoint"]
            proof.update(aut_stopped=True, app_bundle=str(bundle), source_unchanged=True,
                provider=str(driver.fixture_directory), provider_identity=list(driver.provider_identity),
                fixtures=[{key: item[key] for key in ("name", "bytes", "sha256")} for item in driver.summary["fixtures"]])
            if self.native_folder_control:
                proof.update(provider_root=str(driver.fixture_directory.parent),
                             fixture_identity=list(driver.fixture_identity))
            # Persist the completed byte/source/stopped-AUT proof before the
            # external ACK can release the consumer's destructive reset.
            self.save()
            command("checkpoint-ack", ["xcrun", "simctl", "notify_set_state", self.owned, request["name"], "1"])
            proof.update(status="acknowledged", finish=time.monotonic() - self.started)
            self.report["batch_checkpoint_verified"] = True
            self.save()
        finally:
            self.commands.limit = previous_limit

    def prepare_native_seed(self, driver):
        require(self.mode == "batch" and "native_seed" not in self.report
                and self.report.get("files_preparation_verified") is True
                and ((getattr(getattr(driver, "args", None), "native_root", False)
                      and self.report.get("native_root", {}).get("verified_empty_before_seed") is True)
                     or (not getattr(getattr(driver, "args", None), "native_root", False)
                         and self.report.get("native_folder_verified") is True)),
                "Native seed requires verified Files preparation and destination")
        require(self.owned is not None and self.baseline is not None and self.owned not in self.baseline,
                "Native seed requires exclusive device ownership")
        require(not self.commands.active and not self.commands.unknown_spawn
                and not self.xcode.active and not self.xcode.unknown_spawn, "Native seed writer unresolved")
        # Driver.__init__ already started its 1200s clock. The seed consumes it;
        # no fresh deadline is granted to either phase or to the main UI case.
        require(driver.remaining() > SEED_SECONDS + 600 + 8
                and time.monotonic() + SEED_SECONDS + 600 + 120 < self.work_deadline,
                "Insufficient native seed and main driver budget")
        self.native_seed_files(driver, empty=True)
        derived = self.root / self.report["files_preparation"]["derived_data"]
        expected = self.root / "build" / ("QualificationPreparationDerivedData-" + self.job["GITHUB_RUN_ID"]
                                          + "-" + self.job["GITHUB_RUN_ATTEMPT"])
        require(derived == expected and derived.is_dir() and derived.resolve(strict=True) == derived,
                "Invalid shared preparation build")
        require(getattr(driver, "qualified_build", None) == derived
                and "before_seed" in self.report.get("shared_build", {}).get("observations", {}),
                "Native seed lacks verified shared products")
        self.report["native_seed"] = {"calls": 1, "case": SEED_CASE, "phase_seconds": SEED_SECONDS,
            "case_seconds": SEED_CASE_SECONDS, "token": driver.token, "ingress": "native Save to Files",
            "driver_deadline": driver.deadline - self.started, "driver_remaining_before": driver.remaining(),
            "shared_derived_data": str(derived.relative_to(self.root)),
            "source_retention": "Exclusive synthetic app temporary directory removed with owned Simulator"}
        argv = ["xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio", "-configuration", "Debug",
            "-destination", "platform=iOS Simulator,id=" + self.owned, "-destination-timeout", "30",
            "-parallel-testing-enabled", "NO", "-maximum-concurrent-test-simulator-destinations", "1",
            "-collect-test-diagnostics", "never", "-default-test-execution-time-allowance", str(SEED_CASE_SECONDS),
            "-maximum-test-execution-time-allowance", str(SEED_CASE_SECONDS), "-derivedDataPath", derived,
            "-resultBundlePath", self.out / "native-seed.xcresult",
            "-only-testing:TripfolioUITests/" + SEED_CASE.removesuffix("()"), "CODE_SIGNING_ALLOWED=NO", "test-without-building"]
        previous = self.commands.ops.env
        self.commands.ops.env = {**previous, "TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_UI": "1",
            "TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_TOKEN": driver.token,
            "TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER": driver.folder_name,
            "TEST_RUNNER_NSUnbufferedIO": "YES", "NSUnbufferedIO": "YES"}
        if getattr(getattr(driver, "args", None), "native_root", False):
            self.commands.ops.env.update({"TEST_RUNNER_TRIPDOCKET_NATIVE_ROOT_UI": "1",
                                          "TEST_RUNNER_TRIPDOCKET_NATIVE_ROOT_TOKEN": driver.token})
        failure = None
        try:
            self.command("native-seed-ui", argv, min(SEED_SECONDS, driver.remaining()))
        except BaseException as error:
            failure = error
        finally:
            self.commands.ops.env = previous
            self.report["native_seed"]["driver_remaining_after"] = max(0, driver.deadline - time.monotonic())
        try:
            require(not self.commands.active and not self.commands.unknown_spawn
                    and not self.xcode.active and not self.xcode.unknown_spawn, "Native seed writer unresolved")
            self.inspect_files_preparation(native_seed=True)
            self.native_seed_files(driver)
        except BaseException as error:
            self.report["native_seed_inspection_error"] = repr(error)
            if failure is None: failure = error
        if failure is not None: raise failure
        self.observe_shared_build(driver, "after_seed")
        self.report["native_seed_verified"] = True
        self.report["native_seed"]["destination_fixtures"] = [
            {key: item[key] for key in ("name", "bytes", "sha256")} for item in driver.summary["fixtures"]]
        driver.record("native_saved_provider_root" if getattr(getattr(driver, "args", None), "native_root", False)
                      else "native_saved_owned_folder", fixtures=driver.summary["fixtures"])
        self.save()

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
            # The first post-boot inventory can outlast 30 seconds. Match the
            # existing inventory budget only for this exact read-only command;
            # the caller's shorter timeout and shared work deadline still apply.
            cap = 120 if tuple(argv) == ("xcrun", "simctl", "list", "devices", "--json") else 30
            output = self.command("driver-command-" + str(len(self.commands.report["commands"])), argv, min(timeout, cap))
            return subprocess.CompletedProcess(argv, 0, output if text else output.encode(), "" if text else b"")
        def popen(argv, **kwargs):
            require(self.driver_calls == 0 and argv[0] == "xcodebuild"
                    and kwargs.get("start_new_session") is True and Path(kwargs["cwd"]).resolve() == self.root,
                    "Driver may launch exactly one owned xcodebuild")
            require("platform=iOS Simulator,id=" + self.owned in argv,
                    "Driver selected another destination")
            require([arg for arg in argv if isinstance(arg, str) and arg.startswith(
                ("EXCLUDED_SOURCE_FILE_NAMES=", "INCLUDED_SOURCE_FILE_NAMES="))] == list(self.build_settings),
                "Driver changed the qualified build settings")
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

    def driver_budget(self):
        # The diagnostic adds a separate native folder invocation. Allocate its
        # existing envelope before constructing the driver; never renew its clock.
        return MODES[self.mode][1] + (FOLDER_SECONDS if self.native_folder_control else 0)

    def run_driver(self):
        filename = MODES[self.mode][0]
        timeout = self.driver_budget()
        require(time.monotonic() + timeout + 120 < self.work_deadline, "Insufficient full driver/postcheck budget")
        module = load_module(HERE / filename, "qualification_" + self.mode)
        module.subprocess = self.facade()
        args = SimpleNamespace(device=self.owned, timeout=timeout, only_test=None,
                               native_seed=self.mode == "batch", native_folder=self.native_folder_control,
                               native_root=self.mode == "batch" and not self.native_folder_control,
                               combined_batch=self.mode == "batch")
        driver = module.Driver(args); failure = None
        self.report["driver_directory"] = str(driver.directory.relative_to(self.root))
        try:
            driver.prepare()
            if self.mode == "batch":
                if self.native_folder_control:
                    self.prepare_native_folder(driver)
                else:
                    self.prepare_native_root(driver)
                self.prepare_shared_build(driver)
                self.prepare_combined_batch(driver)
            remaining = driver.remaining() if self.mode == "batch" else timeout
            require(time.monotonic() + remaining + 8 < self.work_deadline,
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
                if self.mode == "batch" and hasattr(self, "shared_products"):
                    try:
                        label = "after_main" if self.xcode.report["commands"] else "final_after_failure"
                        self.observe_shared_build(driver, label)
                    except BaseException as error:
                        self.report.setdefault("shared_build_errors", []).append(repr(error))
                        failure = failure or error
                try:
                    if self.mode == "batch":
                        if driver.fixture_directory is not None:
                            driver.verify_fixtures()
                            if getattr(getattr(driver, "args", None), "native_root", False):
                                # Recheck the complete directory, not just the two
                                # expected files, after the last native writer stops.
                                self.native_seed_files(driver)
                                if failure is None:
                                    driver.summary["native_root_post_main_verified"] = True
                                    self.report["native_root"]["verified_after_main"] = True
                            elif self.native_folder_control:
                                self.native_seed_files(driver)
                                if failure is None:
                                    driver.summary["native_folder_post_main_verified"] = True
                                    self.report["native_folder"]["verified_after_main"] = True
                            driver.remove_fixtures()
                            if self.native_folder_control:
                                cleanup = driver.summary.get("native_folder_cleanup", {})
                                require(cleanup == {"leaf_absent": True,
                                                   "provider_identity": list(driver.provider_identity)},
                                        "Native folder cleanup proof is incomplete")
                                self.report["native_folder"]["cleanup"] = dict(cleanup)
                        else:
                            driver.summary["fixture_cleanup"] = "Unadopted native folder intent; owned Simulator teardown only"
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
        expected = list(driver.expected_cases) if self.mode == "batch" else ["PrivacyTransitionUITests/" + name + "()" for name in module.EXPECTED_METHODS]
        tree = json.loads(bounded_read(driver.directory, "xcresult-tests.json", 16 * MIB, self.check))
        validate_driver(self.mode, driver.summary, result, tree, expected, self.owned, self.job["GITHUB_SHA"])
        if self.native_folder_control:
            require(driver.summary.get("native_folder_post_main_verified") is True,
                    "Native folder originals not verified after main flow")
        validate_runtime_result(self.mode, self.report.get("runtime_selection"), result)
        if self.mode == "batch":
            order = checkpoint.execution_order(bounded_read(driver.directory, "xcodebuild.log", 16 * MIB, self.check),
                                               driver.checkpoint_session, driver.token)
            require(order == driver.summary.get("execution_order")
                    and self.report.get("batch_checkpoint_verified") is True
                    and order["request"] == self.report["batch_checkpoint"]["request"],
                    "Combined checkpoint/order proof mismatch")
            monitor = driver.summary.get("combined_monitor", {})
            elapsed = monitor.get("seed_observed_seconds")
            require(monitor.get("returncode") == 0 and type(elapsed) in (int, float)
                    and 0 <= elapsed <= 300 and monitor.get("seed_envelope_seconds") == 300
                    and monitor.get("seed_envelope_boundary") == "combined invocation start to observed seed PASS",
                    "Missing combined seed-envelope evidence")
            self.report["batch_execution_order"] = order
            self.report["combined_monitor"] = monitor
        self.products(driver)
        if self.mode == "batch": self.batch_snapshot(driver)
        self.report["driver_capture_verified"] = True
        self.report["selected_cases"] = (
            [*checkpoint.PREPARATION_CASES, FOLDER_CASE, *expected] if self.native_folder_control
            else [checkpoint.PREPARATION_CASES[0], *expected] if self.mode == "batch" else expected)

    def products(self, driver):
        if self.mode == "batch" and hasattr(self, "shared_products"):
            app = self.shared_products["Tripfolio"]
            runner = self.shared_products["TripfolioUITestsRunner"]
        else:
            derived = driver.directory / "DerivedData" if self.mode == "batch" else self.root / "build/DerivedData"
            directory = derived / "Build/Products/Debug-iphonesimulator"
            runners = list(directory.glob("*-Runner.app")); require(len(runners) == 1, "Ambiguous built test runner")
            app, runner = directory / "Tripfolio.app", runners[0]
        manifests = {}
        for identifier, built in ((APP_ID, app), (RUNNER_ID, runner)):
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
        if self.mode == "batch":
            root = self.report.get("native_root")
            if root is not None:
                require(root.get("verified_empty_before_seed") is True
                        and root.get("verified_after_main") is True and root.get("device") == self.owned
                        and self.baseline is not None and self.owned not in self.baseline
                        and self.report.get("final_inventory") == self.baseline,
                        "Native root lacks original-byte or owned-device cleanup proof")
                if "combined_batch" in self.report:
                    prerequisite = self.verify_preparation_prerequisite()
                    require(prerequisite == self.report["combined_batch"].get("preparation_prerequisite")
                            == self.report.get("batch_checkpoint", {}).get("preparation_prerequisite"),
                            "Preparation prerequisite changed before final capture")
                    require(self.report["combined_batch"].get("preparation_cases") == list(checkpoint.PREPARATION_CASES),
                            "Combined capture lacks first preparation pair")
                    require(self.report.get("batch_checkpoint_verified") is True
                            and self.report["combined_batch"].get("result_bundles") == 2
                            and self.report["combined_batch"].get("cases") == list(checkpoint.CASES)
                            and self.report.get("batch_execution_order", {}).get("request")
                                == self.report.get("batch_checkpoint", {}).get("request"),
                            "Combined capture lacks verified checkpoint and exact two UI cases")
                    require(not any(key.startswith("native_seed") or key.startswith("native_folder")
                                    for key in self.report)
                            and not (self.out / "native-seed.xcresult").exists()
                            and not (self.out / "native-folder.xcresult").exists(),
                            "Combined capture cannot claim separate seed/folder result bundles")
                    prerequisites = (("files_preparation", "files-prepare"),)
                else:
                    prerequisites = (("files_preparation", "files-prepare"), ("native_seed", "native-seed"))
            elif self.native_folder_control and "combined_batch" in self.report:
                folder = self.report.get("native_folder", {})
                require(self.report.get("native_folder_verified") is True
                        and folder.get("adopted") is True and folder.get("empty_after") is True
                        and folder.get("verified_after_main") is True
                        and folder.get("cleanup") == {"leaf_absent": True,
                                                      "provider_identity": folder.get("provider_identity")}
                        and self.baseline is not None and self.owned not in self.baseline
                        and self.report.get("final_inventory") == self.baseline,
                        "Native folder lacks original-byte or owned-device cleanup proof")
                prerequisite = self.verify_preparation_prerequisite()
                combined = self.report["combined_batch"]
                require(prerequisite == combined.get("preparation_prerequisite")
                        == self.report.get("batch_checkpoint", {}).get("preparation_prerequisite")
                        and combined.get("preparation_cases") == list(checkpoint.PREPARATION_CASES)
                        and combined.get("destination_mode") == "native_folder"
                        and combined.get("result_bundles") == 3
                        and combined.get("cases") == list(checkpoint.CASES)
                        and self.report.get("batch_checkpoint_verified") is True
                        and self.report.get("batch_execution_order", {}).get("request")
                            == self.report.get("batch_checkpoint", {}).get("request"),
                        "Combined folder capture lacks exact prerequisite/checkpoint proof")
                require(not any(key.startswith("native_seed") for key in self.report)
                        and not (self.out / "native-seed.xcresult").exists(),
                        "Combined folder capture cannot claim a separate seed result bundle")
                prerequisites = (("files_preparation", "files-prepare"), ("native_folder", "native-folder"))
            else:
                prerequisites = (("files_preparation", "files-prepare"), ("native_folder", "native-folder"),
                                 ("native_seed", "native-seed"))
            for key, prefix in prerequisites:
                proof = self.report.get(key + "_original", {})
                require(self.report.get(key + "_verified") is True
                        and proof.get("path") == prefix + ".xcresult"
                        and proof.get("manifest") == prefix + "-original-manifest.json"
                        and proof.get("unchanged_after_reader") is True,
                        "Missing verified Files preparation, native folder or native seed")
                raw = bounded_read(self.out, proof["manifest"], 16 * MIB, self.check)
                require(hashlib.sha256(raw).hexdigest() == proof.get("sha256")
                        and self.preparation_manifest(self.out / proof["path"]) == json.loads(raw),
                        "Original Files preparation or seed result changed before final capture")
                proof["unchanged_after_cleanup"] = True
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
                             and (self.mode != "batch" or (self.report.get("batch_snapshot", {}).get("verified")
                                  and self.report.get("files_preparation_verified") is True
                                  and self.report.get("batch_checkpoint_verified") is True
                                  and self.report.get("combined_batch", {}).get("result_bundles")
                                      == (3 if self.native_folder_control else 2))))
            if capture_ready:
                try: self.capture_original_result()
                except BaseException as error: self.report["errors"].append("Original result capture: " + repr(error))
            self.report["status"] = ("captured_pending_review" if capture_ready and not self.report["errors"]
                                     and self.report.get("original_xcresult") else "failed")
            if self.native_reopen_control and self.report["status"] == "captured_pending_review":
                self.report["status"] = "diagnostic_captured_pending_review"
            self.save()
        return 0 if self.report["status"] in {"captured_pending_review", "diagnostic_captured_pending_review"} else 1


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
