#!/usr/bin/env python3
"""Compile actual session-order orchestration and ordinary routing with inert stubs."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=r'''
import Foundation
struct BatchTestFailure: Error { let message: String }
struct XCTSkip: Error { init(_ message: String) {} }
@MainActor enum Fixture {
    static let ready = "purchase-state isPro=false isBusy=false load=returned purchase=notStarted restore=notStarted"
    static var environment: [String:String] = [:]
    static var events: [String] = [], attachments: [String] = []
    static var value: String? = ready + "\npurchase-diagnostic none"
    static var navCount = 1, buttonCount = 1
    static var hittable = true, failStop = false, onPro = false
    static func reset(_ mode: String) {
        environment = ["TRIPDOCKET_PURCHASE_SESSION_ORDER_CONTROL":"1", "TRIPDOCKET_PURCHASE_SESSION_ORDER_MODE":mode]
        events=[];attachments=[];value=ready+"\npurchase-diagnostic none";navCount=1;buttonCount=1
        hittable=true;failStop=false;onPro=false
    }
}
@MainActor final class XCUIElement {
    let identifier: String
    init(_ identifier: String) { self.identifier=identifier }
    var buttons: Query { Query("buttons") }
    var exists: Bool { identifier == "TripDocket Pro" ? Fixture.onPro : identifier != "batch.chooseFiles" }
    var isHittable: Bool { Fixture.hittable }
    var value: Any? { Fixture.value }
}
@MainActor struct Query {
    let identifier: String
    init(_ identifier: String) { self.identifier=identifier }
    func matching(identifier: String) -> Query { Query(identifier) }
    var count: Int { identifier == "TripDocket" ? Fixture.navCount : Fixture.buttonCount }
    var element: XCUIElement { XCUIElement(identifier) }
    subscript(_ name: String) -> XCUIElement { XCUIElement(name) }
}
@MainActor final class XCUIApplication {
    enum State { case notRunning, runningForeground }
    var state = State.notRunning
    var launchArguments: [String] = []
    var navigationBars: Query { Query("navigation") }
    var buttons: Query { Query("buttons") }
    init(bundleIdentifier: String = "AUT") {}
    func launch() {
        precondition(launchArguments.contains("--ui-testing-purchase-session-state"))
        precondition(!launchArguments.contains(where: {$0.hasPrefix("--ui-testing-purchase-anchor")}))
        Fixture.events.append("launch");state = .runningForeground
    }
    func terminate() {
        Fixture.events.append("terminate")
        if !Fixture.failStop { state = .notRunning }
    }
}
@MainActor final class XCTAttachment {
    enum Lifetime { case keepAlways }
    let string: String
    var name = ""
    var lifetime = Lifetime.keepAlways
    init(string: String) { self.string=string }
}
@MainActor final class SKTestSession {
    init() { Fixture.events.append("session") }
    func clearTransactions() { Fixture.events.append("clear") }
    func resetToDefaultState() { Fixture.events.append("reset") }
}
@MainActor final class Harness {
    var executionTimeAllowance = 0, continueAfterFailure = true
    func add(_ attachment: XCTAttachment) { Fixture.attachments.append(attachment.name+"\n"+attachment.string) }
    func capture(_ app: XCUIApplication, _ name: String) { Fixture.events.append("capture") }
    func wait(_ message: String, app: XCUIApplication, condition: @MainActor () -> Bool) async throws {
        if !condition() { throw BatchTestFailure(message: message) }
    }
    func localStoreSession() async throws -> SKTestSession { SKTestSession() }
    func openTrip(_ app: XCUIApplication) async throws {}
    func openBatchEntry(_ app: XCUIApplication) async throws { Fixture.onPro=true }
    func purchaseOnce(_ app: XCUIApplication, springboard: XCUIApplication, session: SKTestSession) async throws { Fixture.events.append("purchase") }
    // ACTUAL_UI
}
// ACTUAL_OBSERVATION
@MainActor final class UIWindowScene {
    enum State { case foregroundActive, background }
    var activationState = State.foregroundActive
}
@MainActor final class UIWindow { var windowScene: UIWindowScene? }
@MainActor final class UIView { var window: UIWindow? }
@MainActor final class UIViewController {
    var parent: UIViewController?
    var viewIfLoaded: UIView? = UIView()
    var isBeingDismissed=false, isMovingFromParent=false
}
enum ProductError: Error { case expected }
@MainActor final class Counter { var calls=0;var failure: Error? }
@MainActor struct Product {
    enum PurchaseResult { case controller, scene }
    let counter: Counter
    func purchase(confirmIn: UIViewController) async throws -> PurchaseResult {
        counter.calls += 1
        if let failure=counter.failure { throw failure }
        return .controller
    }
    func purchase(confirmIn: UIWindowScene) async throws -> PurchaseResult { .scene }
}
@MainActor final class Route {
    weak var controller: UIViewController?
    var isActive=true
    enum PresentationError: Error { case unavailable }
    enum ObservationPoint { case entry, returned }
    func tracePresentation(_ point: ObservationPoint) {}
    // ACTUAL_PURCHASE
}
@MainActor func expect(_ value: Bool, _ label: String) {
    if !value { print("FAIL \(label): \(Fixture.events)");exit(1) }
}
@MainActor func rejects(_ body: () async throws -> Void) async {
    do { try await body();print("FAIL accepted invalid state");exit(1) } catch {}
}
@main struct Main {
    @MainActor static func main() async throws {
        let name=CommandLine.arguments[1], h=Harness()
        switch name {
        case "fresh-order", "prelaunch-order", "catalog-error-is-recorded":
            let mode=name == "fresh-order" ? "fresh" : "prelaunch"
            Fixture.reset(mode)
            if name == "catalog-error-is-recorded" { Fixture.value=Fixture.ready+"\npurchase-diagnostic phase=catalog category=storeKit domain=SKErrorDomain code=0" }
            try await h.testDiagnosticPurchaseSessionOrder()
            let order=Fixture.events.filter {$0 != "capture"}
            let expected=mode == "fresh" ? ["terminate","session","launch","purchase","terminate","clear","reset"] : ["terminate","launch","terminate","session","launch","purchase","terminate","clear","reset"]
            expect(order==expected,"exact operation order")
            expect(h.executionTimeAllowance==180 && !h.continueAfterFailure,"original case budget")
            expect(Fixture.attachments[0].contains("mode=\(mode) api=child"),"truthful selection")
            expect(Fixture.attachments.count==(mode == "fresh" ? 1 : 2),"no extra prelaunch for fresh")
            if mode == "prelaunch" { expect(Fixture.attachments[1].contains(Fixture.value!),"complete observed state retained") }
        case "invalid-config-before-any-action":
            let invalid:[[String:String]]=[[:],["TRIPDOCKET_PURCHASE_SESSION_ORDER_CONTROL":"1"],["TRIPDOCKET_PURCHASE_SESSION_ORDER_MODE":"prelaunch"],["TRIPDOCKET_PURCHASE_SESSION_ORDER_CONTROL":"0","TRIPDOCKET_PURCHASE_SESSION_ORDER_MODE":"fresh"],["TRIPDOCKET_PURCHASE_SESSION_ORDER_CONTROL":"1","TRIPDOCKET_PURCHASE_SESSION_ORDER_MODE":"child"],["TRIPDOCKET_PURCHASE_SESSION_ORDER_CONTROL":"1","TRIPDOCKET_PURCHASE_SESSION_ORDER_MODE":"swiftUI"],["TRIPDOCKET_PURCHASE_SESSION_ORDER_CONTROL":"1","TRIPDOCKET_PURCHASE_SESSION_ORDER_MODE":"fresh","TRIPDOCKET_PURCHASE_SESSION_ORDER_OTHER":"1"]]
            for env in invalid {
                Fixture.reset("fresh");Fixture.environment=env
                await rejects {try await h.testDiagnosticPurchaseSessionOrder()}
                expect(Fixture.events.isEmpty,"invalid config must not act")
            }
        case "unready-prelaunch-stops-before-session":
            for fault in ["missing","pro","busy","load","purchase","restore","duplicate-nav","duplicate-button","hidden","oversize"] {
                Fixture.reset("prelaunch")
                switch fault {
                case "missing":Fixture.value=nil
                case "pro":Fixture.value=Fixture.ready.replacingOccurrences(of:"isPro=false",with:"isPro=true")
                case "busy":Fixture.value=Fixture.ready.replacingOccurrences(of:"isBusy=false",with:"isBusy=true")
                case "load":Fixture.value=Fixture.ready.replacingOccurrences(of:"load=returned",with:"load=catalog")
                case "purchase":Fixture.value=Fixture.ready.replacingOccurrences(of:"purchase=notStarted",with:"purchase=returned")
                case "restore":Fixture.value=Fixture.ready.replacingOccurrences(of:"restore=notStarted",with:"restore=returned")
                case "duplicate-nav":Fixture.navCount=2
                case "duplicate-button":Fixture.buttonCount=2
                case "hidden":Fixture.hittable=false
                default:Fixture.value=Fixture.ready+String(repeating:"x",count:512)
                }
                await rejects {try await h.testDiagnosticPurchaseSessionOrder()}
                expect(Fixture.events==["terminate","launch","terminate"],"failed prelaunch closes without session or purchase")
            }
        case "unproven-stop-blocks-session":
            Fixture.reset("prelaunch");Fixture.failStop=true
            await rejects {try await h.testDiagnosticPurchaseSessionOrder()}
            expect(Fixture.events.filter {$0 != "capture"} == ["terminate","launch","terminate"],"stop not retried and session blocked")
        case "cancelled-prelaunch-does-not-configure":
            Fixture.reset("prelaunch")
            let task=Task {try await h.testDiagnosticPurchaseSessionOrder()};task.cancel()
            await rejects {try await task.value}
            expect(!Fixture.events.contains("session") && !Fixture.events.contains("purchase"),"cancel before explicit session")
            expect(Fixture.events.last=="terminate","cancel cleanup")
        case "passive-opt-in":
            let flag="--ui-testing-purchase-session-state"
            expect(PurchaseSessionOrderObservation.value(arguments:[],state:Fixture.ready,diagnostic:nil)==nil,"no ordinary observation")
            expect(PurchaseSessionOrderObservation.value(arguments:[flag,flag],state:Fixture.ready,diagnostic:nil)==nil,"duplicate flag rejected")
            expect(PurchaseSessionOrderObservation.value(arguments:[flag],state:nil,diagnostic:nil)==nil,"missing state rejected")
            expect(PurchaseSessionOrderObservation.value(arguments:[flag],state:Fixture.ready,diagnostic:"catalog-failure")==Fixture.ready+"\ncatalog-failure","passive value only")
        case "ordinary-route-and-guards":
            let scene=UIWindowScene(),window=UIWindow(),bridge=UIViewController(),parent=UIViewController(),route=Route(),counter=Counter()
            window.windowScene=scene;bridge.parent=parent;bridge.viewIfLoaded!.window=window;route.controller=bridge
            let product=Product(counter:counter)
            expect(try await route.purchase(product) == .controller,"ordinary child controller API")
            expect(counter.calls==1,"one call")
            route.isActive=false;await rejects {_ = try await route.purchase(product)};route.isActive=true
            bridge.parent=nil;await rejects {_ = try await route.purchase(product)};bridge.parent=parent
            parent.isBeingDismissed=true;await rejects {_ = try await route.purchase(product)};parent.isBeingDismissed=false
            scene.activationState = .background;await rejects {_ = try await route.purchase(product)};scene.activationState = .foregroundActive
            expect(counter.calls==1,"failed guards do not buy")
            counter.failure=CancellationError();await rejects {_ = try await route.purchase(product)}
            expect(counter.calls==2,"error has no fallback")
        default:fatalError("Unknown scenario")
        }
        print("PASS \(name)")
    }
}
'''
def between(s,a,z):
    assert s.count(a)==1 and s.count(z)==1
    return s[s.index(a):s.index(z,s.index(a))]
class SessionOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='purchase-session-order-');cls.addClassCleanup(cls.tmp.cleanup)
        views=(ROOT/'App/Views.swift').read_text();ui=(ROOT/'UITests/BatchImportUITests.swift').read_text()
        methods=between(ui,'    private static func diagnosticPurchaseSessionOrder(', '    private func localStoreSession()')
        methods=methods.replace('ProcessInfo.processInfo.environment','Fixture.environment')
        observation=between(views,'private enum PurchaseSessionOrderObservation {','private struct PurchaseDiagnosticValue:')
        purchase=between(views,'    func purchase(_ product: Product)','    private enum ObservationPoint:').removesuffix('    #if DEBUG && targetEnvironment(simulator)\n')
        path=Path(cls.tmp.name)/'main.swift';path.write_text(FIXTURE.replace('    // ACTUAL_UI',methods).replace('// ACTUAL_OBSERVATION',observation).replace('    // ACTUAL_PURCHASE',purchase))
        cls.binary=path.with_suffix('')
        r=subprocess.run(['swiftc','-swift-version','6','-parse-as-library',str(path),'-o',str(cls.binary)],capture_output=True,text=True,timeout=60)
        if r.returncode:raise AssertionError(r.stdout+r.stderr)
    def test_actual_order_readiness_configuration_and_child_route(self):
        for case in ('fresh-order','prelaunch-order','catalog-error-is-recorded','invalid-config-before-any-action','unready-prelaunch-stops-before-session','unproven-stop-blocks-session','cancelled-prelaunch-does-not-configure','passive-opt-in','ordinary-route-and-guards'):
            with self.subTest(case=case):
                r=subprocess.run([str(self.binary),case],capture_output=True,text=True,timeout=5)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(r.stdout.strip().splitlines()[-1],'PASS '+case)
    def test_passive_toolbar_only_and_no_alternate_purchase_api(self):
        views=(ROOT/'App/Views.swift').read_text();ui=(ROOT/'UITests/BatchImportUITests.swift').read_text()
        trips=between(views,'private struct TripsView: View {','private struct TripRow: View {')
        self.assertEqual(trips.count('PurchaseSessionOrderObservation.value('),1)
        toolbar=trips[trips.index('.toolbar {'):trips.index('.sheet(isPresented: $showsNewTrip)')]
        self.assertIn('Button(action: addTrip)',toolbar);self.assertIn('PurchaseSessionOrderObservation.value(',toolbar)
        self.assertNotIn('accessibilityIdentifier',toolbar);self.assertNotIn('.task',toolbar)
        self.assertNotIn('diagnosticPurchase(',views);self.assertNotIn('@Environment(\\.purchase)',views)
        self.assertEqual(views.count('try await purchasePresentation.purchase(product)'),1)
        case=between(ui,'    func testDiagnosticPurchaseSessionOrder()', '    private func localStoreSession()')
        self.assertEqual(case.count('purchaseOnce('),1);self.assertEqual(case.count('localStoreSession()'),1)
        self.assertNotIn('purchase-anchor=',case)
if __name__=='__main__':unittest.main()
