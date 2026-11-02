#!/usr/bin/env python3
"""Initialize the selected CI Files provider once; never certify cold first use."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import time
import uuid

import recovery_process as process

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("guidance_selector", HERE / "select-simulator.py")
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)
require = process.require
FILES = "com.apple.DocumentsApp"
GROUP = "group.com.apple.FileProvider.LocalStorage"
WORK, STOP, WRITE = 420, 30, 10
# Existing initial inventory can take more than 30s, so each full inventory
# retains its measured 120s cap. Boot readiness gets at most 180s; ordinary
# commands get 30/60s. Every command includes the shared primitive's 8s stop
# reserve, and their sum cannot extend this independent 420s setup budget.
INPUTS = ("sdk.txt", "architecture.txt", "runtimes.json", "device-types.json", "devices.json")
IDENTITY = ("selection", "sdk", "architecture", "runtime", "runtime_build", "udid", "device_type", "device_name")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_selection(directory):
    require(directory.resolve(strict=True) == directory and directory.is_dir(), "Unsafe selection directory")
    raw = {name: selector.read_file(directory / name) for name in INPUTS}
    selected_raw = selector.read_file(directory / "selection.json")
    selected = selector.decode(selected_raw)
    require(selected.get("inventory_sha256") == {name: digest(value) for name, value in raw.items()},
            "Selection inventory digest mismatch")
    actual = selector.select_device(raw["sdk.txt"].decode("utf-8").strip(),
        raw["architecture.txt"].decode("utf-8").strip(), selector.decode(raw["runtimes.json"]),
        selector.decode(raw["device-types.json"]), selector.decode(raw["devices.json"]), selected.get("requested_udid"))
    require(selected == {**actual, "inventory_sha256": selected["inventory_sha256"]}, "Selection record mismatch")
    return selected, {**{name: digest(value) for name, value in raw.items()}, "selection.json": digest(selected_raw)}


def selected_device(selected, runtimes, types, devices):
    actual = selector.select_device(selected["sdk"], selected["architecture"], runtimes, types,
                                    devices, selected["udid"])
    require(all(actual[key] == selected[key] for key in IDENTITY), "Selected Simulator identity changed")
    row = next(row for row in devices["devices"][selected["runtime"]]
               if selector.identifier(row["udid"]) == selected["udid"])
    require(row.get("state") in {"Shutdown", "Booted"}, "Selected Simulator state is not stable")
    expected = Path.home() / "Library/Developer/CoreSimulator/Devices" / selected["udid"] / "data"
    require(row.get("dataPath") == str(expected), "Unexpected selected Simulator data path")
    require(expected.resolve(strict=True) == expected and expected.is_dir(), "Unsafe Simulator data path")
    return row, expected


def group_path(output, root):
    rows = [line.split("\t") for line in output.splitlines() if line.split("\t")[0] == GROUP]
    require(len(rows) == 1 and len(rows[0]) == 2, "Files local group missing or ambiguous")
    path = Path(rows[0][1])
    prefix = root / "Containers/Shared/AppGroup"
    require(path.is_absolute() and path.parent == prefix, "Unexpected Files group path")
    require(str(uuid.UUID(path.name)).upper() == path.name, "Invalid Files group UUID")
    require(path.resolve(strict=True) == path and path.is_dir(), "Unsafe Files group path")
    return path


def directory_identity(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode), "Directory replaced or linked: " + str(path))
    return [info.st_dev, info.st_ino]


class Bootstrap(process.Smoke):
    def __init__(self, directory, env=None):
        started = time.monotonic()
        self.env = dict(os.environ if env is None else env)
        require(self.env.get("GITHUB_ACTIONS") == "true" and self.env.get("RUNNER_OS") == "macOS"
                and self.env.get("RUNNER_ENVIRONMENT") == "github-hosted"
                and self.env.get("GITHUB_WORKFLOW") == "CI" and self.env.get("GITHUB_JOB") == "ui_guidance",
                "Files preparation is hosted CI ui-guidance only")
        self.directory = directory.absolute()
        self.selected, self.input_hashes = read_selection(self.directory)
        self.out = self.directory / "files-bootstrap"
        self.out.mkdir(exist_ok=False)
        self.ops = process.RealOps(self.env, str(HERE.parent))
        self.t0 = started; self.limit = self.t0 + WORK
        self.cleanup_deadline = self.limit + STOP; self.write_deadline = self.cleanup_deadline + WRITE
        self.active = {}; self.absent_groups = set(); self.unknown_spawn = False; self.log_total = 0
        self.interrupted = False
        self.report = {"schema_version": 1, "status": "running", "commands": [], "errors": [],
            "coverage": "preinitialized-provider; not cold first-use acceptance", "selected": self.selected,
            "input_sha256": self.input_hashes, "limits": {"work_seconds": WORK, "stop_seconds": STOP,
                "receipt_seconds": WRITE, "per_stream_bytes": process.PER_LOG, "all_stream_bytes": process.ALL_LOG},
            "device_ownership": "preexisting; never delete, erase, or shut down",
            "cleanup_scope": "owned host command groups only; Simulator service lifetime is not claimed"}
        self.report["source_sha256"] = {name: digest(selector.read_file(HERE / name)) for name in
            ("prepare-guidance-files.py", "select-simulator.py", "recovery_process.py")}

    def checkpoint(self, **_):
        require(not self.interrupted, "Interrupted")
        require(self.ops.now() < self.limit, "Files preparation work deadline reached")

    def command(self, label, argv, cap):
        super().command(label, argv, cap)
        # The process primitive keeps raw bytes; structured input must be strict UTF-8.
        return Path(self.report["commands"][-1]["logs"]["stdout"]).read_bytes().decode("utf-8")

    def json_command(self, label, arguments, cap):
        return selector.decode(self.command(label, ["xcrun", "simctl", *arguments], cap))

    def wait_provider(self, group):
        end = min(self.limit, self.ops.now() + 30)
        observation = {"probes": 0, "absent_observations": 0, "start": self.ops.now() - self.t0}
        self.report["provider"] = observation
        # Pin every ancestor, so replacing a higher directory cannot redirect a
        # later lookup through the same leaf name. No directory is created here.
        with ExitStack() as stack:
            pins = []
            for path in [*reversed(group.parents), group]:
                self.checkpoint()
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, fd)
                info = os.fstat(fd); pin = [info.st_dev, info.st_ino]
                require(directory_identity(path) == pin, "Directory changed while pinning")
                pins.append((path, fd, pin))
            def check():
                self.checkpoint()
                require(self.ops.now() < end, "Files provider readiness deadline reached")
                for path, descriptor, pin in pins:
                    info = os.fstat(descriptor)
                    require([info.st_dev, info.st_ino] == pin and directory_identity(path) == pin,
                            "Pinned provider ancestry changed")
                self.checkpoint()
                require(self.ops.now() < end, "Provider observation exceeded deadline")
            while True:
                check(); observation["probes"] += 1
                try:
                    info = os.stat("File Provider Storage", dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    observation["absent_observations"] += 1
                    check(); self.ops.sleep(min(.1, end - self.ops.now())); continue
                require(stat.S_ISDIR(info.st_mode), "Files provider is not a real directory")
                pin = [info.st_dev, info.st_ino]
                leaf = os.open("File Provider Storage", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    actual = os.fstat(leaf)
                    require([actual.st_dev, actual.st_ino] == pin
                            and directory_identity(group / "File Provider Storage") == pin, "Provider changed while opening")
                    check()
                    observation.update(status="ready", group=str(group), group_identity=pins[-1][2],
                                       identity=pin, finish=self.ops.now() - self.t0)
                    return
                finally:
                    os.close(leaf)

    def prepare(self):
        version = self.command("xcode", ["xcodebuild", "-version"], 30).strip()
        require(version == "Xcode 26.2\nBuild version 17C52", "Unexpected guidance Xcode")
        sdk = self.command("sdk", ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], 30).strip()
        arch = self.command("architecture", ["uname", "-m"], 30).strip()
        require(sdk == self.selected["sdk"] and arch == self.selected["architecture"], "Live toolchain differs from selection")
        runtimes = self.json_command("runtimes", ["list", "runtimes", "--json"], 60)
        types = self.json_command("types", ["list", "devicetypes", "--json"], 60)
        devices = self.json_command("devices-before", ["list", "devices", "--json"], 120)
        row, root = selected_device(self.selected, runtimes, types, devices)
        root_pin = directory_identity(root)
        self.report["initial_state"] = row["state"]; self.report["data_root_identity"] = root_pin
        udid = self.selected["udid"]
        if row["state"] == "Shutdown":
            self.command("boot", ["xcrun", "simctl", "boot", udid], 60)
        self.command("bootstatus", ["xcrun", "simctl", "bootstatus", udid, "-b"], 180)
        live = self.json_command("devices-booted", ["list", "devices", "--json"], 120)
        row, same_root = selected_device(self.selected, runtimes, types, live)
        require(row["state"] == "Booted" and same_root == root and directory_identity(root) == root_pin,
                "Selected Simulator did not become ready with unchanged data root")
        launched = self.command("files-launch", ["xcrun", "simctl", "launch", udid, FILES], 60)
        require(re.fullmatch(re.escape(FILES) + r": [1-9][0-9]*\n?", launched) is not None,
                "Unexpected Files launch identity")
        self.report["files_launch_response"] = launched.strip()
        listing = self.command("files-group", ["xcrun", "simctl", "get_app_container", udid, FILES, "groups"], 60)
        self.wait_provider(group_path(listing, root))
        final = self.json_command("devices-final", ["list", "devices", "--json"], 120)
        row, same_root = selected_device(self.selected, runtimes, types, final)
        require(row["state"] == "Booted" and same_root == root, "Final selected Simulator changed")
        def others(inventory):
            return {runtime: {selector.identifier(device["udid"]): device for device in rows
                              if selector.identifier(device["udid"]) != udid}
                    for runtime, rows in inventory["devices"].items()}
        require(others(devices) == others(final), "A nontarget Simulator changed during preparation")
        self.report["final_inventory_verified"] = True
        require(directory_identity(root) == root_pin, "Simulator data root changed")
        selected, hashes = read_selection(self.directory)
        require(selected == self.selected and hashes == self.input_hashes, "Selection inputs changed during preparation")

    def execute(self):
        self.save()
        try:
            self.prepare(); self.checkpoint()
            require(not self.active and not self.unknown_spawn, "Unresolved host process ownership")
            self.report["status"] = "provider_ready"
        except BaseException as error:
            self.error(repr(error)); self.report["status"] = "failed"
        finally:
            # No device/app lifecycle cleanup: this is a preexisting CI device.
            for pid, child in list(self.active.items()):
                records = [row for row in self.report["commands"] if row.get("pgid") == pid]
                if len(records) == 1 and not records[0].get("stop", {}).get("attempted"):
                    try:
                        self.stop(child, self.cleanup_deadline, records[0])
                    except BaseException as error:
                        self.error(repr(error))
            self.report["host_cleanup"] = {"active_groups": sorted(self.active), "unknown_spawn": self.unknown_spawn}
            if self.active or self.unknown_spawn or self.report["errors"]:
                self.report["status"] = "failed"
            self.save()
        return 0 if self.report["status"] == "provider_ready" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-directory", type=Path, required=True)
    args = parser.parse_args()
    runner = Bootstrap(args.selection_directory)
    signal.signal(signal.SIGINT, runner.signal); signal.signal(signal.SIGTERM, runner.signal)
    raise SystemExit(runner.execute())


if __name__ == "__main__":
    main()
