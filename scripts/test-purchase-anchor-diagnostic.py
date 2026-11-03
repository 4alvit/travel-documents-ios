#!/usr/bin/env python3
"""Compile the actual diagnostic selector with a minimal UIKit graph substitute."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
import Foundation
import CoreGraphics
@MainActor final class UIWindowScene {
    enum State { case foregroundActive, background }
    var activationState = State.foregroundActive
}
@MainActor class UIView {
    var bounds = CGRect(x: 0, y: 0, width: 300, height: 500)
    var isHidden = false
    var alpha: CGFloat = 1
    weak var window: UIWindow?
    weak var superview: UIView?
    func isDescendant(of view: UIView) -> Bool {
        var next: UIView? = self
        for _ in 0..<32 {
            guard let current = next else { return false }
            if current === view { return true }
            next = current.superview
        }
        return false
    }
}
@MainActor final class UIWindow: UIView { var windowScene: UIWindowScene? }
@MainActor final class UIViewController {
    var viewIfLoaded: UIView? = UIView()
    var parent: UIViewController?
    var isBeingDismissed = false
    var isMovingFromParent = false
    var isBeingPresented = false
    var isMovingToParent = false
    var transitionCoordinator: Bool?
    var presentedViewController: UIViewController?
}
struct BatchTestFailure: Error { let message: String }
@MainActor struct Harness {
    enum PresentationError: Error { case unavailable }
    // ACTUAL_HELPERS
    // ACTUAL_UI_CONFIGURATION
}
@MainActor func expect(_ value: Bool, _ message: String) {
    if !value { print("FAIL \(message)"); exit(1) }
}
@MainActor func rejects(_ body: () throws -> Void) {
    do { try body(); print("FAIL unexpectedly accepted"); exit(1) } catch {}
}
@main struct Main {
    @MainActor static func main() throws {
        let name = CommandLine.arguments[1]
        let scene = UIWindowScene(), window = UIWindow()
        window.windowScene = scene
        let bridge = UIViewController(), parent = UIViewController(), root = UIViewController()
        bridge.parent = parent; parent.parent = root
        bridge.viewIfLoaded!.bounds = .zero
        bridge.viewIfLoaded!.superview = parent.viewIfLoaded
        parent.viewIfLoaded!.superview = root.viewIfLoaded
        for node in [bridge, parent, root] { node.viewIfLoaded!.window = window }
        func choose(_ mode: Harness.DiagnosticAnchorMode = .ownedAncestor) throws -> (controller: UIViewController, depth: Int) {
            try Harness.diagnosticAnchor(mode, from: bridge, window: window, scene: scene)
        }
        let flags = ["--ui-testing-purchase-diagnostics", "--ui-testing-purchase-anchor-control"]
        switch name {
        case "ordinary-flags-preserve-default":
            expect(try Harness.diagnosticAnchorMode(arguments: []) == nil, "ordinary default")
            expect(try Harness.diagnosticAnchorMode(arguments: [flags[0]]) == nil, "existing trace-only default")
        case "exact-mode-and-opt-in":
            for mode in ["child", "ownedAncestor"] {
                let actual = try Harness.diagnosticAnchorMode(arguments: flags + ["--ui-testing-purchase-anchor="+mode])
                expect(actual?.rawValue == mode, "exact selector")
            }
        case "malformed-duplicate-unknown-reject":
            for arguments in [flags, [flags[1], "--ui-testing-purchase-anchor=child"],
                flags + ["--ui-testing-purchase-anchor=scene"], flags + ["--ui-testing-purchase-anchor="],
                flags + ["--ui-testing-purchase-anchor=child", "--ui-testing-purchase-anchor=ownedAncestor"],
                flags + [flags[1], "--ui-testing-purchase-anchor=child"],
                flags + [flags[0], "--ui-testing-purchase-anchor=child"],
                flags + ["--ui-testing-purchase-anchor-malformed"]] {
                rejects { _ = try Harness.diagnosticAnchorMode(arguments: arguments) }
            }
        case "ui-configuration":
            expect(try Harness.diagnosticPurchaseAnchorMode([:]) == nil, "missing skips")
            for mode in ["child", "ownedAncestor"] {
                expect(try Harness.diagnosticPurchaseAnchorMode(["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"1", "TRIPDOCKET_PURCHASE_ANCHOR_MODE":mode]) == mode, "valid UI mode")
            }
            for env in [["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"1"], ["TRIPDOCKET_PURCHASE_ANCHOR_MODE":"child"],
                ["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"0", "TRIPDOCKET_PURCHASE_ANCHOR_MODE":"child"],
                ["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"1", "TRIPDOCKET_PURCHASE_ANCHOR_MODE":"scene"]] {
                rejects { _ = try Harness.diagnosticPurchaseAnchorMode(env) }
            }
        case "child-keeps-empty-bridge":
            let result = try choose(.child)
            expect(result.controller === bridge && result.depth == 0, "child identity")
        case "nearest-nonempty-owned-ancestor":
            let result = try choose()
            expect(result.controller === parent && result.depth == 1, "nearest parent")
            parent.viewIfLoaded!.bounds = .zero
            let farther = try choose()
            expect(farther.controller === root && farther.depth == 2, "skip empty only")
        case "missing-owned-ancestor":
            parent.viewIfLoaded!.bounds = .zero; root.viewIfLoaded!.bounds = .zero
            rejects { _ = try choose() }
        case "cross-window-and-view-ownership":
            let foreignWindow = UIWindow()
            parent.viewIfLoaded!.window = foreignWindow
            rejects { _ = try choose() }
            parent.viewIfLoaded!.window = window
            bridge.viewIfLoaded!.superview = root.viewIfLoaded
            rejects { _ = try choose() }
        case "foreground-scene-binding":
            scene.activationState = .background; rejects { _ = try choose() }
            scene.activationState = .foregroundActive; window.windowScene = UIWindowScene()
            rejects { _ = try choose() }
        case "visibility-and-finite-geometry":
            parent.viewIfLoaded!.isHidden = true; rejects { _ = try choose() }
            parent.viewIfLoaded!.isHidden = false; parent.viewIfLoaded!.alpha = 0
            rejects { _ = try choose() }; parent.viewIfLoaded!.alpha = 1
            parent.viewIfLoaded!.bounds.size.width = .infinity; rejects { _ = try choose() }
            parent.viewIfLoaded!.bounds.size.width = 300; window.isHidden = true
            rejects { _ = try choose() }
        case "ancestor-transitions-and-presentation":
            parent.isBeingPresented = true; rejects { _ = try choose() }; parent.isBeingPresented = false
            parent.isMovingToParent = true; rejects { _ = try choose() }; parent.isMovingToParent = false
            parent.transitionCoordinator = true; rejects { _ = try choose() }; parent.transitionCoordinator = nil
            parent.presentedViewController = UIViewController(); rejects { _ = try choose() }
        case "original-ancestor-removal-guards":
            root.isBeingDismissed = true; rejects { _ = try choose(.child) }; rejects { _ = try choose() }
            root.isBeingDismissed = false; root.isMovingFromParent = true
            rejects { _ = try choose(.child) }; rejects { _ = try choose() }
        case "higher-ancestor-transitions-stop-before-purchase":
            var purchases = 0
            func request() throws { _ = try choose(); purchases += 1 }
            root.isBeingPresented = true; rejects { try request() }; root.isBeingPresented = false
            root.isMovingToParent = true; rejects { try request() }; root.isMovingToParent = false
            root.transitionCoordinator = true; rejects { try request() }
            expect(purchases == 0, "invalid ancestor must stop before purchase")
            expect(try choose(.child).controller === bridge, "child keeps original transition policy")
        case "cycle-and-depth-bounded":
            root.parent = bridge; rejects { _ = try choose() }; root.parent = nil
            var last = root
            for _ in 0..<12 { let next = UIViewController(); last.parent = next; last = next }
            rejects { _ = try choose() }
        case "selection-change-is-observable":
            let before = try choose()
            parent.viewIfLoaded!.bounds = .zero
            let after = try choose()
            expect(before.controller !== after.controller && before.depth != after.depth, "revalidation rejects changed choice")
        default: fatalError("Unknown case")
        }
        print("PASS \(name)")
    }
}
'''

def between(source, start, end):
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError("Unique source boundary missing")
    return source[source.index(start):source.index(end, source.index(start))]

class AnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="tripdocket-anchor-")
        cls.addClassCleanup(cls.directory.cleanup)
        views = (ROOT / "App/Views.swift").read_text()
        ui = (ROOT / "UITests/BatchImportUITests.swift").read_text()
        helper = between(views, "    enum DiagnosticAnchorMode:", "    private enum ObservationPoint:")
        config = between(ui, "    private static func diagnosticPurchaseAnchorMode(", "    func testDiagnosticPurchasePresentationAnchor()")
        config = config.replace("private static func", "static func", 1)
        source = Path(cls.directory.name) / "main.swift"
        source.write_text(FIXTURE.replace("    // ACTUAL_HELPERS", helper).replace("    // ACTUAL_UI_CONFIGURATION", config))
        cls.executable = source.with_suffix("")
        result = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library", str(source), "-o", str(cls.executable)], capture_output=True, text=True, timeout=60)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def test_actual_selectors_and_ownership(self):
        for case in ["ordinary-flags-preserve-default", "exact-mode-and-opt-in", "malformed-duplicate-unknown-reject", "ui-configuration", "child-keeps-empty-bridge", "nearest-nonempty-owned-ancestor", "missing-owned-ancestor", "cross-window-and-view-ownership", "foreground-scene-binding", "visibility-and-finite-geometry", "ancestor-transitions-and-presentation", "original-ancestor-removal-guards", "higher-ancestor-transitions-stop-before-purchase", "cycle-and-depth-bounded", "selection-change-is-observable"]:
            with self.subTest(case=case):
                result = subprocess.run([str(self.executable), case], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), "PASS " + case)

    def test_one_purchase_and_same_overload_under_debug_only(self):
        views = (ROOT / "App/Views.swift").read_text()
        scope = between(views, "    func purchase(_ product: Product)", "    private enum ObservationPoint:")
        branch = between(scope, "        #if DEBUG && targetEnvironment(simulator)\n        if let mode", "        var ancestor: UIViewController?")
        self.assertEqual(branch.count("product.purchase(confirmIn: selected.controller)"), 1)
        self.assertEqual(branch.count("Self.diagnosticAnchor(mode"), 2)
        self.assertIn("current.controller === selected.controller, current.depth == selected.depth", branch)
        self.assertNotIn("confirmIn: scene", branch)
        self.assertNotIn("catch", branch)
        self.assertTrue(branch.rstrip().endswith("#endif"))
        ui = (ROOT / "UITests/BatchImportUITests.swift").read_text()
        case = between(ui, "    func testDiagnosticPurchasePresentationAnchor()", "    private func localStoreSession()")
        self.assertEqual(case.count("purchaseOnce("), 1)
        self.assertEqual(case.count("app.launch()"), 1)
        self.assertEqual(case.count("localStoreSession()"), 1)
        self.assertIn("executionTimeAllowance = 180", case)
        self.assertIn("session.clearTransactions()", case)
        self.assertIn("session.resetToDefaultState()", case)
        for forbidden in ["choose.tap", "selectRealFiles", "nativeFolder", "session.buyProduct", "sleep(", "while "]:
            self.assertNotIn(forbidden, case)

if __name__ == "__main__": unittest.main()
