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

READINESS_FIXTURE = r'''
import Foundation
struct BatchTestFailure: Error { let message: String }
struct Instant: Comparable {
    let milliseconds: Double
    static func < (a: Self, b: Self) -> Bool { a.milliseconds < b.milliseconds }
    func advanced(by duration: Duration) -> Self {
        let value = duration.components
        return Self(milliseconds: milliseconds + Double(value.seconds) * 1000
                    + Double(value.attoseconds) / 1e15)
    }
}
@MainActor enum ContinuousClock {
    static var now = Instant(milliseconds: 0)
}
@MainActor enum Task {
    static func sleep(for duration: Duration) async throws {
        ContinuousClock.now = ContinuousClock.now.advanced(by: duration)
    }
}
struct Sample: Decodable { let value: Int; let milliseconds: Double }
@MainActor final class Script {
    let samples: [String: [Sample]]
    var offsets: [String: Int] = [:]
    var calls: [String] = []
    var captures = 0
    init(_ samples: [String: [Sample]]) { self.samples = samples }
    func read(_ key: String) -> Int {
        calls.append(key)
        guard let values = samples[key], !values.isEmpty else { fatalError("Unexpected query: " + key) }
        let offset = offsets[key, default: 0]
        offsets[key] = offset + 1
        let value = values[min(offset, values.count - 1)]
        ContinuousClock.now = Instant(milliseconds: ContinuousClock.now.milliseconds + value.milliseconds)
        return value.value
    }
}
@MainActor final class Node {
    let script: Script
    let name: String
    init(_ script: Script, _ name: String) { self.script = script; self.name = name }
    var count: Int { script.read(name + ".count") }
    var element: Node { self }
    var exists: Bool { script.read(name + ".exists") == 1 }
    var isEnabled: Bool { script.read(name + ".enabled") == 1 }
    var isHittable: Bool { script.read(name + ".hittable") == 1 }
}
typealias XCUIApplication = Node
@MainActor final class Harness {
    let script: Script
    init(_ script: Script) { self.script = script }
    func isRecoveryFolder(_ title: String, navigation: Node) -> Bool {
        precondition(title == "Recents")
        return script.read("folder.recents") == 1
    }
    func capture(_ app: Node, _ message: String, springboard: Node?, batchDiagnostic: Bool) {
        precondition(batchDiagnostic); script.captures += 1
    }
    // ACTUAL_WAIT
    func run(oldBranching: Bool, initialTimeout: Duration) async throws {
        let app = Node(script, "app")
        let navigations = Node(script, "navigation")
        let pickers = Node(script, "picker")
        let recents = Node(script, "recents")
        let tabs = Node(script, "tabs")
        let browse = Node(script, "browse")
        // ACTUAL_PREDICATES
        if oldBranching {
            try await wait("Native root Files browser or supported Recents screen is missing", app: app) {
                browserReady() || recentsReady()
            }
        } else {
            // ACTUAL_INITIAL_WAIT
        }
    }
}
@main struct Probe {
    @MainActor static func main() async throws {
        let args = Array(CommandLine.arguments.dropFirst())
        let samples = try JSONDecoder().decode([String: [Sample]].self, from: Data(args[0].utf8))
        let script = Script(samples)
        var accepted = false
        let initialTimeout = Duration.seconds(Int(args[2])!)
        do { try await Harness(script).run(oldBranching: args[1] == "old",
                                          initialTimeout: initialTimeout); accepted = true }
        catch {}
        let result: [String: Any] = ["accepted": accepted, "milliseconds": ContinuousClock.now.milliseconds,
                                    "calls": script.calls, "captures": script.captures]
        print(String(decoding: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), as: UTF8.self))
    }
}
'''


class InitialNativeRootReadiness(unittest.TestCase):
    """Run the actual initial wait and predicate with deterministic RPC latency."""
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.scratch.cleanup)
        temp = Path(cls.scratch.name); cls.binary = temp / "readiness"
        route = helper("    private func openNativeFilesRoot", "    private func openLocalFilesFolder")
        start = route.index('        try await wait("Native root Files browser or supported Recents screen is missing"')
        initial_wait = route[start:route.index("        if !browserReady()", start)]
        predicates = route[route.index("        let browseReady ="):start]
        actual_wait = helper("    private func wait(", "    private func check(")
        source = (READINESS_FIXTURE.replace("    // ACTUAL_WAIT", actual_wait)
                  .replace("        // ACTUAL_PREDICATES", predicates)
                  .replace("            // ACTUAL_INITIAL_WAIT", initial_wait))
        swift = temp / "Readiness.swift"; swift.write_text(source)
        subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library", str(swift), "-o", str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=60)

    def run_predicate(self, samples, old=False, timeout=15):
        encoded = {key: [{"value": value, "milliseconds": cost} for value, cost in values]
                   for key, values in samples.items()}
        result = subprocess.run([str(self.binary), json.dumps(encoded), "old" if old else "current", str(timeout)],
                                check=True, capture_output=True, text=True, timeout=5)
        return json.loads(result.stdout)

    def test_late_browser_transition_is_not_misclassified_as_recents(self):
        # C26's last nav0 then slow nav1/picker1 observations, with measured
        # query costs. This is a deterministic counterexample, not a UI replay.
        samples = {"navigation.count": [(0, 3996.98), (1, 12967.8)],
                   "picker.count": [(1, 2846.04)], "picker.exists": [(1, 10)]}
        old = self.run_predicate(samples, old=True)
        current = self.run_predicate(samples)
        self.assertFalse(old["accepted"])
        self.assertEqual(old["captures"], 1)
        self.assertTrue(current["accepted"])
        self.assertEqual(current["captures"], 0)
        self.assertEqual(old["calls"], ["navigation.count", "navigation.count", "picker.count"])
        self.assertEqual(current["calls"], old["calls"] + ["picker.exists"])
        # An in-flight synchronous query may finish after the existing 15s
        # deadline. The unchanged wait already accepts a true result then.
        self.assertGreater(current["milliseconds"], 15000)

    def test_cold_initial_wait_observes_ready_picker_after_default_budget(self):
        # A true predicate arrives at18s; service lifecycle alone is not modeled
        # as readiness. Execute the extracted wait and full initial predicate.
        samples = {"navigation.count": [(0, 900)] * 18 + [(1, 1)],
                   "picker.count": [(1, 1)], "picker.exists": [(1, 1)]}
        normal = self.run_predicate(samples)
        cold = self.run_predicate(samples, timeout=30)
        self.assertFalse(normal["accepted"])
        self.assertEqual(normal["captures"], 1)
        self.assertNotIn("picker.count", normal["calls"])
        self.assertTrue(cold["accepted"])
        self.assertEqual(cold["captures"], 0)
        self.assertGreater(cold["milliseconds"], 18000)
        self.assertLess(cold["milliseconds"], 19000)
        self.assertEqual(cold["calls"][-2:], ["picker.count", "picker.exists"])

    def test_cold_initial_wait_does_not_poll_again_at_its_deadline(self):
        # A valid next observation must remain unread once the same fixed
        # deadline expires; no rolling retry or indefinite cold-start wait.
        samples = {"navigation.count": [(0, 0)] * 300 + [(1, 0)],
                   "picker.count": [(1, 0)], "picker.exists": [(1, 0)]}
        result = self.run_predicate(samples, timeout=30)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["captures"], 1)
        self.assertEqual(result["milliseconds"], 30000)
        self.assertEqual(result["calls"], ["navigation.count"] * 300)

    def test_browser_branch_reads_each_count_once_and_requires_existence(self):
        samples = {"navigation.count": [(1, 1)], "picker.count": [(1, 1)], "picker.exists": [(1, 1)]}
        result = self.run_predicate(samples)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["calls"], list(samples))
        samples["picker.exists"] = [(0, 16000)]
        result = self.run_predicate(samples)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["captures"], 1)
        self.assertEqual(result["calls"], list(samples))

    def test_missing_or_duplicate_navigation_cannot_read_or_accept_picker(self):
        for count in (0, 2):
            with self.subTest(count=count):
                result = self.run_predicate({"navigation.count": [(count, 16000)]})
                self.assertFalse(result["accepted"])
                self.assertEqual(result["captures"], 1)
                self.assertEqual(result["calls"], ["navigation.count"])

    def test_duplicate_picker_cannot_fall_through_to_recents(self):
        result = self.run_predicate({"navigation.count": [(1, 1)], "picker.count": [(2, 16000)]})
        self.assertFalse(result["accepted"])
        self.assertEqual(result["calls"], ["navigation.count", "picker.count"])

    def test_recents_retains_all_identity_existence_and_action_requirements(self):
        samples = {"navigation.count": [(1, 1)], "picker.count": [(0, 1)],
                   "recents.count": [(1, 1)], "recents.exists": [(1, 1)],
                   "folder.recents": [(1, 1)], "tabs.count": [(1, 1)],
                   "browse.count": [(1, 1)], "browse.enabled": [(1, 1)], "browse.hittable": [(1, 1)]}
        result = self.run_predicate(samples)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["calls"], list(samples))
        for key in list(samples)[2:]:
            rejected_values = (0, 2) if key.endswith(".count") else (0,)
            for value in rejected_values:
                with self.subTest(key=key, value=value):
                    altered = dict(samples); altered[key] = [(value, 16000)]
                    result = self.run_predicate(altered)
                    self.assertFalse(result["accepted"])
                    self.assertEqual(result["captures"], 1)
                    self.assertEqual(result["calls"], list(samples)[:list(samples).index(key) + 1])


if __name__ == "__main__": unittest.main(verbosity=2)
