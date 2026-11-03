#!/usr/bin/env python3
"""Exercise the real host protocol and extracted Swift await with no Simulator.

The Swift fixture substitutes only notification I/O, the clock, and surrounding
UI checks. Its asynchronous control flow is the actual requestBiometric method.
"""
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("privacy_driver", ROOT / "scripts/test-privacy-simulator.py")
driver_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver_module)
SESSION = "1A5C10F8-85FD-473F-9CF3-6B12E9D82F61"
NONCE = "A4D2EBE3-F809-4BF4-A98C-045FA9036C80"
SECOND = "74450B14-C9C3-4775-99A0-BB3BFA8B8E6F"


class HostTests(unittest.TestCase):
    def setUp(self):
        self.driver = driver_module.Driver.__new__(driver_module.Driver)
        self.driver.args = SimpleNamespace(device=SESSION)
        self.driver.ack_session = SESSION
        self.driver.request_nonces = set()
        self.driver.requests = {"match": 0, "nomatch": 0}
        self.driver.record = Mock()
        self.driver.command = Mock(return_value="")
        self.clock = patch.object(driver_module.time, "monotonic", return_value=100)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def send(self, event="match", ordinal=1, nonce=NONCE, deadline=200):
        self.driver.handle_biometric_request(f"{driver_module.MARKER} {event} {ordinal} {nonce}\n", deadline)

    def test_one_event_then_exact_nonce_sequence_event_ack(self):
        self.send()
        self.send("nomatch", 2, SECOND)
        calls = self.driver.command.call_args_list
        self.assertEqual(len(calls), 4)
        for index, (event, nonce, state) in enumerate((("match", NONCE, "3"), ("nomatch", SECOND, "4"))):
            self.assertEqual(calls[index * 2].args, ("biometric_" + event,
                             ["xcrun", "simctl", "notify_post", SESSION, driver_module.EVENTS[event]]))
            self.assertEqual(calls[index * 2 + 1].args, ("biometric_acknowledgement",
                             ["xcrun", "simctl", "notify_set_state", SESSION,
                              f"{driver_module.ACK_PREFIX}.{SESSION}.{nonce}", state]))
        self.assertTrue(all(call.kwargs == {"timeout": 30} for call in calls))

    def test_failed_event_is_not_acknowledged_or_retried(self):
        self.driver.command.side_effect = driver_module.DriverError("event command failed")
        with self.assertRaises(driver_module.DriverError):
            self.send()
        self.assertEqual(self.driver.command.call_count, 1)
        with self.assertRaises(driver_module.DriverError):
            self.send()
        self.assertEqual(self.driver.command.call_count, 1)

    def test_failed_ack_does_not_repeat_the_event(self):
        self.driver.command.side_effect = ["", driver_module.DriverError("ack command failed")]
        with self.assertRaises(driver_module.DriverError):
            self.send()
        self.assertEqual(self.driver.command.call_count, 2)
        self.assertNotIn("biometric_acknowledged", [call.args[0] for call in self.driver.record.call_args_list])

    def test_rejects_legacy_malformed_wrong_order_and_bound(self):
        invalid = ["match", f"match 0 {NONCE}", f"match 2 {NONCE}", f"match 65 {NONCE}",
                   f"match 01 {NONCE}", f"match 1 {NONCE.lower()}", f"other 1 {NONCE}",
                   "match 1 00000000-0000-0000-0000-000000000000",
                   f"match 1 {NONCE} trailing", f"match 1 {NONCE} {driver_module.MARKER}"]
        for suffix in invalid:
            with self.subTest(suffix=suffix), self.assertRaises(driver_module.DriverError):
                self.driver.handle_biometric_request(driver_module.MARKER + " " + suffix, 200)
        self.driver.command.assert_not_called()

    def test_reused_nonce_cannot_acknowledge_a_later_case(self):
        self.send()
        with self.assertRaises(driver_module.DriverError):
            self.send("nomatch", 2, NONCE)
        self.assertEqual(self.driver.command.call_count, 2)

    def test_global_deadline_clamps_each_command(self):
        with patch.object(driver_module.time, "monotonic", side_effect=[100, 108]):
            self.send(deadline=110)
        self.assertEqual([call.kwargs["timeout"] for call in self.driver.command.call_args_list], [10, 2])

    def test_expired_deadline_never_posts_or_acknowledges(self):
        with self.assertRaises(driver_module.DriverError):
            self.send(deadline=100)
        self.driver.command.assert_not_called()
        self.driver.requests = {"match": 0, "nomatch": 0}
        self.driver.request_nonces = set()
        with patch.object(driver_module.time, "monotonic", side_effect=[100, 111]):
            with self.assertRaises(driver_module.DriverError):
                self.send(deadline=110)
        self.assertEqual(self.driver.command.call_count, 1)

    def test_actual_run_loop_supplies_session_and_uses_the_handshake(self):
        self.driver.args = SimpleNamespace(device=SESSION, timeout=1200, only_test=None)
        self.driver.root = ROOT
        self.driver.summary = {"result_bundle": "unused.xcresult"}
        self.driver.log = io.StringIO()
        self.driver.validate_result = Mock()
        process = Mock(stdout=iter([f"{driver_module.MARKER} match 1 {NONCE}\n"]))
        process.wait.return_value = 0
        with patch.object(driver_module.subprocess, "Popen", return_value=process) as spawn, \
             patch.object(driver_module.sys, "stdout", io.StringIO()), \
             patch.dict(os.environ, {"TEST_RUNNER_TRIPDOCKET_BIOMETRIC_ACK_SESSION": "stale"}):
            self.driver.run_tests()
        self.assertEqual(spawn.call_args.kwargs["env"]["TEST_RUNNER_TRIPDOCKET_BIOMETRIC_ACK_SESSION"], SESSION)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        self.assertEqual(self.driver.command.call_count, 2)
        self.driver.validate_result.assert_called_once_with()
        command = spawn.call_args.args[0]
        self.assertEqual(command[command.index("-maximum-test-execution-time-allowance") + 1], "180")
        self.assertEqual(command[command.index("-default-test-execution-time-allowance") + 1], "120")


SWIFT = r'''
import Darwin
import Foundation
import notify

struct Failure: Error {}
@MainActor
enum UI {
    static var visible: Set<String> = []
    static var covered: Set<String> = []
    static var authentication = false
    static var shareSheet = false
    static var hittabilityReads: [String] = []
}
@MainActor
struct Element {
    let name: String
    var exists: Bool { UI.visible.contains(name) }
    var isHittable: Bool {
        precondition(exists, "Must not read missing element hittability")
        UI.hittabilityReads.append(name)
        return !UI.covered.contains(name)
    }
    var buttons: Query { Query(prefix: name + "/") }
    var firstMatch: Element { self }
}
@MainActor
struct Query {
    let prefix: String
    subscript(_ name: String) -> Element { Element(name: prefix + name) }
}
@MainActor
struct XCUIApplication {
    var staticTexts: Query { Query(prefix: "text/") }
    var navigationBars: Query { Query(prefix: "nav/") }
    var textFields: Query { Query(prefix: "field/") }
    var buttons: Query { Query(prefix: "button/") }
}

@MainActor
enum Fake {
    static var mode = CommandLine.arguments[1]
    static var time = 0.0
    static var registered = 0
    static var cancelled = 0
    static var names: [String] = []
    static var markers: [String] = []
    static var expected: UInt64 = 0
    static var reads = 0
    static var observedPrompt = false
    static var privateChecked = false
    static func register(_ name: String, _ token: inout Int32) -> UInt32 {
        registered += 1
        names.append(name)
        token = 42
        reads = 0
        return mode == "register-failure" ? 1 : 0
    }
    static func cancel(_ token: Int32) -> UInt32 { cancelled += 1; return 0 }
    static func read(_ token: Int32, _ state: inout UInt64) -> UInt32 {
        reads += 1
        state = 0
        if mode == "read-failure" && reads > 1 { return 1 }
        if mode == "initial-stale" && reads == 1 { state = 3 }
        if reads > 1 {
            if mode == "wrong-event" { state = expected ^ 1 }
            if mode == "wrong-sequence" { state = expected + 2 }
            if mode == "delayed" && time >= 12 { state = expected }
            if mode == "two-requests" { state = expected }
            if mode == "at-deadline" && time >= 60 { state = expected }
        }
        return 0
    }
    static func sleep(for duration: Duration) async throws {
        if mode == "cancelled" { throw CancellationError() }
        time += mode == "at-deadline" ? 60 : 0.1
    }
}

@MainActor
struct FakeClock {
    struct Instant: Comparable {
        let value: Double
        func advanced(by duration: Duration) -> Instant {
            Instant(value: value + Double(duration.components.seconds))
        }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.value < rhs.value }
    }
    var now: Instant { Instant(value: Fake.time) }
}

@MainActor
func print(_ value: String) {
    precondition(Fake.observedPrompt && Fake.privateChecked)
    Fake.markers.append(value)
    let fields = value.split(separator: " ")
    precondition(fields.count == 4)
    Fake.expected = UInt64(fields[2])! * 2 + (fields[1] == "match" ? 1 : 0)
}

@MainActor
final class Harness {
    static var biometricSequence: UInt64 = 0
    func waitForAuthenticationUI(_ app: XCUIApplication) async throws { Fake.observedPrompt = true }
    func assertPrivate(_ app: XCUIApplication, checkpoint: String) throws { Fake.privateChecked = true }
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw Failure() }
    }
    func require(_ message: String, app: XCUIApplication, condition: @MainActor () -> Bool) async throws {
        if !condition() { throw Failure() }
    }
    func lockTitle(in app: XCUIApplication) -> Element { Element(name: "lock") }
    func hasAuthenticationUI(in app: XCUIApplication) -> Bool { UI.authentication }
    func hasShareSheet(in app: XCUIApplication) -> Bool { UI.shareSheet }
    // ACTUAL_REQUEST
    // ACTUAL_UNLOCKED
}

@main
struct Main {
    @MainActor
    static func main() async {
        let harness = Harness()
        if Fake.mode.hasPrefix("ui-") {
            switch Fake.mode {
            case "ui-editor": UI.visible = ["field/Document title"]
            case "ui-covered": UI.visible = ["field/Document title"]; UI.covered = UI.visible
            case "ui-locked": UI.visible = ["lock", "field/Document title"]
            case "ui-authentication": UI.visible = ["field/Document title"]; UI.authentication = true
            case "ui-share": UI.shareSheet = true
            case "ui-missing": break
            default: preconditionFailure("Unknown UI fixture")
            }
            var accepted = false
            do { try await harness.requireUnlocked(XCUIApplication()); accepted = true } catch {}
            precondition(accepted == ["ui-editor", "ui-share"].contains(Fake.mode))
            let expectedReads = ["ui-editor", "ui-covered"].contains(Fake.mode) ? ["field/Document title"] : []
            precondition(UI.hittabilityReads == expectedReads)
            Swift.print("PASS \(Fake.mode)")
            return
        }
        if Fake.mode == "maximum" { Harness.biometricSequence = 64 }
        var completed = 0
        do {
            try await harness.requestBiometric("match", in: XCUIApplication())
            completed += 1 // The caller's UI postcondition starts only here.
            if Fake.mode == "two-requests" {
                try await harness.requestBiometric("nomatch", in: XCUIApplication())
                completed += 1
            }
        } catch {}
        switch Fake.mode {
        case "delayed": precondition(completed == 1 && Fake.time >= 12 && Fake.time < 60)
        case "two-requests":
            precondition(completed == 2 && Fake.names.count == 2 && Set(Fake.names).count == 2)
            precondition(Fake.markers[0].contains("match 1 ") && Fake.markers[1].contains("nomatch 2 "))
        default: precondition(completed == 0)
        }
        let beforeRegistration = ["maximum", "bad-session"].contains(Fake.mode)
        precondition(Fake.registered == (beforeRegistration ? 0 : (Fake.mode == "two-requests" ? 2 : 1)))
        precondition(Fake.cancelled == (Fake.mode == "register-failure" ? 0 : Fake.registered))
        let noMarker = beforeRegistration || ["register-failure", "initial-stale"].contains(Fake.mode)
        precondition(Fake.markers.count == (noMarker ? 0 : (Fake.mode == "two-requests" ? 2 : 1)))
        if ["timeout", "at-deadline"].contains(Fake.mode) { precondition(Fake.time >= 60 && Fake.time < 61) }
        Swift.print("PASS \(Fake.mode)")
    }
}
'''


class SwiftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "UITests/PrivacyTransitionUITests.swift").read_text()
        start = "    private func requestBiometric("
        end = "\n    private func hasAuthenticationFailure("
        if text.count(start) != 1 or text.count(end) != 1:
            raise AssertionError("Cannot identify the unique actual handshake method")
        method = text[text.index(start):text.index(end, text.index(start))]
        # Replace external I/O/time only, leaving all checks and control flow intact.
        substitutions = {"private func requestBiometric": "func requestBiometric",
                         "notify_register_check": "Fake.register", "notify_cancel": "Fake.cancel",
                         "notify_get_state": "Fake.read", "ContinuousClock": "FakeClock",
                         "Task.sleep": "Fake.sleep"}
        for old, new in substitutions.items():
            method = method.replace(old, new)
        unlocked_start = "    private func requireUnlocked("
        unlocked_end = "\n    private func startAuthentication("
        if text.count(unlocked_start) != 1 or text.count(unlocked_end) != 1:
            raise AssertionError("Cannot identify the unique actual unlocked predicate")
        unlocked = text[text.index(unlocked_start):text.index(unlocked_end, text.index(unlocked_start))]
        unlocked = unlocked.replace("private func requireUnlocked", "func requireUnlocked")
        cls.directory = tempfile.TemporaryDirectory(prefix="tripdocket-biometric-handshake-")
        cls.addClassCleanup(cls.directory.cleanup)
        source = Path(cls.directory.name) / "main.swift"
        source.write_text(SWIFT.replace("    // ACTUAL_REQUEST", method).replace("    // ACTUAL_UNLOCKED", unlocked))
        cls.executable = Path(cls.directory.name) / "handshake"
        result = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library",
                                 str(source), "-o", str(cls.executable)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, mode):
        environment = os.environ.copy()
        environment["TRIPDOCKET_BIOMETRIC_ACK_SESSION"] = "invalid" if mode == "bad-session" else SESSION
        result = subprocess.run([str(self.executable), mode], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS " + mode)

    def test_delayed_command_is_awaited_before_the_ui_postcondition(self):
        self.run_case("delayed")

    def test_two_requests_have_distinct_ack_identity_and_increasing_sequence(self):
        self.run_case("two-requests")

    def test_non_success_paths_never_start_the_ui_postcondition(self):
        for mode in ("register-failure", "initial-stale", "wrong-event", "wrong-sequence",
                     "read-failure", "timeout", "at-deadline", "cancelled", "maximum", "bad-session"):
            with self.subTest(mode=mode):
                self.run_case(mode)

    def test_unlocked_predicate_skips_missing_but_requires_live_hittability(self):
        for mode in ("ui-editor", "ui-covered", "ui-locked", "ui-authentication", "ui-share", "ui-missing"):
            with self.subTest(mode=mode):
                self.run_case(mode)


# This is separate from the small require stub used by requireUnlocked above.
# Compile the actual readiness wait, substituting only the clock/sleep and UI check.
READINESS_SWIFT = r'''

import Foundation

struct Failure: Error {}
struct XCUIApplication {}
@MainActor
enum Fake {
    static var time = 0.0
    static var steps: [(Double, Bool)] = []
    static var sleeps = 0
    static var cancelSleep = false
    static func condition() -> Bool {
        precondition(!steps.isEmpty, "Unexpected extra predicate call")
        let (elapsed, result) = steps.removeFirst()
        time += elapsed
        return result
    }
    static func sleep(for duration: Duration) async throws {
        sleeps += 1
        if cancelSleep { throw CancellationError() }
        time += 0.1
    }
}
@MainActor
struct FakeClock {
    struct Instant: Comparable {
        let value: Double
        func advanced(by duration: Duration) -> Instant {
            Instant(value: value + Double(duration.components.seconds))
        }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.value < rhs.value }
    }
    var now: Instant { Instant(value: Fake.time) }
}
@MainActor
final class Harness {
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw Failure() }
    }
    // ACTUAL_REQUIRE
}
@main
struct Main {
    @MainActor
    static func main() async {
        let scenarios: [(String, [(Double, Bool)], Bool, String, Int)] = [
            ("before", [(14.9, true)], false, "accepted", 0),
            ("at", [(15, true)], false, "rejected", 0),
            ("after", [(15.1, true)], false, "rejected", 0),
            ("false-crossing", [(15.1, false)], false, "rejected", 0),
            ("delayed", [(0, false), (14, true)], false, "accepted", 1),
            ("cancelled", [(0, false)], true, "cancelled", 1),
        ]
        for (name, steps, cancel, expected, sleeps) in scenarios {
            Fake.time = 0; Fake.steps = steps; Fake.sleeps = 0; Fake.cancelSleep = cancel
            var outcome = "accepted"
            do {
                try await Harness().require("deadline", app: XCUIApplication(), condition: Fake.condition)
            } catch is CancellationError { outcome = "cancelled" }
              catch is Failure { outcome = "rejected" }
              catch { preconditionFailure("Unexpected error: \(error)") }
            guard outcome == expected, Fake.steps.isEmpty, Fake.sleeps == sleeps else {
                print("FAIL \(name): \(outcome), expected \(expected); sleeps=\(Fake.sleeps)")
                exit(1)
            }
            print("PASS \(name)")
        }
    }
}
'''


class ReadinessDeadlineTests(unittest.TestCase):
    def test_actual_wait_enforces_post_predicate_deadline_and_preserves_cancellation(self):
        text = (ROOT / "UITests/PrivacyTransitionUITests.swift").read_text()
        start, end = "    private func require(", "\n    private func check("
        self.assertEqual(text.count(start), 1)
        self.assertEqual(text.count(end), 1)
        method = text[text.index(start):text.index(end, text.index(start))]
        method = method.replace("private func require", "func require")
        method = method.replace("ContinuousClock", "FakeClock").replace("Task.sleep", "Fake.sleep")
        with tempfile.TemporaryDirectory(prefix="tripdocket-readiness-deadline-") as directory:
            source, executable = Path(directory) / "main.swift", Path(directory) / "readiness"
            source.write_text(READINESS_SWIFT.replace("    // ACTUAL_REQUIRE", method))
            compiled = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library",
                                       str(source), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["PASS " + name for name in
                             ("before", "at", "after", "false-crossing", "delayed", "cancelled")])


if __name__ == "__main__":
    unittest.main()
