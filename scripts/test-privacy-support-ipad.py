#!/usr/bin/env python3
"""One selected guidance locale on one fresh owned iPad. No retries or purchases."""
import argparse
import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid


CASES = (
    ("en-US", "testEnglishFreeGuidanceAndCancelledLinks", "large", 600),
    ("ru-RU", "testRussianMaximumTypeFreeGuidanceAndCancelledLinks", "accessibility-extra-extra-extra-large", 570),
)
BUNDLE_ID = "com.4alvit.tripfolio"
WORK_SECONDS = 24 * 60
CLEANUP_SECONDS = 3 * 60
# Existing command waits + each owned7s stop;30s for local manifests/copy/validation.
CASE_PREP_SECONDS = (60 + 7) + (60 + 7) + (30 + 7) + (30 + 7)
CASE_POST_SECONDS = (60 + 7) + (30 + 7) + (30 + 7) + 30


def selected_case(locale):
    matches = [case for case in CASES if case[0] == locale]
    require(len(matches) == 1, "Exactly one supported locale is required")
    return matches[0]


def require(value, message):
    if not value:
        raise RuntimeError(message)


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_entry(path, relative, checkpoint):
    checkpoint()
    before = path.lstat()
    entry = {"path": relative, "mode": stat.S_IMODE(before.st_mode)}
    if stat.S_ISLNK(before.st_mode):
        entry.update(kind="symlink", target=os.readlink(path))
    elif stat.S_ISDIR(before.st_mode):
        entry.update(kind="directory")
    else:
        require(stat.S_ISREG(before.st_mode), "Unsupported file type: " + str(path))
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checkpoint()
                digest.update(chunk)
        after = path.lstat()
        require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode) ==
                (after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode), "File changed while hashing: " + str(path))
        entry.update(kind="file", bytes=before.st_size, sha256=digest.hexdigest())
    return entry


def tree_manifest(path, checkpoint=lambda: None):
    """Include all files, symlinks and modes; never follow directory symlinks."""
    path = Path(path)
    require(path.exists() and not path.is_symlink(), "Missing or symlinked manifest root: " + str(path))
    entries = []

    def visit(current, relative):
        entry = file_entry(current, relative, checkpoint)
        entries.append(entry)
        if entry["kind"] == "directory":
            for child in sorted(current.iterdir()):
                visit(child, child.name if relative == "." else relative + "/" + child.name)

    visit(path, ".")
    return {"entries": entries, "sha256": canonical_digest(entries)}


def payload(manifest):
    """Installed payload comparison uses exact path/type/bytes/link targets, not OS modes."""
    return [{key: value for key, value in entry.items() if key != "mode"}
            for entry in manifest["entries"] if entry["kind"] != "directory"]


def choose_pair(runtimes, device_types, architecture):
    available_types = {item["identifier"]: item for item in device_types["devicetypes"]}
    candidates = []
    for runtime in runtimes["runtimes"]:
        if not runtime.get("isAvailable") or ".iOS-" not in runtime.get("identifier", ""):
            continue
        version = tuple(int(v) for v in re.findall(r"\d+", runtime["version"]))
        if version < (17,) or architecture not in runtime.get("supportedArchitectures", []):
            continue
        # Use the runtime's explicit compatibility list, never a guessed name/OS pair.
        for supported in runtime.get("supportedDeviceTypes", []):
            identifier = supported.get("identifier")
            dtype = available_types.get(identifier)
            if not dtype or dtype.get("productFamily") != "iPad":
                continue
            name = dtype["name"]
            key = (version, "13-inch" in name, "Pro" in name, identifier)
            candidates.append((key, {"runtime": runtime["identifier"], "os_version": runtime["version"],
                                     "os_build": runtime.get("buildversion"), "device_type": identifier,
                                     "device_name": name, "architecture": architecture}))
    require(candidates, "No explicitly compatible available iOS 17+ runtime/iPad pair for this architecture")
    return max(candidates, key=lambda candidate: candidate[0])[1]


def devices(inventory):
    require(isinstance(inventory.get("devices"), dict), "Invalid simulator inventory")
    return [(runtime, device) for runtime, items in inventory["devices"].items() for device in items]


def recover_owned(inventory, intent, baseline):
    matches = [device for runtime, device in devices(inventory)
               if runtime == intent["runtime"] and device.get("name") == intent["name"]
               and device.get("deviceTypeIdentifier") == intent["device_type"]
               and device.get("udid", "").upper() not in baseline]
    require(len(matches) <= 1, "Ambiguous create outcome; refusing to delete multiple devices")
    return str(uuid.UUID(matches[0]["udid"])).upper() if matches else None


def validate_result(summary, tree, method, udid):
    expected = "PrivacySupportUITests/" + method + "()"
    counts = {"totalTestCount": 1, "passedTests": 1, "failedTests": 0, "skippedTests": 0, "expectedFailures": 0}
    require(summary.get("result") == "Passed" and all(type(summary.get(k)) is int and summary[k] == v
            for k, v in counts.items()), "Expected exactly one passing case, no skips or expected failures")
    require(isinstance(tree.get("testNodes"), list) and isinstance(tree.get("devices"), list), "Invalid test tree")
    cases, pending = [], list(tree["testNodes"])
    while pending:
        node = pending.pop()
        require(isinstance(node, dict) and isinstance(node.get("children", []), list), "Invalid test node")
        pending.extend(node.get("children", []))
        if node.get("nodeType") == "Test Case":
            cases.append({"identifier": node.get("nodeIdentifier"), "result": node.get("result")})
    require(cases == [{"identifier": expected, "result": "Passed"}], "Executed case differs from exact requested case")
    require(len(tree["devices"]) == 1 and tree["devices"][0].get("deviceId", "").upper() == udid
            and tree["devices"][0].get("platform") == "iOS Simulator", "Test tree device mismatch")
    configs = summary.get("devicesAndConfigurations", [])
    require(len(configs) == 1 and configs[0].get("device", {}).get("deviceId", "").upper() == udid
            and configs[0]["device"].get("platform") == "iOS Simulator", "Test summary device mismatch")
    return {"counts": counts, "cases": cases, "device": configs[0]["device"]}


class Driver:
    def __init__(self, root, locale):
        self.case = selected_case(locale)
        self.root = Path(root).resolve()
        self.out = self.root / "build/PrivacySupport-iPad" / locale
        self.out.mkdir(parents=True)  # Refuse to overwrite another run's evidence.
        self.derived = self.root / ("build/PrivacySupport-iPad-DerivedData-" + locale)
        require(not self.derived.exists(), "DerivedData must be fresh; no build reuse")
        self.start = time.monotonic()
        self.work_deadline = self.start + WORK_SECONDS
        self.final_deadline = self.work_deadline + CLEANUP_SECONDS
        self.cleaning = False
        self.active = {}
        self.confirmed_absent_groups = set()
        self.owned = None
        self.intent = None
        self.baseline = set()
        self.acquiring = False
        self.registering_process = False
        self.pending_signal = None
        self.source_before = None
        self.built = None
        self.products = None
        self.originals = {}
        self.report = {"status": "running", "started_at": self.now(), "commands": [], "cases": [],
                       "work_seconds": WORK_SECONDS, "cleanup_reserve_seconds": CLEANUP_SECONDS,
                       "selected_locale": locale, "requested_method": self.case[1], "expected_case_count": 1,
                       "cleanup": {"verified": False}, "errors": []}
        self.save()

    @staticmethod
    def now():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def save(self):
        self.write("run-summary.json", self.report)

    def write(self, name, data):
        target = self.out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def checkpoint(self):
        limit = self.final_deadline if self.cleaning else self.work_deadline
        require(time.monotonic() < limit, "Cleanup deadline expired" if self.cleaning else "Work deadline expired; cleanup reserve preserved")

    def signal(self, signum, _frame):
        if self.acquiring or self.registering_process:
            # Python-level deferral does not change the child's signal mask.
            self.pending_signal = self.pending_signal or signum
        else:
            raise InterruptedError("Signal " + str(signum))

    def deliver_deferred_signal(self):
        if self.pending_signal and not (self.acquiring or self.registering_process or self.cleaning):
            signum, self.pending_signal = self.pending_signal, None
            raise InterruptedError("Deferred signal " + str(signum))

    def stop(self, process):
        # Only handles registered immediately after our start_new_session spawn.
        # An exited leader is not proof that its descendants have stopped writing.
        require(process.pid > 0 and self.active.get(process.pid) is process, "Refusing to stop an unowned process group")
        limit = self.final_deadline if self.cleaning else self.work_deadline
        deadline = min(limit, time.monotonic() + 7)
        record = {"owned_process_group": process.pid, "started_at": self.now(), "signals": [], "group_absent": False,
                  "deadline_monotonic": deadline, "observations": {}}
        self.report.setdefault("process_stops", []).append(record)
        confirmed_stopped = False

        def observed(operation, call):
            # Four fixed slots; observe existing calls without adding probes.
            started = time.monotonic()
            require(started < deadline, "Owned process stop deadline expired")
            slot = record["observations"].setdefault(operation, {"calls": 0, "first_start": started})
            slot.update(calls=slot["calls"] + 1, last_start=started, operation=operation)
            try:
                value = call()
                slot.update(outcome="returned", result=value)
                slot.pop("exception_type", None)
                slot.pop("errno", None)
                return value
            except BaseException as error:
                slot.update(outcome="raised", exception_type=type(error).__name__, errno=getattr(error, "errno", None))
                slot.pop("result", None)
                raise
            finally:
                slot["last_finish"] = time.monotonic()
                slot["last_duration_seconds"] = slot["last_finish"] - started

        def group_absent():
            if process.pid in self.confirmed_absent_groups:
                return True  # Never signal that numeric PGID again without a new spawn.
            try:
                observed("group_probe", lambda: os.killpg(process.pid, 0))
            except ProcessLookupError as error:
                if error.errno != errno.ESRCH:
                    raise
                self.confirmed_absent_groups.add(process.pid)
                return True
            return False  # Permission errors remain failures, never proof of absence.

        def stopped():
            nonlocal confirmed_stopped
            if confirmed_stopped:
                return True
            leader_exited = observed("poll", process.poll) is not None  # Reap our child when possible.
            record["leader_returncode"] = process.returncode
            record["group_absent"] = group_absent()
            confirmed_stopped = leader_exited and record["group_absent"]
            return confirmed_stopped

        # Keep 5s TERM + 2s KILL inside this phase's existing global budget.
        failure = None
        try:
            if not stopped():
                for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 2)):
                    if not record["group_absent"]:
                        try:
                            observed("signal_" + str(int(sig)), lambda: os.killpg(process.pid, sig))
                            record["signals"].append(int(sig))
                        except ProcessLookupError as error:
                            if error.errno != errno.ESRCH:
                                raise
                            self.confirmed_absent_groups.add(process.pid)
                    phase_end = min(deadline, time.monotonic() + wait)
                    while not stopped() and time.monotonic() < phase_end:
                        time.sleep(min(0.05, max(0, phase_end - time.monotonic())))
                    if stopped():
                        break
            require(stopped(), "Owned process group disappearance not confirmed after SIGKILL")
            self.active.pop(process.pid)  # Retain the handle on any unconfirmed stop.
        except BaseException as error:
            failure = error
            record["error"] = repr(error)
            raise
        finally:
            record["finished_at"] = self.now()
            try:
                self.save()
            except BaseException as error:
                record["finalization_error"] = repr(error)
                if failure is None:
                    raise

    def command(self, argv, label, timeout=30, check=True, stream=False, required_after=0):
        limit = self.final_deadline if self.cleaning else self.work_deadline
        deadline = min(limit - 7, time.monotonic() + timeout)
        prefix = f"commands/{len(self.report['commands']):03d}-{label}"
        stdout, stderr = self.out / (prefix + ".stdout"), self.out / (prefix + ".stderr")
        stdout.parent.mkdir(exist_ok=True)
        item = {"argv": [str(v) for v in argv], "label": label, "start": self.now(),
                "timeout_seconds": timeout, "wait_deadline_monotonic": deadline, "phase_deadline_monotonic": limit,
                "stdout": str(stdout.relative_to(self.out)), "stderr": str(stderr.relative_to(self.out))}
        self.report["commands"].append(item)
        process, failure, traceback = None, None, None
        try:
            self.checkpoint()
            self.save()
            with stdout.open("wb") as output, stderr.open("wb") as errors, stdout.open("rb") as reader, stderr.open("rb") as error_reader:
                require(limit - time.monotonic() > 7, "Insufficient command/stop budget; cleanup reserve preserved")
                require(time.monotonic() < deadline, label + " exceeded its finite timeout before spawn")
                if required_after:
                    # Recheck immediately before spawn; no clipped test is admitted.
                    require(time.monotonic() + timeout + 7 + required_after < limit,
                            label + " lacks full test/post-validation budget; no test spawned")
                self.registering_process = True
                try:
                    process = subprocess.Popen(item["argv"], cwd=self.root, stdout=output, stderr=errors, start_new_session=True)
                    self.confirmed_absent_groups.discard(process.pid)
                    self.active[process.pid] = process
                    item["owned_process_group"] = process.pid
                finally:
                    self.registering_process = False
                self.deliver_deferred_signal()  # A local handle and owned PGID now exist.
                self.save()
                while process.poll() is None:
                    if stream:
                        for channel in (reader, error_reader):
                            chunk = channel.read(1024 * 1024)
                            if chunk:
                                print(chunk.decode("utf-8", "replace"), end="", flush=True)
                    require(time.monotonic() < deadline, label + " exceeded its finite timeout")
                    time.sleep(min(0.2, max(0, deadline - time.monotonic())))
                if stream:
                    for channel in (reader, error_reader):
                        chunk = channel.read(1024 * 1024)
                        if chunk:
                            print(chunk.decode("utf-8", "replace"), end="", flush=True)
                item["returncode"] = process.returncode
        except BaseException as error:
            item["error"] = repr(error)
            failure, traceback = error, error.__traceback__
        finally:
            try:
                if process is not None:
                    self.stop(process)  # Also reap descendants after the group leader exits.
            except BaseException as error:
                item["stop_error"] = repr(error)
                if failure is None:
                    failure, traceback = error, error.__traceback__
            finally:
                if process is not None:
                    item["returncode"] = process.returncode
                item["finish"] = self.now()
                try:
                    self.save()
                except BaseException as error:
                    item["finalization_error"] = repr(error)
                    if failure is None:
                        failure, traceback = error, error.__traceback__
        if failure is not None:
            raise failure.with_traceback(traceback)
        require(not check or item["returncode"] == 0, label + " failed; see command stdout/stderr")
        return item["returncode"], stdout.read_text(errors="replace")

    def json_command(self, argv, label, timeout=30):
        return json.loads(self.command(argv, label, timeout=timeout)[1])

    def source_snapshot(self, label):
        def git(*args):
            return self.command(["git", *args], label + "-git-" + args[0])[1]
        head, tree = git("rev-parse", "HEAD").strip(), git("rev-parse", "HEAD^{tree}").strip()
        names = git("ls-files", "-z").split("\0")
        entries = [file_entry(self.root / name, name, self.checkpoint) for name in sorted(set(filter(None, names)))]
        result = {"head": head, "tree": tree, "tracked": entries, "tracked_sha256": canonical_digest(entries),
                  "status": git("status", "--porcelain=v1", "--untracked-files=all")}
        self.write(label + ".json", result)
        return result

    def prepare(self):
        self.source_before = self.source_snapshot("source-before")
        require(not self.source_before["status"], "Hosted source checkout must be clean")
        self.report["source_before"] = self.source_before["head"]
        for argv, label in ((["xcodebuild", "-version"], "xcode-version"),
                            (["xcrun", "xcresulttool", "version"], "xcresulttool-version")):
            self.command(argv, label)
        for kind in ("summary", "tests"):
            self.command(["xcrun", "xcresulttool", "help", "get", "test-results", kind], "xcresulttool-help-" + kind)
        # Finite initial inventory scheduling allowance; all later waits keep their own caps.
        runtimes = self.json_command(["xcrun", "simctl", "list", "runtimes", "--json"], "runtimes", timeout=120)
        # A final poll may reap exactly at the effective deadline. Do not admit
        # that inventory (or a late parse) into later commands or device selection.
        require(time.monotonic() < self.report["commands"][-1]["wait_deadline_monotonic"],
                "Initial runtime inventory wait deadline reached")
        dtypes = self.json_command(["xcrun", "simctl", "list", "devicetypes", "--json"], "device-types")
        architecture = self.command(["uname", "-m"], "architecture")[1].strip()
        pair = choose_pair(runtimes, dtypes, architecture)
        inventory = self.json_command(["xcrun", "simctl", "list", "devices", "--json"], "devices-before")
        self.baseline = {device["udid"].upper() for _, device in devices(inventory)}
        self.intent = {**pair, "name": "TripDocket-Privacy-" + str(uuid.uuid4())}
        require(all(device.get("name") != self.intent["name"] for _, device in devices(inventory)), "Device name collision")
        self.write("ownership.json", {"intent": self.intent, "baseline_uuids": sorted(self.baseline), "owned_uuid": None})
        self.acquiring = True
        try:
            result = self.command(["xcrun", "simctl", "create", self.intent["name"], pair["device_type"], pair["runtime"]], "create-owned-ipad")
            created = str(uuid.UUID(result[1].strip())).upper()
            require(created not in self.baseline, "Create returned an existing UUID; refusing ownership")
            self.owned = created
            self.write("ownership.json", {"intent": self.intent, "baseline_uuids": sorted(self.baseline), "owned_uuid": self.owned})
            self.report["destination"] = {**self.intent, "owned_uuid": self.owned}
            self.save()
        finally:
            self.acquiring = False
        self.deliver_deferred_signal()  # Device acquisition also recorded the owned UUID.
        verify = self.json_command(["xcrun", "simctl", "list", "devices", "--json"], "devices-created")
        require(recover_owned(verify, self.intent, self.baseline) == self.owned, "Created device identity could not be verified")
        print("Owned iPad: " + json.dumps(self.report["destination"], sort_keys=True), flush=True)
        self.command(["xcrun", "simctl", "boot", self.owned], "boot", timeout=45)
        self.command(["xcrun", "simctl", "bootstatus", self.owned, "-b"], "bootstatus", timeout=180)

    def common_xcode(self):
        return ["-destination", "platform=iOS Simulator,id=" + self.owned, "-destination-timeout", "60",
                "-parallel-testing-enabled", "NO", "-maximum-concurrent-test-simulator-destinations", "1",
                "-collect-test-diagnostics", "never", "-default-test-execution-time-allowance", "180",
                "-maximum-test-execution-time-allowance", "480"]

    def discover_products(self):
        products = self.derived / "Build/Products"
        runfiles = sorted(products.glob("*.xctestrun"))
        require(len(runfiles) == 1, "Expected exactly one fresh generated xctestrun")
        data = plistlib.loads(runfiles[0].read_bytes())
        require(data.get("__xctestrun_metadata__", {}).get("FormatVersion") == 2, "Unsupported generated xctestrun format")
        configs = [item for item in data.get("TestConfigurations", []) if item.get("IsEnabled", True)]
        require(len(configs) == 1, "Expected one active test configuration")
        targets = [item for item in configs[0].get("TestTargets", []) if item.get("BlueprintName") == "TripfolioUITests"]
        require(len(targets) == 1 and targets[0].get("IsUITestBundle") is True, "Expected TripfolioUITests target")
        target = targets[0]

        def resolve(value, host=None):
            value = value.replace("__TESTROOT__", str(products))
            if host:
                value = value.replace("__TESTHOST__", str(host))
            path = Path(value).resolve()
            require("__" not in value and path.is_relative_to(products.resolve()) and path.exists(), "Unresolved/outside generated product path")
            return path

        runner = resolve(target["TestHostPath"])
        self.products = {"aut": resolve(target["UITargetAppPath"]), "runner": runner,
                         "test_bundle": resolve(target["TestBundlePath"], runner), "xctestrun": runfiles[0]}
        app_info = plistlib.loads((self.products["aut"] / "Info.plist").read_bytes())
        require(app_info.get("CFBundleIdentifier") == BUNDLE_ID, "Wrong AUT bundle identifier")
        self.report["product_paths"] = {key: str(path) for key, path in self.products.items()}

    def product_snapshot(self, label):
        snapshot = {key: tree_manifest(path, self.checkpoint) for key, path in self.products.items()}
        self.write(label + ".json", snapshot)
        if self.built is not None:
            require(snapshot == self.built, "Built AUT/runner/xctestrun changed: " + label)
        return snapshot

    def build_once(self):
        self.command(["xcodegen", "generate"], "xcodegen", timeout=120)
        self.command(["xcodebuild", "build-for-testing", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio",
                      "-configuration", "Debug", "-derivedDataPath", self.derived,
                      *self.common_xcode(), "CODE_SIGNING_ALLOWED=NO"], "build-for-testing", timeout=360, stream=True)
        self.discover_products()
        self.built = self.product_snapshot("products-after-build")

    def installed(self, label, required=False):
        # Fresh lookup every time: test-without-building may replace the container.
        code, output = self.command(["xcrun", "simctl", "get_app_container", self.owned, BUNDLE_ID, "app"], label + "-lookup", timeout=60, check=False)
        if code:
            record = {"available": False, "lookup_exit_code": code}
            self.write(label + ".json", record)
            require(not required, "Installed AUT unavailable: " + label)
            return record
        path = Path(output.strip())
        require(path.is_absolute() and path.name == self.products["aut"].name and path.is_dir() and not path.is_symlink(), "Invalid fresh AUT container path")
        info = plistlib.loads((path / "Info.plist").read_bytes())
        require(info.get("CFBundleIdentifier") == BUNDLE_ID, "Fresh container has wrong AUT bundle identifier")
        manifest = tree_manifest(path, self.checkpoint)
        record = {"available": True, "path": str(path), "manifest": manifest,
                  "matches_built_bytes": payload(manifest) == payload(self.built["aut"])}
        self.write(label + ".json", record)
        require(record["matches_built_bytes"], "Installed AUT bytes differ from built AUT: " + label)
        return record

    def copy_for_reader(self, original, label):
        before = tree_manifest(original, self.checkpoint)
        self.originals[label] = (original, before)
        self.write(label + "/original-before-reader.json", before)
        destination = self.out / "reader-copies" / (label + ".xcresult")
        destination.parent.mkdir(exist_ok=True)

        def bounded_copy(source, target):
            with open(source, "rb") as src, open(target, "xb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    self.checkpoint()
                    dst.write(chunk)
            shutil.copystat(source, target, follow_symlinks=False)
            return target

        shutil.copytree(original, destination, symlinks=True, copy_function=bounded_copy)
        copied = tree_manifest(destination, self.checkpoint)
        self.write(label + "/reader-copy-before.json", copied)
        require(copied == before, "Reader copy is not exact")
        return destination

    def parse_case(self, original, label, method):
        copied = self.copy_for_reader(original, label)
        parsed = {}
        try:
            for kind in ("summary", "tests"):
                parsed[kind] = self.json_command(["xcrun", "xcresulttool", "get", "test-results", kind,
                                                  "--path", copied, "--compact"], label + "-" + kind)
                self.write(label + "/" + kind + ".json", parsed[kind])
            return validate_result(parsed["summary"], parsed["tests"], method, self.owned)
        finally:
            after = tree_manifest(original, self.checkpoint)
            self.write(label + "/original-after-reader.json", after)
            require(after == self.originals[label][1], "Original xcresult changed while parsing its copy")

    def run_case(self, locale, method, size, allowance):
        require((locale, method, size, allowance) == self.case, "Case differs from selected locale")
        require(not self.report["cases"], "One locale attempt per driver; no retry")
        label = locale
        original = self.out / "originals" / (locale + ".xcresult")
        original.parent.mkdir(exist_ok=True)
        entry = {"locale": locale, "method": method, "system_content_size_expected": size,
                 "original_xcresult": str(original), "status": "not_admitted"}
        self.report["cases"].append(entry)
        required = CASE_PREP_SECONDS + allowance + 7 + CASE_POST_SECONDS
        entry["admission"] = {"required_seconds": required, "remaining_seconds": self.work_deadline - time.monotonic(),
                              "post_validation_seconds": CASE_POST_SECONDS, "work_deadline": self.work_deadline}
        self.save()
        require(time.monotonic() + required < self.work_deadline,
                label + " lacks full case/post-validation budget; no case started")
        entry["status"] = "started"
        self.product_snapshot(label + "/products-before")
        self.command(["xcrun", "simctl", "install", self.owned, self.products["aut"]], label + "-install", timeout=60)
        entry["installed_before"] = self.installed(label + "/installed-before", required=True)["available"]
        self.command(["xcrun", "simctl", "ui", self.owned, "content_size", size], label + "-set-size")
        actual = self.command(["xcrun", "simctl", "ui", self.owned, "content_size"], label + "-read-size")[1].strip()
        entry["system_content_size_actual"] = actual
        require(actual == size, "System content-size readback mismatch for " + label)
        self.save()
        primary, primary_traceback = None, None
        try:
            code, _ = self.command(["xcodebuild", "test-without-building", "-xctestrun", self.products["xctestrun"],
                                   *self.common_xcode(), "-resultBundlePath", original,
                                   "-only-testing:TripfolioUITests/PrivacySupportUITests/" + method],
                                  label + "-test", timeout=allowance, check=False, stream=True,
                                  required_after=CASE_POST_SECONDS)
            entry["xcodebuild_exit_code"] = code
            require(code == 0, "xcodebuild failed; result data cannot override nonzero exit")
        except BaseException as error:
            primary, primary_traceback = error, error.__traceback__
            entry["primary_error"] = repr(error)
        finally:
            # Post-test evidence is mandatory, but must never replace the test's
            # original timeout/nonzero/stop error when the remaining work expires.
            for stage, operation in (
                    ("products-after", lambda: self.product_snapshot(label + "/products-after")),
                    ("installed-after", lambda: entry.update(installed_after=self.installed(label + "/installed-after", required=True)["available"])),
                    ("save", self.save)):
                try:
                    operation()
                except BaseException as error:
                    entry.setdefault("post_validation_errors", []).append({"stage": stage, "error": repr(error)})
                    if primary is None:
                        primary, primary_traceback = error, error.__traceback__
                        entry["primary_error"] = repr(error)
        if primary is not None:
            raise primary.with_traceback(primary_traceback)
        require(original.is_dir(), "Missing original result bundle for " + label)
        entry["validated"] = self.parse_case(original, label, method)
        require(code == 0, "xcodebuild failed; result data cannot override nonzero exit")
        entry["status"] = "passed"
        self.save()

    def cleanup(self):
        self.cleaning = True
        self.final_deadline = min(self.final_deadline, time.monotonic() + CLEANUP_SECONDS)
        cleanup = self.report["cleanup"]
        cleanup["started_at"] = self.now()
        stop_errors = []
        for process in list(self.active.values()):
            try:
                self.stop(process)
            except Exception as error:
                stop_errors.append(repr(error))
        cleanup["process_stop_errors"] = stop_errors
        # An interrupted create may have succeeded before its UUID was returned.
        if self.intent and self.owned is None:
            inventory = self.json_command(["xcrun", "simctl", "list", "devices", "--json"], "cleanup-recover-owned", timeout=20)
            self.owned = recover_owned(inventory, self.intent, self.baseline)
            cleanup["recovered_uuid"] = self.owned
            self.write("ownership-recovery.json", {"intent": self.intent, "owned_uuid": self.owned})
            require(self.owned is not None, "Create outcome uncertain; no unique owned device found for cleanup")
        if self.owned is not None:
            for verb, limit in (("shutdown", 30), ("delete", 30)):
                try:
                    code, _ = self.command(["xcrun", "simctl", verb, self.owned], "cleanup-" + verb, timeout=limit, check=False)
                    cleanup[verb + "_exit_code"] = code
                except Exception as error:
                    cleanup[verb + "_error"] = repr(error)
                self.save()  # A shutdown error must not skip delete or verification.
            inventory = self.json_command(["xcrun", "simctl", "list", "devices", "--json"], "cleanup-devices-after", timeout=20)
            absent = self.owned not in {device["udid"].upper() for _, device in devices(inventory)}
            cleanup["owned_uuid_absent"] = absent
            require(cleanup.get("delete_exit_code") == 0 and absent, "Owned iPad deletion not confirmed")
        require(not stop_errors, "Owned command process cleanup could not be confirmed")
        cleanup["verified"] = True
        cleanup["finished_at"] = self.now()
        self.save()

    def final_evidence(self):
        if self.source_before is not None:
            after = self.source_snapshot("source-after")
            self.report["source_unchanged"] = after == self.source_before
            require(self.report["source_unchanged"], "Source HEAD/tree/tracked files/status changed")
        if self.products is not None and self.built is not None:
            self.product_snapshot("products-final")
        # Every registered original is mandatory, even if its path disappeared.
        for locale, (original, before) in self.originals.items():
            manifest = tree_manifest(original, self.checkpoint)
            self.write(locale + "/original-final.json", manifest)
            require(manifest == before, "Original result changed after parsing: " + locale)
        # Optional discovery is only for failed/partial outputs never registered.
        for locale, _, _, _ in (self.case,):
            if locale in self.originals:
                continue
            original = self.out / "originals" / (locale + ".xcresult")
            if original.is_dir():
                manifest = tree_manifest(original, self.checkpoint)
                self.write(locale + "/original-final.json", manifest)

    def run(self):
        signal.signal(signal.SIGTERM, self.signal)
        signal.signal(signal.SIGINT, self.signal)
        try:
            self.prepare()
            self.build_once()
            self.run_case(*self.case)
        except BaseException as error:
            self.report["errors"].append(repr(error))
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            for finalize in (self.cleanup, self.final_evidence):
                try:
                    finalize()
                except BaseException as error:
                    self.report["errors"].append("Finalization: " + repr(error))
            passed = (not self.report["errors"] and self.report["cleanup"]["verified"]
                      and len(self.report["cases"]) == 1
                      and self.report["cases"][0].get("locale") == self.case[0]
                      and self.report["cases"][0].get("method") == self.case[1]
                      and self.report["cases"][0]["status"] == "passed")
            self.report.update(status="passed" if passed else "failed", finished_at=self.now(), elapsed_seconds=round(time.monotonic() - self.start, 3))
            self.save()
        print(json.dumps({"status": self.report["status"], "errors": self.report["errors"], "evidence": str(self.out)}, indent=2), flush=True)
        return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", required=True, choices=[case[0] for case in CASES])
    args = parser.parse_args()
    sys.exit(Driver(Path(__file__).resolve().parent.parent, args.locale).run())
