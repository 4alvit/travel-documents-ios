#!/usr/bin/env python3
"""One hosted recovery attempt; ordinary local invocation fails before spawning.

The reviewed workflow and GitHub-provided context are the trust boundary, not an
environment-based cryptographic attestation. No credentials or full event payload
are retained. The 35-minute envelope includes discovery, the unchanged 30-minute
controller, and retention. GitHub's independent 45-minute job timeout is the final
backstop. Ephemeral device/DerivedData paths are not durable artifact promises.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("room_recovery_controller", ROOT / "scripts/run-recovery-journey.py")
controller = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = controller
spec.loader.exec_module(controller)
require, Failure, Deadline = controller.require, controller.ConfigurationFailure, controller.DeadlineFailure
PROFILE_PATH = "scripts/recovery-hosted-profile.json"
POLICY = {
    "schema_version": 1, "repository": "4alvit/room-inventory-ios", "job_id": "recovery",
    "runner_label": "macos-15", "image_os": "macos15", "workflow_path": ".github/workflows/ci.yml",
    "allowed_caller_workflows": [".github/workflows/quality-gate.yml", ".github/workflows/release-pipeline.yml"],
    "allowed_events": ["pull_request", "push", "merge_group", "schedule", "workflow_dispatch"],
    "discovery_seconds": 120, "recovery_seconds": 1800, "retention_seconds": 180,
    "job_timeout_minutes": 45, "admission_free_bytes": 24 * controller.GIB,
    "abort_free_bytes": 8 * controller.GIB, "device_cap_bytes": 8 * controller.GIB,
    "derived_data_cap_bytes": 4 * controller.GIB, "output_cap_bytes": controller.GIB,
}


def bounded_read(path, cap=controller.MIB):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= cap, "Not a bounded regular file: " + str(path), Failure)
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    require(len(raw) <= cap, "File grew beyond its byte cap", Failure)
    return raw


def load_profile(root, expected):
    require(re.fullmatch(r"[0-9a-f]{64}", expected or ""), "Invalid profile digest", Failure)
    raw = bounded_read(root / PROFILE_PATH, 65536)
    require(controller.sha(raw) == expected, "Profile digest differs", Failure)
    profile = json.loads(raw)
    require(profile == POLICY and all(type(profile[k]) is type(v) for k, v in POLICY.items()),
            "Unsupported hosted policy", Failure)
    return profile, raw


def validate_host(env, profile, root, *, machine=None, system=None):
    for key, value in {"GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                       "RUNNER_OS": "macOS", "ImageOS": profile["image_os"], "GITHUB_SERVER_URL": "https://github.com",
                       "GITHUB_REPOSITORY": profile["repository"], "GITHUB_JOB": profile["job_id"]}.items():
        require(env.get(key) == value, "Unsupported hosted context: " + key, Failure)
    require((system or platform.system()) == "Darwin", "macOS process required", Failure)
    arch = machine or platform.machine()
    require(arch in {"X64": ("x86_64",), "ARM64": ("arm64", "aarch64")}.get(env.get("RUNNER_ARCH"), ()),
            "Runner architecture differs", Failure)
    require(isinstance(env.get("ImageVersion"), str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", env["ImageVersion"]),
            "Missing or invalid runner image version", Failure)
    for key in ("GITHUB_SHA", "GITHUB_WORKFLOW_SHA", "RECOVERY_TESTED_COMMIT", "RECOVERY_TESTED_TREE"):
        require(re.fullmatch(r"[0-9a-f]{40}", env.get(key, "")), "Missing source identity: " + key, Failure)
    require(env["GITHUB_SHA"] == env["RECOVERY_TESTED_COMMIT"], "iOS job tested a different commit", Failure)
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(re.fullmatch(r"[1-9][0-9]*", env.get(key, "")), "Invalid run identity", Failure)
    require(env.get("GITHUB_EVENT_NAME") in profile["allowed_events"], "Unsupported event", Failure)
    workspace = Path(env.get("GITHUB_WORKSPACE", ""))
    require(workspace.is_absolute() and workspace.resolve() == root.resolve(), "Checkout path differs", Failure)
    temp = Path(env.get("RUNNER_TEMP", ""))
    require(temp.is_absolute() and temp.is_dir() and not temp.is_symlink()
            and not temp.resolve().is_relative_to(root.resolve()) and not root.resolve().is_relative_to(temp.resolve()),
            "Runner temporary root must be separate", Failure)
    caller = env.get("GITHUB_WORKFLOW_REF", "")
    prefix, separator, caller_ref = caller.partition("@")
    allowed = [profile["repository"] + "/" + p for p in profile["allowed_caller_workflows"]]
    require(separator and prefix in allowed and caller_ref == env.get("GITHUB_REF")
            and caller_ref.startswith("refs/"), "Caller workflow identity differs", Failure)
    return {"repository": env["GITHUB_REPOSITORY"], "job_id": env["GITHUB_JOB"],
            "run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"],
            "event_name": env["GITHUB_EVENT_NAME"], "ref": env["GITHUB_REF"],
            "workflow_ref": caller, "workflow_sha": env["GITHUB_WORKFLOW_SHA"],
            "runner_environment": env["RUNNER_ENVIRONMENT"], "runner_os": env["RUNNER_OS"],
            "runner_arch": env["RUNNER_ARCH"], "process_arch": arch,
            "image_os": env["ImageOS"], "image_version": env["ImageVersion"]}


MISSING = object()
SHA40 = r"[0-9a-f]{40}"
REPOSITORY = r"(?!\.{1,2}/)[A-Za-z0-9_.-]{1,100}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}"


class IdentityAudit:
    """Small allowlisted evidence, including failures before directory admission."""
    def __init__(self):
        self.stage, self.checks, self.observed = "host", {}, {}

    def observe(self, name, value=MISSING, pattern=None):
        kind = ("missing" if value is MISSING else "null" if value is None else
                "boolean" if type(value) is bool else "integer" if type(value) is int else
                "string" if isinstance(value, str) else "object" if isinstance(value, dict) else
                "array" if isinstance(value, list) else "other")
        item = {"type": kind}
        if isinstance(value, str):
            item["length"] = len(value)
            if len(value) <= 256 and pattern and re.fullmatch(pattern, value):
                item["value"] = value
        elif type(value) is bool or (type(value) is int and 0 < value <= 2**53 - 1):
            item["value"] = value
        self.observed[name] = item

    def check(self, name, condition):
        self.checks[name] = bool(condition)
        require(condition, "Identity check failed: " + name, Failure)

    def snapshot(self):
        value = {"schema_version": 1, "stage": self.stage,
                 "checks": dict(self.checks), "observed": dict(self.observed)}
        if len(json.dumps(value).encode()) > 8192:
            # Keys are source constants; never truncate an arbitrary raw value.
            value = {"schema_version": 1, "stage": self.stage,
                     "checks": dict(list(self.checks.items())[-64:]), "observed": {},
                     "observations_omitted_for_size": True}
        return value


def valid_text(value, pattern):
    return isinstance(value, str) and len(value) <= 256 and re.fullmatch(pattern, value) is not None


def validate_event(event, env, audit=None):
    audit = audit or IdentityAudit()
    audit.stage = "event"
    audit.observe("event", event)
    audit.check("event_object", isinstance(event, dict))
    repository = event.get("repository", MISSING)
    audit.observe("repository", repository)
    audit.check("event_repository_object", isinstance(repository, dict))
    audit.observe("event_repository", repository.get("full_name", MISSING), REPOSITORY)
    audit.check("event_repository_matches", repository.get("full_name") == env["GITHUB_REPOSITORY"])
    kind, commit, ref = env["GITHUB_EVENT_NAME"], env["GITHUB_SHA"], env["GITHUB_REF"]
    identity = {"kind": kind, "source_commit": commit, "ref": ref}
    if kind == "pull_request":
        pr = event.get("pull_request", MISSING)
        audit.observe("pull_request", pr)
        audit.check("pr_object", isinstance(pr, dict))
        number = event.get("number")
        audit.observe("number", event.get("number", MISSING))
        audit.check("pr_number", type(number) is int and 0 < number <= 2**53 - 1)
        audit.check("pr_merge_ref", ref == f"refs/pull/{number}/merge")
        merge = pr.get("merge_commit_sha", MISSING)
        audit.observe("merge_commit_sha", merge, SHA40)
        audit.check("pr_merge_metadata_type", merge is MISSING or merge is None or valid_text(merge, SHA40))
        # Webhook snapshot metadata is not an atomic identity for the run.
        audit.observe("merge_metadata_matches_run", merge == commit)
        identity["merge_metadata_matches_run"] = merge == commit
        identity["merge_metadata_state"] = "missing" if merge is MISSING else "null" if merge is None else "sha"
        if valid_text(merge, SHA40):
            identity["merge_commit_sha"] = merge
        for side in ("base", "head"):
            item = pr.get(side, MISSING)
            audit.observe(side, item)
            audit.check("pr_" + side + "_object", isinstance(item, dict))
            sha = item.get("sha")
            audit.observe(side + "_sha", item.get("sha", MISSING), SHA40)
            audit.check("pr_" + side + "_sha", valid_text(sha, SHA40))
            repo = item.get("repo", MISSING)
            audit.observe(side + "_repo", repo)
            audit.check("pr_" + side + "_repo_object", isinstance(repo, dict))
            name = repo.get("full_name")
            audit.observe(side + "_repository", repo.get("full_name", MISSING), REPOSITORY)
            audit.check("pr_" + side + "_repository", valid_text(name, REPOSITORY))
            identity[side] = {"sha": sha, "repository": name}
        audit.check("pr_base_repository_matches", identity["base"]["repository"] == repository["full_name"])
        identity["number"] = number
    elif kind == "merge_group":
        group = event.get("merge_group", {})
        audit.check("merge_group_object", isinstance(group, dict))
        require(group.get("head_sha") == commit and group.get("head_ref") == ref
                and ref.startswith("refs/heads/gh-readonly-queue/"), "Merge-group identity differs", Failure)
        identity["base_ref"] = group.get("base_ref")
    elif kind == "push":
        require(event.get("after") == commit and event.get("ref") == ref and ref.startswith("refs/heads/")
                and event.get("deleted") is not True, "Push identity differs", Failure)
    else:
        require(kind in ("schedule", "workflow_dispatch"), "Unsupported event", Failure)
        branch = repository.get("default_branch")
        require(isinstance(branch, str) and branch and ref == "refs/heads/" + branch,
                "Scheduled/manual run must use default branch", Failure)
        inputs = event.get("inputs") or {}
        audit.check("event_inputs_object", isinstance(inputs, dict))
        expected = inputs.get("expected_sha") if kind == "workflow_dispatch" else None
        require(not expected or expected == commit, "Manual expected_sha differs", Failure)
        identity["default_branch"] = branch
    return identity


class Alarm:
    """Non-renewing operation deadline; relinquished before the base controller."""
    def __init__(self, end, clock=time.monotonic):
        self.end, self.clock = end, clock

    def check(self):
        require(self.clock() < self.end, "Hosted absolute deadline reached", Deadline)

    def arm(self, end=None):
        remaining = min(self.end, end if end is not None else self.end) - self.clock()
        require(remaining > 0, "Hosted deadline exhausted", Deadline)
        signal.setitimer(signal.ITIMER_REAL, remaining)

    def __enter__(self):
        require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "Existing process timer is active", Failure)
        self.previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self.expired)
        try:
            self.arm()
        except BaseException:
            signal.signal(signal.SIGALRM, self.previous)
            raise
        return self

    def expired(self, *_):
        raise Deadline("Hosted absolute deadline reached")

    def __exit__(self, *_):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous)


class Discovery:
    """Bounded one-pass commands with the controller's owned-group cleanup."""
    def __init__(self, root, output, env, alarm, *, disk_usage=shutil.disk_usage):
        self.root, self.output, self.env, self.alarm = root, output, dict(env), alarm
        self.disk_usage = disk_usage
        self.records, self.cleanup_errors = [], []

    def check(self):
        self.alarm.check()
        require(self.disk_usage(self.output).free >= POLICY["abort_free_bytes"], "Hosted disk abort floor reached")
        self.alarm.check()

    def command(self, args, name, cap=20, *, retain_output=True):
        self.check()
        start = self.alarm.clock()
        end = min(self.alarm.end, start + cap)
        require(end - self.alarm.clock() >= 8, "Insufficient discovery/cleanup budget", Deadline)
        record = {"name": name, "args": [str(a) for a in args], "exit_code": None, "primary_error": None,
                  "timing": {"start": start, "work_deadline": end - 4,
                             "command_deadline": end, "requested_cap": cap}}
        self.records.append(record)
        buffers, process, selector, primary = [bytearray(), bytearray()], None, None, None
        state = {}
        def tick():
            self.check()
            require(self.alarm.clock() < end - 4, "Discovery command deadline reached", Deadline)
        try:
            self.alarm.arm(end - 4)
            selector = selectors.DefaultSelector()
            oldmask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
            try:
                tick()
                process = subprocess.Popen(record["args"], cwd=self.root, env=self.env, start_new_session=True,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, oldmask)
            for index, pipe in enumerate((process.stdout, process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, index)
            while selector.get_map() or process.poll() is None:
                tick()
                for key, _ in selector.select(min(.1, max(0, end - 4 - self.alarm.clock()))):
                    tick()
                    try:
                        data = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        require(len(buffers[key.data]) + len(data) <= 4 * controller.MIB, "Discovery stream cap reached")
                        buffers[key.data].extend(data)
            tick()
            record["exit_code"] = process.wait(timeout=0)
            require(record["exit_code"] == 0, "Discovery command failed: " + name)
        except BaseException as error:
            primary = error
            record["primary_error"] = {"type": type(error).__name__, "message": str(error)}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            # Kill/reap before closing pipes, and never renew the absolute end.
            operations = []
            if process is not None:
                operations.append(("owned_group", lambda: controller.kill_owned(process, end, state=state, clock=self.alarm.clock)))
            if selector is not None:
                operations.append(("selector_close", selector.close))
            if process is not None:
                operations.extend(("pipe_close", p.close) for p in (process.stdout, process.stderr))
            for operation, action in operations:
                try:
                    require(self.alarm.clock() < end, "Discovery cleanup deadline reached", Deadline)
                    self.alarm.arm(end)
                    result = action()
                    if operation == "owned_group":
                        record["cleanup"] = result
                        require(result["success"], "Discovery owned-group cleanup uncertain")
                except BaseException as error:
                    self.cleanup_errors.append({"command": name, "operation": operation, "error": str(error)})
            signal.setitimer(signal.ITIMER_REAL, 0)
            try:
                # Sample only after owned-group cleanup. Receipt failures must
                # not prevent cleanup or replace an existing command error.
                record["timing"]["finish"] = self.alarm.clock()
                self.alarm.arm()
                self.check()
                for suffix, data in zip(("stdout", "stderr"), buffers):
                    self.check()
                    if retain_output:
                        (self.output / (name + "." + suffix)).write_bytes(data)
                        record[suffix + "_sha256"] = controller.sha(data)
                    else:
                        # Raw commit output includes names, email and message.
                        record[suffix + "_bytes"] = len(data)
                record["output_retained"] = retain_output
                controller.write_json(self.output / "commands.json", self.records)
                controller.tree_size(self.output, 16 * controller.MIB, self.check, max_entries=128)
                self.check()
            except BaseException as error:
                self.cleanup_errors.append({"command": name, "operation": "receipt", "error": str(error)})
                primary = primary or error
        if primary:
            raise primary
        require(not any(e["command"] == name for e in self.cleanup_errors), "Discovery cleanup/receipt incomplete")
        return bytes(buffers[0])


def version(value):
    require(isinstance(value, str) and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value), "Invalid SDK/runtime version", Failure)
    return tuple(int(p) for p in value.split(".")) + ((0,) if value.count(".") == 1 else ())


def select_runtime(inventory, sdk):
    """Same SDK major/minor; newest installed patch, then newest iPhone generation.

    Patch equality is intentionally not required. A compatible type must appear
    in runtime support data, an available device, or a declared version range.
    No device boot, runtime download, fallback runtime or retry is performed.
    """
    sdk_version = version(sdk)
    require(isinstance(inventory.get("runtimes"), list) and isinstance(inventory.get("devicetypes"), list)
            and isinstance(inventory.get("devices"), dict), "Incomplete simulator inventory", Failure)
    runtimes = [r for r in inventory["runtimes"] if r.get("isAvailable") is True
                and re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-[0-9-]+", r.get("identifier", ""))
                and version(r.get("version"))[:2] == sdk_version[:2]]
    require(runtimes, "No installed available runtime matches SDK major/minor", Failure)
    runtime = max(runtimes, key=lambda r: (version(r["version"]), r["identifier"]))
    supported = {t.get("identifier") for t in runtime.get("supportedDeviceTypes", []) if isinstance(t, dict)}
    supported.update(d.get("deviceTypeIdentifier") for d in inventory["devices"].get(runtime["identifier"], [])
                     if d.get("isAvailable") is True)
    v = version(runtime["version"])
    encoded = (v[0] << 16) | (v[1] << 8) | v[2]
    types = [t for t in inventory["devicetypes"]
             if re.fullmatch(r"com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-[A-Za-z0-9-]+", t.get("identifier", ""))
             and (t["identifier"] in supported or
                  (type(t.get("minRuntimeVersion")) is int and type(t.get("maxRuntimeVersion")) is int
                   and t["minRuntimeVersion"] <= encoded <= t["maxRuntimeVersion"]))]
    require(types, "No evidenced compatible installed iPhone type", Failure)
    selected = max(types, key=lambda t: (int((re.search(r"iPhone-(\d+)", t["identifier"]) or ["", "0"])[1]), t["identifier"]))
    return {"runtime": runtime["identifier"], "runtime_version": runtime["version"], "sdk_version": sdk,
            "device_type": selected["identifier"], "patch_policy": "same-major-minor-newest-installed-patch"}


def parse_commit_identity(raw, audit):
    """Read only tree/parent headers, including in a depth-one checkout."""
    audit.check("commit_object_bound", isinstance(raw, bytes) and len(raw) <= 4 * controller.MIB)
    end = raw.find(b"\n\n", 0, 65538)
    audit.check("commit_header_bound", 0 <= end <= 65536)
    lines = raw[:end].split(b"\n")
    trees = [line[5:] for line in lines if line.startswith(b"tree ")]
    parents = [line[7:] for line in lines if line.startswith(b"parent ")]
    audit.check("commit_tree_header", len(trees) == 1 and lines[0].startswith(b"tree ")
                and re.fullmatch(rb"[0-9a-f]{40}", trees[0]) is not None)
    audit.check("commit_parent_headers", len(parents) <= 2
                and all(re.fullmatch(rb"[0-9a-f]{40}", p) is not None for p in parents))
    identity = {"tree": trees[0].decode("ascii"), "parents": [p.decode("ascii") for p in parents]}
    audit.observe("commit_tree", identity["tree"], SHA40)
    for i, parent in enumerate(identity["parents"]):
        audit.observe("commit_parent_" + str(i), parent, SHA40)
    return identity


def source_identity(discovery, env, event_identity=None, audit=None):
    audit = audit or IdentityAudit()
    audit.stage = "source"
    lines = discovery.command(["git", "--no-replace-objects", "rev-parse", "HEAD", "HEAD^{tree}"],
                              "source-head", 10).decode("ascii", errors="replace").splitlines()
    audit.check("checkout_identity_shape", len(lines) == 2)
    audit.observe("checkout_commit", lines[0], SHA40)
    audit.observe("checkout_tree", lines[1], SHA40)
    audit.check("checkout_commit_matches", lines[0] == env["GITHUB_SHA"] == env["RECOVERY_TESTED_COMMIT"])
    audit.check("checkout_tree_matches", lines[1] == env["RECOVERY_TESTED_TREE"])
    audit.check("checkout_clean", discovery.command(["git", "status", "--porcelain=v1"], "source-status", 10) == b"")
    if env["GITHUB_EVENT_NAME"] == "pull_request":
        audit.check("pr_event_identity_available", isinstance(event_identity, dict) and event_identity.get("kind") == "pull_request")
        raw = discovery.command(["git", "--no-replace-objects", "cat-file", "commit", env["GITHUB_SHA"]],
                                "source-commit", 10, retain_output=False)
        actual = parse_commit_identity(raw, audit)
        audit.check("commit_tree_matches", actual["tree"] == lines[1])
        audit.check("pr_parent_count", len(actual["parents"]) == 2)
        audit.check("pr_head_is_parent", event_identity["head"]["sha"] in actual["parents"])
        audit.check("pr_base_is_parent", event_identity["base"]["sha"] in actual["parents"])
        # Conservative snapshot policy; base advancement can fail this gate.
        # Parent order is observed, not assumed to be part of GitHub's contract.
        audit.check("pr_snapshot_parents_match", sorted(actual["parents"]) ==
                    sorted([event_identity["base"]["sha"], event_identity["head"]["sha"]]))
        discovery.check()
        controller.write_json(discovery.output / "source-identity.json", actual)
        discovery.check()
    audit.stage = "source_verified"
    return lines


def make_envelope(root, work, profile_hash, workflow_hash, host, source, selection, developer_dir, xcodegen, hashes):
    now = controller.utc_now()
    grant = {"schema_version": 1, "native_execution_authorized": True,
             "not_before": now.isoformat(), "expires_at": (now + dt.timedelta(seconds=1860)).isoformat(),
             "source_commit": source[0], "source_tree": source[1], "worktree": str(root), "output_root": str(work / "run"),
             "controller_sha256": hashes["controller"], "collector_sha256": hashes["collector"],
             "device_type": selection["device_type"], "runtime": selection["runtime"],
             "xcodegen_path": str(xcodegen), "xcodegen_sha256": hashes["xcodegen"],
             "developer_dir": str(developer_dir), "journey_run_id": str(uuid.uuid4()).upper()}
    # Embedding never bypasses the unchanged standalone controller validator.
    controller.validate_grant(grant, now=controller.utc_now(), script_root=root)
    return {"schema_version": 1, "kind": "github-hosted-recovery", "hosted_identity": host,
            "source_commit": source[0], "source_tree": source[1], "profile_sha256": profile_hash,
            "workflow_sha256": workflow_hash, "tool_hashes": hashes, "selection": selection,
            "controller_grant": grant, "policy": POLICY,
            "ephemeral_paths_are_not_durable_artifacts": True}


class HostedRecoveryRun(controller.RecoveryRun):
    def build(self):
        super().build()
        from recovery_retention import capture_build_identity
        capture_build_identity(self, self.output.parent / "build-identity", self.guard)


def run_hosted(expected, *, root=ROOT, env=None, clock=time.monotonic, disk_usage=shutil.disk_usage):
    env = dict(os.environ if env is None else env)
    start = clock()
    outer_end = start + 2100
    work, upload, runner, discovery = None, None, None, None
    context, primary, code = {}, None, 1
    audit = IdentityAudit()
    try:
        with Alarm(start + 120, clock) as alarm:
            profile, profile_raw = load_profile(root, expected)
            host = validate_host(env, profile, root)
            for key in ("GITHUB_SHA", "RECOVERY_TESTED_COMMIT", "RECOVERY_TESTED_TREE"):
                audit.observe(key, env[key], SHA40)
            audit.observe("run_ref", env["GITHUB_REF"], r"refs/[A-Za-z0-9_./-]+")
            audit.stage = "event_read"
            event_name = env.get("GITHUB_EVENT_PATH", "")
            audit.check("event_path_type", isinstance(event_name, str))
            event_path = Path(event_name)
            audit.check("event_path_absolute", event_path.is_absolute())
            try:
                event_raw = bounded_read(event_path, 4 * controller.MIB)
            except Failure:
                audit.check("event_file_bounded_regular", False)
            except (OSError, ValueError) as error:
                audit.observe("event_file_errno", getattr(error, "errno", None))
                audit.check("event_file_readable", False)
            audit.check("event_file_bounded_regular", True)
            try:
                event = json.loads(event_raw)
            except (ValueError, UnicodeError, RecursionError):
                audit.check("event_json", False)
            audit.check("event_json", True)
            host["event"] = validate_event(event, env, audit)
            temporary = Path(env["RUNNER_TEMP"])
            proposed, upload = temporary / "room-recovery-work", temporary / "room-recovery-upload"
            require(not any(p.exists() or p.is_symlink() for p in (proposed, upload)), "Attempt output already exists", Failure)
            admission_free_bytes = disk_usage(temporary).free
            require(admission_free_bytes >= profile["admission_free_bytes"], "Admission requires 24 GiB free", Failure)
            proposed.mkdir(mode=0o700)
            work = proposed
            preflight = work / "preflight"
            preflight.mkdir(mode=0o700)
            context = {"source_commit": env["GITHUB_SHA"], "source_tree": env["RECOVERY_TESTED_TREE"],
                       "profile_sha256": expected, "hosted_identity": host, "controller_exit_code": None,
                       "primary_error": None, "cleanup_errors": [], "admission_free_bytes": admission_free_bytes}
            workflow_raw = bounded_read(root / profile["workflow_path"])
            context["workflow_sha256"] = controller.sha(workflow_raw)
            (preflight / "recovery-hosted-profile.json").write_bytes(profile_raw)
            (preflight / "ci.yml").write_bytes(workflow_raw)
            controller.write_json(preflight / "hosted-identity.json", host)
            # No tokens/context dump: native tools receive only their ordinary
            # OS/tool environment. Git identity checks need no credentials.
            child_env = {k: v for k, v in env.items() if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "DEVELOPER_DIR"}}
            discovery = Discovery(root, preflight, child_env, alarm, disk_usage=disk_usage)
            source = source_identity(discovery, env, host["event"], audit)
            hashes = {name: controller.sha(bounded_read(root / "scripts" / path)) for name, path in {
                "controller": "run-recovery-journey.py", "collector": "recovery_collector.py",
                "adapter": "recovery_hosted.py", "retention": "recovery_retention.py",
                "xcodegen_installer": "install-xcodegen.py"}.items()}
            # All source/host/profile checks precede the first native command.
            selected = discovery.command(["xcode-select", "-p"], "xcode-select", 10).decode().strip()
            developer = Path(selected)
            require(developer.is_absolute() and developer.is_dir() and developer.name == "Developer",
                    "Selected Xcode developer directory is invalid", Failure)
            require(not env.get("DEVELOPER_DIR") or Path(env["DEVELOPER_DIR"]).resolve() == developer.resolve(),
                    "DEVELOPER_DIR differs from selected Xcode", Failure)
            developer = developer.resolve()
            discovery.env["DEVELOPER_DIR"] = str(developer)
            xcode_version = discovery.command(["xcodebuild", "-version"], "xcode-version", 10).decode().strip()
            require(re.fullmatch(r"Xcode [0-9.]+\nBuild version [A-Za-z0-9]+", xcode_version), "Invalid Xcode version response", Failure)
            sdk = discovery.command(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], "sdk-version", 10).decode().strip()
            inventory = json.loads(discovery.command(["xcrun", "simctl", "list", "--json"], "simulator-inventory", 60))
            selection = select_runtime(inventory, sdk)
            selection.update({"developer_dir": str(developer), "xcode_version": xcode_version})
            controller.write_json(preflight / "selection.json", selection)
            installed = discovery.command([sys.executable, str(root / "scripts/install-xcodegen.py")], "install-xcodegen", 70).decode().strip()
            xcodegen = root / ".build/tools/xcodegen-2.46.0/xcodegen/bin/xcodegen"
            require(installed == str(xcodegen) and xcodegen.resolve() == xcodegen and os.access(xcodegen, os.X_OK),
                    "Installer returned an unexpected executable", Failure)
            hashes["xcodegen"] = controller.sha(bounded_read(xcodegen, 64 * controller.MIB))
            context["tool_hashes"] = hashes
            envelope = make_envelope(root, work, expected, context["workflow_sha256"], host, source, selection, developer, xcodegen, hashes)
            controller.write_json(work / "hosted-grant-envelope.json", envelope)
            discovery.check()
        require(outer_end - clock() >= 1980, "Insufficient full controller and retention budget", Deadline)
        controller.validate_grant(envelope["controller_grant"], now=controller.utc_now(), script_root=root)
        runner = HostedRecoveryRun(envelope["controller_grant"], clock=clock, disk_usage=disk_usage)
        code = runner.execute()
        context["controller_exit_code"] = code
        context["primary_error"] = runner.record.get("primary_error") or runner.record.get("finalization_error")
        context["cleanup_errors"] = runner.record.get("cleanup_errors", [])
    except BaseException as error:
        primary = {"type": type(error).__name__, "message": str(error)}
        code = error.exit_code if isinstance(error, controller.RunFailure) else 1
        context["primary_error"] = context.get("primary_error") or primary
    if runner is not None:
        context["controller_exit_code"] = runner.record.get("exit_code", context.get("controller_exit_code"))
        context["primary_error"] = runner.record.get("primary_error") or context.get("primary_error")
        context["cleanup_errors"] = runner.record.get("cleanup_errors", context.get("cleanup_errors", []))
    if discovery:
        context.setdefault("cleanup_errors", []).extend(discovery.cleanup_errors)
    if context.get("primary_error") or context.get("cleanup_errors"):
        code = code or 1
    context["identity_audit"] = audit.snapshot()
    if work is not None:
        try:
            with Alarm(min(outer_end, clock() + 180), clock) as alarm:
                from recovery_retention import package_evidence
                def retention_guard():
                    alarm.check()
                    require(disk_usage(work).free >= profile["abort_free_bytes"], "Retention disk abort floor reached")
                    alarm.check()
                retention_guard()
                controller.write_json(work / "preflight/adapter-result.json", context)
                report = package_evidence(work, upload, context, retention_guard, collector=runner.collector if runner else None)
                retention_guard()
                if not report.get("complete") or report.get("status") != "COMPLETE":
                    code = code or 1
        except BaseException as error:
            code = code or (error.exit_code if isinstance(error, controller.RunFailure) else 1)
            primary = primary or {"type": type(error).__name__, "message": str(error)}
    if clock() >= outer_end:
        code = 124
    return {"exit_code": code, "status": "COMPLETE" if code == 0 else "INCOMPLETE", "primary_error": context.get("primary_error") or primary,
            "upload_root": str(upload) if work is not None else None,
            "identity_audit": audit.snapshot()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-sha256", required=True)
    args = parser.parse_args(argv)
    result = run_hosted(args.profile_sha256)
    controller.emit_summary(result)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
