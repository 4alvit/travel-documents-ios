#!/usr/bin/env python3
"""Exercise actual diagnostic state/reader code without XCTest or Simulator."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "App/BatchImportView.swift"
UI = ROOT / "UITests/BatchImportUITests.swift"
FLAG = "--ui-testing-batch-diagnostics"


def section(source, start, end):
    if source.count(start) != 1:
        raise ValueError("Expected one source boundary: " + start)
    offset = source.index(start)
    return source[offset:source.index(end, offset)]


FIXTURE = r'''
import Foundation
enum BatchImportDraft {
    enum Phase { case choosing, preparing, reviewing, committing }
}
// ACTUAL_STATE
enum ElementType { case other, collectionView }
@MainActor
protocol XCUIElementSnapshot {
    var children: [any XCUIElementSnapshot] { get }
    var elementType: ElementType { get }
    var identifier: String { get }
    var value: Any? { get }
}
@MainActor
final class Node: XCUIElementSnapshot {
    let children: [any XCUIElementSnapshot]
    let elementType: ElementType
    let identifier: String
    let value: Any?
    init(_ value: Any? = nil, identifier: String = "batch.importer",
         type: ElementType = .collectionView, children: [any XCUIElementSnapshot] = []) {
        self.value = value; self.identifier = identifier
        self.elementType = type; self.children = children
    }
}
@MainActor
struct Reader {
    // ACTUAL_READER
    func read(_ root: any XCUIElementSnapshot) -> String { batchImporterDiagnosticValue(root) }
}
struct PrivateFailure: LocalizedError {
    var errorDescription: String? { "/private/secret-user-document.pdf token=secret" }
}
@MainActor
final class XCUIApplication {}
@MainActor
final class XCUIElement {
    var exists = true
    var lateResult = false
    var requests: [TimeInterval] = []
    func waitForNonExistence(timeout: TimeInterval) -> Bool {
        requests.append(timeout)
        return lateResult
    }
}
@MainActor
final class XCTAttachment {
    enum Lifetime { case keepAlways }
    let text: String
    var name = ""
    var lifetime = Lifetime.keepAlways
    init(string: String) { text = string }
}
final class BatchTestFailure: Error, @unchecked Sendable {}
@MainActor
final class DismissalHarness {
    let original = BatchTestFailure()
    var cancelled = false
    var captures: [String] = []
    var attachments: [XCTAttachment] = []
    func wait(_ message: String, app: XCUIApplication, condition: @MainActor () -> Bool) async throws {
        if cancelled { throw CancellationError() }
        if condition() { return }
        capture(app, message, batchDiagnostic: true)
        throw original
    }
    func capture(_ app: XCUIApplication, _ name: String, batchDiagnostic: Bool) { captures.append(name) }
    func add(_ attachment: XCTAttachment) { attachments.append(attachment) }
    func run(_ navigation: XCUIElement) async throws {
        try await requireFilesDismissal(XCUIApplication(), navigation: navigation, openedAt: .now)
    }
    // ACTUAL_DISMISSAL
}
@MainActor
func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { print("FAIL " + message); exit(1) }
}
@main
struct Main {
    @MainActor
    static func main() async {
        let name = CommandLine.arguments[1]
        var state = BatchImporterDiagnostics()
        let reader = Reader()
        let initial = "batch-importer showsFiles=1 callbackCount=0 resultKind=none urlCount=0 draftPhase=choosing"
        switch name {
        case "disabled":
            state.record(.success([URL(fileURLWithPath: "/private/secret.pdf")]))
            expect(state.value(showsFiles: true, phase: .choosing) == nil, "Flagless diagnostics must be absent")
        case "initial-and-phases":
            expect(state.value(showsFiles: true, phase: .choosing) == initial, "Initial state")
            for phase in [BatchImportDraft.Phase.choosing, .preparing, .reviewing, .committing] {
                let value = state.value(showsFiles: false, phase: phase)!
                expect(reader.read(Node(value)) == value, "Actual producer/reader phase contract")
                expect(value.utf8.count <= 128, "Value bound")
            }
        case "saturation-and-private-payload":
            let urls = Array(repeating: URL(fileURLWithPath: "/private/secret-user-document.pdf"), count: 100)
            for _ in 0..<200 { state.record(.success(urls)) }
            let value = state.value(showsFiles: false, phase: .reviewing)!
            expect(value == "batch-importer showsFiles=0 callbackCount=99 resultKind=success urlCount=11 draftPhase=reviewing", "Counts must saturate")
            expect(reader.read(Node(value)) == value, "Saturated producer value is accepted")
            state.record(.failure(PrivateFailure()))
            let failure = state.value(showsFiles: false, phase: .choosing)!
            expect(failure == "batch-importer showsFiles=0 callbackCount=99 resultKind=failure urlCount=0 draftPhase=choosing", "Failure must erase URL count and omit error payload")
            expect(reader.read(Node(failure)) == failure, "Failure enum accepted")
        case "malformed-values":
            let invalid: [Any?] = [nil, 1, initial + "\n", initial + " token=secret",
                initial.replacingOccurrences(of: "callbackCount=0", with: "callbackCount=100"),
                initial.replacingOccurrences(of: "callbackCount=0", with: "callbackCount=00"),
                initial.replacingOccurrences(of: "urlCount=0", with: "urlCount=12"),
                initial.replacingOccurrences(of: "urlCount=0", with: "urlCount=-1"),
                initial.replacingOccurrences(of: "showsFiles=1", with: "showsFiles=true"),
                initial.replacingOccurrences(of: "resultKind=none", with: "resultKind=/private/secret"),
                initial.replacingOccurrences(of: "draftPhase=choosing", with: "draftPhase=unknown"),
                String(repeating: "x", count: 129)]
            for value in invalid { expect(reader.read(Node(value)) == "unavailable", "Malformed value leaked or accepted") }
        case "identity-and-duplicates":
            expect(reader.read(Node(initial, identifier: "other")) == "unavailable", "Wrong identifier")
            expect(reader.read(Node(initial, type: .other)) == "unavailable", "Wrong element type")
            expect(reader.read(Node(identifier: "root", type: .other, children: [Node(initial), Node(initial)])) == "unavailable", "Duplicate identity")
            expect(reader.read(Node(identifier: "root", type: .other, children: [Node(initial)])) == initial, "Nested exact container")
        case "tree-bounds":
            var node: any XCUIElementSnapshot = Node(initial)
            for _ in 0..<64 { node = Node(identifier: "parent", type: .other, children: [node]) }
            expect(reader.read(node) == initial, "Depth64 must be admitted")
            node = Node(identifier: "parent", type: .other, children: [node])
            expect(reader.read(node) == "unavailable", "Depth65 must fail")
            let leaf = Node(identifier: "other", type: .other)
            let valid = Node(identifier: "root", type: .other, children: [Node(initial)] + Array(repeating: leaf, count: 1022))
            expect(reader.read(valid) == initial, "1024 total nodes must be admitted")
            let excessive = Node(identifier: "root", type: .other, children: [Node(initial)] + Array(repeating: leaf, count: 1023))
            expect(reader.read(excessive) == "unavailable", "Excessive tree must fail")
        case "dismissal-success", "dismissal-late", "dismissal-still-present", "dismissal-cancelled":
            let harness = DismissalHarness()
            let navigation = XCUIElement()
            navigation.exists = name != "dismissal-success"
            navigation.lateResult = name == "dismissal-late"
            harness.cancelled = name == "dismissal-cancelled"
            var returned = false
            var originalRethrown = false
            var cancellationRethrown = false
            do {
                try await harness.run(navigation)
                returned = true
            } catch let error as BatchTestFailure {
                originalRethrown = error === harness.original
            } catch is CancellationError {
                cancellationRethrown = true
            } catch { expect(false, "Unexpected replacement error") }
            if name == "dismissal-success" || name == "dismissal-cancelled" {
                expect(returned == (name == "dismissal-success"), "Success must retain original outcome")
                expect(cancellationRethrown == (name == "dismissal-cancelled"), "Cancellation must propagate")
                expect(navigation.requests.isEmpty && harness.captures.isEmpty && harness.attachments.isEmpty,
                       "No passive diagnostic outside the original dismissal failure")
            } else {
                expect(!returned && originalRethrown, "Late disappearance must still throw exact original failure")
                expect(navigation.requests == [30], "Exactly one passive request")
                expect(harness.captures == ["Files remained after opening the selection",
                    "Files after passive late observation — original failure retained"], "Before/after capture order")
                expect(harness.attachments.count == 1, "One timing attachment")
                let timing = harness.attachments[0].text
                for key in ["originalDismissalCriterion=failed", "requestedObservationSeconds=30",
                            "observationStartedSinceOpenReturned=", "observationFinishedSinceOpenReturned=",
                            "observedElapsed=", "navigationDisappeared=\(navigation.lateResult)", "acceptance=failed"] {
                    expect(timing.contains(key), "Missing timing/result field: " + key)
                }
            }
        default: preconditionFailure("Unknown fixture")
        }
        print("PASS " + name)
    }
}
'''


class BatchImportDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="tripdocket-batch-diagnostics-")
        cls.addClassCleanup(cls.directory.cleanup)
        source = section(APP.read_text(), "@MainActor\nprivate struct BatchImporterDiagnostics", "\nprivate struct BatchImporterDiagnosticValue")
        reader = section(UI.read_text(), "    private func batchImporterDiagnosticValue(", "\n    private struct BatchTestFailure")
        dismissal = section(UI.read_text(), "    private func requireFilesDismissal(", "\n    private func reviewRows(")
        swift = Path(cls.directory.name) / "main.swift"
        swift.write_text(FIXTURE.replace("// ACTUAL_STATE", source).replace("    // ACTUAL_READER", reader)
                         .replace("    // ACTUAL_DISMISSAL", dismissal))
        cls.binary = Path(cls.directory.name) / "diagnostic-tests"
        result = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library",
                                 str(swift), "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name, enabled=True):
        result = subprocess.run([str(self.binary), name] + ([FLAG] if enabled else []),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS " + name)

    def test_explicit_opt_in(self):
        self.run_case("disabled", enabled=False)

    def test_initial_state_and_all_phases(self):
        self.run_case("initial-and-phases")

    def test_saturating_counts_and_payload_privacy(self):
        self.run_case("saturation-and-private-payload")

    def test_strict_value_allowlist(self):
        self.run_case("malformed-values")

    def test_exact_container_and_duplicates(self):
        self.run_case("identity-and-duplicates")

    def test_snapshot_work_bounds(self):
        self.run_case("tree-bounds")

    def test_original_dismissal_success_has_no_extra_observation(self):
        self.run_case("dismissal-success")

    def test_late_disappearance_still_throws_original_failure(self):
        self.run_case("dismissal-late")

    def test_still_present_still_throws_original_failure(self):
        self.run_case("dismissal-still-present")

    def test_cancellation_is_not_observed_or_replaced(self):
        self.run_case("dismissal-cancelled")

    def test_late_observation_has_no_actions_or_polling_loop(self):
        ui = UI.read_text()
        dismissal = section(ui, "    private func requireFilesDismissal(", "\n    private func reviewRows(")
        self.assertEqual(dismissal.count("waitForNonExistence(timeout: 30)"), 1)
        self.assertEqual(dismissal.count('try await wait("Files remained after opening the selection", app: app) { !navigation.exists }'), 1)
        self.assertIn("catch let originalFailure as BatchTestFailure", dismissal)
        self.assertIn("throw originalFailure", dismissal)
        self.assertNotIn("timeout:", dismissal.split("catch let")[0])
        for forbidden in [".tap(", ".swipe", ".launch(", ".terminate(", "Task.sleep", "while ", "repeat {", "try?"]:
            self.assertNotIn(forbidden, dismissal)
        self.assertLess(dismissal.index("add(timing)"), dismissal.index("capture(app,"))
        self.assertLess(dismissal.index("capture(app,"), dismissal.index("throw originalFailure"))

    def test_all_app_diagnostics_are_debug_simulator_only(self):
        stack = []
        required = "#if DEBUG && targetEnvironment(simulator)"
        for line in APP.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#if "):
                stack.append(stripped)
            elif stripped == "#endif":
                stack.pop()
            elif any(token in line for token in ["BatchImporterDiagnostic", "importerDiagnostics", FLAG, '"batch.importer"', '"batch-importer']):
                self.assertIn(required, stack, line)
        self.assertFalse(stack)

    def test_capture_is_observation_only_and_before_existing_screenshot(self):
        app = APP.read_text()
        callback = section(app, "                          allowsMultipleSelection: true)", "\nprivate struct BatchItemReviewView")
        self.assertLess(callback.index("importerDiagnostics.record(result)"), callback.index("guard model.batchImportDraft?.id"))
        ui = UI.read_text()
        selection = section(ui, "    private func selectRealFiles(", "\n    private func reviewRows(")
        self.assertEqual(selection.count("open.tap()"), 1)
        diagnostic = 'capture(app, "Two synthetic originals selected in real Files", batchDiagnostic: true)'
        self.assertEqual(selection.count(diagnostic), 1)
        self.assertLess(selection.index(diagnostic), selection.index("open.tap()"))
        between = selection[selection.index(diagnostic) + len(diagnostic):selection.index("open.tap()")]
        self.assertEqual(between.strip(), """if nativeRoot {
            try check(isNativeFilesRoot(app) && openActions.count == 1,
                      app: app, "Batch selection left its verified local root or unique Open action")
        }""")
        capture = section(ui, "    private func capture(", "\n    private struct BatchTestFailure")
        self.assertIn('if batchDiagnostic && app.launchArguments.contains("' + FLAG + '")', capture)
        self.assertEqual(capture.count("app.snapshot()"), 1)
        self.assertLess(capture.index("app.snapshot()"), capture.index("XCUIScreen.main.screenshot()"))
        self.assertNotIn(".tap()", capture)
        self.assertNotIn("sleep", capture)
        self.assertIn("timeout: Duration = .seconds(15)", ui)
        batch = section(ui, "    func testRealFilesBatchRequiresEveryReviewAndPreservesOriginals()",
                        "\n    // Opt-in prepare/export/restore phases.")
        self.assertEqual(batch.count("executionTimeAllowance ="), 1)
        self.assertIn("executionTimeAllowance = 600", batch)
        recovery = section(ui, "    private func recoveryConfiguration(", "\n    private func recoveryTab(")
        self.assertIn('executionTimeAllowance = phase == "prepare" ? 180 : 300', recovery)


if __name__ == "__main__":
    unittest.main()
