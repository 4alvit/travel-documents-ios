#!/usr/bin/env python3
"""Offline checks of actual batch selection, results and ordered log evidence."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("batch_driver", Path(__file__).with_name("test-batch-simulator.py"))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

OWNED = "11111111-1111-4111-8111-111111111111"
SELECTORS = (
    "TripfolioTests/PlatformTests/testVerifiedPurchaseAndRestoreFromLocalHistory",
    "TripfolioUITests/BatchImportUITests/testRealFilesBatchRequiresEveryReviewAndPreservesOriginals",
)
IDENTIFIERS = (
    "PlatformTests/testVerifiedPurchaseAndRestoreFromLocalHistory()",
    "BatchImportUITests/testRealFilesBatchRequiresEveryReviewAndPreservesOriginals()",
)
HOST = "Test Case '-[TripfolioTests.PlatformTests testVerifiedPurchaseAndRestoreFromLocalHistory]' "
BATCH = "Test Case '-[TripfolioUITests.BatchImportUITests testRealFilesBatchRequiresEveryReviewAndPreservesOriginals]' "
LINES = [HOST + "started.", HOST + "passed (10.131 seconds).",
         BATCH + "started.", BATCH + "passed (156.674 seconds)."]


def log_bytes(lines=LINES):
    return ("Native test output\n" + "\n".join(lines) + "\n").encode()


class BatchDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "xcodebuild.log"
        self.log.write_bytes(log_bytes())

    def fixture(self):
        run = driver.Driver.__new__(driver.Driver)
        run.args = SimpleNamespace(device=OWNED)
        run.root = run.directory = self.root
        run.folder_name = "owned-synthetic-folder"
        run.summary = {"result_bundle": str(self.root / "Tests.xcresult")}
        run.save = Mock()
        run.record = Mock()
        run.remaining = Mock(return_value=100)
        result = {"result": "Passed", "totalTestCount": 2, "passedTests": 2,
                  "failedTests": 0, "skippedTests": 0, "expectedFailures": 0,
                  "devicesAndConfigurations": [{"device": {"deviceId": OWNED}}]}
        tree = {"testNodes": [{"nodeType": "Test Case", "nodeIdentifier": name, "result": "Passed"}
                              for name in IDENTIFIERS],
                "devices": [{"deviceId": OWNED, "platform": "iOS Simulator"}]}
        run.command = Mock(side_effect=lambda *argv: json.dumps({"summary": result, "tests": tree}[argv[4]]).encode())
        return run, result, tree

    def test_single_invocation_selects_exact_two_cases_and_preserves_limits(self):
        run, _, _ = self.fixture()
        process = Mock()
        process.wait.return_value = 0

        def spawn(argv, **kwargs):
            kwargs["stdout"].write(log_bytes())
            kwargs["stdout"].flush()
            self.assertEqual(kwargs["cwd"], self.root)
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(kwargs["env"]["TEST_RUNNER_TRIPDOCKET_BATCH_UI"], "1")
            self.assertEqual(kwargs["env"]["TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER"], run.folder_name)
            return process

        with patch.object(driver.subprocess, "Popen", side_effect=spawn) as mocked, patch("builtins.print"):
            run.run_test()
        mocked.assert_called_once()
        argv = mocked.call_args.args[0]
        self.assertEqual([x for x in argv if x.startswith("-only-testing:")],
                         ["-only-testing:" + x for x in SELECTORS])
        for key, value in [("-destination", "platform=iOS Simulator,id=" + OWNED),
                           ("-destination-timeout", "30"), ("-parallel-testing-enabled", "NO"),
                           ("-maximum-concurrent-test-simulator-destinations", "1"),
                           ("-default-test-execution-time-allowance", "300"),
                           ("-maximum-test-execution-time-allowance", "300")]:
            self.assertEqual(argv[argv.index(key) + 1], value)
        self.assertEqual(argv[-2:], ["CODE_SIGNING_ALLOWED=NO", "test"])
        process.wait.assert_called_once_with(timeout=100)
        self.assertEqual(run.summary["execution_order"], driver.execution_order(log_bytes()))

    def test_exact_results_accept_either_tree_order(self):
        run, _, tree = self.fixture()
        tree["testNodes"].reverse()
        run.validate_result()
        self.assertEqual(run.summary["execution_order"]["cases"][0]["identifier"], IDENTIFIERS[0])

    def test_nonzero_xcodebuild_exit_cannot_pass_despite_complete_evidence(self):
        run, _, _ = self.fixture()
        process = Mock()
        process.wait.return_value = 65

        def spawn(_argv, **kwargs):
            kwargs["stdout"].write(log_bytes())
            kwargs["stdout"].flush()
            return process

        with patch.object(driver.subprocess, "Popen", side_effect=spawn), patch("builtins.print"), \
             self.assertRaisesRegex(RuntimeError, "xcodebuild failed"):
            run.run_test()

    def test_results_reject_old_count_missing_duplicate_wrong_failed_or_skipped_case(self):
        mutations = [
            lambda r,t: r.update(totalTestCount=1, passedTests=1),
            lambda r,t: r.update(passedTests=True),
            lambda r,t: r.update(failedTests=1),
            lambda r,t: r.update(skippedTests=1),
            lambda r,t: r.update(expectedFailures=1),
            lambda r,t: r.update(result="Failed"),
            lambda r,t: t["testNodes"].pop(),
            lambda r,t: t["testNodes"].append(copy.deepcopy(t["testNodes"][0])),
            lambda r,t: t["testNodes"][0].update(nodeIdentifier=IDENTIFIERS[1]),
            lambda r,t: t["testNodes"][0].update(nodeIdentifier="BatchImportUITests/testVerifiedPurchaseAndRestoreFromLocalHistory()"),
            lambda r,t: t["testNodes"][0].update(result="Skipped"),
            lambda r,t: t["testNodes"][1].update(result="Failed"),
        ]
        for mutation in mutations:
            run, result, tree = self.fixture()
            mutation(result, tree)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(RuntimeError, "both exact"):
                run.validate_result()
            self.assertNotIn("execution_order", run.summary)

    def test_results_reject_wrong_or_multiple_devices_and_configurations(self):
        for target in ("tree", "configuration", "platform", "extra-device", "extra-config"):
            run, result, tree = self.fixture()
            if target == "tree": tree["devices"][0]["deviceId"] = "other"
            if target == "platform": tree["devices"][0]["platform"] = "iOS"
            if target == "configuration": result["devicesAndConfigurations"][0]["device"]["deviceId"] = "other"
            if target == "extra-device": tree["devices"].append(copy.deepcopy(tree["devices"][0]))
            if target == "extra-config": result["devicesAndConfigurations"].append(copy.deepcopy(result["devicesAndConfigurations"][0]))
            with self.subTest(target=target), self.assertRaises(RuntimeError): run.validate_result()
            self.assertNotIn("execution_order", run.summary)

    def test_passed_xcresult_cannot_replace_missing_or_failed_log_evidence(self):
        for payload in [b"", log_bytes(LINES[:-1]), log_bytes(LINES[:-1] + [BATCH + "failed (156.674 seconds)."])]:
            self.log.write_bytes(payload)
            run, _, _ = self.fixture()
            with self.subTest(payload=payload), self.assertRaises(RuntimeError): run.validate_result()
            self.assertNotIn("execution_order", run.summary)

    def test_order_receipt_binds_original_bytes_and_line_numbers(self):
        raw = log_bytes()
        proof = driver.execution_order(raw)
        self.assertEqual(proof["log"], {"path": "xcodebuild.log", "bytes": len(raw),
                                         "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(proof["cases"], [
            {"identifier": IDENTIFIERS[0], "started_line": 2, "passed_line": 3, "duration_seconds": "10.131"},
            {"identifier": IDENTIFIERS[1], "started_line": 4, "passed_line": 5, "duration_seconds": "156.674"},
        ])
        self.assertTrue(proof["hosted_pass_before_batch_start"])
        self.assertNotEqual(driver.execution_order(raw + b"trailer\n")["log"]["sha256"], proof["log"]["sha256"])

    def test_order_rejects_missing_duplicate_retried_reversed_or_overlapping_markers(self):
        invalid = [LINES[1:], LINES[:-1], LINES + [LINES[-1]], LINES + LINES,
                   [LINES[2], LINES[3], LINES[0], LINES[1]],
                   [LINES[0], LINES[2], LINES[1], LINES[3]],
                   [LINES[1], LINES[0], LINES[2], LINES[3]],
                   [LINES[0], HOST + "failed (1.0 seconds).", *LINES],
                   [LINES[0], HOST + "skipped.", *LINES[2:]]]
        for lines in invalid:
            with self.subTest(lines=lines), self.assertRaises(RuntimeError): driver.execution_order(log_bytes(lines))

    def test_order_requires_full_anchored_exact_case_markers(self):
        for bad in ["prefix " + LINES[0], LINES[0] + " suffix", LINES[0].replace("PlatformTests", "OtherTests"),
                    LINES[0].replace("started.", "started"), LINES[0].replace("started.", "started.\rjunk")]:
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                driver.execution_order(log_bytes([bad, *LINES[1:]]))

    def test_order_rejects_nonfinite_negative_or_unbounded_duration_text(self):
        for duration in ["nan", "inf", "-1", "1e9", "9" * 100, "1." + "0" * 100]:
            with self.subTest(duration=duration), self.assertRaises(RuntimeError):
                driver.execution_order(log_bytes([LINES[0], HOST + f"passed ({duration} seconds).", *LINES[2:]]))

    def test_log_requires_bounded_utf8_bytes_without_nul(self):
        for data in ["text", b"", log_bytes() + b"\xff", log_bytes() + b"\0"]:
            with self.subTest(data=data), self.assertRaises(RuntimeError): driver.execution_order(data)
        with patch.object(driver, "MAX_LOG_BYTES", len(log_bytes()) - 1), self.assertRaises(RuntimeError):
            driver.execution_order(log_bytes())

    def test_regular_file_reader_accepts_crlf_and_checks_deadline(self):
        raw = log_bytes().replace(b"\n", b"\r\n")
        self.log.write_bytes(raw)
        check = Mock()
        self.assertEqual(driver.read_execution_order(self.log, check), driver.execution_order(raw))
        self.assertGreater(check.call_count, 0)

    def test_regular_file_reader_rejects_symlink_directory_and_fifo(self):
        link = self.root / "link"
        link.symlink_to(self.log)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for path in [link, self.root, fifo]:
            with self.subTest(path=path), self.assertRaises(RuntimeError): driver.read_execution_order(path, lambda: None)

    def test_regular_file_reader_rejects_empty_or_oversized_file_before_open(self):
        for data, bound in [(b"", 100), (log_bytes(), 10)]:
            self.log.write_bytes(data)
            with self.subTest(bound=bound), patch.object(driver, "MAX_LOG_BYTES", bound), \
                 patch.object(driver.os, "open") as opened, self.assertRaises(RuntimeError):
                driver.read_execution_order(self.log, lambda: None)
            opened.assert_not_called()

    def test_regular_file_reader_rejects_growth_and_replacement_during_read(self):
        read = os.read
        for mode in ["growth", "replacement"]:
            self.log.write_bytes(log_bytes())
            changed = False

            def mutate(fd, count):
                nonlocal changed
                data = read(fd, count)
                if not changed:
                    changed = True
                    if mode == "growth":
                        with self.log.open("ab") as stream: stream.write(b"changed\n")
                    else:
                        replacement = self.root / "replacement"
                        replacement.write_bytes(log_bytes())
                        replacement.replace(self.log)
                return data

            with self.subTest(mode=mode), patch.object(driver.os, "read", side_effect=mutate), self.assertRaisesRegex(RuntimeError, "changed"):
                driver.read_execution_order(self.log, lambda: None)

    def test_regular_file_reader_closes_descriptor_on_deadline_failure(self):
        check = Mock(side_effect=TimeoutError("deadline"))
        with patch.object(driver.os, "close", wraps=os.close) as close, self.assertRaises(TimeoutError):
            driver.read_execution_order(self.log, check)
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
