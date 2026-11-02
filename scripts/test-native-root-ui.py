#!/usr/bin/env python3
"""Exercise actual native-root opt-in and Files identity helpers, without Simulator."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "UITests/BatchImportUITests.swift").read_text()
TOKEN = "12345678-1234-4234-8234-123456789abc"

def helper(start, end):
    return UI[UI.index(start):UI.index(end, UI.index(start))]

FIXTURE = r'''
import Foundation
struct BatchTestFailure: Error { let message: String }
@MainActor final class XCUIElement {
    enum ElementType: Int { case any = 0, application, other, navigationBar, collectionView, staticText, button }
    var elementType: ElementType
    var identifier: String
    var label: String
    var exists = true
    var isHittable = true
    var children: [XCUIElement]
    init(_ type: ElementType, _ identifier: String = "", _ label: String = "", _ children: [XCUIElement] = []) {
        elementType = type; self.identifier = identifier; self.label = label; self.children = children
    }
    func descendants(matching type: ElementType) -> Query {
        let all = children.flatMap { [$0] + $0.descendants(matching: .any).values }
        return Query(all.filter { type == .any || $0.elementType == type })
    }
    var navigationBars: Query { descendants(matching: .navigationBar) }
    var otherElements: Query { descendants(matching: .other) }
    var collectionViews: Query { descendants(matching: .collectionView) }
}
@MainActor struct Query {
    let values: [XCUIElement]
    init(_ values: [XCUIElement]) { self.values = values }
    var count: Int { values.count }
    var element: XCUIElement { precondition(count == 1); return values[0] }
    func element(boundBy index: Int) -> XCUIElement { values[index] }
    func matching(identifier: String) -> Query { Query(values.filter { $0.identifier == identifier }) }
    func matching(_ predicate: NSPredicate) -> Query {
        Query(values.filter { predicate.evaluate(with: ["elementType": $0.elementType.rawValue, "label": $0.label]) })
    }
}
typealias XCUIApplication = XCUIElement
@MainActor final class Harness {
    // ACTUAL_HELPERS
    func valid(_ app: XCUIApplication) -> Bool { isNativeFilesRoot(app) }
    static func config(_ env: [String: String], mode: String, debug: Bool) throws -> Bool {
        try nativeRootConfiguration(env, mode: mode, debugSimulator: debug)
    }
}
@main struct Probe {
    @MainActor static func main() throws {
        let args = Array(CommandLine.arguments.dropFirst())
        if args[0] == "config" {
            let env = try JSONDecoder().decode([String: String].self, from: Data(args[1].utf8))
            do { print(try Harness.config(env, mode: args[2], debug: args[3] == "true") ? "root" : "folder") }
            catch { print("rejected") }
            return
        }
        let title = XCUIElement(.staticText, "", "On My iPhone")
        let nav = XCUIElement(.navigationBar, "FullDocumentManagerViewControllerNavigationBar", "", [title])
        let grid = XCUIElement(.collectionView, "File View")
        let root = XCUIElement(.other, "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone", "", [nav, grid])
        let picker = XCUIElement(.other, "Browse View (Picker)", "", [root])
        let app = XCUIElement(.application, "", "", [picker])
        switch args[1] {
        case "exact-root": break
        case "actions-title": title.elementType = .button; title.label = "On My iPhone, Actions Menu"
        case "wrong-provider": root.identifier = "DOC.browsingRoot Source: com.apple.CloudDocs, Title: On My iPhone"
        case "same-title-child-folder": root.identifier = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: child"
        case "missing-root": picker.children = [nav,grid]
        case "duplicate-root": picker.children.append(root)
        case "missing-picker": picker.identifier = "Recent Documents"
        case "missing-picker-existence": picker.exists = false
        case "duplicate-picker": app.children.append(picker)
        case "duplicate-global-navigation": app.children.append(XCUIElement(.navigationBar, nav.identifier))
        case "navigation-outside-root": root.children = [grid]; picker.children.append(nav)
        case "grid-outside-root": root.children = [nav]; picker.children.append(grid)
        case "duplicate-grid": root.children.append(XCUIElement(.collectionView, "File View"))
        case "second-grid-outside-root": picker.children.append(XCUIElement(.collectionView, "File View"))
        case "missing-grid": root.children = [nav]
        case "missing-root-existence": root.exists = false
        case "missing-grid-existence": grid.exists = false
        case "missing-nav-existence": nav.exists = false
        case "wrong-title": title.label = "iCloud Drive"
        case "duplicate-title": nav.children.append(XCUIElement(.staticText, "", "On My iPhone"))
        case "covered-title": title.isHittable = false
        case "plain-back-button": title.elementType = .button
        default: fatalError("Unknown fixture")
        }
        print(Harness().valid(app) ? "accepted" : "rejected")
    }
}
'''

class NativeRootUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.scratch.cleanup)
        temp = Path(cls.scratch.name); cls.binary = temp / "probe"
        actual = helper("    private static func nativeRootConfiguration", "    private func isNativeFilesRoot")
        actual += helper("    private func isNativeFilesRoot", "    private func openNativeFilesRoot")
        actual += helper("    private func isRecoveryFolder", "    private func recoveryFilesNavigation")
        swift = temp / "Probe.swift"; swift.write_text(FIXTURE.replace("    // ACTUAL_HELPERS", actual))
        subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library", str(swift), "-o", str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=60)

    def probe(self, *args):
        return subprocess.run([str(self.binary), *args], check=True, capture_output=True, text=True, timeout=5).stdout.strip()

    def environment(self, mode):
        env = {"TRIPDOCKET_NATIVE_ROOT_UI":"1", "TRIPDOCKET_NATIVE_ROOT_TOKEN":TOKEN,
               "TRIPDOCKET_BATCH_FOLDER":"TripDocket-Batch-QA-"+TOKEN}
        if mode == "seed": env.update(TRIPDOCKET_NATIVE_SEED_UI="1", TRIPDOCKET_NATIVE_SEED_TOKEN=TOKEN)
        else: env["TRIPDOCKET_BATCH_UI"] = "1"
        return env

    def config(self, env, mode="batch", debug=True):
        return self.probe("config", json.dumps(env), mode, str(debug).lower())

    def test_actual_gate_preserves_default_named_folder(self):
        self.assertEqual(self.config({}), "folder")
        self.assertEqual(self.config({"TRIPDOCKET_BATCH_UI":"1", "TRIPDOCKET_BATCH_FOLDER":"manual-fixture"}), "folder")

    def test_actual_gate_accepts_only_complete_root_optins(self):
        for mode in ("batch", "seed"):
            env = self.environment(mode)
            with self.subTest(mode=mode): self.assertEqual(self.config(env, mode), "root")
            with self.subTest(mode=mode, debug=False): self.assertEqual(self.config(env, mode, False), "rejected")
            for key in env:
                altered = dict(env); altered.pop(key)
                with self.subTest(mode=mode, missing=key): self.assertEqual(self.config(altered, mode), "rejected")
            for token in ("", TOKEN.upper(), "../outside", "not-a-uuid"):
                altered = dict(env); altered["TRIPDOCKET_NATIVE_ROOT_TOKEN"] = token
                with self.subTest(mode=mode, token=token): self.assertEqual(self.config(altered, mode), "rejected")
            for key in ("TRIPDOCKET_NATIVE_ROOT_UI", "TRIPDOCKET_BATCH_FOLDER"):
                altered = dict(env); altered[key] = "different"
                with self.subTest(mode=mode, wrong=key): self.assertEqual(self.config(altered, mode), "rejected")
        self.assertEqual(self.config(self.environment("batch"), "recovery"), "rejected")
        env = self.environment("seed"); env["TRIPDOCKET_NATIVE_SEED_TOKEN"] = "00000000-0000-4000-8000-000000000001"
        self.assertEqual(self.config(env, "seed"), "rejected")

    def test_actual_root_identity_requires_owned_local_provider_and_live_unique_heading(self):
        accepted = ("exact-root", "actions-title")
        rejected = ("wrong-provider", "same-title-child-folder", "missing-root", "duplicate-root", "missing-picker",
                    "missing-picker-existence", "duplicate-picker", "duplicate-global-navigation", "navigation-outside-root", "grid-outside-root",
                    "second-grid-outside-root", "duplicate-grid", "missing-grid", "missing-root-existence", "missing-grid-existence",
                    "missing-nav-existence", "wrong-title", "duplicate-title", "covered-title", "plain-back-button")
        for shape in accepted + rejected:
            with self.subTest(shape=shape):
                self.assertEqual(self.probe("shape",shape), "accepted" if shape in accepted else "rejected")

    def test_root_route_has_no_named_folder_action_and_mode_is_build_gated(self):
        route = helper("    private func openNativeFilesRoot", "    private func openLocalFilesFolder")
        self.assertIn('UIDevice.current.userInterfaceIdiom == .phone', route)
        self.assertIn('reachRecoveryLocalRoot("On My iPhone"', route)
        self.assertIn('self.isNativeFilesRoot(app)', route)
        self.assertNotIn('directory', route)
        gate = helper("    private func nativeRootMode", "    private static func nativeRootConfiguration")
        self.assertIn('#if DEBUG && targetEnvironment(simulator)', gate)
        self.assertIn('let debugSimulator = false', gate)
        seed = helper("    func testNativeSaveSeedsBothSyntheticOriginals", "    @MainActor\n    private func nativeFolderBlankPoint")
        select = helper("    private func selectRealFiles", "    private func requireFilesDismissal")
        self.assertIn('navigation.buttons.matching(NSPredicate(format: "label == %@", "Save")).count == 1', seed)
        self.assertIn('isNativeFilesRoot(app) && matchingFiles.count == 1', select)
        self.assertIn('isNativeFilesRoot(app) && openActions.count == 1', select)

if __name__ == "__main__": unittest.main(verbosity=2)
