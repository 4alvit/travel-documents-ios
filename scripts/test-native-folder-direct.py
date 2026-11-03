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
enum Kind: Int { case application, window, other, collectionView, navigationBar, keyboard, cell, button, textView, staticText }
@MainActor final class XCUIElementSnapshot {
    var elementType: Kind
    var identifier: String
    var label: String
    var frame: CGRect
    var children: [XCUIElementSnapshot]
    var isEnabled = true
    var isHittable = true
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
    static func editor(_ snapshot: XCUIElementSnapshot, _ application: XCUIElementSnapshot, _ expected: String, introduction: Bool = false) -> CGRect? {
        nativeFolderEditorFrame(in: snapshot, applicationSnapshot: application, expectedName: expected, localTitle: "On My iPhone", keyboardIntroduction: introduction)
    }
    static func evidence(_ snapshot: XCUIElementSnapshot?, _ application: XCUIElementSnapshot, environment: Bool = false) -> String {
        var reason: String?
        let result = snapshot.flatMap {
            nativeFolderEditorFrame(in: $0, applicationSnapshot: application, expectedName: "untitled folder", localTitle: "On My iPhone",
                                    diagnostic: { if reason == nil { reason = $0 } })
        }
        let data = nativeFolderSnapshotEvidence(environment ? application : snapshot, observation: "pretype-actual-helper-input",
            expectedName: "untitled folder", localTitle: "On My iPhone", returnedFrame: result,
            liveFrame: CGRect(x: 0, y: 305, width: 169, height: 63), reason: reason)
        return String(decoding: data, as: UTF8.self)
    }
    static func candidate(_ snapshot: XCUIElementSnapshot, _ application: XCUIElementSnapshot) -> CGRect? {
        nativeFolderRenameFrame(in: snapshot, applicationSnapshot: application, localTitle: "On My iPhone")
    }
    static func initial(_ snapshot: XCUIElementSnapshot, _ application: XCUIElementSnapshot) -> String {
        let state = nativeFolderInitialState(in: snapshot, applicationSnapshot: application, localTitle: "On My iPhone")
        if let frame = state.renameFrame {
            precondition(state.ready && frame == CGRect(x: 10, y: 212, width: 122, height: 190))
            return "rename"
        }
        return state.ready ? "editor" : "rejected"
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
        window.children = []; app.children = [window]
        nav.children = [XCUIElementSnapshot(.button, "Save", "Save", CGRect(x: 316, y: 88, width: 70, height: 44))]
    }
    func mutate(_ name: String) {
        switch name {
        case "exact", "application-as-picker", "root-as-picker", "picker-as-application", "window-as-application": break
        case "application-also-includes-picker": window.children.append(picker)
        case "second-compatible-window": app.children.append(XCUIElementSnapshot(.window, "", "", window.frame))
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
        case "duplicate-picker": picker.children.append(XCUIElementSnapshot(.other, "Browse View (Picker)"))
        case "duplicate-grid": root.children.append(grid)
        case "duplicate-navigation": root.children.append(nav)
        case "root-outside-picker": picker.children = []; window.children.append(root)
        case "grid-outside-root": root.children = [nav]; picker.children.append(grid)
        case "navigation-outside-root": root.children = [grid]; picker.children.append(nav)
        case "nonfinite-cell": cell.frame.origin.x = .nan
        case "empty-cell": cell.frame.size.width = 0
        case "outside-grid": cell.frame.origin.y = 900
        case "outside-window": window.frame.size.height = 200
        case "missing-window": app.children = []
        case "oversized-tree": picker.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "environment-oversized-tree": window.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "environment-too-deep":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let next = XCUIElementSnapshot(.other); current.children = [next]; current = next }
            window.children.append(top)
        case "too-deep":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let next = XCUIElementSnapshot(.other); current.children = [next]; current = next }
            picker.children.append(top)
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
        root.children = [nav, grid]; picker.children = [root]; window.children = [keyboard]; app.children = [window]
    }
    func mutate(_ name: String) {
        switch name {
        case "exact", "application-as-picker", "root-as-picker", "picker-as-application", "window-as-application": break
        case "application-also-includes-picker": window.children.append(picker)
        case "second-compatible-window": app.children.append(XCUIElementSnapshot(.window, "", "", window.frame))
        case "wrong-provider": root.identifier = "DOC.browsingRoot Source: com.apple.CloudDocs, Title: On My iPhone"
        case "duplicate-picker": picker.children.append(XCUIElementSnapshot(.other, "Browse View (Picker)"))
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
        case "missing-keyboard": window.children = []
        case "missing-window": app.children = [keyboard]
        case "duplicate-keyboard": window.children.append(keyboard)
        case "root-outside-picker": picker.children = []; window.children.append(root)
        case "nav-outside-root": root.children = [grid]; picker.children.append(nav)
        case "grid-outside-root": root.children = [nav]; picker.children.append(grid)
        case "introduction-overlay": window.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "introduction-in-picker": picker.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "wrong-introduction-type": window.children.last!.elementType = .button
        case "remote-placeholder": picker.children = [XCUIElementSnapshot(.other, "RemotePlaceholder")]
        case "non-string-value": editor.value = 5
        case "long-strings": editor.label = String(repeating: "x", count: 10000)
        case "byte-limit":
            let payload = String(repeating: "\u{0001}", count: 128)
            picker.children += (0..<3000).map { _ in XCUIElementSnapshot(.other, payload, payload) }

        case "oversized-tree": picker.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "environment-oversized-tree": window.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "environment-too-deep":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let next = XCUIElementSnapshot(.other); current.children = [next]; current = next }
            window.children.append(top)
        case "too-deep":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let next = XCUIElementSnapshot(.other); current.children = [next]; current = next }
            picker.children.append(top)
        default: fatalError("Unknown editor shape")
        }
    }
}
@main struct Main {
    @MainActor static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        if args[0] == "initial-transition" {
            let folder = Tree(), editor = EditorTree("untitled folder"), empty = Tree()
            empty.mutate("missing-folder")
            let before = Harness.initial(folder.picker, folder.app)
            // The old fallback, selected by an earlier live editor=false,
            // rejects this now-editing pair. The actual classifier must not.
            precondition(Harness.candidate(editor.picker, editor.app) == nil)
            let editing = Harness.initial(editor.picker, editor.app)
            editor.mutate("introduction-overlay")
            let introduction = Harness.initial(editor.picker, editor.app)
            let absent = Harness.initial(empty.picker, empty.app)
            print([before, editing, introduction, absent,
                   Harness.initial(folder.picker, folder.app)].joined(separator: ","))
            return
        }
        if args[0] == "initial-crossed-pair" {
            let folder = Tree(), editor = EditorTree("untitled folder")
            print(Harness.initial(editor.picker, folder.app) + "," + Harness.initial(folder.picker, editor.app))
            return
        }
        if ["initial-editor", "initial-introduction"].contains(args[0]) {
            let tree = EditorTree("untitled folder")
            if args[0] == "initial-introduction" { tree.mutate("introduction-overlay") }
            tree.mutate(args[1])
            let scoped = args[1] == "application-as-picker" ? tree.app : (args[1] == "root-as-picker" ? tree.root : tree.picker)
            let application = args[1] == "picker-as-application" ? tree.picker : (args[1] == "window-as-application" ? tree.window : tree.app)
            print(Harness.initial(scoped, application)); return
        }
        if args[0] == "initial-rename" {
            let tree = Tree(); tree.mutate(args[1])
            print(Harness.initial(tree.picker, tree.app)); return
        }
        if args[0] == "evidence" || args[0] == "environment-evidence" {
            let tree = EditorTree("untitled folder")
            if args[1] == "missing" { print(Harness.evidence(nil, tree.app)); return }
            tree.mutate(args[1])
            print(Harness.evidence(tree.picker, tree.app, environment: args[0] == "environment-evidence")); return
        }
        if ["editor", "introduction-editor", "introduction-editor-absent"].contains(args[0]) {
            let tree = EditorTree(args[2])
            if args[0] == "introduction-editor" { tree.mutate("introduction-overlay") }
            tree.mutate(args[1])
            let scoped = args[1] == "application-as-picker" ? tree.app : (args[1] == "root-as-picker" ? tree.root : tree.picker)
            let application = args[1] == "picker-as-application" ? tree.picker : (args[1] == "window-as-application" ? tree.window : tree.app)
            if let frame = Harness.editor(scoped, application, args[2], introduction: args[0] != "editor") {
                precondition(frame == tree.editor.frame)
                precondition(!tree.cell.frame.contains(frame))
                print("accepted")
            } else { print("rejected") }
            return
        }
        if args[0] == "shape" {
            let tree = Tree(); tree.mutate(args[1])
            let scoped = args[1] == "application-as-picker" ? tree.app : (args[1] == "root-as-picker" ? tree.root : tree.picker)
            let application = args[1] == "picker-as-application" ? tree.picker : (args[1] == "window-as-application" ? tree.window : tree.app)
            if let rect = Harness.candidate(scoped, application) {
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


INTRODUCTION_SWIFT = r'''
@MainActor enum Task {
    static var cancelled = false
    static func checkCancellation() throws {
        if cancelled { throw CancellationError() }
    }
}
@MainActor func descendants(_ root: XCUIElementSnapshot) -> [XCUIElementSnapshot] {
    [root] + root.children.flatMap(descendants)
}
@MainActor final class XCUIElementQuery {
    let app: XCUIApplication
    let nodes: () -> [XCUIElementSnapshot]
    init(_ app: XCUIApplication, _ nodes: @escaping () -> [XCUIElementSnapshot]) {
        self.app = app; self.nodes = nodes
    }
    var count: Int { nodes().count }
    var element: XCUIElement { XCUIElement(app, nodes().first ?? XCUIElementSnapshot(.other)) }
    func matching(identifier: String) -> XCUIElementQuery {
        XCUIElementQuery(app) { self.nodes().filter { $0.identifier == identifier } }
    }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        XCUIElementQuery(app) { self.nodes().filter { predicate.evaluate(with: ["label": $0.label]) } }
    }
}
@MainActor final class XCUIElement {
    let app: XCUIApplication
    let node: XCUIElementSnapshot
    init(_ app: XCUIApplication, _ node: XCUIElementSnapshot) { self.app = app; self.node = node }
    func query(_ kind: Kind) -> XCUIElementQuery {
        XCUIElementQuery(app) { descendants(self.node).filter { $0.elementType == kind } }
    }
    var collectionViews: XCUIElementQuery { query(.collectionView) }
    var textViews: XCUIElementQuery { query(.textView) }
    var staticTexts: XCUIElementQuery { query(.staticText) }
    var buttons: XCUIElementQuery { query(.button) }
    var cells: XCUIElementQuery { query(.cell) }
    var isEnabled: Bool { node.isEnabled }
    var isHittable: Bool { node.isHittable }
    var value: Any? { node.value }
    var frame: CGRect { node.frame }
    func tap() {
        precondition(node.label == "Continue")
        app.taps += 1
        if app.mode != "dismissal-stalls" { app.tree.window.children.removeAll { $0 === app.introduction } }
        app.tree.editor.isHittable = true
        if app.mode == "wrong-value-after-tap" { app.tree.editor.value = "foreign" }
    }
}
@MainActor final class XCUIApplication {
    let tree = EditorTree("untitled folder")
    let introduction = XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView")
    let explanation = XCUIElementSnapshot(.staticText, "", "Speed up your typing by sliding your finger across the letters to compose a word.")
    let button = XCUIElementSnapshot(.button, "", "Continue")
    let mode: String
    var taps = 0
    var captures = 0
    var waits = 0
    var samples = 0
    init(_ mode: String) {
        self.mode = mode
        introduction.children = [explanation, button]
    }
    var otherElements: XCUIElementQuery {
        XCUIElementQuery(self) {
            (descendants(self.tree.picker) + descendants(self.tree.app)).filter { $0.elementType == .other }
        }
    }
    func showIntroduction() {
        tree.window.children.append(introduction)
        // The overlay blocks the editor; Continue, not the editor, must be hittable.
        tree.editor.isHittable = false
    }
    func mutate() {
        switch mode {
        case "duplicate-introduction": tree.window.children.append(introduction)
        case "wrong-explanation": explanation.label = "unrelated"
        case "duplicate-explanation": introduction.children.append(explanation)
        case "hidden-explanation": explanation.isHittable = false
        case "wrong-button": button.label = "Other"
        case "duplicate-button": introduction.children.append(button)
        case "disabled-button": button.isEnabled = false
        case "hidden-button": button.isHittable = false
        case "wrong-value": tree.editor.value = "foreign"
        case "disabled-editor": tree.editor.isEnabled = false
        case "duplicate-editor": tree.cell.children.append(tree.editor)
        case "missing-grid": tree.grid.identifier = "unrelated"
        case "duplicate-cell": tree.grid.children.append(tree.cell)
        case "wrong-provider": tree.mutate("wrong-provider")
        case "bad-frame": tree.mutate("editor-under-keyboard")
        case "initial-cancel": Task.cancelled = true
        default: break
        }
    }
}
@MainActor final class IntroductionHarness {
    static func nativeFolderEditorFrame(in snapshot: XCUIElementSnapshot,
        applicationSnapshot: XCUIElementSnapshot, expectedName: String,
        localTitle: String, keyboardIntroduction: Bool) -> CGRect? {
        precondition(localTitle == "On My iPhone")
        return Harness.editor(snapshot, applicationSnapshot, expectedName, introduction: keyboardIntroduction)
    }
    func nativeFolderSnapshots(_ app: XCUIApplication) throws -> (picker: XCUIElementSnapshot, application: XCUIElementSnapshot) {
        app.samples += 1
        return (app.tree.picker, app.tree.app)
    }
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw BatchTestFailure(message: message) }
    }
    func capture(_ app: XCUIApplication, _ message: String) {
        app.captures += 1
        if app.mode == "change-after-capture" { app.tree.editor.value = "foreign" }
        if app.mode == "cancel-after-capture" { Task.cancelled = true }
    }
    func wait(_ message: String, app: XCUIApplication, _ condition: () throws -> Bool) async throws {
        app.waits += 1
        // No fake time is advanced: evaluate the unchanged post-action predicate.
        // Failure simulates its final unsatisfied observation, never a retry tap.
        try check(try condition(), app: app, message)
    }
    // ACTUAL_INTRODUCTION_HELPER
    func run(_ app: XCUIApplication) async -> [String: Any] {
        var acknowledged = false
        var outcome = "returned"
        do {
            for phase in 0..<3 {
                let expected = phase == 2 ? "TripDocket-Batch-QA-12345678-1234-4234-8234-123456789abc" : "untitled folder"
                app.tree.editor.value = expected
                let show = app.mode == "posttype" ? phase == 2 : app.mode == "rename" ? phase == 1 : app.mode == "absent" ? false : phase == 0
                if show || app.mode == "repeated" && phase == 2 { app.showIntroduction(); app.mutate() }
                try await acknowledgeNativeFolderKeyboardIntroduction(app, expectedName: expected, acknowledged: &acknowledged)
            }
        } catch is CancellationError { outcome = "cancelled" }
        catch { outcome = "rejected" }
        return ["outcome": outcome, "acknowledged": acknowledged, "taps": app.taps,
                "captures": app.captures, "waits": app.waits, "samples": app.samples]
    }
}
@main struct Main {
    @MainActor static func main() async throws {
        let app = XCUIApplication(CommandLine.arguments[1])
        let result = await IntroductionHarness().run(app)
        print(String(decoding: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), as: UTF8.self))
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
        helpers += section("    private static func nativeFolderConfiguration", "    private func acknowledgeNativeFolderKeyboardIntroduction(")
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
        for case in ["exact", "application-also-includes-picker", "second-compatible-window"]:
            self.assertEqual(self.probe("shape", case), "accepted")
        for case in ["second-folder", "duplicate-folder", "wrong-name", "nonempty-folder", "wrong-label",
                     "save-as-cell", "button-not-folder", "disabled-folder", "missing-folder", "editor-present",
                     "editor-outside-grid", "keyboard-present", "wrong-provider", "wrong-root-title",
                     "duplicate-root", "duplicate-picker", "duplicate-grid", "duplicate-navigation",
                     "root-outside-picker", "grid-outside-root", "navigation-outside-root",
                     "nonfinite-cell", "empty-cell", "outside-grid", "outside-window", "missing-window",
                     "oversized-tree", "too-deep", "environment-oversized-tree", "environment-too-deep",
                     "application-as-picker", "root-as-picker", "picker-as-application", "window-as-application"]:
            with self.subTest(case=case): self.assertEqual(self.probe("shape", case), "rejected")

    def test_actual_editing_hierarchy_accepts_visible_title_and_real_editor_geometry(self):
        # Current original AX: editor x0..169 extends beyond its cell x10..132.
        # Snapshot titles have no hittability API; actual live editor remains checked at both call sites.
        for expected in ["untitled folder", "TripDocket-Batch-QA-" + TOKEN]:
            for case in ["exact", "application-also-includes-picker", "second-compatible-window"]:
                self.assertEqual(self.probe("editor", case, expected), "accepted")
            for case in ["wrong-provider", "duplicate-picker", "duplicate-root", "duplicate-grid", "duplicate-nav",
                         "duplicate-title", "wrong-title", "title-outside-nav", "title-outside-window", "empty-title",
                         "nonfinite-title", "missing-editor", "duplicate-editor", "wrong-value", "disabled-editor",
                         "editor-outside-cell-ancestry", "editor-outside-grid", "editor-outside-window",
                         "editor-under-keyboard", "empty-editor", "nonfinite-editor", "second-cell", "cell-outside-grid",
                         "missing-keyboard", "duplicate-keyboard", "root-outside-picker", "nav-outside-root",
                         "grid-outside-root", "introduction-overlay", "oversized-tree", "too-deep", "missing-window",
                         "environment-oversized-tree", "environment-too-deep", "application-as-picker",
                         "root-as-picker", "picker-as-application", "window-as-application"]:
                with self.subTest(expected=expected, case=case):
                    self.assertEqual(self.probe("editor", case, expected), "rejected")

    def test_introduction_opt_in_preserves_editor_identity_and_geometry(self):
        for expected in ["untitled folder", "TripDocket-Batch-QA-" + TOKEN]:
            self.assertEqual(self.probe("introduction-editor", "exact", expected), "accepted")
            self.assertEqual(self.probe("introduction-editor-absent", "exact", expected), "rejected")
            self.assertEqual(self.probe("editor", "introduction-overlay", expected), "rejected")
            for case in ["introduction-overlay", "wrong-introduction-type", "introduction-in-picker",
                         "wrong-provider", "duplicate-root", "duplicate-picker", "duplicate-editor",
                         "missing-editor", "wrong-value", "disabled-editor", "editor-outside-cell-ancestry",
                         "editor-outside-grid", "editor-under-keyboard", "duplicate-keyboard", "missing-keyboard"]:
                with self.subTest(expected=expected, case=case):
                    self.assertEqual(self.probe("introduction-editor", case, expected), "rejected")

    def test_actual_initial_classifier_recognizes_both_editors_and_exact_rename(self):
        for mode in ["initial-editor", "initial-introduction"]:
            for case in ["exact", "application-also-includes-picker", "second-compatible-window"]:
                with self.subTest(mode=mode, case=case):
                    self.assertEqual(self.probe(mode, case), "editor")
        self.assertEqual(self.probe("initial-rename", "exact"), "rename")

    def test_actual_initial_classifier_rejects_invalid_editor_pairs(self):
        for case in ["wrong-value", "wrong-provider", "wrong-title", "duplicate-picker", "duplicate-root",
                     "duplicate-grid", "duplicate-nav", "duplicate-editor", "second-cell", "missing-editor",
                     "missing-keyboard", "duplicate-keyboard", "missing-window", "disabled-editor",
                     "editor-outside-cell-ancestry", "editor-outside-grid", "editor-under-keyboard",
                     "remote-placeholder", "application-as-picker", "root-as-picker", "picker-as-application",
                     "window-as-application"]:
            with self.subTest(case=case):
                self.assertEqual(self.probe("initial-editor", case), "rejected")
        self.assertEqual(self.probe("initial-crossed-pair"), "rejected,rejected")

    def test_actual_initial_classifier_rejects_ambiguous_introduction_and_rename(self):
        for case in ["introduction-overlay", "wrong-introduction-type", "introduction-in-picker",
                     "missing-editor", "wrong-value", "missing-keyboard"]:
            with self.subTest(case=case):
                self.assertEqual(self.probe("initial-introduction", case), "rejected")
        for case in ["missing-folder", "duplicate-folder", "wrong-name", "nonempty-folder",
                     "save-as-cell", "disabled-folder", "editor-present", "keyboard-present", "wrong-provider"]:
            with self.subTest(case=case):
                self.assertEqual(self.probe("initial-rename", case), "rejected")

    def test_actual_initial_classifier_changes_state_without_stale_rename_frame(self):
        self.assertEqual(self.probe("initial-transition"), "rename,editor,editor,rejected,rename")

    def test_initial_wait_uses_one_pair_without_earlier_live_branch_or_new_deadline(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        initial = case[case.index('try await wait("Native folder has neither'):case.index("if let before = renameFrame")]
        self.assertEqual(initial.count("try self.nativeFolderSnapshots(app, diagnostic:"), 1)
        self.assertEqual(initial.count("Self.nativeFolderInitialState("), 1)
        self.assertIn("in: snapshots.picker, applicationSnapshot: snapshots.application", initial)
        self.assertLess(initial.index("renameFrame = nil"), initial.index("try self.nativeFolderSnapshots(app, diagnostic:"))
        self.assertIn("initialObservation.begin()", initial)
        self.assertIn("initialObservation.failed(error)\n                    return false", initial)
        self.assertIn("recordNativeFolderInitialFailure(initialObservation, localTitle: localTitle)\n            throw error", initial)
        self.assertIn("renameFrame = state.renameFrame", initial)
        self.assertIn("return state.ready", initial)
        for forbidden in [".count", ".isHittable", ".isEnabled", "nativeFolderRenameFrame(",
                          "timeout:", ".tap(", ".press(", "sleep", "while "]:
            self.assertNotIn(forbidden, initial)

    def test_editing_checks_keep_live_editor_actions_and_normal_navigation_hittability(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        self.assertEqual(case.count("Self.nativeFolderEditorFrame("), 2)
        self.assertIn("in: snapshots.picker, applicationSnapshot: snapshots.application", case)
        self.assertIn('expectedName: "untitled folder"', case)
        self.assertIn("expectedName: ownedFolder", case)
        pretype = case[case.index("let pretypeLiveReady"):case.index("inlineNames.element.typeText(ownedFolder)")]
        self.assertIn("files.count == 1 && files.element.cells.count == 1", pretype)
        self.assertIn("inlineNames.count == 1 && inlineNames.element.isEnabled && inlineNames.element.isHittable", pretype)
        self.assertEqual(pretype.count("try nativeFolderSnapshots(app)"), 1)
        self.assertNotIn("app.snapshot()", pretype)
        self.assertIn("pretypeSnapshot = snapshots.picker", pretype)
        self.assertIn("pretypeApplicationSnapshot = snapshots.application", pretype)
        self.assertIn("let frame = inlineNames.element.frame", pretype)
        self.assertIn("pretypeFramesMatch = pretypeReturnedFrame == frame", pretype)
        self.assertIn("try check(pretypeLiveReady && pretypeFramesMatch,", pretype)
        self.assertLess(pretype.index("if pretypeLiveReady {"), pretype.index("try nativeFolderSnapshots(app)"))
        self.assertLess(pretype.index("if !pretypeLiveReady || !pretypeFramesMatch"), pretype.index("recordNativeFolderSnapshot("))
        self.assertIn('pretypeSnapshot, observation: "pretype-actual-picker-input"', pretype)
        self.assertIn('pretypeApplicationSnapshot, observation: "pretype-actual-application-input"', pretype)
        self.assertEqual(pretype.count("recordNativeFolderSnapshot("), 2)
        self.assertNotIn("pretype-failure-later-scoped-picker", pretype)
        self.assertNotIn("scopedPickers", pretype)
        self.assertNotIn(".tap()", pretype)
        self.assertNotIn("sleep", pretype)
        end = case[case.index("try check(files.count == 1 && inlineNames.count == 1"):case.index("guard let before = nativeFolderBlankPoint")]
        self.assertIn("inlineNames.element.isEnabled && inlineNames.element.isHittable", end)
        self.assertIn("== inlineNames.element.frame", end)
        self.assertIn("in: endEditingSnapshots.picker", end)
        self.assertIn("applicationSnapshot: endEditingSnapshots.application", end)
        normal = UI[UI.index("    private func isRecoveryFolder"): ]
        self.assertIn("navigation.exists && titles.count == 1 && titles.element(boundBy: 0).isHittable", normal.split("\n    private func", 1)[0])

    def test_live_sampler_binds_two_scopes_without_actions_or_replacement(self):
        sampler = section("    @MainActor\n    private func nativeFolderSnapshots(", "    private func presentRecoverySave(")
        self.assertEqual(sampler.count("app.state == .runningForeground"), 2)
        self.assertEqual(sampler.count("pickers.count == 1"), 2)
        self.assertEqual(sampler.count("try pickers.element.snapshot()"), 1)
        self.assertEqual(sampler.count("try app.snapshot()"), 1)
        self.assertLess(sampler.index("try pickers.element.snapshot()"), sampler.index("try app.snapshot()"))
        self.assertLess(sampler.index("try app.snapshot()"), sampler.index("pickers.element.frame == picker.frame"))
        self.assertIn('picker.identifier == "Browse View (Picker)"', sampler)
        self.assertIn("picker.elementType == .other", sampler)
        self.assertIn("application.elementType == .application", sampler)
        self.assertIn("return (picker, application)", sampler)
        self.assertNotRegex(sampler, r"(?m)^\s*while\s")
        for forbidden in [".tap(", ".press(", "sleep", "children +", "children.append"]:
            self.assertNotIn(forbidden, sampler)

    def test_actual_evidence_serializes_input_fields_and_returned_frame(self):
        evidence = json.loads(self.probe("evidence", "exact"))
        self.assertTrue(evidence["treeComplete"])
        self.assertFalse(evidence["stringsTruncated"])
        self.assertIsNone(evidence["helperReason"])
        self.assertEqual(evidence["helperReturnedFrame"], [0, 305, 169, 63])
        self.assertEqual(evidence["liveComparedFrame"], [0, 305, 169, 63])
        rows = evidence["nodes"]
        self.assertEqual([n["index"] for n in rows], list(range(len(rows))))
        editor = next(n for n in rows if n["identifier"] == "DOC.inlineRenameField")
        self.assertEqual(editor["value"], "untitled folder")
        self.assertEqual(editor["frame"], [0, 305, 169, 63])
        self.assertEqual(editor["valueType"], "string")
        self.assertTrue(editor["enabled"])
        self.assertEqual(rows[editor["parent"]]["identifier"], "Folder")
        windows = [n for n in rows if n["type"] == 1]
        self.assertEqual(windows, [])
        self.assertFalse(any(n["type"] == 5 for n in rows))
        environment = json.loads(self.probe("environment-evidence", "exact"))
        self.assertEqual(environment["helperReturnedFrame"], [0, 305, 169, 63])
        self.assertEqual([n["frame"] for n in environment["nodes"] if n["type"] == 1], [[0, 0, 402, 874]])
        self.assertEqual(sum(n["type"] == 5 for n in environment["nodes"]), 1)
        self.assertFalse(any(n["identifier"] in ["Browse View (Picker)", "File View", "DOC.inlineRenameField"]
                             for n in environment["nodes"]))

    def test_actual_evidence_retains_rejected_shape_without_manufacturing_acceptance(self):
        for case in ["duplicate-editor", "duplicate-root", "editor-outside-grid", "nonfinite-editor",
                     "wrong-value", "disabled-editor", "remote-placeholder", "non-string-value"]:
            with self.subTest(case=case):
                evidence = json.loads(self.probe("evidence", case))
                self.assertTrue(evidence["treeComplete"])
                self.assertIsNone(evidence["helperReturnedFrame"])
                self.assertIsInstance(evidence["helperReason"], str)
        duplicate = json.loads(self.probe("evidence", "duplicate-editor"))
        self.assertEqual(sum(n["identifier"] == "DOC.inlineRenameField" for n in duplicate["nodes"]), 2)
        bad = json.loads(self.probe("evidence", "nonfinite-editor"))
        self.assertEqual(next(n for n in bad["nodes"] if n["identifier"] == "DOC.inlineRenameField")["frame"][0], "+inf")
        remote = json.loads(self.probe("evidence", "remote-placeholder"))
        self.assertEqual(remote["helperReason"], "structure-counts-or-ancestry")
        self.assertTrue(any(n["identifier"] == "RemotePlaceholder" for n in remote["nodes"]))

    def test_actual_evidence_bounds_and_unavailable_state_are_explicit(self):
        for case in ["oversized-tree", "too-deep", "byte-limit"]:
            with self.subTest(case=case):
                raw = self.probe("evidence", case)
                self.assertLessEqual(len(raw.encode()), 1048576)
                evidence = json.loads(raw)
                self.assertFalse(evidence["treeComplete"])
                self.assertIsInstance(evidence["truncation"], str)
                self.assertLessEqual(len(evidence["nodes"]), 4096)
        missing = json.loads(self.probe("evidence", "missing"))
        self.assertFalse(missing["snapshotPresent"])
        self.assertFalse(missing["treeComplete"])
        self.assertEqual(missing["nodes"], [])
        long = json.loads(self.probe("evidence", "long-strings"))
        self.assertTrue(long["stringsTruncated"])
        self.assertTrue(all(len(n["label"]) <= 128 for n in long["nodes"]))

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

    def test_introduction_uses_one_shared_action_budget_at_both_typing_boundaries(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        helper = section("    private func acknowledgeNativeFolderKeyboardIntroduction(", "    func testNativeCreateOwnedFilesFolder")
        self.assertEqual(case.count("var keyboardIntroductionAcknowledged = false"), 1)
        self.assertEqual(case.count("acknowledgeNativeFolderKeyboardIntroduction("), 2)
        self.assertEqual(case.count("acknowledged: &keyboardIntroductionAcknowledged"), 2)
        first = case.index("acknowledgeNativeFolderKeyboardIntroduction(")
        second = case.index("acknowledgeNativeFolderKeyboardIntroduction(", first + 1)
        self.assertLess(case.index("if let before = renameFrame"), first)
        self.assertLess(case.index("rename.element.tap()"), first)
        self.assertLess(first, case.index("let pretypeLiveReady"))
        self.assertLess(case.index("inlineNames.element.typeText(ownedFolder)"), second)
        self.assertLess(second, case.index("let endEditingSnapshots"))
        initial_wait = case[case.index('try await wait("Native folder has neither'):first]
        rename_wait = case[case.index('try await wait("Native folder Rename did not'):first]
        self.assertIn("Self.nativeFolderInitialState(", initial_wait)
        self.assertIn("keyboardIntroduction.count != 0", rename_wait)
        self.assertEqual(helper.count("acknowledge.element.tap()"), 1)
        self.assertEqual(helper.count("try ready()"), 2)
        self.assertLess(helper.index("try Task.checkCancellation()"), helper.index("acknowledged = true"))
        self.assertLess(helper.index("acknowledged = true"), helper.index("acknowledge.element.tap()"))
        self.assertIn("guard !acknowledged, introduction.count == 1", helper)
        self.assertIn("keyboardIntroduction: true", helper)
        self.assertNotIn("timeout:", helper)
        self.assertNotRegex(helper, r"(?m)^\s*(while|repeat|for)\b")

    def test_exact_name_and_single_rename_request_precede_host_handoff(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        self.assertIn("inlineNames.element.value as? String == ownedFolder", case)
        self.assertEqual(case.count("nativeFolderBlankPoint(in:"), 2)
        for name in ["beforeBlankSnapshots", "currentBlankSnapshots"]:
            self.assertIn(name + " = try nativeFolderSnapshots(app)", case)
            self.assertIn("in: " + name + ".picker", case)
            self.assertIn("applicationSnapshot: " + name + ".application", case)
        self.assertIn("current.point == before.point, current.normalized == before.normalized", case)
        self.assertEqual(case.count("files.element.coordinate(withNormalizedOffset: current.normalized).tap()"), 1)
        self.assertIn("defer { app.terminate() }", case)
        self.assertIn("app.state == .notRunning", case)
        self.assertIn('capture(app, "Native folder rename requested; host empty-folder verification pending")', case)
        self.assertIn("saved.count == 0 && !failed.exists", case)


    def test_post_rename_handoff_checks_no_save_and_stops_before_host_proof(self):
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        request = "files.element.coordinate(withNormalizedOffset: current.normalized).tap()"
        self.assertEqual(case.count(request), 1)
        handoff = case[case.index(request) + len(request):]
        ordered = [
            "try check(saved.count == 0 && !failed.exists, app: app,",
            'capture(app, "Native folder rename requested; host empty-folder verification pending")',
            "app.terminate()",
            'try await wait("Native-folder fixture did not stop before host verification", app: app)',
            "app.state == .notRunning",
        ]
        for text in ordered:
            self.assertEqual(handoff.count(text), 1)
        self.assertEqual([handoff.index(text) for text in ordered], sorted(handoff.index(text) for text in ordered))
        self.assertEqual(handoff.count("try await wait("), 1)
        # UI completion is now only a stopped fixture. The unchanged host must
        # independently adopt the exact empty leaf before seed can start.
        for forbidden in ["remainingEditors", "isRecoveryFolder(", "directory.element", ".tap(",
                          ".press(", ".typeText(", "timeout:", "sleep", "while ", "for attempt",
                          "recordBatchProducer", "native_folder_verified", "fixture_directory ="]:
            self.assertNotIn(forbidden, handoff)
        self.assertIn("executionTimeAllowance = 180", case)


class KeyboardIntroductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="native-folder-introduction-")
        cls.addClassCleanup(cls.scratch.cleanup)
        path = Path(cls.scratch.name)
        helpers = section("    @MainActor\n    private static func nativeFolderRenameFrame", "    private let productID")
        helpers += section("    private static func nativeFolderConfiguration", "    private func acknowledgeNativeFolderKeyboardIntroduction(")
        helpers += section("    private static func combinedBatchConfiguration", "    private static func recordBatchProducer")
        introduction = section("    private func acknowledgeNativeFolderKeyboardIntroduction(", "    func testNativeCreateOwnedFilesFolder")
        source = SWIFT[:SWIFT.index("@main struct Main")].replace("    // ACTUAL_HELPERS", helpers)
        source += INTRODUCTION_SWIFT.replace("    // ACTUAL_INTRODUCTION_HELPER", introduction)
        swift = path / "Introduction.swift"
        swift.write_text(source)
        cls.binary = path / "introduction-tests"
        compiled = subprocess.run(["/usr/bin/swiftc", "-swift-version", "6", "-strict-concurrency=complete",
                                   "-parse-as-library", str(swift), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def probe(self, mode):
        result = subprocess.run([str(self.binary), mode], check=True, capture_output=True, text=True, timeout=5)
        return json.loads(result.stdout)

    def test_absent_introduction_performs_no_actions_or_extra_observation(self):
        self.assertEqual(self.probe("absent"), {"outcome": "returned", "acknowledged": False,
                                             "taps": 0, "captures": 0, "waits": 0, "samples": 0})

    def test_first_introduction_can_occur_at_each_of_three_boundaries(self):
        for phase in ["pretype", "rename", "posttype"]:
            with self.subTest(phase=phase):
                self.assertEqual(self.probe(phase), {"outcome": "returned", "acknowledged": True,
                                                   "taps": 1, "captures": 1, "waits": 1, "samples": 2})

    def test_ambiguous_or_wrong_introduction_never_taps(self):
        for mode in ["duplicate-introduction", "wrong-explanation", "duplicate-explanation", "hidden-explanation",
                     "wrong-button", "duplicate-button", "disabled-button", "hidden-button", "wrong-value",
                     "disabled-editor", "duplicate-editor", "missing-grid", "duplicate-cell", "wrong-provider", "bad-frame"]:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual(result["outcome"], "rejected")
                self.assertFalse(result["acknowledged"])
                self.assertEqual((result["taps"], result["captures"], result["waits"]), (0, 0, 0))

    def test_changed_target_and_cancellation_cannot_spend_the_action(self):
        for mode, outcome in [("change-after-capture", "rejected"),
                              ("initial-cancel", "cancelled"), ("cancel-after-capture", "cancelled")]:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual(result["outcome"], outcome)
                self.assertFalse(result["acknowledged"])
                self.assertEqual((result["taps"], result["waits"]), (0, 0))

    def test_reappearance_or_unsatisfied_dismissal_never_repeats_continue(self):
        for mode in ["repeated", "dismissal-stalls", "wrong-value-after-tap"]:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual(result["outcome"], "rejected")
                self.assertTrue(result["acknowledged"])
                self.assertEqual((result["taps"], result["captures"], result["waits"]), (1, 1, 1))




PREACTION_SUPPORT = r"""
@MainActor final class ActionCounters { var presses = 0; var taps = 0; var waits = 0 }
@MainActor final class ActionElement {
    var frame = CGRect(x: 10, y: 212, width: 122, height: 190)
    var isEnabled = true; var isHittable = true
    var cells: ActionQuery!
    let counters: ActionCounters
    init(_ counters: ActionCounters) { self.counters = counters }
    func press(forDuration seconds: Double) { precondition(seconds == 1); counters.presses += 1 }
    func tap() { counters.taps += 1 }
}
@MainActor final class ActionQuery {
    var count = 1
    let element: ActionElement
    init(_ counters: ActionCounters) { element = ActionElement(counters) }
    func matching(_ predicate: NSPredicate) -> ActionQuery { self }
}
@MainActor final class ActionApp {
    let counters = ActionCounters()
    let files: ActionQuery; let created: ActionQuery; let buttons: ActionQuery
    let inlineNames: ActionQuery; let introduction: ActionQuery
    var rootValid = true
    init(_ mode: String) {
        files = ActionQuery(counters); created = ActionQuery(counters); buttons = ActionQuery(counters)
        inlineNames = ActionQuery(counters); introduction = ActionQuery(counters)
        introduction.count = 0; files.element.cells = created
        switch mode {
        case "live-root": rootValid = false
        case "live-duplicate": created.count = 2
        case "live-frame": created.element.frame.origin.x += 1
        case "live-disabled": created.element.isEnabled = false
        case "live-hidden": created.element.isHittable = false
        case "menu-hidden": buttons.element.isHittable = false
        default: break
        }
    }
}
"""

PREACTION_METHOD = r"""
    func check(_ value: Bool, app: ActionApp, _ message: String) throws {
        if !value { throw BatchTestFailure(message: message) }
    }
    func isNativeFilesRoot(_ app: ActionApp) -> Bool { app.rootValid }
    func wait(_ message: String, app: ActionApp, _ condition: () -> Bool) async throws {
        app.counters.waits += 1
        try check(condition(), app: app, message)
    }
    func exerciseAction(_ app: ActionApp, _ picker: XCUIElementSnapshot,
                        _ application: XCUIElementSnapshot) async -> String {
        let before = CGRect(x: 10, y: 212, width: 122, height: 190)
        let snapshots = (picker: picker, application: application)
        let localTitle = "On My iPhone"
        let files = app.files, created = app.created
        let inlineNames = app.inlineNames, keyboardIntroduction = app.introduction
        do {
            // ACTUAL_PREACTION
            return "accepted"
        } catch { return "rejected" }
    }
"""

PREACTION_MAIN = r"""
@main struct ActionMain {
    @MainActor static func main() async {
        let mode = CommandLine.arguments[1]
        let folder = Tree(), editor = EditorTree("untitled folder")
        let app = ActionApp(mode)
        var picker = folder.picker, application = folder.app
        if mode.hasPrefix("editor") || mode.hasPrefix("invalid-editor-") {
            picker = editor.picker; application = editor.app
            if mode == "editor-introduction" { editor.mutate("introduction-overlay") }
            if mode.hasPrefix("invalid-editor-") { editor.mutate(String(mode.dropFirst("invalid-editor-".count))) }
        } else if mode == "changed-frame" { folder.cell.frame.origin.x += 1 }
        else if mode == "unknown" { folder.mutate("missing-folder") }
        else if mode == "ambiguous" { folder.mutate("duplicate-folder") }
        else if mode == "wrong-provider" { folder.mutate("wrong-provider") }
        else if mode == "crossed-pair" { application = editor.app }
        let result = await Harness().exerciseAction(app, picker, application)
        print("\(result),\(app.counters.presses),\(app.counters.taps),\(app.counters.waits)")
    }
}
"""


class PreRenameActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="native-folder-preaction-")
        cls.addClassCleanup(cls.scratch.cleanup)
        path = Path(cls.scratch.name)
        helpers = section("    @MainActor\n    private static func nativeFolderRenameFrame", "    private let productID")
        helpers += section("    private static func nativeFolderConfiguration", "    private func acknowledgeNativeFolderKeyboardIntroduction(")
        helpers += section("    private static func combinedBatchConfiguration", "    private static func recordBatchProducer")
        case = section("    func testNativeCreateOwnedFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        block = case[case.index("            let currentState = Self.nativeFolderInitialState("):case.index("        // One shared acknowledgement")]
        # Remove only the closing brace of the outer initial-candidate branch.
        assert block.endswith("        }\n")
        block = block[:-len("        }\n")]
        common = SWIFT[:SWIFT.index("@main struct Main")].replace("    // ACTUAL_HELPERS", helpers)
        common = common.replace("}\n@MainActor final class Tree", PREACTION_METHOD.replace("            // ACTUAL_PREACTION", block) + "}\n@MainActor final class Tree", 1)
        swift = path / "PreAction.swift"; cls.binary = path / "preaction"
        swift.write_text(common + PREACTION_SUPPORT + PREACTION_MAIN)
        result = subprocess.run(["/usr/bin/swiftc", "-swift-version", "6", "-strict-concurrency=complete",
                                 "-parse-as-library", str(swift), "-o", str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def probe(self, mode):
        return subprocess.run([str(self.binary), mode], capture_output=True, text=True,
                              check=True, timeout=5).stdout.strip()

    def test_late_real_editor_bypasses_both_rename_actions(self):
        for mode in ["editor", "editor-introduction"]:
            with self.subTest(mode=mode): self.assertEqual(self.probe(mode), "accepted,0,0,0")

    def test_same_untitled_folder_still_requires_exactly_one_press_and_rename(self):
        self.assertEqual(self.probe("same-folder"), "accepted,1,1,2")

    def test_unknown_ambiguous_or_changed_frame_stops_before_any_action(self):
        for mode in ["unknown", "ambiguous", "changed-frame", "wrong-provider", "crossed-pair"]:
            with self.subTest(mode=mode): self.assertEqual(self.probe(mode), "rejected,0,0,0")

    def test_invalid_editor_cannot_be_used_as_rename_bypass(self):
        for mode in ["wrong-value", "duplicate-editor", "missing-keyboard", "wrong-provider",
                     "editor-under-keyboard", "duplicate-picker", "introduction-in-picker"]:
            with self.subTest(mode=mode): self.assertEqual(self.probe("invalid-editor-" + mode), "rejected,0,0,0")

    def test_original_live_guards_remain_before_long_press(self):
        for mode in ["live-root", "live-duplicate", "live-frame", "live-disabled", "live-hidden"]:
            with self.subTest(mode=mode): self.assertEqual(self.probe(mode), "rejected,0,0,0")
        self.assertEqual(self.probe("menu-hidden"), "rejected,1,0,1")

if __name__ == "__main__":
    unittest.main()
