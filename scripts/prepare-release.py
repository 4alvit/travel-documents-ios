#!/usr/bin/env python3
"""Prepare a verified GitHub source/Simulator release. Never publishes or rebuilds."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import tarfile
import time
import zipfile

REPOSITORY = "4alvit/travel-documents-ios"
WORKFLOW = ".github/workflows/ci.yml"
SCOPE = "github-source-simulator"
MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_JSON = 8 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
PAYLOAD = ("TripDocket-Simulator.zip", "TripDocket-source.tar.gz", "provenance.json")
JOBS = {
    "Swift, hosted tests and purchase UI", "Accessibility, localization and guidance UI",
    "iPad privacy and support (en-US)", "iPad privacy and support (ru-RU)",
    "Free backup and recovery", "CI gate", "Change scope",
}
BIOMETRIC_TESTS = {
    "testFailedAndCancelledAuthenticationKeepDocumentsPrivate",
    "testOriginalPreviewIsPrivateAcrossBackgroundAndReturn",
    "testExportShareIsPrivateAcrossBackgroundAndReturn",
    "testEditDraftIsPrivateAcrossBackgroundAndReturn",
    "testUnsavedDocumentDraftSurvivesBackgroundAfterAuthentication",
    "testMaximumTypeUnlockIsReachablePortraitAndLandscapeWithoutAuthenticationSuccess",
}
TESTS = {
    "release-smoke": {"ordinary-release-launch"},
    "batch-import": {
        "testVerifiedPurchaseAndRestoreFromLocalHistory",
        "testBatchPrepareFilesProviderDirectly",
        "testNativeCreateOwnedFilesFolder",
        "testNativeSaveSeedsBothSyntheticOriginals",
        "testRealFilesBatchRequiresEveryReviewAndPreservesOriginals",
    },
    "privacy-biometric": BIOMETRIC_TESTS,
}


class InvalidRelease(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidRelease(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def valid_hash(value, length=64):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def decode_json(data):
    require(len(data) <= MAX_JSON, "JSON exceeds size limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(InvalidRelease("non-finite JSON")))


def encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def read_regular(path, maximum=MAX_JSON):
    require(not path.is_symlink() and path.is_file() and path.resolve(strict=True) == path.absolute(), "expected regular file without symbolic-link parents: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, "file exceeds size limit: " + str(path))
    return data


def command(argv, cwd=None, maximum=MAX_DOWNLOAD, timeout=180):
    # Bound elapsed time and bytes while consuming the pipe, not after EOF.
    with subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            data = bytearray()
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, "command deadline exceeded: " + argv[0])
                    for key, _ in selector.select(min(remaining, 1)):
                        chunk = os.read(key.fd, min(1024 * 1024, maximum - len(data) + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        data.extend(chunk)
                        require(len(data) <= maximum, "command output exceeds limit: " + argv[0])
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            require(code == 0, "command failed (exit %d): %s" % (code, argv[0]))
            return bytes(data)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


class GitHub:
    def api(self, path):
        return decode_json(command(["gh", "api", "--hostname", "github.com", "--method", "GET", path], maximum=MAX_JSON))

    def pages(self, path, field):
        result = []
        for page in range(1, 101):
            values = self.api(path + ("&" if "?" in path else "?") + "per_page=100&page=" + str(page))[field]
            require(isinstance(values, list), "invalid paginated API response")
            result.extend(values)
            if len(values) < 100:
                return result
        raise InvalidRelease("API pagination limit exceeded")

    def binary(self, path, *, accept="application/octet-stream"):
        require(accept in {"application/octet-stream", "application/vnd.github+json"}, "unsupported download media type")
        return command(["gh", "api", "--hostname", "github.com", "--method", "GET", "-H", "Accept: " + accept, path])


def validate_run(run, jobs, commit, run_id):
    require(run.get("id") == run_id, "CI run ID mismatch")
    require(run.get("head_sha") == commit and run.get("head_branch") == "main", "CI source mismatch")
    require(run.get("event") in {"push", "workflow_dispatch"}, "CI must be a main push or dispatch")
    require(run.get("path") == WORKFLOW, "unexpected CI workflow")
    for field in ("repository", "head_repository"):
        require(run.get(field, {}).get("full_name") == REPOSITORY, "unexpected CI repository")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "CI is not successful and complete")
    require(type(run.get("run_attempt")) is int and run["run_attempt"] > 0, "invalid CI attempt")
    require(len(jobs) == len(JOBS) and {job.get("name") for job in jobs} == JOBS, "required CI jobs missing or duplicated")
    for job in jobs:
        require(job.get("status") == "completed" and job.get("conclusion") == "success", "CI job did not pass: " + str(job.get("name")))
        require(job.get("head_sha") == commit and job.get("run_id") == run_id, "CI job source/run mismatch")
        require(job.get("run_attempt") == run["run_attempt"], "CI job attempt mismatch")
    return {key: run[key] for key in ("id", "run_attempt", "head_sha", "head_branch", "event", "path", "conclusion")}


def select_artifact(artifacts, run, commit):
    name = "TripDocket-simulator-%s-%s-%s" % (commit, run["id"], run["run_attempt"])
    matches = [item for item in artifacts if item.get("name") == name]
    require(len(matches) == 1, "exact CI artifact missing or duplicated")
    artifact = matches[0]
    require(artifact.get("expired") is False, "CI artifact expired")
    require(type(artifact.get("size_in_bytes")) is int and 0 < artifact["size_in_bytes"] <= MAX_DOWNLOAD, "CI artifact size invalid")
    origin = artifact.get("workflow_run", {})
    require(origin.get("id") == run["id"] and origin.get("head_sha") == commit, "CI artifact run/source mismatch")
    require(origin.get("repository_id") == run["repository"]["id"] and origin.get("head_repository_id") == run["head_repository"]["id"], "CI artifact repository mismatch")
    require(origin.get("head_branch") == "main", "CI artifact branch mismatch")
    require(isinstance(artifact.get("digest"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]), "CI artifact digest missing")
    return artifact


def archive_members(data, *, strict_modes=False, allowed_roots=None):
    require(0 < len(data) <= MAX_DOWNLOAD, "invalid ZIP size")
    files, seen, total = {}, set(), 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(0 < len(archive.infolist()) <= 10000, "invalid ZIP member count")
        for item in archive.infolist():
            name = item.filename.rstrip("/")
            require(item.orig_filename == item.filename and item.filename == name + ("/" if item.is_dir() else ""), "noncanonical ZIP member spelling")
            parts = PurePosixPath(name).parts
            require(allowed_roots is None or (parts and parts[0] in allowed_roots), "unexpected ZIP root")
            require(name and not item.filename.startswith("/") and "\\" not in name and "\x00" not in name,
                    "unsafe ZIP member")
            require(all(part not in {".", "..", ""} for part in item.filename.rstrip("/").split("/")), "noncanonical ZIP member")
            require(name not in seen, "duplicate ZIP member")
            seen.add(name)
            require(not item.flag_bits & 1, "encrypted ZIP member")
            mode = item.external_attr >> 16
            kind = stat.S_IFMT(mode)
            allowed = {stat.S_IFDIR} if item.is_dir() else {stat.S_IFREG}
            if not strict_modes:
                allowed.add(0)
            require(kind in allowed and not mode & 0o7000, "ZIP contains links or special files")
            total += item.file_size
            require(total <= MAX_EXPANDED and item.file_size <= MAX_EXPANDED, "ZIP expanded size exceeded")
            if item.is_dir():
                require(item.file_size == 0, "nonempty ZIP directory")
            else:
                files[name] = (archive.read(item), stat.S_IMODE(mode))
    # A file cannot also be an ancestor directory, even with a different spelling.
    require(not any(str(parent) in files for name in seen for parent in PurePosixPath(name).parents if str(parent) != "."), "ZIP file/directory collision")
    return files


def parse_checksums(data):
    result = {}
    for line in data.decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        require(match is not None, "invalid checksum line")
        sha, name = match.groups()
        require(name not in result and name != "SHA256SUMS", "duplicate or recursive checksum")
        result[name] = sha
    require(result, "empty checksum file")
    return result


def verify_checksums(files):
    require("SHA256SUMS" in files, "checksums missing")
    expected = parse_checksums(files["SHA256SUMS"])
    require(set(files) == set(expected) | {"SHA256SUMS"}, "unlisted or missing asset")
    require(all(digest(files[name]) == sha for name, sha in expected.items()), "asset checksum mismatch")
    return expected


def validate_payload(files, commit, tree, run, version):
    require(set(files) == {"TripDocket-Simulator.zip", "provenance.json", "SHA256SUMS"}, "unexpected CI artifact contents")
    verify_checksums(files)
    provenance = decode_json(files["provenance.json"])
    source, build, artifact = (provenance.get(key, {}) for key in ("source", "build", "artifact"))
    require(provenance.get("schema_version") == 1 and source.get("commit") == commit and source.get("tree") == tree and source.get("clean_checkout") is True, "producer source mismatch")
    require(build.get("configuration") == "Release" and build.get("sdk") == "iphonesimulator" and build.get("code_signing_allowed") is False and build.get("successful_verify_receipt_commit") == commit, "producer build identity mismatch")
    ci = provenance.get("ci", {})
    for key, expected in {"GITHUB_WORKFLOW": "CI", "GITHUB_JOB": "validate", "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_ID": str(run["id"]), "GITHUB_RUN_ATTEMPT": str(run["run_attempt"]), "GITHUB_SHA": commit, "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": run["event"]}.items():
        require(ci.get(key) == expected, "producer CI identity mismatch: " + key)
    zip_data = files["TripDocket-Simulator.zip"]
    require(artifact.get("filename") == "TripDocket-Simulator.zip" and artifact.get("sha256") == digest(zip_data) and artifact.get("source_bytes_and_unix_modes_match_zip") is True, "producer ZIP mismatch")
    app = archive_members(zip_data, strict_modes=True, allowed_roots={"Tripfolio.app", "__MACOSX"})
    require(all(name.startswith("Tripfolio.app/") or name.startswith("__MACOSX/") for name in app), "unexpected app ZIP root")
    actual_files = {name: value for name, value in app.items() if name.startswith("Tripfolio.app/")}
    executable = actual_files.get("Tripfolio.app/Tripfolio")
    require(executable is not None and executable[0] and executable[1] & 0o111, "app executable missing or not executable")
    require(artifact.get("executable_sha256") == digest(executable[0]) and artifact.get("app_file_count") == len(actual_files), "app executable or file count mismatch")
    import plistlib
    info = plistlib.loads(actual_files["Tripfolio.app/Info.plist"][0])
    require(info.get("CFBundleExecutable") == "Tripfolio" and info.get("CFBundlePackageType") == "APPL", "invalid app bundle")
    require(info.get("DTPlatformName") == "iphonesimulator" and info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"], "not a Simulator app")
    require(info.get("CFBundleShortVersionString") == version, "app release version mismatch")
    return provenance


def required_receipts(stage):
    return {"release-smoke"} if stage == "beta" else set(TESTS)


def exact_fields(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names), "unexpected or missing fields in " + label)


def validate_public_text(value):
    require(isinstance(value, str) and 0 < len(value) <= 2000 and value.isprintable(), "receipt limitations must be bounded single-line strings")
    # Deliberately small accidental-disclosure checks, not a complete secret or
    # personal-data detector. An operator still reviews these public records.
    markers = (
        r"(?<![\w:/])/(?!/)[^\s,;!?\"<>]+",  # POSIX absolute paths, not ordinary HTTPS URLs
        r"\b[A-Za-z]:[\\/]|\\\\[^\s\\]+\\|(?<!\w)~[/\\]|\$HOME[/\\]|file://",
        r"(?i)\b(?:raw_commands|cwd|argv|command_line|environment|env)[\"']?\s*[:=]",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})\b",
        r"(?i)\b(?:password|passwd|secret|token|api[_ -]?key|authorization)[\"']?\s*[:=]\s*\S+|\bBearer\s+[A-Za-z0-9._~+/-]+",
        r"https?://[^/\s@]+@",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    )
    require(not any(re.search(pattern, value) for pattern in markers), "receipt text resembles private paths, raw commands, or credentials; sanitize it before publication")


def validate_receipt(data, kind, commit, tree, zip_sha):
    receipt = decode_json(data)
    exact_fields(receipt, {"schema_version", "kind", "source", "release_artifact_sha256", "status", "cleanup_verified", "tests", "runtime_warnings", "tested_product", "limitations"}, "execution receipt")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1 and receipt["kind"] == kind, "invalid execution receipt kind/version")
    exact_fields(receipt["source"], {"commit", "tree"}, "receipt source")
    require(receipt["source"] == {"commit": commit, "tree": tree}, "execution receipt source mismatch")
    require(receipt["release_artifact_sha256"] == zip_sha, "execution receipt candidate artifact mismatch")
    require(receipt["status"] == "passed" and receipt["cleanup_verified"] is True, "execution or cleanup not passed")
    tests = receipt["tests"]
    require(isinstance(tests, list) and len(tests) == len(TESTS[kind]), "execution receipt test count mismatch")
    for item in tests:
        exact_fields(item, {"name", "result"}, "receipt test")
        require(isinstance(item["name"], str) and item["result"] == "passed", "execution receipt includes nonpassing test")
    require({item["name"] for item in tests} == TESTS[kind], "execution receipt test set mismatch")
    require(receipt["runtime_warnings"] == [], "execution receipt has warnings or missing warning result")
    product = receipt["tested_product"]
    fields = {"configuration", "files_manifest_sha256"}
    if kind == "release-smoke":
        fields.add("archive_sha256")
    exact_fields(product, fields, "tested product")
    require(valid_hash(product["files_manifest_sha256"]), "tested product manifest identity missing")
    if kind == "release-smoke":
        require(product["configuration"] == "Release" and product["archive_sha256"] == zip_sha, "smoke did not test the Release payload")
    else:
        require(product["configuration"] == "Debug", "functional receipt must describe its actual Debug test product")
    limitations = receipt["limitations"]
    require(isinstance(limitations, list) and len(limitations) <= 20, "execution receipt limitations must be a bounded string list")
    for limitation in limitations:
        validate_public_text(limitation)
    return receipt


def load_evidence(path, stage, commit, tree, zip_sha):
    raw = read_regular(path)
    evidence = decode_json(raw)
    require(evidence.get("schema_version") == 1, "unknown operator evidence version")
    review = evidence.get("review", {})
    require(review.get("status") == "approved" and review.get("blockers") == [], "review not approved or blockers remain")
    references = evidence.get("receipts", {})
    require(isinstance(references, dict) and required_receipts(stage) <= set(references) <= set(TESTS), "required execution receipts missing")
    blobs, records = {}, {}
    for kind, reference in references.items():
        receipt_path = Path(reference["path"])
        if not receipt_path.is_absolute():
            receipt_path = path.parent / receipt_path
        data = read_regular(receipt_path)
        require(valid_hash(reference.get("sha256")) and digest(data) == reference["sha256"], "execution receipt hash mismatch")
        validate_receipt(data, kind, commit, tree, zip_sha)
        filename = kind + "-receipt.json"
        blobs[filename] = data
        records[kind] = {"file": filename, "sha256": digest(data)}
    return blobs, records, {"status": "approved", "blockers": []}, digest(raw)


def source_archive(repo, commit):
    # Read Git objects directly: neither dirty files nor export-ignore/export-subst
    # attributes may silently omit or rewrite bytes in this exact-source archive.
    entries = command(["git", "ls-tree", "-r", "-z", "--full-tree", commit], cwd=repo, maximum=MAX_JSON)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo("TripDocket-source/")
        root.type, root.mode, root.mtime = tarfile.DIRTYPE, 0o755, 0
        archive.addfile(root)
        total = 0
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            header, raw_name = entry.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            require(kind == "blob" and mode in {"100644", "100755"}, "source tree contains a link or submodule")
            name = raw_name.decode("utf-8")
            require(name and not name.startswith("/") and "\\" not in name and all(part not in {"", ".", ".."} for part in name.split("/")), "unsafe source path")
            data = command(["git", "cat-file", "blob", oid], cwd=repo)
            total += len(data)
            require(total <= MAX_EXPANDED, "source archive exceeds limit")
            item = tarfile.TarInfo("TripDocket-source/" + name)
            item.size, item.mode, item.mtime = len(data), int(mode, 8) & 0o777, 0
            archive.addfile(item, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as stream:
        stream.write(output.getvalue())
    require(compressed.tell() <= MAX_DOWNLOAD, "compressed source archive exceeds limit")
    return compressed.getvalue()


def validate_predecessor(files, stage, version, commit, tree, payload):
    verify_checksums(files)
    acceptance = decode_json(files["acceptance.json"])
    previous_stage = {"rc": "beta", "stable": "rc"}[stage]
    require(acceptance.get("schema_version") == 1 and acceptance.get("scope") == SCOPE and acceptance.get("stage") == previous_stage and acceptance.get("version") == version, "predecessor stage/scope/version mismatch")
    require(acceptance.get("source") == {"commit": commit, "tree": tree}, "predecessor source mismatch")
    require(acceptance.get("payload") == payload, "predecessor payload manifest mismatch")
    for name, expected in payload.items():
        require(name in files and digest(files[name]) == expected["sha256"] and len(files[name]) == expected["size"], "predecessor payload bytes differ")
    receipts = acceptance.get("execution_receipts", {})
    require(required_receipts(previous_stage) <= set(receipts) <= set(TESTS), "predecessor execution receipts incomplete")
    require(set(files) == set(PAYLOAD) | {"acceptance.json", "SHA256SUMS"} | {kind + "-receipt.json" for kind in receipts}, "unreferenced predecessor asset")
    for kind, reference in receipts.items():
        filename = kind + "-receipt.json"
        require(reference.get("file") == filename and filename in files and reference.get("sha256") == digest(files[filename]), "predecessor execution receipt hash mismatch")
        validate_receipt(files[filename], kind, commit, tree, payload["TripDocket-Simulator.zip"]["sha256"])
    require(acceptance.get("review", {}).get("status") == "approved" and acceptance["review"].get("blockers") == [], "predecessor review not accepted")
    return acceptance


def previous_release(github, tag, stage, version, commit, tree, payload):
    suffix = "beta" if stage == "rc" else "rc"
    require(re.fullmatch(re.escape("v" + version + "-" + suffix + ".") + r"[1-9][0-9]*", tag), "invalid predecessor tag")
    base = "repos/" + REPOSITORY
    release = github.api(base + "/releases/tags/" + tag)
    require(release.get("tag_name") == tag and release.get("draft") is False and release.get("prerelease") is True, "predecessor is not a published prerelease")
    ref = github.api(base + "/git/ref/tags/" + tag)["object"]
    for _ in range(5):
        if ref.get("type") == "commit":
            break
        require(ref.get("type") == "tag" and valid_hash(ref.get("sha"), 40), "invalid predecessor tag object")
        ref = github.api(base + "/git/tags/" + ref["sha"])["object"]
    require(ref.get("type") == "commit" and ref.get("sha") == commit, "predecessor tag commit mismatch")
    allowed = set(PAYLOAD) | {"acceptance.json", "SHA256SUMS"} | {kind + "-receipt.json" for kind in TESTS}
    files = {}
    for asset in release.get("assets", []):
        name = asset.get("name")
        require(name in allowed and name not in files, "unexpected or duplicate predecessor asset")
        require(asset.get("state") == "uploaded" and 0 < asset.get("size", 0) <= MAX_DOWNLOAD, "invalid predecessor asset")
        data = github.binary(base + "/releases/assets/" + str(asset["id"]))
        require(len(data) == asset["size"], "predecessor asset size mismatch")
        if asset.get("digest") is not None:
            require(asset["digest"] == "sha256:" + digest(data), "predecessor API digest mismatch")
        files[name] = data
    validate_predecessor(files, stage, version, commit, tree, payload)
    return {"tag": tag, "release_id": release["id"], "acceptance_sha256": digest(files["acceptance.json"])}


def write_output(output, files, repo):
    require(output.is_absolute(), "output must be absolute")
    parent = output.parent.resolve(strict=True)
    require(parent == output.parent.absolute(), "output parent must not contain symbolic links or traversal")
    target = parent / output.name
    require(not target.is_relative_to(repo.resolve()), "output must be outside the repository")
    require(not os.path.lexists(target), "output already exists; refusing to update it")
    # mkdir is exclusive even if another writer races the preflight check.
    target.mkdir()
    created = []
    try:
        for name, data in files.items():
            require(PurePosixPath(name).name == name and name not in {".", ".."}, "unsafe output filename")
            path = target / name
            with path.open("xb") as stream:
                identity = os.fstat(stream.fileno())
                created.append((path, (identity.st_dev, identity.st_ino)))
                stream.write(data)
    except BaseException:
        for path, identity in created:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == identity:
                    path.unlink()
            except OSError:
                pass  # Retain the original failure; never remove a replacement.
        try:
            target.rmdir()
        except OSError:
            pass  # Never delete somebody else's concurrently-created data.
        raise
    return target


def prepare(args, github=None):
    require(valid_hash(args.commit, 40), "commit must be a full lowercase SHA-1")
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version), "version must be major.minor.patch")
    require(args.run_id > 0, "invalid CI run ID")
    require((args.stage == "beta") == (args.predecessor_tag is None), "only RC/stable require a predecessor tag")
    repo = args.repo.resolve(strict=True)
    require(args.output.is_absolute() and not os.path.lexists(args.output), "output must be new and absolute")
    tree = command(["git", "rev-parse", args.commit + "^{tree}"], cwd=repo, maximum=1024).decode().strip()
    require(valid_hash(tree, 40), "candidate tree is invalid")
    github = github or GitHub()
    base = "repos/" + REPOSITORY
    run_path = base + "/actions/runs/" + str(args.run_id)
    run = github.api(run_path)
    attempt = run.get("run_attempt", 0)
    jobs = github.pages(run_path + "/attempts/" + str(attempt) + "/jobs", "jobs")
    ci = validate_run(run, jobs, args.commit, args.run_id)
    artifacts = github.pages(run_path + "/artifacts", "artifacts")
    artifact = select_artifact(artifacts, run, args.commit)
    archive = github.binary(base + "/actions/artifacts/" + str(artifact["id"]) + "/zip", accept="application/vnd.github+json")
    require(len(archive) == artifact["size_in_bytes"] and "sha256:" + digest(archive) == artifact["digest"], "downloaded CI artifact mismatch")
    files = {name: entry[0] for name, entry in archive_members(archive).items()}
    provenance = validate_payload(files, args.commit, tree, run, args.version)
    actual_parents = command(["git", "show", "-s", "--format=%P", args.commit], cwd=repo, maximum=2048).decode().strip().split()
    require(provenance["source"].get("parents") == actual_parents, "producer source parents mismatch")
    files.pop("SHA256SUMS")
    files["TripDocket-source.tar.gz"] = source_archive(repo, args.commit)
    payload = {name: {"size": len(files[name]), "sha256": digest(files[name])} for name in PAYLOAD}
    receipts, records, review, evidence_sha = load_evidence(args.evidence, args.stage, args.commit, tree, payload["TripDocket-Simulator.zip"]["sha256"])
    predecessor = None
    if args.predecessor_tag:
        predecessor = previous_release(github, args.predecessor_tag, args.stage, args.version, args.commit, tree, payload)
    # Do not silently use evidence from an older attempt after a rerun starts.
    latest = github.api(run_path)
    require(all(latest.get(key) == run.get(key) for key in ("id", "run_attempt", "head_sha", "head_branch", "event", "path", "status", "conclusion")), "CI run changed during preparation")
    acceptance = {
        "schema_version": 1, "scope": SCOPE, "stage": args.stage, "version": args.version,
        "source": {"commit": args.commit, "tree": tree}, "ci": ci,
        "jobs": [{key: job[key] for key in ("id", "name", "conclusion")} for job in jobs],
        "ci_artifact": {key: artifact[key] for key in ("id", "name", "digest")},
        "payload": payload, "execution_receipts": records, "review": review,
        "operator_evidence_sha256": evidence_sha, "predecessor": predecessor,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "limits": ["Operator execution receipts are trusted inputs, not cryptographic attestations.",
                   "Source/unsigned Simulator distribution only; physical-device, TestFlight and App Store gates remain separate.",
                   "Preparation does not publish a release or verify its future public downloads."],
    }
    files.update(receipts)
    files["acceptance.json"] = encode_json(acceptance)
    files["SHA256SUMS"] = "".join(digest(files[name]) + "  " + name + "\n" for name in sorted(files)).encode()
    return write_output(args.output, files, repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--stage", choices=("beta", "rc", "stable"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predecessor-tag")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        output = prepare(args)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, UnicodeError, zipfile.BadZipFile, tarfile.TarError, subprocess.TimeoutExpired) as error:
        parser.exit(1, "Release preparation failed: " + str(error) + "\n")
    print("Prepared and verified (not published): " + str(output))


if __name__ == "__main__":
    main()
