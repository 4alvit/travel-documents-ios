import XCTest

@MainActor
final class TripfolioUITests: XCTestCase {
    func testCreateTripAndSeeFreeLimit() {
        let app = launch()
        let create = app.buttons["Create a trip"]
        XCTAssertTrue(create.waitForExistence(timeout: 15))
        create.tap()
        let name = app.textFields["Trip name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.tap()
        name.typeText("Synthetic weekend")
        app.buttons["Create"].tap()
        XCTAssertTrue(app.staticTexts["Synthetic weekend"].waitForExistence(timeout: 5))
        app.buttons["Create trip"].tap()
        XCTAssertTrue(app.staticTexts["TripDocket Pro"].firstMatch.waitForExistence(timeout: 5))
        attach(app, name: "Free limit explains Pro")
    }

    func testOriginalReadinessAndExplicitPacketWarning() {
        let app = launch(demo: true)
        let trip = app.staticTexts["Coast weekend"]
        XCTAssertTrue(trip.waitForExistence(timeout: 15))
        trip.tap()
        let check = app.buttons["Check original"]
        XCTAssertTrue(check.waitForExistence(timeout: 10))
        check.tap()
        XCTAssertTrue(app.staticTexts["1 of 1 original verified"].waitForExistence(timeout: 5))
        attach(app, name: "Synthetic original readiness")
        let export = app.buttons["Export trip packet"]
        if !export.isHittable { app.swipeUp() }
        export.tap()
        XCTAssertTrue(app.buttons["Export…"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "unencrypted form")).firstMatch.exists)
        if app.buttons["Cancel"].exists {
            app.buttons["Cancel"].tap()
        } else {
            // Newer iOS popovers dismiss by tapping outside and omit Cancel.
            let dismissRegion = app.otherElements["PopoverDismissRegion"]
            XCTAssertTrue(dismissRegion.waitForExistence(timeout: 3))
            dismissRegion.tap()
        }
        XCTAssertTrue(export.waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["Export…"].waitForNonExistence(timeout: 3))
    }

    func testLockNowRemovesDocumentInterface() {
        let app = launch(demo: true)
        XCTAssertTrue(app.staticTexts["Coast weekend"].waitForExistence(timeout: 15))
        app.buttons["Settings"].firstMatch.tap()
        let lock = app.buttons["Lock now"]
        for _ in 0..<4 where !lock.isHittable { app.swipeUp() }
        XCTAssertTrue(lock.exists)
        lock.tap()
        XCTAssertTrue(app.staticTexts["TripDocket is locked"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["Settings"].firstMatch.exists)
        XCTAssertFalse(app.buttons["Trips"].firstMatch.exists)
        attach(app, name: "Locked interface")
    }

    private func launch(demo: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset"] + (demo ? ["--demo"] : [])
        app.launch()
        return app
    }

    private func attach(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
