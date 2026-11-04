#!/usr/bin/env python3
"""Exercise actual folder identity/snapshot gates without a Simulator or XCTest."""
import json
import re
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


def native_folder_execution():
    """Read the actual one-call helper at its caller position to check runtime order."""
    caller = section("    func testNativeCreateOwnedFilesFolder", "    // Both callers supply")
    helper = section("    private func createNativeEmptyFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
    call = "        try await createNativeEmptyFilesFolder(app, picker: picker, ownedFolder: ownedFolder)\n"
    assert caller.count(call) == 1
    opening = "    ) async throws {\n"
    body = helper.split(opening, 1)[1]
    assert body.endswith("    }\n\n")
    return caller.replace(call, body[:-len("    }\n\n")], 1)


SWIFT = r'''
import Foundation
import CoreGraphics
struct BatchTestFailure: Error { let message: String }
enum Kind: Int { case application, window, other, collectionView, navigationBar, keyboard, cell, button, textView, staticText, image, searchField }
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
        case "introduction-without-keyboard":
            window.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView", "",
                CGRect(x: 0, y: 539, width: 402, height: 335)))
        case "introduction-in-picker": picker.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "wrong-type-introduction": window.children.append(XCUIElementSnapshot(.button, "UIContinuousPathIntroductionView"))
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
        if name.hasPrefix("without-keyboard:") {
            mutate("missing-keyboard")
            mutate(String(name.dropFirst("without-keyboard:".count)))
            return
        }
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
        case "missing-keyboard": window.children.removeAll { $0 === keyboard }
        case "missing-window": app.children = [keyboard]
        case "duplicate-keyboard": window.children.append(keyboard)
        case "root-outside-picker": picker.children = []; window.children.append(root)
        case "nav-outside-root": root.children = [grid]; picker.children.append(nav)
        case "grid-outside-root": root.children = [nav]; picker.children.append(grid)
        case "introduction-overlay": window.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView", "",
            CGRect(x: 0, y: 539, width: 402, height: 335)))
        case "introduction-in-picker": picker.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "wrong-introduction-type": window.children.last!.elementType = .button
        case "nested-introduction-and-window":
            let introduction = window.children.removeLast()
            window.children.append(XCUIElementSnapshot(.window, "", "", window.frame, [introduction]))
            app.children.append(XCUIElementSnapshot(.window, "", "", window.frame))
        case "dismissed-introduction":
            window.children.removeAll { $0.identifier == "UIContinuousPathIntroductionView" }
        case "empty-introduction": window.children.last!.frame.size.height = 0
        case "nonfinite-introduction": window.children.last!.frame.origin.x = .nan
        case "introduction-outside-window": window.children.last!.frame.origin.y = 600
        case "introduction-over-editor": window.children.last!.frame = editor.frame
        case "introduction-over-title": window.children.last!.frame = title.frame
        case "empty-keyboard": keyboard.frame.size.height = 0
        case "nonfinite-keyboard": keyboard.frame.origin.x = .infinity
        case "keyboard-over-title": keyboard.frame = title.frame
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
        if app.mode == "without-keyboard" { app.tree.window.children.append(app.tree.keyboard) }
        app.tree.editor.isHittable = true
        if app.mode == "wrong-value-after-tap" { app.tree.editor.value = "foreign" }
    }
}
@MainActor final class XCUIApplication {
    let tree = EditorTree("untitled folder")
    let introduction = XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView", "",
        CGRect(x: 0, y: 539, width: 402, height: 335))
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
        case "without-keyboard": tree.mutate("missing-keyboard")
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
                    "TRIPDOCKET_RECOVERY_CREATE_FOLDER", "TRIPDOCKET_BATCH_PREPARE_UI", "TRIPDOCKET_BATCH_PREPARE_TOKEN",
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
                         "editor-outside-grid", "editor-under-keyboard", "duplicate-keyboard"]:
                with self.subTest(expected=expected, case=case):
                    self.assertEqual(self.probe("introduction-editor", case, expected), "rejected")

    def test_visible_introduction_accepts_zero_or_one_keyboard_only_when_opted_in(self):
        for shape in ["exact", "missing-keyboard", "nested-introduction-and-window",
                      "without-keyboard:nested-introduction-and-window"]:
            for expected in ["untitled folder", "TripDocket-Batch-QA-" + TOKEN]:
                with self.subTest(shape=shape, expected=expected):
                    self.assertEqual(self.probe("introduction-editor", shape, expected), "accepted")
            self.assertEqual(self.probe("initial-introduction", shape), "editor")
        self.assertEqual(self.probe("editor", "missing-keyboard", "untitled folder"), "rejected")
        self.assertEqual(self.probe("initial-introduction", "without-keyboard:dismissed-introduction"), "rejected")
        self.assertEqual(self.probe("initial-introduction", "dismissed-introduction"), "editor")

    def test_introduction_geometry_and_any_present_keyboard_remain_required(self):
        for keyboard in ["", "without-keyboard:"]:
            for invalid in ["empty-introduction", "nonfinite-introduction", "introduction-outside-window",
                            "introduction-over-editor", "introduction-over-title", "introduction-overlay",
                            "wrong-introduction-type", "introduction-in-picker", "wrong-value", "wrong-provider",
                            "duplicate-editor", "disabled-editor", "missing-editor", "editor-outside-cell-ancestry"]:
                shape = keyboard + invalid
                with self.subTest(shape=shape):
                    self.assertEqual(self.probe("introduction-editor", shape, "untitled folder"), "rejected")
                    self.assertEqual(self.probe("initial-introduction", shape), "rejected")
        for shape in ["empty-keyboard", "nonfinite-keyboard", "keyboard-over-title", "duplicate-keyboard"]:
            with self.subTest(shape=shape):
                self.assertEqual(self.probe("introduction-editor", shape, "untitled folder"), "rejected")
                self.assertEqual(self.probe("initial-introduction", shape), "rejected")

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
                     "missing-editor", "wrong-value"]:
            with self.subTest(case=case):
                self.assertEqual(self.probe("initial-introduction", case), "rejected")
        for case in ["missing-folder", "duplicate-folder", "wrong-name", "nonempty-folder",
                     "save-as-cell", "disabled-folder", "editor-present", "keyboard-present", "wrong-provider"]:
            with self.subTest(case=case):
                self.assertEqual(self.probe("initial-rename", case), "rejected")

    def test_introduction_without_editor_cannot_fall_back_to_rename(self):
        for shape in ["introduction-without-keyboard", "introduction-in-picker", "wrong-type-introduction"]:
            with self.subTest(shape=shape):
                self.assertEqual(self.probe("shape", shape), "rejected")
                self.assertEqual(self.probe("initial-rename", shape), "rejected")

    def test_actual_initial_classifier_changes_state_without_stale_rename_frame(self):
        self.assertEqual(self.probe("initial-transition"), "rename,editor,editor,rejected,rename")

    def test_shared_creation_preserves_caller_boundaries_and_action_order(self):
        caller = section("    func testNativeCreateOwnedFilesFolder", "    // Both callers supply")
        helper = section("    private func createNativeEmptyFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        call = 'try await createNativeEmptyFilesFolder(app, picker: picker, ownedFolder: ownedFolder)'
        self.assertEqual(caller.count(call), 1)
        before, after = caller.split(call)
        self.assertIn('Self.nativeFolderConfiguration(', before)
        self.assertIn('source.element.tap()', before)
        self.assertIn('try await openNativeFilesRoot(app, initialTimeout: .seconds(30))', before)
        self.assertIn('saved.count == 0 && !failed.exists', before)
        self.assertIn('saved.count == 0 && !failed.exists', after)
        self.assertIn('app.terminate()', after)
        self.assertIn('app.state == .notRunning', after)
        self.assertIn('UIDevice.current.userInterfaceIdiom == .phone', helper)
        self.assertIn('files.element.cells.count == 0', helper)
        self.assertIn('directory.count == 0', helper)
        for forbidden in ('app.launch()', 'app.terminate()', 'presentRecoverySave(',
                          'openNativeFilesRoot(', 'buttons["Save"]', 'executionTimeAllowance'):
            self.assertNotIn(forbidden, helper)
        self.assertEqual(helper.count('more.element.tap()'), 1)
        self.assertEqual(helper.count('newFolder.element.tap()'), 1)
        self.assertEqual(helper.count('inlineNames.element.typeText(ownedFolder)'), 1)
        self.assertLess(helper.index('files.element.cells.count == 0'), helper.index('more.element.tap()'))
        self.assertLess(helper.index('more.element.tap()'), helper.index('newFolder.element.tap()'))
        self.assertLess(helper.index('newFolder.element.tap()'), helper.index('inlineNames.element.typeText(ownedFolder)'))

    def test_initial_wait_keeps_parent_pair_and_one_scoped_return_allowance(self):
        case = native_folder_execution()
        initial = case[case.index('try await wait("Native folder has neither'):case.index("if let before = renameFrame")]
        self.assertEqual(initial.count("try self.nativeFolderSnapshots(app, diagnostic:"), 2)
        self.assertEqual(initial.count("Self.nativeFolderInitialState("), 1)
        self.assertIn("in: snapshots.picker, applicationSnapshot: snapshots.application", initial)
        self.assertLess(initial.index("renameFrame = nil"), initial.index("try self.nativeFolderSnapshots(app, diagnostic:"))
        self.assertIn("initialObservation.begin()", initial)
        self.assertIn("initialObservation.failed(error)\n                    return false", initial)
        self.assertIn("recordNativeFolderInitialFailure(initialObservation, localTitle: localTitle)\n            throw error", initial)
        self.assertIn("renameFrame = state.renameFrame", initial)
        self.assertIn("if state.ready { return ContinuousClock.now < initialDeadline }", initial)
        self.assertEqual(initial.count("timeout: .seconds(30)"), 1)
        self.assertIn('app: app, timeout: .seconds(30)) {', initial.splitlines()[0])
        for forbidden in ["nativeFolderRenameFrame(", ".press(", "sleep", "while "]:
            self.assertNotIn(forbidden, initial)
        self.assertNotIn("timeout:", "\n".join(initial.splitlines()[1:]))
        self.assertEqual(initial.count("back.element.tap()"), 1)
        self.assertEqual(initial.count("let current = try self.nativeFolderSnapshots(app, diagnostic:"), 1)
        self.assertEqual(initial.count("Self.nativeFolderParentReturnFrame("), 2)
        self.assertLess(initial.index("parentReturnAttempted = true"), initial.index("let current = try"))
        self.assertLess(initial.index("parentReturnRejected = true", initial.index("parentReturnAttempted = true")),
                        initial.index("let current = try"))
        self.assertIn("guard !parentReturnRejected, ContinuousClock.now < initialDeadline", initial)
        before_back = initial[:initial.index("back.element.tap()")]
        self.assertIn("try Task.checkCancellation()\n                    guard ContinuousClock.now < initialDeadline", before_back)

    def test_editing_checks_keep_live_editor_actions_and_normal_navigation_hittability(self):
        case = native_folder_execution()
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
        case = native_folder_execution()
        self.assertIn("executionTimeAllowance = 180", case)
        self.assertIn("Self.nativeFolderConfiguration(environment, debugSimulator: debugSimulator)", case)
        self.assertIn("#if DEBUG && targetEnvironment(simulator)", case)
        self.assertIn('"--ui-testing-native-batch-token", configuration.sourceToken', case)
        self.assertEqual(case.count("source.element.tap()"), 1)
        self.assertIn("let picker = try await openNativeFilesRoot(app, initialTimeout: .seconds(30))", case)
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
        case = native_folder_execution()
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
        case = native_folder_execution()
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
        case = native_folder_execution()
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

    def test_introduction_without_keyboard_uses_one_acknowledgment_then_normal_editor(self):
        self.assertEqual(self.probe("without-keyboard"), {"outcome": "returned", "acknowledged": True,
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
        case = native_folder_execution()
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

CHILD_RETURN_SUPPORT = r'''
// Synthetic replay of the complete empty-child hierarchy. In particular, the
// picker has no File View and the separate application has no remote subtree.
@MainActor final class ChildTree {
    let pickerNodes: [XCUIElementSnapshot]
    let appNodes: [XCUIElementSnapshot]
    var picker: XCUIElementSnapshot { pickerNodes[0] }
    var app: XCUIElementSnapshot { appNodes[0] }
    var root: XCUIElementSnapshot { pickerNodes[5] }
    var nav: XCUIElementSnapshot { pickerNodes[6] }
    var back: XCUIElementSnapshot { pickerNodes[7] }
    var title: XCUIElementSnapshot { pickerNodes[8] }
    var empty: XCUIElementSnapshot { pickerNodes[20] }
    init() {
        pickerNodes = (0..<25).map { _ in XCUIElementSnapshot(.other, "", "", CGRect(x: 0, y: 72, width: 402, height: 802)) }
        appNodes = (0..<23).map { _ in XCUIElementSnapshot(.other, "", "", CGRect(x: 0, y: 0, width: 402, height: 874)) }
        let parents = [-1,0,1,2,3,3,5,6,6,6,6,6,11,5,13,14,15,16,17,18,18,5,21,0,23]
        let appParents = [-1,0,1,2,2,4,5,6,7,8,9,10,11,10,13,14,15,16,17,18,0,20,21]
        for i in 1..<parents.count { pickerNodes[parents[i]].children.append(pickerNodes[i]) }
        for i in 1..<appParents.count { appNodes[appParents[i]].children.append(appNodes[i]) }
        picker.identifier = "Browse View (Picker)"
        root.identifier = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: untitled folder"
        nav.elementType = .navigationBar; nav.identifier = "FullDocumentManagerViewControllerNavigationBar"
        nav.frame = CGRect(x: 0, y: 88, width: 402, height: 114)
        back.elementType = .button; back.identifier = "BackButton"; back.label = "On My iPhone"
        back.frame = CGRect(x: 16, y: 88, width: 44, height: 44)
        title.elementType = .button; title.label = "untitled folder, Actions Menu"
        title.frame = CGRect(x: 72, y: 99.66666666666666, width: 112, height: 20.66666666666667)
        pickerNodes[9].elementType = .button; pickerNodes[9].identifier = "OverflowBarButtonItem"; pickerNodes[9].label = "More"
        pickerNodes[9].frame = CGRect(x: 263.6666666666667, y: 92, width: 36, height: 36)
        pickerNodes[10].elementType = .button; pickerNodes[10].label = "Save"
        pickerNodes[10].frame = CGRect(x: 319.6666666666667, y: 92, width: 62.333333333333314, height: 36)
        pickerNodes[11].elementType = .searchField; pickerNodes[11].label = "Search"
        pickerNodes[11].frame = CGRect(x: 16, y: 143, width: 370, height: 44)
        pickerNodes[12].elementType = .image; pickerNodes[12].identifier = "magnifyingglass"; pickerNodes[12].label = "Search"
        pickerNodes[12].frame = CGRect(x: 28, y: 155, width: 20.66666666666667, height: 19.333333333333343)
        pickerNodes[19].elementType = .image; pickerNodes[19].identifier = "folder.fill"; pickerNodes[19].label = "move"
        pickerNodes[19].frame = CGRect(x: 168.33333333333334, y: 475.3333333333333, width: 65.33333333333331, height: 49.99999999999994)
        empty.elementType = .staticText; empty.label = "Folder is Empty"
        empty.frame = CGRect(x: 122, y: 540, width: 158, height: 26.666666666666742)
        app.elementType = .application; app.label = "Synthetic Fixture"
        appNodes[1].elementType = .window; appNodes[20].elementType = .window
        appNodes[3].frame = CGRect(x: -402, y: -874, width: 1206, height: 2622)
        appNodes[12].label = "Cancel"; appNodes[12].frame = pickerNodes[9].frame
    }
    func mutate(_ mode: String) {
        let grid = XCUIElementSnapshot(.collectionView, "File View", "", CGRect(x: 0, y: 202, width: 402, height: 672))
        switch mode {
        case "empty-grid": root.children.append(grid)
        case "duplicate-grid": root.children += [grid, grid]
        case "wrong-grid": grid.identifier = "Other"; root.children.append(grid)
        case "grid-type": grid.elementType = .other; root.children.append(grid)
        case "detached-grid": picker.children.append(grid)
        case "grid-frame": grid.frame.origin.x = 10; root.children.append(grid)
        case "wrong-provider": root.identifier = root.identifier.replacingOccurrences(of: "LocalStorage", with: "CloudStorage")
        case "wrong-root-title": root.identifier += " 2"
        case "root-type": root.elementType = .cell
        case "duplicate-root": picker.children.append(root)
        case "other-root": picker.children.append(Tree().root)
        case "environment-root": appNodes[1].children.append(Tree().root)
        case "duplicate-picker": root.children.append(XCUIElementSnapshot(.other, "Browse View (Picker)"))
        case "duplicate-nav": root.children.append(nav)
        case "nav-type": nav.elementType = .other
        case "detached-nav": root.children.removeAll { $0 === nav }; picker.children.append(nav)
        case "wrong-title": title.label = "Other, Actions Menu"
        case "title-type": title.elementType = .staticText
        case "duplicate-title": nav.children.append(title)
        case "other-title": nav.children.append(XCUIElementSnapshot(.button, "", "Other, Actions Menu", title.frame))
        case "detached-title": nav.children.removeAll { $0 === title }; root.children.append(title)
        case "wrong-back-id": back.identifier = "Other"
        case "wrong-back-label": back.label = "Browse"
        case "back-type": back.elementType = .other
        case "duplicate-back": nav.children.append(back)
        case "disabled-back": back.isEnabled = false
        case "detached-back": nav.children.removeAll { $0 === back }; root.children.append(back)
        case "missing-empty": empty.label = ""
        case "empty-type": empty.elementType = .button
        case "duplicate-empty": root.children.append(empty)
        case "detached-empty": pickerNodes[18].children.removeAll { $0 === empty }; picker.children.append(empty)
        case "cell": root.children.append(Tree().cell)
        case "environment-cell": appNodes[1].children.append(Tree().cell)
        case "editor": root.children.append(XCUIElementSnapshot(.textView, "DOC.inlineRenameField"))
        case "environment-editor": appNodes[1].children.append(XCUIElementSnapshot(.other, "DOC.inlineRenameField"))
        case "keyboard": root.children.append(XCUIElementSnapshot(.keyboard))
        case "environment-keyboard": appNodes[1].children.append(XCUIElementSnapshot(.keyboard))
        case "introduction": root.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "environment-introduction": appNodes[1].children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "back-empty-frame": back.frame = .zero
        case "back-nan": back.frame.origin.x = .nan
        case "back-outside-nav": back.frame.origin.y = 250
        case "empty-outside-root": empty.frame.origin.y = 900
        case "title-outside-window": title.frame.origin.x = 500
        case "invalid-window": appNodes[20].frame.size.width = 0
        case "disjoint-window": appNodes[20].frame.origin.x = 500
        case "missing-window": appNodes[1].elementType = .other; appNodes[20].elementType = .other
        case "depth":
            var tail = XCUIElementSnapshot(.other)
            for _ in 0..<97 { tail = XCUIElementSnapshot(.other, "", "", .zero, [tail]) }
            root.children.insert(tail, at: 0)
        case "count": root.children += (0..<4_096).map { _ in XCUIElementSnapshot(.other) }
        default: break
        }
    }
}
'''


CHILD_ROUTE_SUPPORT = r'''
@MainActor enum ContinuousClock {
    struct Instant: Comparable {
        var seconds: Double
        static func < (a: Self, b: Self) -> Bool { a.seconds < b.seconds }
        func advanced(by value: Duration) -> Self {
            let parts = value.components
            return Self(seconds: seconds + Double(parts.seconds) + Double(parts.attoseconds) / 1e18)
        }
    }
    static var now = Instant(seconds: 0)
}
@MainActor enum Task {
    static var cancelled = false
    static func checkCancellation() throws { if cancelled { throw CancellationError() } }
    static func sleep(for value: Duration) async throws {
        try checkCancellation(); ContinuousClock.now = ContinuousClock.now.advanced(by: value)
    }
}
@MainActor final class RouteElement {
    var frame = CGRect(x: 16, y: 88, width: 44, height: 44)
    var isEnabled = true
    var hittable = true
    var exists = false
    var onHittable: (() -> Void)?
    var onTap: (() -> Void)?
    var onPress: (() -> Void)?
    var isHittable: Bool { onHittable?(); return hittable }
    var cells: RouteQuery!
    var buttons: RouteQuery!
    func tap() { onTap?() }
    func press(forDuration value: Double) { precondition(value == 1); onPress?() }
}
@MainActor final class RouteQuery {
    var count = 1
    let element = RouteElement()
    func matching(_ value: NSPredicate) -> RouteQuery { self }
    subscript(_ value: String) -> RouteElement { element }
}
@MainActor final class XCUIApplication {
    let mode: String
    let navigation = RouteQuery(), back = RouteQuery(), staticTexts = RouteQuery()
    let files = RouteQuery(), created = RouteQuery(), buttons = RouteQuery()
    let inlineNames = RouteQuery(), introduction = RouteQuery()
    var backs = 0, presses = 0, renames = 0, samples = 0, captures = 0, failures = 0
    var rootValid = true
    init(_ mode: String) {
        self.mode = mode
        navigation.element.buttons = back; files.element.cells = created
        introduction.count = 0; staticTexts.count = 0
        created.element.frame = Tree().cell.frame
        created.element.onPress = { [unowned self] in presses += 1 }
        buttons.element.onTap = { [unowned self] in renames += 1 }
        back.element.onTap = { [unowned self] in
            backs += 1
            if mode == "cancel-after" { Task.cancelled = true }
        }
        if mode == "live-duplicate" { back.count = 2 }
        if mode == "live-nav-duplicate" { navigation.count = 2 }
        if mode == "live-moved" { back.element.frame.origin.x += 1 }
        if mode == "live-disabled" { back.element.isEnabled = false }
        if mode == "live-hidden" { back.element.hittable = false }
        if mode == "saved" { staticTexts.count = 1 }
        if mode == "failure" { staticTexts.element.exists = true }
        if mode == "live-expiry" {
            back.element.onHittable = { ContinuousClock.now.seconds = 30 }
        }
    }
}
'''

CHILD_ROUTE_METHODS = r'''
    var lastInitialEvidence: [String: Any] = [:]
    func capture(_ app: XCUIApplication, _ message: String, springboard: XCUIApplication? = nil,
                 batchDiagnostic: Bool = false) { app.captures += 1 }
    private func recordNativeFolderInitialFailure(_ value: NativeFolderInitialObservation, localTitle: String) {
        precondition(value.attempt > 0)
        lastInitialEvidence = try! JSONSerialization.jsonObject(with: value.metadata()) as! [String: Any]
    }
    func check(_ value: Bool, app: XCUIApplication, _ message: String) throws {
        if !value { throw BatchTestFailure(message: message) }
    }
    func isNativeFilesRoot(_ app: XCUIApplication) -> Bool { app.rootValid }
    func nativeFolderSnapshots(_ app: XCUIApplication,
        diagnostic: ((String, XCUIElementSnapshot?, XCUIElementSnapshot?) -> Void)? = nil
    ) throws -> (picker: XCUIElementSnapshot, application: XCUIElementSnapshot) {
        app.samples += 1
        let child = ChildTree(), parent = Tree(), editor = EditorTree("untitled folder")
        var pair = (picker: child.picker, application: child.app)
        if app.mode == "first-throws" || (app.mode == "fresh-throws" && app.samples == 2) {
            throw BatchTestFailure(message: "synthetic acquisition failure")
        }
        if app.samples == 1 && app.mode == "observed-expiry" { ContinuousClock.now.seconds = 30 }
        if app.samples == 2 {
            if app.mode == "fresh-moved" { child.back.frame.origin.x += 1 }
            if app.mode == "fresh-wrong" { child.mutate("wrong-provider") }
            if app.mode == "fresh-parent" { pair = (editor.picker, editor.app) }
            if app.mode == "fresh-expiry" { ContinuousClock.now.seconds = 30 }
            if app.mode == "cancel-before" { Task.cancelled = true }
        }
        if app.mode == "parent-cell" { pair = (parent.picker, parent.app) }
        if app.mode == "parent-editor" { pair = (editor.picker, editor.app) }
        if app.backs > 0 && app.mode != "repeated-child"
            && !(app.mode == "transient-child" && app.samples == 3) {
            pair = (parent.picker, parent.app)
            if app.mode == "child-editor" || app.mode == "child-introduction" || (app.mode == "late-editor" && app.samples >= 4) {
                if app.mode == "child-introduction" { editor.mutate("introduction-overlay") }
                pair = (editor.picker, editor.app)
            }
            if app.mode == "wrong-parent" { parent.mutate("wrong-provider") }
            if app.mode == "multiple-parent" { parent.mutate("duplicate-folder") }
            if app.mode == "missing-parent" { parent.mutate("missing-folder") }
            if app.mode == "occupied-parent" { parent.cell.identifier = "TripDocket-Batch-QA-12345678-1234-4234-8234-123456789abc, Folder" }
            if app.mode == "nonempty-parent" { parent.cell.label = "untitled folder, 1 item" }
            if app.mode == "parent-expiry" { ContinuousClock.now.seconds = 30 }
            if app.mode == "slow-valid" { ContinuousClock.now.seconds = 29 }
        }
        diagnostic?("bound", pair.picker, pair.application)
        return pair
    }
    // ACTUAL_WAIT
    func exerciseRoute(_ app: XCUIApplication) async -> [String: Any] {
        let navigation = app.navigation, files = app.files
        let inlineNames = app.inlineNames, keyboardIntroduction = app.introduction
        let localTitle = "On My iPhone"
        var outcome = "accepted"
        do {
            // ACTUAL_INITIAL_AND_PRERENAME
        } catch is CancellationError { outcome = "cancelled" }
        catch { outcome = "rejected" }
        return ["outcome": outcome, "backs": app.backs, "presses": app.presses, "renames": app.renames,
                "samples": app.samples, "captures": app.captures, "elapsed": ContinuousClock.now.seconds,
                "failureEvidence": lastInitialEvidence]
    }
    static func childProof(_ mode: String) -> [String: Any] {
        let child = ChildTree(); child.mutate(mode)
        if mode == "evidence" {
            return Dictionary(uniqueKeysWithValues: [("picker", child.picker), ("application", child.app)].map { name, snapshot in
                let data = nativeFolderSnapshotEvidence(snapshot, observation: "synthetic-child-" + name,
                    expectedName: "untitled folder", localTitle: "On My iPhone", returnedFrame: nil, liveFrame: nil, reason: nil)
                return (name, try! JSONSerialization.jsonObject(with: data))
            })
        }
        let picker = mode == "application-as-picker" ? child.app : child.picker
        let application = mode == "picker-as-application" ? child.picker : child.app
        let frame = nativeFolderParentReturnFrame(in: picker, applicationSnapshot: application,
                                                 localTitle: mode == "wrong-local-title" ? "On My iPad" : "On My iPhone")
        let state = nativeFolderInitialState(in: picker, applicationSnapshot: application, localTitle: "On My iPhone")
        return ["return": frame == child.back.frame, "ready": state.ready,
                "pickerCount": child.pickerNodes.count, "applicationCount": child.appNodes.count]
    }
'''

CHILD_ROUTE_MAIN = r'''
@main struct RouteMain {
    @MainActor static func main() async throws {
        let args = Array(CommandLine.arguments.dropFirst())
        let row = args[0] == "proof" ? Harness.childProof(args[1]) : await Harness().exerciseRoute(XCUIApplication(args[1]))
        print(String(decoding: try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]), as: UTF8.self))
    }
}
'''


class ParentReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="native-folder-parent-return-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.root = Path(cls.scratch.name)
        helpers = section("    @MainActor\n    private static func nativeFolderRenameFrame", "    private let productID")
        helpers += section("    private static func nativeFolderConfiguration", "    private func acknowledgeNativeFolderKeyboardIntroduction(")
        helpers += section("    private static func combinedBatchConfiguration", "    private static func recordBatchProducer")
        case = section("    private func createNativeEmptyFilesFolder", "    func testNativeSaveSeedsBothSyntheticOriginals")
        initial = case[case.index("        var renameFrame: CGRect?"):case.index("        // One shared acknowledgement")]
        methods = CHILD_ROUTE_METHODS.replace("    // ACTUAL_WAIT", section("    private func wait(_ message:", "    private func check("))
        methods = methods.replace("            // ACTUAL_INITIAL_AND_PRERENAME", initial)
        common = SWIFT[:SWIFT.index("@main struct Main")].replace("    // ACTUAL_HELPERS", helpers + methods)
        cls.source = common + CHILD_RETURN_SUPPORT + CHILD_ROUTE_SUPPORT + CHILD_ROUTE_MAIN
        cls.binary = cls.compile(cls.source, "route")

    @classmethod
    def compile(cls, source, name):
        path = cls.root / (name + ".swift"); binary = cls.root / name
        path.write_text(source)
        result = subprocess.run(["/usr/bin/swiftc", "-swift-version", "6", "-strict-concurrency=complete",
                                 "-parse-as-library", str(path), "-o", str(binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)
        return binary

    def probe(self, mode, command="route", binary=None):
        return json.loads(subprocess.run([str(binary or self.binary), command, mode], check=True,
                                         capture_output=True, text=True, timeout=5).stdout)

    def test_complete_child_pair_is_only_a_return_intention(self):
        for mode in ["exact", "empty-grid"]:
            with self.subTest(mode=mode):
                self.assertEqual(self.probe(mode, "proof"),
                                 {"return": True, "ready": False, "pickerCount": 25, "applicationCount": 23})
        for name, count in [("picker", 25), ("application", 23)]:
            evidence = self.probe("evidence", "proof")[name]
            self.assertTrue(evidence["treeComplete"])
            self.assertFalse(evidence["stringsTruncated"])
            self.assertEqual(len(evidence["nodes"]), count)
            self.assertFalse(any(n["identifier"] == "File View" for n in evidence["nodes"]))

    def test_child_identity_ancestry_content_and_geometry_fail_closed(self):
        modes = ["duplicate-grid", "wrong-grid", "grid-type", "detached-grid", "grid-frame",
                 "wrong-provider", "wrong-root-title", "root-type", "duplicate-root", "other-root", "environment-root",
                 "duplicate-picker", "duplicate-nav", "nav-type", "detached-nav", "wrong-title", "title-type",
                 "duplicate-title", "other-title", "detached-title", "wrong-back-id", "wrong-back-label", "back-type",
                 "duplicate-back", "disabled-back", "detached-back", "missing-empty", "empty-type", "duplicate-empty",
                 "detached-empty", "cell", "environment-cell", "editor", "environment-editor", "keyboard",
                 "environment-keyboard", "introduction", "environment-introduction", "back-empty-frame", "back-nan",
                 "back-outside-nav", "empty-outside-root", "title-outside-window", "invalid-window", "disjoint-window",
                 "missing-window", "depth", "count", "application-as-picker", "picker-as-application", "wrong-local-title"]
        for mode in modes:
            with self.subTest(mode=mode): self.assertFalse(self.probe(mode, "proof")["return"])

    def test_child_return_then_exact_parent_uses_existing_rename_or_editor(self):
        for mode, backs, presses in [("child-cell", 1, 1), ("child-editor", 1, 0), ("child-introduction", 1, 0),
                                     ("late-editor", 1, 0), ("parent-cell", 0, 1), ("parent-editor", 0, 0)]:
            with self.subTest(mode=mode):
                row = self.probe(mode)
                self.assertEqual((row["outcome"], row["backs"], row["presses"], row["renames"]),
                                 ("accepted", backs, presses, presses))

    def test_fresh_rejection_consumes_opportunity_and_prevents_later_readiness(self):
        for mode in ["fresh-moved", "fresh-wrong", "fresh-parent", "fresh-throws", "live-duplicate",
                     "live-nav-duplicate", "live-moved", "live-disabled", "live-hidden", "saved", "failure"]:
            with self.subTest(mode=mode):
                row = self.probe(mode)
                self.assertEqual((row["outcome"], row["backs"], row["presses"], row["renames"], row["samples"]),
                                 ("rejected", 0, 0, 0, 2))

    def test_fresh_failure_evidence_never_calls_the_old_pair_current(self):
        failed = self.probe("fresh-throws")["failureEvidence"]
        self.assertEqual((failed["attempt"], failed["lastBoundAttempt"]), (2, 1))
        self.assertFalse(failed["currentPairBound"])
        self.assertFalse(failed["currentPickerPresent"])
        self.assertFalse(failed["currentApplicationPresent"])
        self.assertIn("synthetic acquisition failure", failed["acquisitionError"])
        changed = self.probe("fresh-wrong")["failureEvidence"]
        self.assertEqual((changed["attempt"], changed["lastBoundAttempt"]), (2, 2))
        self.assertTrue(changed["currentPairBound"])
        self.assertEqual(changed["alternativeFirstRejections"], ["parent-return: fresh child proof changed"])

    def test_parent_must_be_proved_and_child_must_never_be_reentered(self):
        for mode in ["repeated-child", "wrong-parent", "multiple-parent", "missing-parent", "occupied-parent", "nonempty-parent"]:
            with self.subTest(mode=mode):
                row = self.probe(mode)
                self.assertEqual((row["outcome"], row["backs"], row["presses"], row["renames"]), ("rejected", 1, 0, 0))
                self.assertGreaterEqual(row["elapsed"], 30)
                self.assertLess(row["elapsed"], 30.2)
                if mode == "repeated-child": self.assertGreater(row["samples"], 3)

    def test_transient_old_child_after_back_waits_for_parent_without_second_tap(self):
        row = self.probe("transient-child")
        self.assertEqual((row["outcome"], row["backs"], row["presses"], row["renames"], row["samples"]),
                         ("accepted", 1, 1, 1, 5))
        self.assertLess(row["elapsed"], 1)

    def test_original_deadline_covers_observation_fresh_proof_live_queries_and_parent(self):
        for mode, backs in [("observed-expiry", 0), ("fresh-expiry", 0), ("live-expiry", 0), ("parent-expiry", 1)]:
            with self.subTest(mode=mode):
                row = self.probe(mode)
                self.assertEqual((row["outcome"], row["backs"], row["presses"], row["renames"]), ("rejected", backs, 0, 0))
                self.assertLess(row["elapsed"], 30.2)
        row = self.probe("slow-valid")
        self.assertEqual((row["outcome"], row["backs"], row["presses"]), ("accepted", 1, 1))
        self.assertEqual(row["elapsed"], 29)

    def test_cancellation_and_unbound_acquisition_never_add_an_action(self):
        for mode, backs, samples in [("cancel-before", 0, 2), ("cancel-after", 1, 2)]:
            with self.subTest(mode=mode):
                row = self.probe(mode)
                self.assertEqual((row["outcome"], row["backs"], row["presses"], row["samples"]),
                                 ("cancelled", backs, 0, samples))
        row = self.probe("first-throws")
        self.assertEqual((row["outcome"], row["backs"], row["presses"]), ("rejected", 0, 0))

    def test_causal_mutations_are_detected_by_transition_and_action_observations(self):
        mutations = [
            ("removed-return", "                    back.element.tap()", "                    // removed transition", "child-cell"),
            ("child-ready", "                    guard !parentReturnAttempted else {", "                    return true\n                    guard !parentReturnAttempted else {", "child-cell"),
            ("repeated-return", "                    guard !parentReturnAttempted else {", "                    guard true else {", "repeated-child"),
        ]
        for name, old, new, mode in mutations:
            with self.subTest(name=name):
                self.assertEqual(self.source.count(old), 1)
                binary = self.compile(self.source.replace(old, new, 1), name)
                row = self.probe(mode, binary=binary)
                if name == "removed-return":
                    self.assertEqual((row["outcome"], row["backs"], row["renames"]), ("rejected", 0, 0))
                elif name == "child-ready":
                    self.assertEqual((row["outcome"], row["backs"], row["renames"]), ("accepted", 0, 0))
                else:
                    self.assertGreater(row["backs"], 1)
                self.assertNotEqual((row["outcome"], row["backs"], row["renames"]),
                                    ("accepted", 1, 1) if mode == "child-cell" else ("rejected", 1, 0))


class InitialFolderWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="folder-initial-wait-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        wait = section("    private func wait(_ message:", "    private func check(")
        initial = section('            try await wait("Native folder has neither',
                          "        if let before = renameFrame")
        default = re.search(r"timeout: Duration = \.seconds\((\d+)\)", wait).group(1)
        explicit = re.search(r"timeout: \.seconds\((\d+)\)", initial.splitlines()[0])
        selected = explicit.group(1) if explicit else default
        # Only substitute the clock/sleeper boundary; execute the real wait body.
        wait = wait.replace("ContinuousClock.now", "clock.now")
        wait = wait.replace("Task.sleep(for:", "clock.sleep(for:")
        swift = r'''
import Foundation
struct BatchTestFailure: Error { let message: String }
struct Instant: Comparable {
    var seconds: Double
    static func < (lhs: Self, rhs: Self) -> Bool { lhs.seconds < rhs.seconds }
    func advanced(by duration: Duration) -> Self {
        let parts = duration.components
        return Self(seconds: seconds + Double(parts.seconds) + Double(parts.attoseconds) / 1e18)
    }
}
@MainActor final class Clock {
    var now = Instant(seconds: 0)
    var cancelled = false
    func sleep(for duration: Duration) async throws {
        if cancelled { throw CancellationError() }
        now = now.advanced(by: duration)
    }
}
@MainActor final class XCUIApplication {}
@MainActor final class Harness {
    let clock = Clock()
    var captures = 0
    func capture(_ app: XCUIApplication, _ message: String,
                 springboard: XCUIApplication?, batchDiagnostic: Bool) { captures += 1 }
    // ACTUAL_WAIT
    func run(timeout: Duration, validSecond: Bool, cancel: Bool = false) async -> [String: Any] {
        var observations = 0
        var outcome = "passed"
        do {
            try await wait("initial", app: XCUIApplication(), timeout: timeout) {
                observations += 1
                // Model the observed slow negative first acquisition, not a UI action.
                self.clock.now = self.clock.now.advanced(by: .seconds(observations == 1 ? 18 : 1))
                if cancel { self.clock.cancelled = true }
                return validSecond && observations == 2
            }
        } catch is CancellationError { outcome = "cancelled" }
        catch { outcome = "failed" }
        return ["outcome": outcome, "observations": observations,
                "captures": captures, "elapsed": clock.now.seconds]
    }
}
@main struct Main {
    @MainActor static func main() async throws {
        let rows = [
            "selected": await Harness().run(timeout: .seconds(SELECTED), validSecond: true),
            "old15": await Harness().run(timeout: .seconds(15), validSecond: true),
            "invalid": await Harness().run(timeout: .seconds(SELECTED), validSecond: false),
            "cancel": await Harness().run(timeout: .seconds(SELECTED), validSecond: true, cancel: true)
        ]
        print(String(decoding: try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys]), as: UTF8.self))
    }
}
'''.replace("    // ACTUAL_WAIT", wait).replace("SELECTED", selected)
        path = root / "InitialWait.swift"
        path.write_text(swift)
        binary = root / "InitialWait"
        compiled = subprocess.run(["/usr/bin/swiftc", "-swift-version", "6", "-strict-concurrency=complete",
                                   "-parse-as-library", str(path), "-o", str(binary)],
                                  capture_output=True, text=True, timeout=60)
        if compiled.returncode: raise AssertionError(compiled.stdout + compiled.stderr)
        cls.rows = json.loads(subprocess.run([str(binary)], check=True, capture_output=True,
                                             text=True, timeout=5).stdout)

    def test_slow_negative_then_valid_acquisition_needs_scoped_allowance(self):
        self.assertEqual(self.rows["selected"]["outcome"], "passed")
        self.assertEqual(self.rows["selected"]["observations"], 2)
        self.assertEqual(self.rows["selected"]["captures"], 0)
        self.assertEqual(self.rows["old15"]["outcome"], "failed")
        self.assertEqual(self.rows["old15"]["observations"], 1)
        self.assertEqual(self.rows["old15"]["captures"], 1)

    def test_persistent_invalid_acquisition_exhausts_polling_allowance(self):
        row = self.rows["invalid"]
        self.assertEqual(row["outcome"], "failed")
        self.assertEqual(row["captures"], 1)
        self.assertGreaterEqual(row["elapsed"], 30)
        self.assertLess(row["elapsed"], 31.2)

    def test_cancellation_stops_before_another_acquisition(self):
        row = self.rows["cancel"]
        self.assertEqual(row["outcome"], "cancelled")
        self.assertEqual(row["observations"], 1)
        self.assertEqual(row["captures"], 0)


if __name__ == "__main__":
    unittest.main()
