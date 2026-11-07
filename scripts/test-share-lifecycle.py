#!/usr/bin/env python3
"""Compile actual share callback/diagnostics with fake UIKit; no app or Simulator."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FLAG = "--ui-testing-share-diagnostics"
FIXTURE = r'''
import Foundation
import Dispatch

@MainActor protocol UIViewControllerRepresentable {}
typealias Context = Void
enum UIActivity {
    struct ActivityType: Sendable { let rawValue: String }
}
@MainActor final class UIActivityViewController {
    var completionWithItemsHandler: ((UIActivity.ActivityType?, Bool, [Any]?, Error?) -> Void)?
    init(activityItems: [Any], applicationActivities: [Any]?) {}
}

// ACTUAL_SHARE_SOURCE

@MainActor final class CompletionState {
    var count = 0
    var continuation: CheckedContinuation<Void, Never>?
}
@main struct Main {
    @MainActor static func main() async throws {
        let mode = CommandLine.arguments[1]
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("PRIVATE_FILENAME_SECRET")
        try Data("PRIVATE_CONTENT_SECRET".utf8).write(to: url)
        #if DEBUG
        if mode == "budget" {
            let diagnostics = ShareLifecycleDiagnostics()!
            DispatchQueue.concurrentPerform(iterations: 32) { _ in
                diagnostics.record(.handoff, url: url)
            }
            return
        }
        #endif
        let state = CompletionState()
        let share = ExplicitShareSheet(url: url, onComplete: {
            precondition(Thread.isMainThread)
            state.count += 1
            try! FileManager.default.removeItem(at: url)
            state.continuation!.resume()
        })
        let controller = share.makeUIViewController(context: ())
        let sensitive = mode == "privacy"
        let error: NSError? = mode == "success" ? nil : NSError(
            domain: sensitive ? "PRIVATE_DOMAIN_SECRET" : NSOSStatusErrorDomain,
            code: -10814, userInfo: [NSLocalizedDescriptionKey: "PRIVATE_ERROR_SECRET"])
        let activity = UIActivity.ActivityType(rawValue: sensitive ? "PRIVATE_ACTIVITY_SECRET"
                                               : "com.apple.DocumentManagerUICore.SaveToFiles")
        await withCheckedContinuation { continuation in
            state.continuation = continuation
            controller.completionWithItemsHandler!(activity, mode == "success", nil, error)
            // The real handler must still schedule cleanup asynchronously on MainActor.
            precondition(state.count == 0)
            precondition(FileManager.default.fileExists(atPath: url.path))
        }
        precondition(state.count == 1)
        precondition(!FileManager.default.fileExists(atPath: url.path))
        print("PASS callback scheduling and exactly one cleanup")
    }
}
'''


class ShareLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tripdocket-share-lifecycle-")
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        source = (ROOT / "App/Scanner.swift").read_text()
        anchor = "struct ExplicitShareSheet: UIViewControllerRepresentable {"
        if source.count(anchor) != 1:
            raise AssertionError("Expected unique actual share implementation")
        actual = source[source.index(anchor):]
        swift = root / "main.swift"
        swift.write_text(FIXTURE.replace("// ACTUAL_SHARE_SOURCE", actual))
        cls.programs = {}
        for debug in (False, True):
            program = root / ("debug" if debug else "release")
            args = ["swiftc", "-swift-version", "6", "-parse-as-library"]
            if debug:
                args += ["-D", "DEBUG"]
            result = subprocess.run(args + [str(swift), "-o", str(program)],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.programs[debug] = program

    def invoke(self, mode, *, debug=True, enabled=True):
        args = [str(self.programs[debug]), mode] + ([FLAG] if enabled else [])
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("PRIVATE_", result.stdout + result.stderr)
        rows = [json.loads(line.removeprefix("share-lifecycle "))
                for line in result.stdout.splitlines() if line.startswith("share-lifecycle ")]
        if mode != "budget":
            self.assertIn("PASS callback scheduling and exactly one cleanup", result.stdout)
        return rows

    def check_lifecycle(self, mode):
        rows = self.invoke(mode)
        self.assertEqual([row["stage"] for row in rows],
                         ["handoff", "completion", "cleanupBefore", "cleanupAfter"])
        self.assertEqual(len({row["id"] for row in rows}), 1)
        self.assertEqual([row["exists"] for row in rows], [True, True, True, False])
        self.assertEqual([row["readable"] for row in rows], [True, True, True, False])
        self.assertEqual([row["metadata_available"] for row in rows], [True, True, True, False])
        self.assertEqual([row.get("bytes") for row in rows], [22, 22, 22, None])
        self.assertTrue(all(type(row["ms"]) is int and 0 <= row["ms"] <= 86_400_000 for row in rows))
        self.assertEqual(sorted(row["ms"] for row in rows), [row["ms"] for row in rows])
        return rows[1]

    def test_success_preserves_async_cleanup_and_records_metadata_only(self):
        result = self.check_lifecycle("success")
        self.assertIs(result["completed"], True)
        self.assertNotIn("error_domain", result)
        self.assertEqual(result["activity"], "com.apple.DocumentManagerUICore.SaveToFiles")

    def test_failed_completion_reports_only_bounded_system_error_fields(self):
        result = self.check_lifecycle("error")
        self.assertIs(result["completed"], False)
        self.assertEqual(result["error_domain"], "NSOSStatusErrorDomain")
        self.assertEqual(result["error_code"], -10814)

    def test_arbitrary_error_and_activity_text_are_not_disclosed(self):
        result = self.check_lifecycle("privacy")
        self.assertEqual(result["activity"], "other")
        self.assertEqual(result["error_domain"], "other")
        self.assertNotIn("description", result)
        self.assertNotIn("userInfo", result)

    def test_no_output_without_explicit_flag(self):
        self.assertEqual(self.invoke("success", enabled=False), [])

    def test_release_compiles_out_diagnostics_even_with_flag(self):
        self.assertEqual(self.invoke("success", debug=False), [])
        self.assertNotIn(FLAG.encode(), self.programs[False].read_bytes())
        self.assertNotIn(b"share-lifecycle", self.programs[False].read_bytes())

    def test_parallel_callbacks_cannot_exceed_four_events(self):
        rows = self.invoke("budget")
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["id"] for row in rows}), 1)


if __name__ == "__main__":
    unittest.main()
