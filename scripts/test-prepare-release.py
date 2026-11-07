#!/usr/bin/env python3
"""Offline regression checks for release preparation; no build or publication."""
import argparse
import copy
import contextlib
import gzip
import importlib.util
import io
import itertools
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

SPEC = importlib.util.spec_from_file_location("prepare_release", Path(__file__).with_name("prepare-release.py"))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def zipped(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def checksummed(files):
    files = dict(files)
    files["SHA256SUMS"] = "".join(m.digest(data) + "  " + name + "\n" for name, data in sorted(files.items())).encode()
    return files


class Fixture:
    def __init__(self, root):
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        (self.repo / "source.swift").write_text("// synthetic source\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic fixture"], cwd=self.repo, check=True)
        self.commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=self.repo, text=True).strip()
        self.run = {"id": 10, "run_attempt": 2, "head_sha": self.commit, "head_branch": "main", "event": "push", "path": m.WORKFLOW, "status": "completed", "conclusion": "success", "repository": {"full_name": m.REPOSITORY, "id": 20}, "head_repository": {"full_name": m.REPOSITORY, "id": 20}}
        self.jobs = [{"id": index, "name": name, "run_id": 10, "run_attempt": 2, "head_sha": self.commit, "status": "completed", "conclusion": "success"} for index, name in enumerate(sorted(m.JOBS), 1)]
        executable = b"synthetic executable fixture"
        info = {"CFBundleExecutable": "Tripfolio", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.1.0", "DTPlatformName": "iphonesimulator", "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}
        self.app = zipped([("Tripfolio.app/", b"", stat.S_IFDIR | 0o755), ("Tripfolio.app/Tripfolio", executable, stat.S_IFREG | 0o755), ("Tripfolio.app/Info.plist", plistlib.dumps(info), stat.S_IFREG | 0o644)])
        self.provenance = {"schema_version": 1, "source": {"commit": self.commit, "tree": self.tree, "parents": [], "clean_checkout": True}, "build": {"configuration": "Release", "sdk": "iphonesimulator", "code_signing_allowed": False, "successful_verify_receipt_commit": self.commit}, "artifact": {"filename": "TripDocket-Simulator.zip", "sha256": m.digest(self.app), "source_bytes_and_unix_modes_match_zip": True, "executable_sha256": m.digest(executable), "app_file_count": 2}, "ci": {"GITHUB_WORKFLOW": "CI", "GITHUB_JOB": "validate", "GITHUB_REPOSITORY": m.REPOSITORY, "GITHUB_RUN_ID": "10", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": self.commit, "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push"}, "status": {"runtime_accepted": False, "ci_result_at_packaging": "not_final"}}
        self.files = checksummed({"TripDocket-Simulator.zip": self.app, "provenance.json": m.encode_json(self.provenance)})
        self.outer = zipped([(name, value, stat.S_IFREG | 0o644) for name, value in self.files.items()])
        self.artifact = {"id": 30, "name": "TripDocket-simulator-%s-10-2" % self.commit, "size_in_bytes": len(self.outer), "expired": False, "digest": "sha256:" + m.digest(self.outer), "workflow_run": {"id": 10, "head_sha": self.commit, "head_branch": "main", "repository_id": 20, "head_repository_id": 20}}
        self.evidence = root / "evidence.json"
        self.make_evidence(set(m.TESTS))

    def receipt(self, kind):
        product = {"configuration": "Release" if kind == "release-smoke" else "Debug", "files_manifest_sha256": "f" * 64}
        if kind == "release-smoke":
            product["archive_sha256"] = m.digest(self.app)
        return {"schema_version": 1, "kind": kind, "source": {"commit": self.commit, "tree": self.tree}, "release_artifact_sha256": m.digest(self.app), "status": "passed", "cleanup_verified": True, "tests": [{"name": name, "result": "passed"} for name in sorted(m.TESTS[kind])], "runtime_warnings": [], "tested_product": product, "limitations": ["Synthetic test fixture, not runtime acceptance."]}

    def make_evidence(self, kinds):
        references = {}
        for kind in kinds:
            filename = kind + ".json"
            data = m.encode_json(self.receipt(kind))
            (self.root / filename).write_bytes(data)
            references[kind] = {"path": filename, "sha256": m.digest(data)}
        self.evidence.write_bytes(m.encode_json({"schema_version": 1, "review": {"status": "approved", "blockers": []}, "receipts": references}))

    def args(self, stage="beta", output="output", tag=None):
        return argparse.Namespace(commit=self.commit, run_id=10, stage=stage, version="0.1.0", evidence=self.evidence, output=self.root / output, predecessor_tag=tag, repo=self.repo)

    def producer_attempt(self, attempt):
        self.provenance["ci"]["GITHUB_RUN_ATTEMPT"] = str(attempt)
        self.files = checksummed({"TripDocket-Simulator.zip": self.app, "provenance.json": m.encode_json(self.provenance)})
        self.outer = zipped([(name, value, stat.S_IFREG | 0o644) for name, value in self.files.items()])
        self.artifact.update(name="TripDocket-simulator-%s-10-%s" % (self.commit, attempt),
                             size_in_bytes=len(self.outer), digest="sha256:" + m.digest(self.outer))


class FakeGitHub:
    def __init__(self, fixture, previous=None):
        self.fixture = fixture
        self.previous = previous
        self.calls = []
        self.changed_run = False
        self.reads = 0

    def api(self, path):
        self.calls.append(("GET", path))
        if "/actions/runs/10" in path:
            self.reads += 1
            run = copy.deepcopy(self.fixture.run)
            if self.changed_run and self.reads > 1:
                run["run_attempt"] += 1
            return run
        if "/releases/tags/" in path:
            return {"id": 40, "tag_name": path.rsplit("/", 1)[1], "draft": False, "prerelease": True, "assets": [{"id": i, "name": name, "size": len(data), "state": "uploaded", "digest": "sha256:" + m.digest(data)} for i, (name, data) in enumerate(self.previous.items())]}
        if "/git/ref/tags/" in path:
            return {"object": {"type": "commit", "sha": self.fixture.commit}}
        raise AssertionError(path)

    def pages(self, path, field):
        self.calls.append(("GET", path))
        if field == "jobs":
            if path.endswith("/jobs?filter=all"):
                return copy.deepcopy(getattr(self.fixture, "history", self.fixture.jobs))
            if path.endswith("/jobs?filter=latest"):
                return copy.deepcopy(getattr(self.fixture, "latest_jobs", self.fixture.jobs))
            raise AssertionError("Expected explicit latest or complete job history: " + path)
        return copy.deepcopy([self.fixture.artifact])

    def binary(self, path, *, accept="application/octet-stream"):
        self.calls.append(("GET", path))
        if "/actions/artifacts/30/zip" in path:
            if accept != "application/vnd.github+json":
                raise AssertionError("Actions artifact endpoint requires GitHub JSON Accept")
            return self.fixture.outer
        if "/releases/assets/" in path:
            if accept != "application/octet-stream":
                raise AssertionError("Release asset endpoint requires binary Accept")
            return list(self.previous.values())[int(path.rsplit("/", 1)[1]) ]
        raise AssertionError(path)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.f = Fixture(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_beta_prepares_without_modifying_source_or_producer(self):
        (self.f.repo / "source.swift").write_text("user work remains dirty\n")
        (self.f.repo / "private.txt").write_text("must not be released\n")
        api = FakeGitHub(self.f)
        output = m.prepare(self.f.args(), api)
        files = {p.name: p.read_bytes() for p in output.iterdir()}
        m.verify_checksums(files)
        self.assertEqual(files["provenance.json"], self.f.files["provenance.json"])
        self.assertEqual((self.f.repo / "source.swift").read_text(), "user work remains dirty\n")
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(files["TripDocket-source.tar.gz"]))) as archive:
            self.assertNotIn("TripDocket-source/private.txt", archive.getnames())
            self.assertEqual(archive.extractfile("TripDocket-source/source.swift").read(), b"// synthetic source\n")
            self.assertTrue(all(item.mtime == 0 for item in archive.getmembers()))
        self.assertTrue(all(method == "GET" for method, _ in api.calls))
        self.assertEqual(files["TripDocket-source.tar.gz"], m.source_archive(self.f.repo, self.f.commit))

    def test_incomplete_failed_wrong_source_and_pull_request_runs_rejected(self):
        for key, value in [("status", "in_progress"), ("conclusion", "failure"), ("head_sha", "a" * 40), ("head_branch", "feature"), ("event", "pull_request"), ("path", "other.yml"), ("id", 11), ("run_attempt", 0)]:
            with self.subTest(key=key):
                run = copy.deepcopy(self.f.run); run[key] = value
                with self.assertRaises(m.InvalidRelease):
                    m.validate_run(run, self.f.jobs, self.f.commit, 10)

    def test_missing_duplicate_skipped_or_wrong_attempt_job_rejected(self):
        cases = [self.f.jobs[:-1], self.f.jobs[:-1] + [self.f.jobs[0]]]
        for field, value in [("status", "in_progress"), ("conclusion", "skipped"), ("head_sha", "a" * 40), ("run_id", 12), ("run_attempt", 1)]:
            jobs = copy.deepcopy(self.f.jobs); jobs[0][field] = value; cases.append(jobs)
        for jobs in cases:
            with self.subTest(jobs=jobs), self.assertRaises(m.InvalidRelease):
                m.validate_run(self.f.run, jobs, self.f.commit, 10)

    def partial_attempt(self):
        for job in self.f.jobs:
            if job["name"] in {"Change scope", m.BUILD_JOB}:
                job["run_attempt"] = 1
        self.f.history = copy.deepcopy(self.f.jobs)
        for job in self.f.jobs:
            if job["name"] in {"CI gate", "iPad privacy and support (ru-RU)"}:
                self.f.history.append({**job, "id": job["id"] + 100, "run_attempt": 1, "conclusion": "failure"})
        self.f.producer_attempt(1)

    def test_partial_rerun_preserves_actual_build_and_final_qualification_attempts(self):
        self.partial_attempt()
        api = FakeGitHub(self.f)
        output = m.prepare(self.f.args(), api)
        acceptance = m.decode_json((output / "acceptance.json").read_bytes())
        build = next(job for job in self.f.jobs if job["name"] == m.BUILD_JOB)
        self.assertEqual(acceptance["ci"]["run_attempt"], 2)
        self.assertEqual(acceptance["ci_artifact"]["producer_job_id"], build["id"])
        self.assertEqual(acceptance["ci_artifact"]["producer_run_attempt"], 1)
        self.assertEqual(next(job for job in acceptance["jobs"] if job["name"] == m.BUILD_JOB)["run_attempt"], 1)
        self.assertEqual((output / "provenance.json").read_bytes(), self.f.files["provenance.json"])
        self.assertEqual((output / "TripDocket-Simulator.zip").read_bytes(), self.f.app)
        self.assertEqual(sum(path.endswith("/jobs?filter=latest") for _, path in api.calls), 2)
        self.assertEqual(sum(path.endswith("/jobs?filter=all") for _, path in api.calls), 2)

    def test_partial_rerun_latest_view_can_contain_only_final_attempt(self):
        self.partial_attempt()
        self.f.latest_jobs = [job for job in self.f.jobs if job["run_attempt"] == 2]
        output = m.prepare(self.f.args(), FakeGitHub(self.f))
        acceptance = m.decode_json((output / "acceptance.json").read_bytes())
        self.assertEqual(len(acceptance["jobs"]), 7)
        self.assertEqual(acceptance["ci_artifact"]["producer_run_attempt"], 1)
        self.assertEqual((output / "provenance.json").read_bytes(), self.f.files["provenance.json"])

    def test_latest_view_cannot_omit_current_jobs_or_substitute_stale_rows(self):
        self.partial_attempt()
        current = [job for job in self.f.jobs if job["run_attempt"] == 2]
        old = next(job for job in self.f.history if job["name"] == "CI gate" and job["run_attempt"] == 1)
        cases = [current[:-1], current + [current[0]],
                 [old if job["name"] == "CI gate" else job for job in current],
                 [{**job, "id": job["id"] + 1000} for job in current]]
        for reported in cases:
            with self.subTest(reported=reported), self.assertRaises(m.InvalidRelease):
                m.reconcile_jobs(self.f.run, reported, self.f.history, self.f.commit, 10)

    def test_history_cannot_hide_newer_failure_or_substitute_old_job(self):
        self.partial_attempt()
        cases = []
        build = next(job for job in self.f.jobs if job["name"] == m.BUILD_JOB)
        for conclusion in ("failure", "success"):
            cases.append(self.f.history + [{**build, "id": 400, "run_attempt": 2, "conclusion": conclusion}])
        cases.append(self.f.history[:-1] + [{**self.f.history[-1], "id": build["id"]}])
        cases.append(self.f.history + [{**build, "id": 500}])
        cases.append([job for job in self.f.history if job["name"] != m.BUILD_JOB])
        for history in cases:
            with self.subTest(history=history), self.assertRaises(m.InvalidRelease):
                m.validate_run(self.f.run, self.f.jobs, self.f.commit, 10, history=history)

    def test_history_and_latest_require_positive_unique_ids_and_same_source(self):
        self.partial_attempt()
        for field, value in [("head_sha", "a" * 40), ("run_id", 99), ("run_attempt", 0),
                             ("run_attempt", 3), ("run_attempt", True), ("name", "unknown"),
                             ("id", 0), ("id", True)]:
            history = copy.deepcopy(self.f.history); history[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(m.InvalidRelease):
                m.validate_run(self.f.run, self.f.jobs, self.f.commit, 10, history=history)
        for value in (0, True, self.f.jobs[1]["id"]):
            jobs = copy.deepcopy(self.f.jobs); jobs[0]["id"] = value
            with self.subTest(value=value), self.assertRaises(m.InvalidRelease):
                m.validate_run(self.f.run, jobs, self.f.commit, 10, history=self.f.history)

    def test_final_gate_cannot_be_inherited_even_with_matching_history(self):
        jobs = [{**job, "run_attempt": 1} if job["name"] == "CI gate" else job for job in self.f.jobs]
        with self.assertRaises(m.InvalidRelease):
            m.validate_run(self.f.run, jobs, self.f.commit, 10, history=jobs)

    def test_old_build_cannot_be_relabelled_as_final_attempt(self):
        self.partial_attempt()
        self.f.producer_attempt(2)
        with self.assertRaises(m.InvalidRelease):
            m.prepare(self.f.args(), FakeGitHub(self.f))
        self.assertFalse(self.f.args().output.exists())

    def test_inherited_artifact_provenance_must_match_actual_producer(self):
        self.partial_attempt()
        self.f.producer_attempt(2)
        self.f.artifact["name"] = "TripDocket-simulator-%s-10-1" % self.f.commit
        with self.assertRaises(m.InvalidRelease):
            m.prepare(self.f.args(), FakeGitHub(self.f))
        self.assertFalse(self.f.args().output.exists())

    def test_changed_latest_job_identity_aborts_before_output(self):
        fixture = self.f
        class ChangedJobs(FakeGitHub):
            def pages(self, path, field):
                if field == "jobs" and path.endswith("filter=latest") and any(p.endswith("filter=all") for _, p in self.calls):
                    fixture.jobs[0]["id"] += 1000
                return super().pages(path, field)
        with self.assertRaisesRegex(m.InvalidRelease, "CI jobs changed during preparation"):
            m.prepare(self.f.args(), ChangedJobs(self.f))
        self.assertFalse(self.f.args().output.exists())

    def test_release_job_inventory_matches_actual_ci_with_matrix_expansion(self):
        # Read the actual workflow rather than deriving fixtures from JOBS, which
        # previously let a newly added scope job escape this strict inventory.
        workflow = (Path(__file__).resolve().parents[1] / m.WORKFLOW).read_text()
        blocks = re.split(r"(?m)^  ([a-z][a-z0-9_-]*):\n", workflow.split("\njobs:\n", 1)[1])
        names = []
        for job_id, body in zip(blocks[1::2], blocks[2::2]):
            with self.subTest(job=job_id):
                matches = re.findall(r"(?m)^    name: (.+)$", body)
                self.assertEqual(len(matches), 1, "Every CI job must have an explicit name")
                name = matches[0]
                if "${{ matrix.locale }}" in name:
                    locales = re.findall(r"(?m)^          - locale: ([a-z]{2}-[A-Z]{2})$", body)
                    self.assertTrue(locales, "The locale matrix must be explicitly expanded")
                    matrix = re.split(r"\n    (?=\S)", body.split("      matrix:\n", 1)[1], maxsplit=1)[0]
                    self.assertEqual(matrix.splitlines()[0], "        include:")
                    self.assertTrue(all(re.fullmatch(
                        r"          - locale: [a-z]{2}-[A-Z]{2}|            (?:step_minutes|job_minutes): [0-9]+",
                        line) for line in matrix.splitlines()[1:]), "Unknown matrix expansion")
                    names.extend(name.replace("${{ matrix.locale }}", locale) for locale in locales)
                else:
                    self.assertNotIn("    strategy:", body, "Expand any new matrix explicitly")
                    names.append(name)
        self.assertTrue(names)
        self.assertTrue(all("${{" not in name for name in names))
        self.assertEqual(len(names), len(set(names)), "Duplicate expanded CI job names")
        self.assertEqual(set(names), m.JOBS)

    def test_scope_job_must_pass_for_the_same_source_run_and_attempt(self):
        m.validate_run(self.f.run, self.f.jobs, self.f.commit, 10)
        scope = next(job for job in self.f.jobs if job["name"] == "Change scope")
        cases = [
            [job for job in self.f.jobs if job is not scope],
            self.f.jobs + [scope],
        ]
        for field, value in [("status", "in_progress"), ("conclusion", "skipped"),
                             ("conclusion", "failure"), ("head_sha", "a" * 40),
                             ("run_id", 12), ("run_attempt", 1)]:
            cases.append([{**job, field: value} if job is scope else job for job in self.f.jobs])
        for jobs in cases:
            with self.subTest(jobs=jobs), self.assertRaises(m.InvalidRelease):
                m.validate_run(self.f.run, jobs, self.f.commit, 10)

    def test_wrong_expired_duplicated_artifact_rejected(self):
        for field, value in [("name", "wrong-attempt"), ("expired", True), ("size_in_bytes", m.MAX_DOWNLOAD + 1), ("digest", None)]:
            with self.subTest(field=field):
                item = copy.deepcopy(self.f.artifact); item[field] = value
                with self.assertRaises(m.InvalidRelease): m.select_artifact([item], self.f.run, self.f.commit)
        with self.assertRaises(m.InvalidRelease): m.select_artifact([self.f.artifact] * 2, self.f.run, self.f.commit)
        item = copy.deepcopy(self.f.artifact); item["workflow_run"]["head_repository_id"] = 999
        with self.assertRaises(m.InvalidRelease): m.select_artifact([item], self.f.run, self.f.commit)

    def test_ci_download_corruption_never_creates_output(self):
        self.f.outer += b"changed"
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args(), FakeGitHub(self.f))
        self.assertFalse(self.f.args().output.exists())

    def test_checksum_and_unlisted_files_rejected(self):
        for changed in [{**self.f.files, "TripDocket-Simulator.zip": b"changed"}, {**self.f.files, "extra": b""}]:
            with self.assertRaises(m.InvalidRelease): m.verify_checksums(changed)
        with self.assertRaises(m.InvalidRelease): m.parse_checksums(("a" * 64 + "  ../bad\n").encode())
        with self.assertRaises(m.InvalidRelease): m.parse_checksums(("a" * 64 + "  file\n") .encode() * 2)

    def test_zip_traversal_links_special_files_and_collisions_rejected(self):
        cases = [[("a//", b"", stat.S_IFDIR | 0o755)], [("../bad", b"", stat.S_IFREG | 0o644)], [("/bad", b"", stat.S_IFREG | 0o644)], [("a\\b", b"", stat.S_IFREG | 0o644)], [("a//b", b"", stat.S_IFREG | 0o644)], [("a/./b", b"", stat.S_IFREG | 0o644)], [("link", b"target", stat.S_IFLNK | 0o777)], [("fifo", b"", stat.S_IFIFO | 0o644)], [("a", b"", stat.S_IFREG | 0o644), ("a/b", b"", stat.S_IFREG | 0o644)]]
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(m.InvalidRelease): m.archive_members(zipped(entries))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = zipped([("a", b"", stat.S_IFREG | 0o644)] * 2)
        with self.assertRaises(m.InvalidRelease): m.archive_members(duplicate)
        with patch.object(m, "MAX_EXPANDED", 1), self.assertRaises(m.InvalidRelease): m.archive_members(zipped([("a", b"12", stat.S_IFREG | 0o644)]))

    def test_producer_source_build_and_ci_mismatches_rejected(self):
        for section, key, value in [("source", "tree", "f" * 40), ("source", "clean_checkout", False), ("build", "sdk", "iphoneos"), ("ci", "GITHUB_RUN_ATTEMPT", "1"), ("ci", "GITHUB_JOB", "other"), ("ci", "GITHUB_WORKFLOW", "other"), ("artifact", "executable_sha256", "a" * 64)]:
            producer = copy.deepcopy(self.f.provenance); producer[section][key] = value
            files = checksummed({"TripDocket-Simulator.zip": self.f.app, "provenance.json": m.encode_json(producer)})
            with self.subTest(key=key), self.assertRaises(m.InvalidRelease): m.validate_payload(files, self.f.commit, self.f.tree, self.f.run, "0.1.0")
        with self.assertRaises(m.InvalidRelease): m.validate_payload(self.f.files, self.f.commit, self.f.tree, self.f.run, "0.2.0")

    def test_receipts_must_match_source_artifact_tests_and_cleanup(self):
        for key, value in [("release_artifact_sha256", "a" * 64), ("source", {"commit": "a" * 40, "tree": self.f.tree}), ("cleanup_verified", False), ("runtime_warnings", ["warning"]), ("status", "failed"), ("status", "captured_pending_review"), ("tests", [])]:
            receipt = self.f.receipt("privacy-biometric"); receipt[key] = value
            with self.subTest(key=key), self.assertRaises(m.InvalidRelease): m.validate_receipt(m.encode_json(receipt), "privacy-biometric", self.f.commit, self.f.tree, m.digest(self.f.app))
        receipt = self.f.receipt("privacy-biometric"); receipt["tests"][0]["result"] = "skipped"
        with self.assertRaises(m.InvalidRelease): m.validate_receipt(m.encode_json(receipt), "privacy-biometric", self.f.commit, self.f.tree, m.digest(self.f.app))
        receipt = self.f.receipt("release-smoke"); receipt["tested_product"]["configuration"] = "Debug"
        with self.assertRaises(m.InvalidRelease): m.validate_receipt(m.encode_json(receipt), "release-smoke", self.f.commit, self.f.tree, m.digest(self.f.app))

    def test_batch_receipt_accepts_five_exact_passing_methods_in_any_order(self):
        tests = [
            {"name": "testVerifiedPurchaseAndRestoreFromLocalHistory", "result": "passed"},
            {"name": "testBatchPrepareFilesProviderDirectly", "result": "passed"},
            {"name": "testNativeCreateOwnedFilesFolder", "result": "passed"},
            {"name": "testNativeSaveSeedsBothSyntheticOriginals", "result": "passed"},
            {"name": "testRealFilesBatchRequiresEveryReviewAndPreservesOriginals", "result": "passed"},
        ]
        for permutation in itertools.permutations(tests):
            ordered = list(permutation)
            receipt = self.f.receipt("batch-import")
            receipt["tests"] = ordered
            with self.subTest(tests=ordered):
                self.assertEqual(m.validate_receipt(m.encode_json(receipt), "batch-import",
                                                   self.f.commit, self.f.tree, m.digest(self.f.app)), receipt)

    def test_batch_receipt_rejects_missing_wrong_duplicate_and_nonpassing_methods(self):
        purchase = {"name": "testVerifiedPurchaseAndRestoreFromLocalHistory", "result": "passed"}
        batch = {"name": "testRealFilesBatchRequiresEveryReviewAndPreservesOriginals", "result": "passed"}
        seed = {"name": "testNativeSaveSeedsBothSyntheticOriginals", "result": "passed"}
        preparation = {"name": "testBatchPrepareFilesProviderDirectly", "result": "passed"}
        folder = {"name": "testNativeCreateOwnedFilesFolder", "result": "passed"}
        complete = [purchase, preparation, folder, seed, batch]
        invalid = [[], [batch], [purchase], [seed], [purchase, batch],
                   [purchase, seed], [seed, batch], [purchase, batch, batch],
                   [purchase, seed, {"name": "testOtherBatchCase", "result": "passed"}],
                   [purchase, seed, batch], [purchase, preparation, seed, batch],
                   complete + [seed]]
        for index in range(len(complete)):
            invalid.append(complete[:index] + complete[index + 1:])
            duplicate = copy.deepcopy(complete)
            duplicate[index] = copy.deepcopy(complete[(index + 1) % len(complete)])
            invalid.append(duplicate)
            wrong = copy.deepcopy(complete)
            wrong[index]["name"] = "testOtherBatchCase"
            invalid.append(wrong)
            for result in ("failed", "skipped", "expected failure", "Passed"):
                tests = copy.deepcopy(complete)
                tests[index]["result"] = result
                invalid.append(tests)
        for tests in invalid:
            receipt = self.f.receipt("batch-import")
            receipt["tests"] = tests
            with self.subTest(tests=tests), self.assertRaises(m.InvalidRelease):
                m.validate_receipt(m.encode_json(receipt), "batch-import",
                                   self.f.commit, self.f.tree, m.digest(self.f.app))

    def test_three_or_four_case_batch_cannot_reach_output_with_updated_hash(self):
        original = self.f.receipt("batch-import")
        for omitted in (("testBatchPrepareFilesProviderDirectly", "testNativeCreateOwnedFilesFolder"),
                        ("testNativeCreateOwnedFilesFolder",)):
            receipt = copy.deepcopy(original)
            receipt["tests"] = [case for case in receipt["tests"] if case["name"] not in omitted]
            data = m.encode_json(receipt)
            (self.root / "batch-import.json").write_bytes(data)
            evidence = m.decode_json(self.f.evidence.read_bytes())
            evidence["receipts"]["batch-import"]["sha256"] = m.digest(data)
            self.f.evidence.write_bytes(m.encode_json(evidence))
            with self.subTest(omitted=omitted), self.assertRaisesRegex(m.InvalidRelease, "execution receipt test count mismatch"):
                m.prepare(self.f.args(), FakeGitHub(self.f))
            self.assertFalse(self.f.args().output.exists())

    def test_old_two_case_batch_receipt_cannot_reach_output_with_updated_hash(self):
        receipt = self.f.receipt("batch-import")
        receipt["tests"] = [case for case in receipt["tests"]
                            if case["name"] in {"testVerifiedPurchaseAndRestoreFromLocalHistory",
                                                "testRealFilesBatchRequiresEveryReviewAndPreservesOriginals"}]
        data = m.encode_json(receipt)
        (self.root / "batch-import.json").write_bytes(data)
        evidence = m.decode_json(self.f.evidence.read_bytes())
        evidence["receipts"]["batch-import"]["sha256"] = m.digest(data)
        self.f.evidence.write_bytes(m.encode_json(evidence))
        with self.assertRaisesRegex(m.InvalidRelease, "execution receipt test count mismatch"):
            m.prepare(self.f.args(), FakeGitHub(self.f))
        self.assertFalse(self.f.args().output.exists())

    def test_predecessor_two_case_batch_receipt_rejected_with_updated_hashes(self):
        output = m.prepare(self.f.args(), FakeGitHub(self.f))
        files = {path.name: path.read_bytes() for path in output.iterdir()}
        acceptance = m.decode_json(files["acceptance.json"])
        receipt = m.decode_json(files["batch-import-receipt.json"])
        receipt["tests"] = [case for case in receipt["tests"]
                            if case["name"] in {"testVerifiedPurchaseAndRestoreFromLocalHistory",
                                                "testRealFilesBatchRequiresEveryReviewAndPreservesOriginals"}]
        files["batch-import-receipt.json"] = m.encode_json(receipt)
        acceptance["execution_receipts"]["batch-import"]["sha256"] = m.digest(files["batch-import-receipt.json"])
        files["acceptance.json"] = m.encode_json(acceptance)
        files.pop("SHA256SUMS")
        files = checksummed(files)
        with self.assertRaisesRegex(m.InvalidRelease, "execution receipt test count mismatch"):
            m.validate_predecessor(files, "rc", "0.1.0", self.f.commit,
                                   self.f.tree, acceptance["payload"])

    def test_download_headers_are_specific_to_each_endpoint(self):
        with patch.object(m, "command", return_value=b"download") as command:
            github = m.GitHub()
            github.binary("repos/example/repo/actions/artifacts/1/zip", accept="application/vnd.github+json")
            self.assertIn("Accept: application/vnd.github+json", command.call_args.args[0])
            github.binary("repos/example/repo/releases/assets/1")
            self.assertIn("Accept: application/octet-stream", command.call_args.args[0])

    def test_public_receipt_schema_rejects_extra_and_nested_fields(self):
        for location in ("top", "source", "tested_product", "tests"):
            receipt = self.f.receipt("release-smoke")
            target = receipt if location == "top" else receipt[location]
            if location == "tests": target = target[0]
            target["raw_commands"] = {"cwd": "/" + "Users/synthetic/private", "argv": ["command"]}
            with self.subTest(location=location), self.assertRaises(m.InvalidRelease):
                m.validate_receipt(m.encode_json(receipt), "release-smoke", self.f.commit, self.f.tree, m.digest(self.f.app))
        for limitation in ({"cwd": "private"}, ["nested"], None, 10, "", "multiline\ntext"):
            receipt = self.f.receipt("release-smoke"); receipt["limitations"] = [limitation]
            with self.subTest(limitation=limitation), self.assertRaises(m.InvalidRelease):
                m.validate_receipt(m.encode_json(receipt), "release-smoke", self.f.commit, self.f.tree, m.digest(self.f.app))

    def test_public_receipt_text_rejects_obvious_private_data(self):
        cases = ["Evidence: /" + "Users/synthetic/private", "Evidence: /custom/location/report.json",
                 "Evidence: C:" + "\\Users\\synthetic\\private", "Evidence: file:///private/report",
                 "Evidence: ~/private/report", "Evidence: $HOME/private/report",
                 '"cwd":"private"', '"argv":["command"]', '"password":"synthetic"',
                 "https://synthetic:credential@example.invalid/path",
                 "cwd=private", "argv: [command]", "raw_commands={}",
                 "token=" + "synthetic-token-value", "Bearer " + "synthetic-credential",
                 "ghp_" + "a" * 36, "github_pat_" + "a" * 80,
                 "AKIA" + "A" * 16, "xoxb-" + "1" * 30,
                 "-----BEGIN " + "PRIVATE KEY-----"]
        for value in cases:
            receipt = self.f.receipt("release-smoke"); receipt["limitations"] = [value]
            with self.subTest(value=value), self.assertRaises(m.InvalidRelease):
                m.validate_receipt(m.encode_json(receipt), "release-smoke", self.f.commit, self.f.tree, m.digest(self.f.app))

    def test_public_receipt_allows_concise_scope_and_public_reference(self):
        receipt = self.f.receipt("release-smoke")
        receipt["limitations"] = ["Observed the locked system authentication screen only; no credentials entered.",
                                  "No physical-device or TestFlight acceptance.",
                                  "Public CI: https://github.com/4alvit/travel-documents-ios/actions/runs/10"]
        self.assertEqual(m.validate_receipt(m.encode_json(receipt), "release-smoke", self.f.commit, self.f.tree, m.digest(self.f.app)), receipt)

    def test_private_receipt_never_reaches_output_even_with_updated_hash(self):
        receipt = self.f.receipt("release-smoke"); receipt["raw_commands"] = {"argv": ["private"]}
        data = m.encode_json(receipt)
        (self.root / "release-smoke.json").write_bytes(data)
        evidence = m.decode_json(self.f.evidence.read_bytes())
        evidence["receipts"]["release-smoke"]["sha256"] = m.digest(data)
        self.f.evidence.write_bytes(m.encode_json(evidence))
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args(), FakeGitHub(self.f))
        self.assertFalse(self.f.args().output.exists())

    def test_receipt_hash_and_review_gate(self):
        evidence = m.decode_json(self.f.evidence.read_bytes())
        evidence["receipts"]["release-smoke"]["sha256"] = "a" * 64
        self.f.evidence.write_bytes(m.encode_json(evidence))
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args(), FakeGitHub(self.f))
        self.f.make_evidence({"release-smoke"})
        evidence = m.decode_json(self.f.evidence.read_bytes()); evidence["review"]["blockers"] = ["unresolved issue"]
        self.f.evidence.write_bytes(m.encode_json(evidence))
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args(), FakeGitHub(self.f))

    def test_rc_requires_all_opt_in_receipts(self):
        self.f.make_evidence({"release-smoke"})
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args("rc", tag="v0.1.0-beta.1"), FakeGitHub(self.f))

    def test_beta_rc_stable_promote_same_payload(self):
        previous = None
        for stage, tag in [("beta", None), ("rc", "v0.1.0-beta.1"), ("stable", "v0.1.0-rc.1")]:
            out = m.prepare(self.f.args(stage, stage, tag), FakeGitHub(self.f, previous))
            files = {p.name: p.read_bytes() for p in out.iterdir()}
            m.verify_checksums(files)
            if previous:
                self.assertEqual({name: files[name] for name in m.PAYLOAD}, {name: previous[name] for name in m.PAYLOAD})
            previous = files

    def test_predecessor_cannot_replace_payload_or_skip_stage(self):
        output = m.prepare(self.f.args(), FakeGitHub(self.f))
        files = {p.name: p.read_bytes() for p in output.iterdir()}
        acceptance = m.decode_json(files["acceptance.json"])
        payload = acceptance["payload"]
        changed = {**files, "TripDocket-Simulator.zip": b"changed"}; changed.pop("SHA256SUMS"); changed = checksummed(changed)
        with self.assertRaises(m.InvalidRelease): m.validate_predecessor(changed, "rc", "0.1.0", self.f.commit, self.f.tree, payload)
        with self.assertRaises(m.InvalidRelease): m.validate_predecessor(files, "stable", "0.1.0", self.f.commit, self.f.tree, payload)
        receipt = m.decode_json(files["release-smoke-receipt.json"]); receipt["cleanup_verified"] = False
        changed = {**files, "release-smoke-receipt.json": m.encode_json(receipt)}
        acceptance["execution_receipts"]["release-smoke"]["sha256"] = m.digest(changed["release-smoke-receipt.json"])
        changed["acceptance.json"] = m.encode_json(acceptance); changed.pop("SHA256SUMS"); changed = checksummed(changed)
        with self.assertRaises(m.InvalidRelease): m.validate_predecessor(changed, "rc", "0.1.0", self.f.commit, self.f.tree, payload)

    def test_preexisting_output_and_symlinks_untouched(self):
        output = self.root / "output"; output.mkdir(); (output / "user").write_text("keep")
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args(), FakeGitHub(self.f))
        self.assertEqual((output / "user").read_text(), "keep")
        link = self.root / "link"; link.symlink_to(output, target_is_directory=True)
        with self.assertRaises(m.InvalidRelease): m.write_output(link / "new", {"file": b"x"}, self.f.repo)
        with self.assertRaises(m.InvalidRelease): m.write_output(self.f.repo / "new", {"file": b"x"}, self.f.repo)
        receipt = self.root / "linked-receipt"; receipt.symlink_to(self.f.evidence)
        with self.assertRaises(m.InvalidRelease): m.read_regular(receipt)

    def test_partial_write_cleans_only_files_created_by_preparer(self):
        original_open = Path.open
        for foreign in (False, True):
            output = self.root / ("partial-foreign" if foreign else "partial")
            @contextlib.contextmanager
            def failing_open(path, mode="r", *args, **kwargs):
                with original_open(path, mode, *args, **kwargs) as underlying:
                    if path.name != "owned.bin" or mode != "xb":
                        yield underlying
                        return
                    class FailingStream:
                        def fileno(self): return underlying.fileno()
                        def write(self, data):
                            underlying.write(data[:1])
                            if foreign:
                                with original_open(output / "foreign.bin", "wb") as other:
                                    other.write(b"preserve")
                            raise OSError("synthetic disk-full after partial write")
                    yield FailingStream()
            with patch.object(Path, "open", failing_open), self.assertRaises(OSError):
                m.write_output(output, {"owned.bin": b"data", "next.bin": b"next"}, self.f.repo)
            self.assertFalse((output / "owned.bin").exists())
            self.assertFalse((output / "next.bin").exists())
            if foreign:
                self.assertEqual((output / "foreign.bin").read_bytes(), b"preserve")
            else:
                self.assertFalse(output.exists())

    def test_ci_rerun_starting_mid_prepare_rejected(self):
        api = FakeGitHub(self.f); api.changed_run = True
        with self.assertRaises(m.InvalidRelease): m.prepare(self.f.args(), api)
        self.assertFalse(self.f.args().output.exists())

    def test_source_symlink_rejected(self):
        (self.f.repo / "link").symlink_to("source.swift")
        subprocess.run(["git", "add", "link"], cwd=self.f.repo, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic symlink"], cwd=self.f.repo, check=True)
        with self.assertRaises(m.InvalidRelease): m.source_archive(self.f.repo, "HEAD")

    def test_source_attributes_do_not_rewrite_or_omit_files(self):
        (self.f.repo / ".gitattributes").write_text("source.swift export-ignore\n")
        subprocess.run(["git", "add", ".gitattributes"], cwd=self.f.repo, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic attributes"], cwd=self.f.repo, check=True)
        data = m.source_archive(self.f.repo, "HEAD")
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as archive:
            self.assertEqual(archive.extractfile("TripDocket-source/source.swift").read(), b"// synthetic source\n")

    def test_predecessor_release_flags_and_tag_identity_are_checked(self):
        out = m.prepare(self.f.args(), FakeGitHub(self.f))
        files = {p.name: p.read_bytes() for p in out.iterdir()}
        payload = m.decode_json(files["acceptance.json"])["payload"]
        for mutation in ("draft", "not-prerelease", "wrong-commit"):
            api = FakeGitHub(self.f, files)
            original = api.api
            def changed(path):
                result = original(path)
                if "/releases/tags/" in path:
                    if mutation == "draft": result["draft"] = True
                    if mutation == "not-prerelease": result["prerelease"] = False
                if "/git/ref/" in path and mutation == "wrong-commit":
                    result["object"]["sha"] = "a" * 40
                return result
            api.api = changed
            with self.subTest(mutation=mutation), self.assertRaises(m.InvalidRelease):
                m.previous_release(api, "v0.1.0-beta.1", "rc", "0.1.0", self.f.commit, self.f.tree, payload)

    def test_nonexecutable_payload_and_unexpected_empty_root_rejected(self):
        for entries in ([
                ("Tripfolio.app/Tripfolio", b"binary", stat.S_IFREG | 0o644),
                ("Tripfolio.app/Info.plist", b"plist", stat.S_IFREG | 0o644)], [
                ("unexpected/", b"", stat.S_IFDIR | 0o755)]):
            app = zipped(entries)
            producer = copy.deepcopy(self.f.provenance)
            producer["artifact"]["sha256"] = m.digest(app)
            files = checksummed({"TripDocket-Simulator.zip": app, "provenance.json": m.encode_json(producer)})
            with self.assertRaises(m.InvalidRelease):
                m.validate_payload(files, self.f.commit, self.f.tree, self.f.run, "0.1.0")

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        with self.assertRaises(m.InvalidRelease): m.decode_json(b'{"stage":"beta","stage":"stable"}')
        with self.assertRaises(m.InvalidRelease): m.decode_json(b'{"number":NaN}')

    def test_command_output_and_elapsed_limits(self):
        with self.assertRaises(m.InvalidRelease): m.command([sys.executable, "-c", "print('x'*1000)"], maximum=10)
        with self.assertRaises(m.InvalidRelease): m.command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)


if __name__ == "__main__":
    unittest.main()
