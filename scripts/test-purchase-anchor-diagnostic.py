#!/usr/bin/env python3
"""Compile actual diagnostic routing with public-API substitutes; never buy anything."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
import Foundation
@MainActor final class UIWindowScene {
    enum State { case foregroundActive, background }
    var activationState = State.foregroundActive
}
@MainActor final class UIWindow { var windowScene: UIWindowScene? }
@MainActor final class UIView { var window: UIWindow? }
@MainActor final class UIViewController {
    var parent: UIViewController?
    var viewIfLoaded: UIView? = UIView()
    var isBeingDismissed = false
    var isMovingFromParent = false
}
enum TestError: Error { case purchase }
@MainActor final class Counter {
    var child = 0
    var swiftUI = 0
    var failure: Error?
}
@MainActor struct Product {
    enum PurchaseResult { case controller, scene, swiftUI }
    let counter: Counter
    func purchase(confirmIn: UIViewController) async throws -> PurchaseResult {
        counter.child += 1
        if let failure = counter.failure { throw failure }
        return .controller
    }
    func purchase(confirmIn: UIWindowScene) async throws -> PurchaseResult { .scene }
}
struct BatchTestFailure: Error { let message: String }
@MainActor final class Harness {
    weak var controller: UIViewController?
    var isActive = true
    enum PresentationError: Error { case unavailable }
    enum ObservationPoint { case entry, returned }
    func tracePresentation(_ point: ObservationPoint) {}
    // ACTUAL_PURCHASE
    // ACTUAL_HELPERS
    // ACTUAL_UI_CONFIGURATION
}
@MainActor func expect(_ value: Bool, _ message: String) {
    if !value { print("FAIL \(message)"); exit(1) }
}
@MainActor func rejects(_ body: () throws -> Void) {
    do { try body(); print("FAIL unexpectedly accepted"); exit(1) } catch {}
}
@MainActor func rejectsAsync(_ body: () async throws -> Void) async {
    do { try await body(); print("FAIL unexpectedly accepted"); exit(1) } catch {}
}
@main struct Main {
    @MainActor static func main() async throws {
        let name = CommandLine.arguments[1]
        let scene = UIWindowScene(), window = UIWindow()
        window.windowScene = scene
        let bridge = UIViewController(), parent = UIViewController(), root = UIViewController()
        bridge.parent = parent; parent.parent = root; bridge.viewIfLoaded!.window = window
        let counter = Counter(), harness = Harness()
        harness.controller = bridge
        let product = Product(counter: counter)
        let flags = ["--ui-testing-purchase-diagnostics", "--ui-testing-purchase-anchor-control"]
        func arguments(_ mode: String) -> [String] { flags + ["--ui-testing-purchase-anchor=" + mode] }
        func request(_ arguments: [String]) async throws -> Product.PurchaseResult {
            try await harness.diagnosticPurchase(product, arguments: arguments, swiftUIPurchase: {
                counter.swiftUI += 1
                if let failure = counter.failure { throw failure }
                return .swiftUI
            })
        }
        switch name {
        case "ordinary-default-and-exact-modes":
            expect(try Harness.diagnosticAnchorMode(arguments: []) == nil, "ordinary default")
            expect(try Harness.diagnosticAnchorMode(arguments: [flags[0]]) == nil, "trace-only default")
            for mode in ["child", "swiftUI"] {
                expect(try Harness.diagnosticAnchorMode(arguments: arguments(mode))?.rawValue == mode, "exact selector")
            }
            expect(try await request([]) == .controller, "ordinary API")
            expect(try await request([flags[0]]) == .controller, "trace-only API")
            expect(counter.child == 2 && counter.swiftUI == 0, "no accidental diagnostic action")
        case "malformed-flags-stop-before-api":
            for invalid in [flags, [flags[1], "--ui-testing-purchase-anchor=child"],
                arguments("ownedAncestor"), arguments("scene"), arguments(""),
                arguments("child") + ["--ui-testing-purchase-anchor=swiftUI"],
                arguments("child") + [flags[1]], arguments("child") + [flags[0]],
                flags + ["--ui-testing-purchase-anchor-malformed"]] {
                await rejectsAsync { _ = try await request(invalid) }
            }
            expect(counter.child == 0 && counter.swiftUI == 0, "invalid arguments must not buy")
        case "ui-configuration":
            expect(try Harness.diagnosticPurchaseAnchorMode([:]) == nil, "missing skips")
            for mode in ["child", "swiftUI"] {
                expect(try Harness.diagnosticPurchaseAnchorMode(["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"1", "TRIPDOCKET_PURCHASE_ANCHOR_MODE":mode]) == mode, "valid UI mode")
            }
            for invalid in [["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"1"], ["TRIPDOCKET_PURCHASE_ANCHOR_MODE":"child"],
                ["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"0", "TRIPDOCKET_PURCHASE_ANCHOR_MODE":"child"],
                ["TRIPDOCKET_PURCHASE_ANCHOR_CONTROL":"1", "TRIPDOCKET_PURCHASE_ANCHOR_MODE":"ownedAncestor"]] {
                rejects { _ = try Harness.diagnosticPurchaseAnchorMode(invalid) }
            }
        case "one-call-per-selected-api":
            expect(try await request(arguments("child")) == .controller, "child uses current public API")
            expect(counter.child == 1 && counter.swiftUI == 0, "exactly one child call")
            expect(try await request(arguments("swiftUI")) == .swiftUI, "SwiftUI result unchanged")
            expect(counter.child == 1 && counter.swiftUI == 1, "exactly one SwiftUI call")
        case "both-arms-retain-site-and-removal-guards":
            for mode in ["child", "swiftUI"] {
                harness.isActive = false
                await rejectsAsync { _ = try await request(arguments(mode)) }; harness.isActive = true
                harness.controller = nil
                await rejectsAsync { _ = try await request(arguments(mode)) }; harness.controller = bridge
                bridge.parent = nil
                await rejectsAsync { _ = try await request(arguments(mode)) }; bridge.parent = parent
                let view = bridge.viewIfLoaded; bridge.viewIfLoaded = nil
                await rejectsAsync { _ = try await request(arguments(mode)) }; bridge.viewIfLoaded = view
                bridge.viewIfLoaded!.window = nil
                await rejectsAsync { _ = try await request(arguments(mode)) }; bridge.viewIfLoaded!.window = window
                window.windowScene = nil
                await rejectsAsync { _ = try await request(arguments(mode)) }; window.windowScene = scene
                scene.activationState = .background
                await rejectsAsync { _ = try await request(arguments(mode)) }; scene.activationState = .foregroundActive
                for ancestor in [bridge, parent, root] {
                    ancestor.isBeingDismissed = true
                    await rejectsAsync { _ = try await request(arguments(mode)) }; ancestor.isBeingDismissed = false
                    ancestor.isMovingFromParent = true
                    await rejectsAsync { _ = try await request(arguments(mode)) }; ancestor.isMovingFromParent = false
                }
            }
            expect(counter.child == 0 && counter.swiftUI == 0, "invalid site must not buy")
        case "error-and-cancellation-no-fallback":
            for mode in ["child", "swiftUI"] {
                counter.failure = TestError.purchase
                do { _ = try await request(arguments(mode)); expect(false, "missing purchase error") }
                catch TestError.purchase {} catch { expect(false, "changed purchase error") }
                counter.failure = CancellationError()
                do { _ = try await request(arguments(mode)); expect(false, "missing cancellation") }
                catch is CancellationError {} catch { expect(false, "changed cancellation") }
            }
            expect(counter.child == 2 && counter.swiftUI == 2, "no retry or fallback")
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
        purchase = between(views, "    func purchase(_ product: Product)", "    enum DiagnosticAnchorMode:")
        purchase = purchase.removesuffix("    #if DEBUG && targetEnvironment(simulator)\n")
        helper = between(views, "    enum DiagnosticAnchorMode:", "    private enum ObservationPoint:")
        config = between(ui, "    private static func diagnosticPurchaseAnchorMode(", "    func testDiagnosticPurchasePresentationAnchor()")
        config = config.replace("private static func", "static func", 1)
        source = Path(cls.directory.name) / "main.swift"
        source.write_text(FIXTURE.replace("    // ACTUAL_PURCHASE", purchase).replace("    // ACTUAL_HELPERS", helper).replace("    // ACTUAL_UI_CONFIGURATION", config))
        cls.executable = source.with_suffix("")
        result = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library", str(source), "-o", str(cls.executable)], capture_output=True, text=True, timeout=60)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def test_actual_routing_and_guards(self):
        for case in ["ordinary-default-and-exact-modes", "malformed-flags-stop-before-api", "ui-configuration", "one-call-per-selected-api", "both-arms-retain-site-and-removal-guards", "error-and-cancellation-no-fallback"]:
            with self.subTest(case=case):
                result = subprocess.run([str(self.executable), case], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip().splitlines()[-1], "PASS " + case)

    def test_action_is_owned_by_pro_view_and_debug_only(self):
        views = (ROOT / "App/Views.swift").read_text()
        scope = between(views, "private struct ProView: View {", "struct PreviewSheet: View {")
        self.assertIn("#if DEBUG && targetEnvironment(simulator)\n    @Environment(\\.purchase) private var purchaseAction\n    #endif", scope)
        route = between(scope, "                                    #if DEBUG && targetEnvironment(simulator)", "                                })")
        self.assertEqual(route.count("purchasePresentation.diagnosticPurchase("), 1)
        self.assertEqual(route.count("swiftUIPurchase: { try await purchaseAction(product) }"), 1)
        self.assertIn("#else\n                                    try await purchasePresentation.purchase(product)\n                                    #endif", route)
        helper = between(views, "    enum DiagnosticAnchorMode:", "    private enum ObservationPoint:")
        self.assertIn("#if DEBUG && targetEnvironment(simulator)\n    enum DiagnosticAnchorMode:", views)
        self.assertEqual(helper.count("return try await swiftUIPurchase()"), 1)
        self.assertNotIn("catch", helper)
        self.assertNotIn("buyProduct", helper)
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
