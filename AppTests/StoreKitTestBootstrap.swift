import Foundation
import StoreKitTest
import XCTest
@testable import Tripfolio

/// XCTest constructs the test bundle's principal class before running tests.
/// Configure StoreKit here so even ordinary model tests cannot initialize its
/// process-wide connection against the sandbox before a purchase scenario.
final class StoreKitTestBootstrap: NSObject, XCTestObservation {
    private let session: SKTestSession

    override init() {
        guard AppLaunch.isHostedUnitTest() else {
            fatalError("The unit-test host must defer app startup before StoreKit setup.")
        }
        guard let configuration = Bundle(for: StoreKitTestBootstrap.self)
            .url(forResource: "Tripfolio", withExtension: "storekit") else {
            fatalError("TripfolioTests must include the local StoreKit configuration.")
        }
        do {
            session = try SKTestSession(contentsOf: configuration)
            session.resetToDefaultState()
            session.clearTransactions()
        } catch {
            fatalError("Cannot initialize local StoreKit before unit tests: \(error)")
        }
        super.init()
        // XCTest documents that its observation center retains observers.
        // Keep this session alive until the bundle finishes, independently of
        // how long XCTest retains the principal-class instance itself.
        XCTestObservationCenter.shared.addTestObserver(self)
    }

    func testBundleDidFinish(_ testBundle: Bundle) {
        guard testBundle == Bundle(for: StoreKitTestBootstrap.self) else { return }
        session.clearTransactions()
        XCTestObservationCenter.shared.removeTestObserver(self)
    }
}

final class AppLaunchTests: XCTestCase {
    func testOnlyTheExactHostedUnitBundleDefersDebugAppStartup() {
        XCTAssertTrue(AppLaunch.isHostedUnitTest(environment: [
            "XCTestBundlePath": "PlugIns/TripfolioTests.xctest"
        ]))
        XCTAssertTrue(AppLaunch.isHostedUnitTest(environment: [
            "XCTestBundlePath": "/Synthetic/Tripfolio.app/PlugIns/TripfolioTests.xctest"
        ]))
        for environment in [
            [:],
            ["XCTestBundlePath": ""],
            ["XCTestBundlePath": "PlugIns/TripfolioUITests.xctest"],
            ["XCTestBundlePath": "PlugIns/OtherTests.xctest"],
            ["XCTestBundlePath": "PlugIns/TripfolioTests.xctest.backup"],
            ["XCTestConfigurationFilePath": "Synthetic.xctestconfiguration"],
            ["XCTestSessionIdentifier": "Synthetic"]
        ] {
            XCTAssertFalse(AppLaunch.isHostedUnitTest(environment: environment))
        }
    }

    func testRunningHostUsesTheDeclaredStoreKitBootstrap() throws {
        XCTAssertTrue(AppLaunch.isHostedUnitTest(), "The real injected unit-test bundle must defer app startup.")
        let bundle = Bundle(for: StoreKitTestBootstrap.self)
        XCTAssertEqual(bundle.infoDictionary?["NSPrincipalClass"] as? String,
                       "TripfolioTests.StoreKitTestBootstrap")
        XCTAssertEqual(NSStringFromClass(try XCTUnwrap(bundle.principalClass)),
                       NSStringFromClass(StoreKitTestBootstrap.self))
    }
}
