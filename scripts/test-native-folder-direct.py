#!/usr/bin/env python3
"""Exercise actual folder identity/snapshot gates without a Simulator or XCTest."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "UITests/BatchImportUITests.swift").read_text()
TOKEN = "12345678-1234-4234-8234-123456789abc"
SESSION = "1A5C10F8-85FD-473F-9CF3-6B12E9D82F61"
SOURCE_TOKEN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def section(start, end):
    offset = UI.index(start)
    return UI[offset:UI.index(end, offset)]


SWIFT = r'''
import Foundation
import CoreGraphics
struct BatchTestFailure: Error { let message: String }
enum Kind { case application, window, other, collectionView, navigationBar, keyboard, cell, button, textView, staticText }
@MainActor final class XCUIElementSnapshot {
    var elementType: Kind
    var identifier: String
    var label: String
    var frame: CGRect
    var children: [XCUIElementSnapshot]
    var isEnabled = true
    var value: Any? = nil
    init(_ kind: Kind, _ id: String = "", _ label: String = "", _ frame: CGRect = .zero,
         _ children: [XCUIElementSnapshot] = []) {
        elementType = kind; identifier = id; self.label = label
        self.frame = frame; self.children = children
    }
}
@MainActor final class Harness {
    struct BatchCheckpointIdentity: Equatable { let session: String; let token: String }
    // ACTUAL_HELPERS
    static func folder(_ env: [String: String], _ debug: Bool) throws -> String {
        let result = try nativeFolderConfiguration(env, debugSimulator: debug)
        return result.token + ":" + result.sourceToken
    }
    static func combined(_ env: [String: String], _ debug: Bool) throws -> String {
        guard let result = try combinedBatchConfiguration(env, debugSimulator: debug) else { return "none" }
        return result.session + ":" + result.token
    }
    static func editor(_ snapshot: XCUIElementSnapshot, _ expected: String) -> CGRect? {
        nativeFolderEditorFrame(in: snapshot, expectedName: expected, localTitle: "On My iPhone")
    }
    static func candidate(_ snapshot: XCUIElementSnapshot) -> CGRect? {
        nativeFolderRenameFrame(in: snapshot, localTitle: "On My iPhone")
    }
}
@MainActor final class Tree {
    let cell = XCUIElementSnapshot(.cell, "untitled folder, Folder", "untitled folder, 0 items",
                                  CGRect(x: 10, y: 212, width: 122, height: 190))
    let grid = XCUIElementSnapshot(.collectionView, "File View", "", CGRect(x: 0, y: 72, width: 402, height: 802))
    let nav = XCUIElementSnapshot(.navigationBar, "FullDocumentManagerViewControllerNavigationBar")
    let root = XCUIElementSnapshot(.other, "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone")
    let picker = XCUIElementSnapshot(.other, "Browse View (Picker)")
    let window = XCUIElementSnapshot(.window, "", "", CGRect(x: 0, y: 0, width: 402, height: 874))
    let app = XCUIElementSnapshot(.application)
    init() {
        grid.children = [cell]; root.children = [nav, grid]; picker.children = [root]
        window.children = [picker]; app.children = [window]
        nav.children = [XCUIElementSnapshot(.button, "Save", "Save", CGRect(x: 316, y: 88, width: 70, height: 44))]
    }
    func mutate(_ name: String) {
        switch name {
        case "exact": break
        case "second-folder": grid.children.append(XCUIElementSnapshot(.cell, "other, Folder", "other, 0 items", cell.frame))
        case "duplicate-folder": grid.children.append(cell)
        case "wrong-name": cell.identifier = "foreign, Folder"
        case "nonempty-folder": cell.label = "untitled folder, 1 item"
        case "wrong-label": cell.label = "foreign, 0 items"
        case "save-as-cell": cell.identifier = "Save"; cell.label = "Save"
        case "button-not-folder": cell.elementType = .button
        case "disabled-folder": cell.isEnabled = false
        case "missing-folder": grid.children = []
        case "editor-present": cell.children.append(XCUIElementSnapshot(.textView, "DOC.inlineRenameField"))
        case "editor-outside-grid": window.children.append(XCUIElementSnapshot(.textView, "DOC.inlineRenameField"))
        case "keyboard-present": window.children.append(XCUIElementSnapshot(.keyboard))
        case "wrong-provider": root.identifier = "DOC.browsingRoot Source: com.apple.CloudDocs, Title: On My iPhone"
        case "wrong-root-title": root.identifier = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: Other"
        case "duplicate-root": picker.children.append(root)
        case "duplicate-picker": window.children.append(picker)
        case "duplicate-grid": root.children.append(grid)
        case "duplicate-navigation": root.children.append(nav)
        case "root-outside-picker": picker.children = []; window.children.append(root)
        case "grid-outside-root": root.children = [nav]; picker.children.append(grid)
        case "navigation-outside-root": root.children = [grid]; picker.children.append(nav)
        case "nonfinite-cell": cell.frame.origin.x = .nan
        case "empty-cell": cell.frame.size.width = 0
        case "outside-grid": cell.frame.origin.y = 900
        case "outside-window": window.frame.size.height = 200
        case "missing-window": app.children = [picker]
        case "oversized-tree": window.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "too-deep":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let next = XCUIElementSnapshot(.other); current.children = [next]; current = next }
            window.children.append(top)
        default: fatalError("Unknown shape")
        }
    }
}
@MainActor final class EditorTree {
    let title = XCUIElementSnapshot(.staticText, "", "On My iPhone", CGRect(x: 72, y: 99.7, width: 109.7, height: 20.7))
    let editor = XCUIElementSnapshot(.textView, "DOC.inlineRenameField", "", CGRect(x: 0, y: 305, width: 169, height: 63))
    let cell = XCUIElementSnapshot(.cell, "Folder", "", CGRect(x: 10, y: 212, width: 122, height: 189.7))
    let grid = XCUIElementSnapshot(.collectionView, "File View", "", CGRect(x: 0, y: 72, width: 402, height: 802))
    let nav = XCUIElementSnapshot(.navigationBar, "FullDocumentManagerViewControllerNavigationBar", "", CGRect(x: 0, y: 88, width: 402, height: 114))
    let root = XCUIElementSnapshot(.other, "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone")
    let picker = XCUIElementSnapshot(.other, "Browse View (Picker)")
    let keyboard = XCUIElementSnapshot(.keyboard, "", "", CGRect(x: 0, y: 583, width: 402, height: 233))
    let window = XCUIElementSnapshot(.window, "", "", CGRect(x: 0, y: 0, width: 402, height: 874))
    let app = XCUIElementSnapshot(.application)
    init(_ expected: String) {
        editor.value = expected; cell.children = [editor]; grid.children = [cell]; nav.children = [title]
        root.children = [nav, grid]; picker.children = [root]; window.children = [picker, keyboard]; app.children = [window]
    }
    func mutate(_ name: String) {
        switch name {
        case "exact": break
        case "wrong-provider": root.identifier = "DOC.browsingRoot Source: com.apple.CloudDocs, Title: On My iPhone"
        case "duplicate-picker": window.children.append(picker)
        case "duplicate-root": picker.children.append(root)
        case "duplicate-grid": root.children.append(grid)
        case "duplicate-nav": root.children.append(nav)
        case "duplicate-title": nav.children.append(title)
        case "wrong-title": title.label = "Other"
        case "title-outside-nav": title.frame.origin.y = 300
        case "title-outside-window": window.frame.origin.y = 200
        case "empty-title": title.frame.size.width = 0
        case "nonfinite-title": title.frame.origin.x = .nan
        case "missing-editor": cell.children = []
        case "duplicate-editor": cell.children.append(editor)
        case "wrong-value": editor.value = "foreign"
        case "disabled-editor": editor.isEnabled = false
        case "editor-outside-cell-ancestry": cell.children = []; grid.children.append(editor)
        case "editor-outside-grid": editor.frame.origin.y = 0
        case "editor-outside-window": window.frame.size.width = 150
        case "editor-under-keyboard": editor.frame.origin.y = 600
        case "empty-editor": editor.frame.size.height = 0
        case "nonfinite-editor": editor.frame.origin.x = .infinity
        case "second-cell": grid.children.append(XCUIElementSnapshot(.cell))
        case "cell-outside-grid": cell.frame.origin.y = 0
        case "missing-keyboard": window.children = [picker]
        case "duplicate-keyboard": window.children.append(keyboard)
        case "root-outside-picker": picker.children = []; window.children.append(root)
        case "nav-outside-root": root.children = [grid]; picker.children.append(nav)
        case "grid-outside-root": root.children = [nav]; picker.children.append(grid)
        case "introduction-overlay": window.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "oversized-tree": window.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "too-deep":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let next = XCUIElementSnapshot(.other); current.children = [next]; current = next }
            window.children.append(top)
        default: fatalError("Unknown editor shape")
        }
    }
}
@main struct Main {
    @MainActor static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        if args[0] == "editor" {
            let tree = EditorTree(args[2]); tree.mutate(args[1])
            if let frame = Harness.editor(tree.app, args[2]) {
                precondition(frame == tree.editor.frame)
                precondition(!tree.cell.frame.contains(frame))
                print("accepted")
            } else { print("rejected") }
            return
        }
        if args[0] == "shape" {
            let tree = Tree(); tree.mutate(args[1])
            if let rect = Harness.candidate(tree.app) {
                precondition(rect == tree.cell.frame); print("accepted")
            } else { print("rejected") }
            return
        }
        do {
            let env = try JSONDecoder().decode([String: String].self, from: Data(args[1].utf8))
            print(try args[0] == "folder" ? Harness.folder(env, args[2] == "true") : Harness.combined(env, args[2] == "true"))
        } catch { print("rejected") }
    }
}
'''


class FolderDirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="native-folder-direct-")
        cls.addClassCleanup(cls.scratch.cleanup)
        path = Path(cls.scratch.name)
        helpers = section("    @MainActor\n    private static func nativeFolderRenameFrame", "    private let productID")
        helpers += section("    private static func nativeFolderConfiguration", "    func testNativeCreateOwnedFilesFolder")
        helpers += section("    private static func combinedBatchConfiguration", "    private static func recordBatchProducer")
        swift = path / "Probe.swift"; cls.binary = path / "probe"
        swift.write_text(SWIFT.replace("    // ACTUAL_HELPERS", helpers))
        result = subprocess.run(["/usr/bin/swiftc", "-swift-version", "6", "-strict-concurrency=complete",
                                 "-parse-as-library", str(swift), "-o", str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def probe(self, *args):
        return subprocess.run([str(self.binary), *args], check=True, capture_output=True,
                              text=True, timeout=5).stdout.strip()

    def config(self, env, mode="folder", debug=True):
        return self.probe(mode, json.dumps(env), str(debug).lower())

    def folder_env(self):
        return {"TRIPDOCKET_NATIVE_FOLDER_UI": "1", "TRIPDOCKET_NATIVE_FOLDER_TOKEN": TOKEN,
                "TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN": SOURCE_TOKEN,
                "TRIPDOCKET_BATCH_FOLDER": "TripDocket-Batch-QA-" + TOKEN}

    def combined_env(self, kind):
        return {"TRIPDOCKET_COMBINED_BATCH_UI": "1", "TRIPDOCKET_BATCH_CHECKPOINT_SESSION": SESSION,
                "TRIPDOCKET_NATIVE_" + kind + "_UI": "1", "TRIPDOCKET_NATIVE_" + kind + "_TOKEN": TOKEN,
                "TRIPDOCKET_NATIVE_SEED_UI": "1", "TRIPDOCKET_NATIVE_SEED_TOKEN": TOKEN,
                "TRIPDOCKET_BATCH_UI": "1", "TRIPDOCKET_BATCH_FOLDER": "TripDocket-Batch-QA-" + TOKEN}

    def test_actual_folder_identity_is_isolated_and_canonical(self):
        env = self.folder_env()
        self.assertEqual(self.config(env), TOKEN + ":" + SOURCE_TOKEN)
        rejected = [{}, {**env, "TRIPDOCKET_NATIVE_FOLDER_UI": "0"},
                    {**env, "TRIPDOCKET_BATCH_FOLDER": "other"}]
        rejected += [{**env, "TRIPDOCKET_NATIVE_FOLDER_TOKEN": token} for token in ["", TOKEN.upper(), "../x", "not-uuid"]]
        rejected += [{**env, "TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN": value}
                     for value in ["", TOKEN, SOURCE_TOKEN.upper(), "../x", "not-uuid"]]
        rejected += [{k: v for k, v in env.items() if k != missing} for missing in env]
        for value in rejected:
            with self.subTest(value=value): self.assertEqual(self.config(value), "rejected")
        self.assertEqual(self.config(env, debug=False), "rejected")

    def test_actual_folder_rejects_every_other_phase_even_empty_flags(self):
        for key in ["TRIPDOCKET_RECOVERY_UI", "TRIPDOCKET_RECOVERY_PHASE", "TRIPDOCKET_RECOVERY_FOLDER",
                    "TRIPDOCKET_BATCH_PREPARE_UI", "TRIPDOCKET_BATCH_PREPARE_TOKEN",
                    "TRIPDOCKET_NATIVE_SEED_UI", "TRIPDOCKET_NATIVE_SEED_TOKEN",
                    "TRIPDOCKET_NATIVE_ROOT_UI", "TRIPDOCKET_NATIVE_ROOT_TOKEN", "TRIPDOCKET_BATCH_UI",
                    "TRIPDOCKET_COMBINED_BATCH_UI", "TRIPDOCKET_BATCH_CHECKPOINT_SESSION", "TRIPDOCKET_NATIVE_REOPEN_CONTROL"]:
            for value in ["", "1"]:
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.config({**self.folder_env(), key: value}), "rejected")

    def test_actual_combined_root_and_folder_require_one_complete_identity(self):
        self.assertEqual(self.config({}, "combined"), "none")
        for kind in ["ROOT", "FOLDER"]:
            env = self.combined_env(kind)
            self.assertEqual(self.config(env, "combined"), SESSION + ":" + TOKEN)
            self.assertEqual(self.config(env, "combined", False), "rejected")
            self.assertEqual(self.config({**env, "TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN": SOURCE_TOKEN}, "combined"), "rejected")
            for key in env:
                wrong = {**env, key: "invalid"}
                with self.subTest(kind=kind, key=key): self.assertEqual(self.config(wrong, "combined"), "rejected")
            opposite = "FOLDER" if kind == "ROOT" else "ROOT"
            for suffix in ["UI", "TOKEN"]:
                for value in ["", "1", TOKEN]:
                    with self.subTest(kind=kind, suffix=suffix, value=value):
                        mixed = {**env, "TRIPDOCKET_NATIVE_" + opposite + "_" + suffix: value}
                        self.assertEqual(self.config(mixed, "combined"), "rejected")
            for bad in [TOKEN.upper(), "../x", ""]:
                self.assertEqual(self.config({**env, "TRIPDOCKET_NATIVE_" + kind + "_TOKEN": bad}, "combined"), "rejected")
            for bad in [SESSION.lower(), "1A5C10F8-85FD-173F-9CF3-6B12E9D82F61", "1A5C10F8-85FD-473F-1CF3-6B12E9D82F61"]:
                self.assertEqual(self.config({**env, "TRIPDOCKET_BATCH_CHECKPOINT_SESSION": bad}, "combined"), "rejected")

    def test_actual_snapshot_accepts_only_exact_empty_native_folder(self):
        self.assertEqual(self.probe("shape", "exact"), "accepted")
        for case in ["second-folder", "duplicate-folder", "wrong-name", "nonempty-folder", "wrong-label",
                     "save-as-cell", "button-not-folder", "disabled-folder", "missing-folder", "editor-present",
                     "editor-outside-grid", "keyboard-present", "wrong-provider", "wrong-root-title",
                     "duplicate-root", "duplicate-picker", "duplicate-grid", "duplicate-navigation",
                     "root-outside-picker", "grid-outside-root", "navigation-outside-root",
                     "nonfinite-cell", "empty-cell", "outside-grid", "outside-window", "missing-window",
                     "oversized-tree", "too-deep"]:
            with self.subTest(case=case): self.assertEqual(self.probe("shape", case), "rejected")

    def test_actual_editing_hierarchy_accepts_visible_title_and_real_editor_geometry(self):
        # Current original AX: editor x0..169 extends beyond its cell x10..132.
        # Snapshot titles have no hittability API; actual live editor remains checked at both call sites.
        for expected in ["untitled folder", "TripDocket-Batch-QA-" + TOKEN]:
            self.assertEqual(self.probe("editor", "exact", expected), "accepted")
            for case in ["wrong-provider", "duplicate-picker", "duplicate-root", "duplicate-grid", "duplicate-nav",
                         "duplicate-title", "wrong-title", "title-outside-nav", "title-outside-window", "empty-title",
                         "nonfinite-title", "missing-editor", "duplicate-editor", "wrong-value", "disabled-editor",
                         "editor-outside-cell-ancestry", "editor-outside-grid", "editor-outside-window",
                         "editor-under-keyboard", "empty-editor", "nonfinite-editor", "second-cell", "cell-outside-grid",
                         "missing-keyboard", "duplicate-keyboard", "root-outside-picker", "nav-outside-root",
                         "grid-outside-root", "introduction-overlay", "oversized-tree", "too-deep"]:
                with self.subTest(expected=expected, case=case):
                    self.assertEqual(self.probe("editor", case, expected), "rejected")

    def test_editing_checks_keep_live_editor_actions_and_normal_navigation_hittability(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        self.assertEqual(case.count("Self.nativeFolderEditorFrame(in: try app.snapshot()"), 2)
        self.assertIn('expectedName: "untitled folder"', case)
        self.assertIn("expectedName: ownedFolder", case)
        for failure in ["Native folder editor left the single newly created local folder",
                        "Native folder editor is not ready for explicit end-editing"]:
            statement = case[:case.index(failure)].rsplit("try check(", 1)[1]
            self.assertIn("inlineNames.element.isEnabled && inlineNames.element.isHittable", statement)
            self.assertIn("== inlineNames.element.frame", statement)
            self.assertNotIn("isRecoveryFolder(", statement)
            self.assertNotIn("isNativeFilesRoot(", statement)
        normal = UI[UI.index("    private func isRecoveryFolder"): ]
        self.assertIn("navigation.exists && titles.count == 1 && titles.element(boundBy: 0).isHittable", normal.split("\n    private func", 1)[0])

    def test_ui_has_one_direct_ingress_and_guarded_rename_without_save_or_retry(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        self.assertIn("executionTimeAllowance = 180", case)
        self.assertIn("Self.nativeFolderConfiguration(environment, debugSimulator: debugSimulator)", case)
        self.assertIn("#if DEBUG && targetEnvironment(simulator)", case)
        self.assertIn('"--ui-testing-native-batch-token", configuration.sourceToken', case)
        self.assertEqual(case.count("source.element.tap()"), 1)
        self.assertIn("let picker = try await openNativeFilesRoot(app)", case)
        self.assertIn("files.element.cells.count == 0", case)
        self.assertEqual(case.count("more.element.tap()"), 1)
        self.assertEqual(case.count("newFolder.element.tap()"), 1)
        self.assertEqual(case.count("created.element.press(forDuration: 1)"), 1)
        self.assertEqual(case.count("rename.element.tap()"), 1)
        self.assertIn("created.element.frame == before", case)
        self.assertIn("created.element.isEnabled && created.element.isHittable", case)
        self.assertIn("rename.count == 1 && rename.element.isEnabled && rename.element.isHittable", case)
        self.assertLess(case.index("files.element.cells.count == 0"), case.index("newFolder.element.tap()"))
        self.assertLess(case.index("if let before = renameFrame"), case.index("created.element.press"))
        self.assertLess(case.index("rename.element.tap()"), case.index("inlineNames.element.typeText(ownedFolder)"))
        for forbidden in ["presentRecoverySave(", "recoveryTab(", '"--demo"', "save.tap()", 'buttons["Save"]',
                          "createDirectory", ".mkdir", "while ", "for attempt", "recordBatchProducer"]:
            self.assertNotIn(forbidden, case)

    def test_existing_exact_name_defocus_and_host_handoff_proofs_are_retained(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        self.assertIn("inlineNames.element.value as? String == ownedFolder", case)
        self.assertEqual(case.count("nativeFolderBlankPoint(in: try app.snapshot()"), 2)
        self.assertIn("current.point == before.point, current.normalized == before.normalized", case)
        self.assertIn("remainingEditors.count == 0", case)
        self.assertIn("self.isRecoveryFolder(ownedFolder, navigation: navigation.element)", case)
        self.assertIn("defer { app.terminate() }", case)
        self.assertIn("app.state == .notRunning", case)
        self.assertIn('capture(app, "Native folder exact destination before host empty-folder verification")', case)
        self.assertIn("saved.count == 0 && !failed.exists", case)


if __name__ == "__main__":
    unittest.main()
