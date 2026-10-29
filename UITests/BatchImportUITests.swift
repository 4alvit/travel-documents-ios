import Foundation
import StoreKit
import StoreKitTest
import XCTest
import UIKit

/// Functional coverage at standard text size. Batch import seeds named synthetic
/// PDFs into real Files and obtains Pro through local StoreKit. Paired recovery
/// phases use the existing demo fixture, remain Free, and export/restore through
/// real Files. Authentication bypass is confined to the existing Debug fixture.
/// Run serially, with a runner maximum/default allowance of at least 300 seconds.
@MainActor
final class BatchImportUITests: XCTestCase {
    private let productID = "com.4alvit.tripfolio.pro"
    private var folder: String {
        ProcessInfo.processInfo.environment["TRIPDOCKET_BATCH_FOLDER"] ?? "TripDocket-Batch-QA"
    }
    private let filenames = ["synthetic-ticket.pdf", "synthetic-insurance.pdf"]

    func testRealFilesBatchRequiresEveryReviewAndPreservesOriginals() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TRIPDOCKET_BATCH_UI"] == "1",
                          "Opt in with TRIPDOCKET_BATCH_UI=1 on the dedicated, fixture-seeded simulator")
        guard !folder.isEmpty, !folder.contains("/"), !folder.contains("\\") else {
            throw BatchTestFailure(message: "TRIPDOCKET_BATCH_FOLDER must name a single nonempty Files folder")
        }
        executionTimeAllowance = 300
        continueAfterFailure = false
        let app = XCUIApplication()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        app.terminate()
        let session = try await localStoreSession()
        defer {
            app.terminate()
            session.clearTransactions()
            session.resetToDefaultState()
        }
        app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset", "--demo",
                               "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
        app.launch()
        try await openTrip(app)
        try await openBatchEntry(app)
        try await wait("Free batch entry must show Pro, not a file picker", app: app) {
            app.navigationBars["TripDocket Pro"].exists && !app.buttons["batch.chooseFiles"].exists
        }
        try await purchaseOnce(app, springboard: springboard, session: session)
        let done = app.navigationBars["TripDocket Pro"].buttons["Done"]
        try check(done.isHittable, app: app, "Pro Done is not reachable after purchase")
        done.tap()
        try await openBatchEntry(app)

        let choose = app.buttons["batch.chooseFiles"]
        try await wait("The purchased batch entry did not open", app: app) { choose.exists && choose.isEnabled }
        try await reveal(choose, app: app, navigation: "Import files")
        choose.tap()
        try await selectRealFiles(app)
        try await wait("Both real files were not prepared for individual review", app: app) {
            self.reviewRow(self.filenames[0], in: app).exists
                && self.reviewRow(self.filenames[1], in: app).exists
                && app.buttons["batch.save"].exists
        }
        try check(reviewRows(in: app).count == 2, app: app, "The draft must contain exactly the two selected files")
        try await assertReviews(0, saveEnabled: false, app: app)
        capture(app, "Two real Files originals; nothing reviewed")

        try await openReview(filenames[0], app: app)
        try await selectMetadata("Type", value: "Ticket", app: app)
        try await selectMetadata("Person", value: "Alex Example", app: app)
        let firstExpiry = app.switches["Add confirmed expiry date"]
        try await reveal(firstExpiry, app: app, navigation: "Review document")
        try check(firstExpiry.value as? String == "0", app: app, "A file must not acquire an inferred expiry date")
        try await replaceTitle("QA reviewed ticket", app: app)
        try await confirmCurrent(app)
        try await assertReviews(1, saveEnabled: false, app: app)
        capture(app, "First document confirmed; Save still disabled")

        try await openReview(filenames[1], app: app)
        try await selectMetadata("Type", value: "Insurance", app: app)
        try await selectMetadata("Person", value: "Everyone / unassigned", app: app)
        let secondExpiry = app.switches["Add confirmed expiry date"]
        try await reveal(secondExpiry, app: app, navigation: "Review document")
        try check(secondExpiry.value as? String == "0", app: app, "Second original has an unexpected inferred expiry")
        // The labelled Switch is the whole row; its centre is the text. Tap
        // the single native switch nested inside that exact row instead.
        let nativeSwitches = secondExpiry.switches
        try check(nativeSwitches.count == 1, app: app, "The expiry row must contain one native switch")
        let nativeExpiry = nativeSwitches.element(boundBy: 0)
        try check(nativeExpiry.isEnabled && nativeExpiry.isHittable, app: app,
                  "The native expiry switch is not reachable")
        nativeExpiry.tap()
        // The native DatePicker has no label. Its own cell carries the exact
        // Expiry date text and one DatePicker with a visible date-value button.
        let dateCells = app.cells.containing(.staticText, identifier: "Expiry date")
        try await wait("Explicit expiry opt-in did not reveal its date control", app: app) {
            guard secondExpiry.value as? String == "1", dateCells.count == 1 else { return false }
            let pickers = dateCells.element(boundBy: 0).datePickers
            guard pickers.count == 1 else { return false }
            let date = pickers.element(boundBy: 0).buttons["Date Picker"]
            return date.exists && date.isHittable
                && !(date.value as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        // This fixture explicitly confirms the displayed current date; it does
        // not claim to test calendar navigation or OCR extraction of a date.
        capture(app, "Explicit expiry choice before confirmation")
        try await replaceTitle("QA reviewed insurance", app: app)
        try await confirmCurrent(app)
        try await assertReviews(2, saveEnabled: true, app: app)

        // A previously confirmed item's metadata cannot be changed silently.
        try await openReview(filenames[0], app: app)
        try await replaceTitle("QA corrected ticket", app: app)
        let reviewNavigation = app.navigationBars["Review document"]
        let back = [reviewNavigation.buttons["Import files"], reviewNavigation.buttons["Back"]]
            .first { $0.exists && $0.isHittable }
        try check(back != nil, app: app, "The review screen did not expose its Back control")
        back?.tap()
        try await assertReviews(1, saveEnabled: false, app: app)
        capture(app, "Editing a confirmed title requires review again")
        try await openReview(filenames[0], app: app)
        try await confirmCurrent(app)
        try await assertReviews(2, saveEnabled: true, app: app)
        let save = app.buttons["batch.save"]
        try await reveal(save, app: app, navigation: "Import files")
        capture(app, "Both documents individually confirmed; Save enabled")
        save.tap()
        try await wait("Batch save did not return to the trip", app: app) {
            !app.navigationBars["Import files"].exists
                && app.navigationBars["Coast weekend"].exists
                && self.documentRow("QA corrected ticket", in: app).exists
                && self.documentRow("QA reviewed insurance", in: app).exists
        }
        try await verifySavedLibrary(app)
        capture(app, "Two saved originals plus unchanged demo original")

        // Relaunch without reset: the successful result must be persistent.
        app.terminate()
        app.launchArguments = ["--ui-testing-unlocked",
                               "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
        app.launch()
        try await openTrip(app)
        try await verifySavedLibrary(app)
        for title in ["QA corrected ticket", "QA reviewed insurance"] {
            let row = documentRow(title, in: app)
            try await reveal(row, app: app, navigation: "Coast weekend")
            row.tap()
            try await wait("Saved original preview did not open: \(title)", app: app) {
                app.navigationBars["Original document"].exists
                    && app.otherElements["QLPreviewControllerView"].exists
            }
            // The renderer starts asynchronously. These captures require
            // independent pixel inspection; a container alone proves no PDF.
            try await Task.sleep(for: .seconds(5))
            capture(app, "Saved original after relaunch — \(title) — inspect PDF pixels")
            let previewDone = app.navigationBars["Original document"].buttons["Done"]
            try check(previewDone.isHittable, app: app, "Original preview Done is not reachable")
            previewDone.tap()
        }
    }

    // Opt-in prepare/export/restore phases. Preparation returns before the host
    // proves the exact UI-created folder empty. Export/restore retain the file
    // and library snapshot boundary. No StoreKit transaction is created.
    func testRecoveryCreateOwnedFilesDestination() async throws {
        let recoveryFolder = try recoveryConfiguration(phase: "prepare")
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--demo"]
        app.launch()
        try await wait("The preparation demo did not finish loading", app: app) {
            app.staticTexts["Coast weekend"].exists
        }
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 1, people: 1, documents: 1, app: app)
        try await presentRecoverySave(app)
        let navigation = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let picker = app.otherElements.matching(identifier: "Browse View (Picker)")
        try await wait("Real Files preparation picker did not open", app: app) {
            navigation.count == 1 && navigation.element.exists && picker.count == 1 && picker.element.exists
        }
        let localTitle = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        let browse = app.tabBars["DOC.browsingModeTabBar"].buttons.matching(NSPredicate(format: "label == %@", "Browse"))
        let location = app.cells.matching(NSPredicate(
            format: "identifier == %@ OR identifier == %@", "DOC.sidebar.item.On My iPhone", "DOC.sidebar.item.On My iPad"
        ))
        if !isRecoveryFolder(localTitle, navigation: navigation.element) {
            if !(location.count == 1 && location.element.isHittable) {
                try await wait("Files preparation has no unique Browse action", app: app) {
                    browse.count == 1 && browse.element.isEnabled && browse.element.isHittable
                }
                browse.element.tap()
            }
            if !isRecoveryFolder(localTitle, navigation: navigation.element) {
                try await wait("Files preparation local location is unavailable", app: app) {
                    location.count == 1 && location.element.isEnabled && location.element.isHittable
                }
                location.element.tap()
            }
        }
        try await wait("Files preparation did not reach the local root", app: app) {
            self.isRecoveryFolder(localTitle, navigation: navigation.element)
        }
        let directory = picker.element.cells.matching(identifier: recoveryFolder + ", Folder")
        try check(directory.count == 0, app: app, "Owned folder already exists before UI creation")
        let more = app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "More", "More Actions"))
        try await wait("Files local root has no unique More action", app: app) {
            self.isRecoveryFolder(localTitle, navigation: navigation.element)
                && more.count == 1 && more.element.isEnabled && more.element.isHittable
        }
        more.element.tap()
        let newFolder = app.buttons.matching(NSPredicate(format: "label == %@", "New Folder"))
        try await wait("Native New Folder action is unavailable", app: app) {
            newFolder.count == 1 && newFolder.element.isEnabled && newFolder.element.isHittable
        }
        newFolder.element.tap()
        let fields = app.alerts.textFields
        try await wait("Native folder-name dialog is ambiguous", app: app) {
            fields.count == 1 && fields.element.isEnabled && fields.element.isHittable
        }
        let field = fields.element
        field.tap()
        if let previous = field.value as? String, !previous.isEmpty {
            field.press(forDuration: 1.1)
            let selectAll = app.menuItems.matching(NSPredicate(format: "label == %@", "Select All"))
            try await wait("Folder name cannot be selected completely", app: app) {
                selectAll.count == 1 && selectAll.element.isEnabled && selectAll.element.isHittable
            }
            selectAll.element.tap()
        }
        field.typeText(recoveryFolder)
        try check(field.value as? String == recoveryFolder, app: app, "Native folder name differs from the exact owned UUID name")
        let create = app.alerts.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "Done", "Create"))
        try await wait("Native folder creation has no unique confirmation", app: app) {
            create.count == 1 && create.element.isEnabled && create.element.isHittable
        }
        create.element.tap()
        try await wait("Created folder or its exact title did not appear", app: app) {
            self.isRecoveryFolder(recoveryFolder, navigation: navigation.element)
                || (directory.count == 1 && directory.element.isHittable)
        }
        if !isRecoveryFolder(recoveryFolder, navigation: navigation.element) { directory.element.tap() }
        try await wait("Native Files did not open the created owned folder", app: app) {
            self.isRecoveryFolder(recoveryFolder, navigation: navigation.element)
        }
        capture(app, "Recovery prepare — unique created Files destination before Cancel")
        let cancel = navigation.element.buttons["Cancel"]
        try check(cancel.exists && cancel.isEnabled && cancel.isHittable, app: app, "Prepared Files destination has no Cancel action")
        cancel.tap()
        try await wait("Files preparation cancellation did not return to Settings", app: app) {
            !picker.element.exists && app.navigationBars["Settings"].exists
        }
        capture(app, "Recovery prepare — cancelled without saving, host empty-folder proof pending")
        // Host must now prove this exact folder is empty before export starts.
    }


    private func presentRecoverySave(_ app: XCUIApplication) async throws {
        let export = app.buttons["Export full backup"]
        try await reveal(export, app: app, navigation: "Settings")
        try check(export.isEnabled, app: app, "Free full-backup export is disabled")
        export.tap()
        let warning = "The backup includes every original document, person and trip in readable, unencrypted form. Anyone with a copy can access them. Keep it in a trusted location. Previously shared copies cannot be revoked."
        let disclosure = app.staticTexts.matching(NSPredicate(format: "label == %@", warning))
        try await wait("Full-backup disclosure is missing", app: app) {
            app.staticTexts["Export an unencrypted backup?"].exists && disclosure.count == 1
                && app.buttons["Export…"].isHittable
        }
        capture(app, "Recovery export — full unencrypted-backup disclosure")
        app.buttons["Export…"].tap()
        // Keep the button contract and the named action cell observed in the native sheet.
        let saveToFiles = app.descendants(matching: .any).matching(NSPredicate(
            format: "(elementType == %@ AND label == %@) OR (elementType == %@ AND identifier == %@ AND label == %@)",
            NSNumber(value: XCUIElement.ElementType.button.rawValue), "Save to Files",
            NSNumber(value: XCUIElement.ElementType.cell.rawValue), "actionGroupCell", "Save to Files"
        ))
        try await wait("Share sheet has no visible Save to Files action", app: app) {
            saveToFiles.count == 1 && saveToFiles.element.isHittable
        }
        saveToFiles.element.tap()
    }

    func testRecoveryExportFullBackupThroughFiles() async throws {
        let recoveryFolder = try recoveryConfiguration(phase: "export")
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--demo"]
        app.launch()
        try await wait("The demo library did not finish loading", app: app) {
            app.staticTexts["Coast weekend"].exists
        }
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 1, people: 1, documents: 1, app: app)
        try await recoveryFreeGate(app)
        try await recoveryTab("People", app: app)
        let add = app.navigationBars["People"].buttons["Add person"]
        try await wait("Add person is unavailable", app: app) { add.isHittable }
        add.tap()
        let alert = app.alerts["Add a person"]
        let name = alert.textFields["Name or nickname"]
        try await wait("Add-person dialog did not open", app: app) { name.isHittable }
        name.tap()
        name.typeText("Recovery Sentinel")
        let confirm = alert.buttons["Add"]
        try check(confirm.isEnabled && confirm.isHittable, app: app, "Add person cannot be confirmed")
        confirm.tap()
        try await wait("The unassigned person was not saved", app: app) {
            app.staticTexts["Recovery Sentinel"].exists && app.staticTexts["Alex Example"].exists
        }
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 1, people: 2, documents: 1, app: app)
        try await presentRecoverySave(app)
        let picker = try await openLocalFilesFolder(recoveryFolder, app: app)
        let fileNavigation = try await recoveryFilesNavigation(recoveryFolder, picker: picker, app: app)
        let save = fileNavigation.buttons["Save"]
        try await wait("The confirmed destination has no reachable Save control", app: app) {
            picker.exists && self.isRecoveryFolder(recoveryFolder, navigation: fileNavigation)
                && save.exists && save.isEnabled && save.isHittable
        }
        capture(app, "Recovery export — selected owned Files destination before Save")
        try check(isRecoveryFolder(recoveryFolder, navigation: fileNavigation), app: app,
                  "Files left the confirmed owned destination before Save")
        save.tap()
        try await wait("Save to Files did not return to Settings", app: app) {
            !picker.exists && app.navigationBars["Settings"].exists
        }
        capture(app, "Recovery export — UI completed, host file verification still required")
        // A dismissed sheet alone proves no export. The host must find exactly
        // Documents.tripbackup and compare its metadata/originals before reset.
    }

    func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal() async throws {
        let recoveryFolder = try recoveryConfiguration(phase: "restore")
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--ui-testing-reset"]
        app.launch()
        try await wait("Reset did not show an empty Trips library", app: app) {
            app.buttons["Create a trip"].exists && !app.staticTexts["Coast weekend"].exists
        }
        try await recoveryTab("People", app: app)
        try await wait("Reset did not show an empty People library", app: app) {
            app.staticTexts["Who’s coming?"].exists
                && !app.staticTexts["Alex Example"].exists && !app.staticTexts["Recovery Sentinel"].exists
        }
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 0, people: 0, documents: 0, app: app)
        capture(app, "Recovery restore — empty Free library before import")
        let restore = app.buttons["Restore from backup"]
        try await reveal(restore, app: app, navigation: "Settings")
        try check(restore.isEnabled, app: app, "Free backup restore is disabled")
        restore.tap()
        let picker = try await openLocalFilesFolder(recoveryFolder, app: app)
        let fileNavigation = try await recoveryFilesNavigation(recoveryFolder, picker: picker, app: app)
        // Folder was created empty and host-verified to contain exactly this
        // one UI-exported file. Match a complete display name, never a prefix.
        let files = picker.cells.matching(NSPredicate(
            format: "label == %@ OR label BEGINSWITH %@ OR label == %@ OR label BEGINSWITH %@",
            "Documents.tripbackup", "Documents.tripbackup,", "Documents", "Documents,"
        ))
        try await wait("Exactly one exported backup must be selectable", app: app) {
            self.isRecoveryFolder(recoveryFolder, navigation: fileNavigation)
                && files.count == 1 && files.element(boundBy: 0).isHittable
        }
        capture(app, "Recovery restore — actual exported file in owned Files folder")
        try check(isRecoveryFolder(recoveryFolder, navigation: fileNavigation), app: app,
                  "Files left the confirmed owned folder before selection")
        files.element(boundBy: 0).tap()
        let replace = app.buttons["Replace library from backup"]
        // A single-file importer normally completes on selection. Some native
        // versions require Open; only accept that control within this picker.
        let open = picker.buttons.matching(NSPredicate(format: "label == %@", "Open")).firstMatch
        try await wait("File selection neither completed nor exposed Open", app: app) {
            replace.isHittable || (picker.exists && open.isHittable && open.isEnabled)
        }
        if !replace.isHittable {
            try check(isRecoveryFolder(recoveryFolder, navigation: fileNavigation), app: app,
                      "Files left the confirmed owned folder before Open")
            open.tap()
        }
        let replacementWarning = "This will replace all 0 current documents, trips and people with the selected backup. Export your current library first if you need to keep it. The backup is validated before replacement; a failed restore keeps your current library."
        let replacementDisclosure = app.staticTexts.matching(NSPredicate(format: "label == %@", replacementWarning))
        try await wait("Empty-library replacement disclosure is missing", app: app) {
            app.staticTexts["Replace your entire library?"].exists
                && replacementDisclosure.count == 1 && replace.isHittable
        }
        capture(app, "Recovery restore — explicit replacement confirmation")
        replace.tap()
        let notices = app.staticTexts.matching(NSPredicate(
            format: "label == %@", "Backup restored and originals verified. Schedule reminders again on this device."
        ))
        let notice = notices.element
        try await reveal(notice, app: app, navigation: "Settings")
        try await wait("The app did not verify and restore the backup", app: app) {
            notices.count == 1 && notice.exists
        }
        capture(app, "Recovery restore — successful app validation")
        try await recoveryCounts(trips: 1, people: 2, documents: 1, app: app)

        // Read persistence after a clean launch, with neither reset nor demo.
        app.terminate()
        app.launchArguments = recoveryArguments
        app.launch()
        try await recoveryFreeGate(app)
        try await recoveryTab("People", app: app)
        try await wait("Restored people did not survive relaunch", app: app) {
            app.staticTexts["Alex Example"].exists && app.staticTexts["Recovery Sentinel"].exists
        }
        capture(app, "Recovery restore — assigned and unassigned people persisted")
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 1, people: 2, documents: 1, app: app)
        try await recoveryTab("Trips", app: app)
        try await openTrip(app)
        let checkOriginal = app.buttons["Check original"]
        try await reveal(checkOriginal, app: app, navigation: "Coast weekend")
        checkOriginal.tap()
        try await wait("The restored complete original did not verify", app: app) {
            app.staticTexts["1 of 1 original verified"].exists
        }
        let document = documentRow("Weekend reservation", in: app)
        try await reveal(document, app: app, navigation: "Coast weekend")
        try check(document.label.contains("Booking") && document.label.contains("Alex Example"),
                  app: app, "Restored document metadata is not visible")
        document.tap()
        try await wait("Restored original preview did not open", app: app) {
            app.navigationBars["Original document"].exists && app.otherElements["QLPreviewControllerView"].exists
        }
        try await Task.sleep(for: .seconds(5))
        capture(app, "Recovery restored original — inspect synthetic PDF pixels")
        let done = app.navigationBars["Original document"].buttons["Done"]
        try check(done.isHittable, app: app, "Restored original Done is not reachable")
        done.tap()
        // The host now compares the active catalog and original bytes against
        // its pre-reset snapshot. UI counts and a preview container are not it.
    }

    private func isRecoveryFolder(_ folder: String, navigation: XCUIElement) -> Bool {
        // This is a navigation-title marker, not the folder's row in its parent.
        // Unknown native accessibility layouts must fail before a write/selection.
        let titles = navigation.staticTexts.matching(NSPredicate(format: "label == %@", folder))
        return navigation.exists && titles.count == 1 && titles.element(boundBy: 0).isHittable
    }

    private func recoveryFilesNavigation(_ folder: String, picker: XCUIElement,
                                         app: XCUIApplication) async throws -> XCUIElement {
        let navigation = app.navigationBars["FullDocumentManagerViewControllerNavigationBar"].firstMatch
        try await wait("Files did not positively identify the current owned folder", app: app) {
            picker.exists && self.isRecoveryFolder(folder, navigation: navigation)
        }
        return navigation
    }

    private var recoveryArguments: [String] {
        ["--ui-testing-unlocked", "-AppleLanguages", "(en)", "-AppleLocale", "en_US",
         "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
    }

    private func recoveryConfiguration(phase: String) throws -> String {
        let env = ProcessInfo.processInfo.environment
        try XCTSkipUnless(env["TRIPDOCKET_RECOVERY_UI"] == "1", "Recovery UI phases require explicit opt-in")
        try XCTSkipUnless(env["TRIPDOCKET_RECOVERY_PHASE"] == phase, "Run exactly the admitted recovery phase")
        guard let value = env["TRIPDOCKET_RECOVERY_FOLDER"],
              value.hasPrefix("TripDocket-Recovery-"), value.count <= 100,
              value.unicodeScalars.allSatisfy({ CharacterSet.alphanumerics.contains($0) || $0 == "-" }) else {
            throw BatchTestFailure(message: "Recovery requires a unique owned TripDocket-Recovery-* Files folder")
        }
        executionTimeAllowance = phase == "prepare" ? 120 : 300
        continueAfterFailure = false
        return value
    }

    private func recoveryTab(_ title: String, app: XCUIApplication) async throws {
        let tab = app.buttons[title].firstMatch
        try await wait("Tab is unavailable: \(title)", app: app) { tab.isHittable }
        tab.tap()
        let navigationTitle = title == "Trips" ? "TripDocket" : title
        try await wait("Tab did not open: \(title)", app: app) { app.navigationBars[navigationTitle].exists }
    }

    private func recoveryFreeCard(_ app: XCUIApplication) async throws {
        let free = app.staticTexts["Make room for every trip"]
        try await reveal(free, app: app, navigation: "Settings")
        try check(free.exists && !app.staticTexts["Pro is unlocked on this device."].exists,
                  app: app, "This phase requires an observed Free library")
    }

    private func recoveryFreeGate(_ app: XCUIApplication) async throws {
        try await recoveryTab("Trips", app: app)
        try await wait("The recovered/demo trip is missing", app: app) { app.staticTexts["Coast weekend"].exists }
        let create = app.navigationBars["TripDocket"].buttons["Create trip"]
        try await wait("Create trip is unavailable", app: app) { create.isEnabled && create.isHittable }
        create.tap()
        try await wait("The second-trip action did not show the real Free gate", app: app) {
            app.navigationBars["TripDocket Pro"].exists && !app.textFields["Trip name"].exists
        }
        capture(app, "Recovery — real second-trip Free gate without purchase")
        let done = app.navigationBars["TripDocket Pro"].buttons["Done"]
        try check(done.isHittable, app: app, "Free gate Done is unavailable")
        done.tap()
        try await wait("Free gate did not close", app: app) { !app.navigationBars["TripDocket Pro"].exists }
    }

    private func recoveryCounts(trips: Int, people: Int, documents: Int, app: XCUIApplication) async throws {
        for (identifier, label, count) in [
            ("settings.count.trips", "Trips", trips),
            ("settings.count.people", "People", people),
            ("settings.count.documents", "Documents", documents)
        ] {
            let rows = app.descendants(matching: .any).matching(identifier: identifier)
            let row = rows.firstMatch
            try await reveal(row, app: app, navigation: "Settings")
            try await wait("Incorrect or ambiguous Settings count for \(label); expected \(count)", app: app) {
                rows.count == 1 && row.isHittable && row.label == label
                    && (row.value as? String) == String(count)
            }
        }
    }


    private func localStoreSession() async throws -> SKTestSession {
        let configuration = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "Tripfolio", withExtension: "storekit"))
        let session = try SKTestSession(contentsOf: configuration)
        session.resetToDefaultState()
        session.clearTransactions()
        session.disableDialogs = true
        do {
            let transaction = try await session.buyProduct(identifier: productID, options: [])
            guard transaction.environment == .xcode, transaction.productID == productID else {
                throw BatchTestFailure(message: "StoreKit preflight did not return the expected Xcode test product; app was not launched")
            }
            session.clearTransactions()
            guard session.allTransactions().isEmpty else {
                throw BatchTestFailure(message: "StoreKit preflight transaction was not cleared")
            }
            session.disableDialogs = false
            return session
        } catch {
            session.clearTransactions()
            session.resetToDefaultState()
            throw error
        }
    }

    private func purchaseOnce(_ app: XCUIApplication, springboard: XCUIApplication, session: SKTestSession) async throws {
        let buy = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Unlock Pro ·")).firstMatch
        try await wait("The local product did not load; no purchase retry is allowed", app: app) { buy.exists && buy.isEnabled }
        try await reveal(buy, app: app, navigation: "TripDocket Pro")
        buy.tap()
        try await wait("No positively identified Xcode payment sheet appeared", app: app, springboard: springboard) {
            self.xcodeMarker(app).exists || self.xcodeMarker(springboard).exists
        }
        let surface = xcodeMarker(app).exists ? app : springboard
        // The saved iOS 27 Xcode sheet labels its confirmation "Purchase".
        // Accept only these exact payment labels, under the same Xcode guard.
        let confirm = surface.buttons.matching(NSPredicate(
            format: "label ==[c] %@ OR label ==[c] %@", "Purchase", "Buy"
        )).firstMatch
        try await wait("Xcode payment sheet has no reachable Purchase or Buy control", app: app, springboard: springboard) {
            self.xcodeMarker(surface).exists && confirm.exists && confirm.isEnabled && confirm.isHittable
        }
        capture(app, "Xcode payment sheet before sole confirmation", springboard: springboard)
        try check(xcodeMarker(surface).exists, app: app, "Xcode marker disappeared before confirmation")
        confirm.tap()
        var successAlert: XCUIElement?
        try await wait("Local purchase neither completed nor showed its identified Xcode success alert",
                       app: app, springboard: springboard) {
            successAlert = self.localSuccessAlert(in: app) ?? self.localSuccessAlert(in: springboard)
            if let successAlert {
                let ok = successAlert.buttons["OK"]
                return ok.exists && ok.isEnabled && ok.isHittable
            }
            return app.staticTexts["Pro is unlocked"].exists
                && !self.xcodeMarker(app).exists && !self.xcodeMarker(springboard).exists
        }
        if let successAlert {
            capture(app, "Identified Xcode purchase success before OK", springboard: springboard)
            try check(isLocalSuccessAlert(successAlert), app: app,
                      "The identified Xcode success alert changed before dismissal")
            let ok = successAlert.buttons["OK"]
            try check(ok.isEnabled && ok.isHittable, app: app, "Xcode success OK became unavailable")
            ok.tap()
        }
        try await wait("Actual local purchase did not unlock Pro", app: app, springboard: springboard) {
            app.staticTexts["Pro is unlocked"].exists
                && !self.xcodeMarker(app).exists && !self.xcodeMarker(springboard).exists
        }
        try check(session.allTransactions().filter { $0.productIdentifier == productID }.count == 1,
                  app: app, "The app purchase did not produce exactly one expected local transaction")
        capture(app, "Actual local StoreKit Pro entitlement")
    }

    private func xcodeMarker(_ app: XCUIApplication) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "Xcode")).firstMatch
    }

    private func localSuccessAlert(in app: XCUIApplication) -> XCUIElement? {
        app.alerts.allElementsBoundByIndex.first { isLocalSuccessAlert($0) }
    }

    private func isLocalSuccessAlert(_ alert: XCUIElement) -> Bool {
        // Both observed messages must belong to this same native alert. Never
        // dismiss a generic OK, account prompt, or failed-purchase alert.
        alert.exists
            && alert.staticTexts.matching(NSPredicate(
                format: "label CONTAINS %@", "Your purchase was successful."
            )).firstMatch.exists
            && alert.staticTexts.matching(NSPredicate(
                format: "label CONTAINS %@", "[Environment: Xcode]"
            )).firstMatch.exists
    }

    private func openTrip(_ app: XCUIApplication) async throws {
        let trip = app.staticTexts["Coast weekend"]
        try await wait("The synthetic trip did not load", app: app) { trip.exists && trip.isHittable }
        trip.tap()
        try await wait("Trip navigation did not open", app: app) { app.navigationBars["Coast weekend"].exists }
    }

    private func openBatchEntry(_ app: XCUIApplication) async throws {
        let actions = app.navigationBars["Coast weekend"].buttons["Trip actions"]
        try await wait("Trip actions is unavailable", app: app) { actions.exists && actions.isHittable }
        actions.tap()
        let batch = app.buttons["Import multiple files · Pro"]
        try await wait("Trip actions did not expose multiple-file import", app: app) { batch.isHittable }
        batch.tap()
    }

    private func openLocalFilesFolder(_ folder: String, app: XCUIApplication) async throws -> XCUIElement {
        let navigation = app.navigationBars["FullDocumentManagerViewControllerNavigationBar"].firstMatch
        try await wait("Files did not present its navigation", app: app) { navigation.exists }
        let picker = app.otherElements["Browse View (Picker)"].firstMatch
        try await wait("The real Files picker root is missing", app: app) { picker.exists }
        let directory = picker.cells.matching(identifier: folder + ", Folder").firstMatch
        // The captured native tab bar is a sibling of Browse View (Picker),
        // not its descendant. Its controls can appear after the root/navigation.
        let browse = app.tabBars["DOC.browsingModeTabBar"].buttons["Browse"].firstMatch
        let location = app.cells.matching(NSPredicate(
            format: "identifier == %@ OR identifier == %@", "DOC.sidebar.item.On My iPhone", "DOC.sidebar.item.On My iPad"
        )).firstMatch
        try await wait("Native Files navigation did not render its local browsing controls", app: app) {
            navigation.exists && picker.exists
                && ((directory.exists && directory.isHittable)
                    || (location.exists && location.isHittable)
                    || (browse.exists && browse.isHittable))
        }
        if !(directory.exists && directory.isHittable) {
            if !(location.exists && location.isHittable) {
                try check(browse.exists && browse.isHittable, app: app, "Native Files Browse is unavailable")
                browse.tap()
            }
            // Browse can restore On My iPhone directly instead of showing
            // the locations sidebar. Wait for either observed destination.
            try await wait("Files did not show the exact fixture folder or its local location", app: app) {
                (directory.exists && directory.isHittable) || (location.exists && location.isHittable)
            }
            if !(directory.exists && directory.isHittable) { location.tap() }
        }
        try await wait("The named synthetic Files folder is missing", app: app) { directory.exists && directory.isHittable }
        directory.tap()
        return picker
    }

    private func selectRealFiles(_ app: XCUIApplication) async throws {
        let navigation = app.navigationBars["FullDocumentManagerViewControllerNavigationBar"].firstMatch
        let picker = try await openLocalFilesFolder(folder, app: app)
        for filename in filenames {
            let basename = (filename as NSString).deletingPathExtension
            let file = picker.cells.matching(NSPredicate(format: "label BEGINSWITH %@", basename)).firstMatch
            try await wait("Missing selectable real Files original: \(filename)", app: app) { file.exists && file.isHittable }
            file.tap()
            try check(navigation.exists, app: app, "Files closed before both originals could be selected")
        }
        let open = picker.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", "Open", "Open (")).firstMatch
        try await wait("Files did not expose Open after selecting both originals", app: app) { open.exists && open.isEnabled && open.isHittable }
        capture(app, "Two synthetic originals selected in real Files")
        open.tap()
        try await wait("Files remained after opening the selection", app: app) { !navigation.exists }
    }

    private func reviewRows(in app: XCUIApplication) -> XCUIElementQuery {
        app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "batch.review."))
    }

    private func reviewRow(_ filename: String, in app: XCUIApplication) -> XCUIElement {
        reviewRows(in: app).matching(NSPredicate(format: "label CONTAINS %@", filename)).firstMatch
    }

    private func openReview(_ filename: String, app: XCUIApplication) async throws {
        let row = reviewRow(filename, in: app)
        try await reveal(row, app: app, navigation: "Import files")
        row.tap()
        try await wait("Individual review did not open for \(filename)", app: app) { app.navigationBars["Review document"].exists }
    }

    private func selectMetadata(_ title: String, value: String, app: XCUIApplication) async throws {
        let picker = app.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", title, title + ",")).firstMatch
        try await reveal(picker, app: app, navigation: "Review document")
        picker.tap()
        try await wait("\(title) choices did not open", app: app) { app.navigationBars[title].exists }
        // Navigation-link Picker rows are native buttons in the presented
        // choices collection, not StaticTexts (observed Type picker hierarchy).
        let choice = app.collectionViews.buttons.matching(NSPredicate(format: "label == %@", value)).firstMatch
        try await wait("Metadata choice is not reachable: \(value)", app: app) {
            app.navigationBars[title].exists && choice.exists && choice.isHittable
        }
        if choice.isSelected {
            // Selecting the current value leaves this native picker open.
            // Preserve the verified selection and return using its own Back.
            let back = app.navigationBars[title].buttons.matching(identifier: "BackButton").firstMatch
            try check(app.navigationBars[title].exists && back.exists && back.isHittable
                        && back.label == "Review document",
                      app: app, "Selected \(title) picker has no verified Back control")
            back.tap()
        } else {
            choice.tap()
        }
        try await wait("\(title) choice did not return to review", app: app) {
            !app.navigationBars[title].exists && app.navigationBars["Review document"].exists
        }
    }

    private func replaceTitle(_ value: String, app: XCUIApplication) async throws {
        let field = app.textFields["batch.title"].firstMatch
        try await reveal(field, app: app, navigation: "Review document")
        field.tap()
        // A native tap can place the caret at the beginning of this field.
        // Select the complete value through the iOS edit menu instead of
        // assuming where repeated Delete keystrokes will start.
        field.press(forDuration: 1.1)
        var selectAll: XCUIElement?
        try await wait("The title edit menu did not expose a reachable Select All", app: app) {
            selectAll = [app.menuItems["Select All"].firstMatch, app.buttons["Select All"].firstMatch]
                .first { $0.exists && $0.isEnabled && $0.isHittable }
            return selectAll != nil
        }
        capture(app, "Native title edit menu before Select All")
        try XCTUnwrap(selectAll).tap()
        field.typeText(value)
        try check(field.value as? String == value, app: app, "The document title was not edited exactly")
    }

    private func confirmCurrent(_ app: XCUIApplication) async throws {
        let confirm = app.buttons["batch.confirmItem"]
        try await reveal(confirm, app: app, navigation: "Review document")
        try check(confirm.isEnabled, app: app, "Valid document details could not be confirmed")
        confirm.tap()
        try await wait("Confirmation did not return to batch review", app: app) { !app.navigationBars["Review document"].exists }
    }

    private func assertReviews(_ count: Int, saveEnabled: Bool, app: XCUIApplication) async throws {
        let save = app.buttons["batch.save"]
        try await wait("Review count or Save availability is incorrect", app: app) {
            app.staticTexts["\(count) of 2 reviewed"].exists && save.exists && save.isEnabled == saveEnabled
        }
    }

    private func documentRow(_ title: String, in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", title)).firstMatch
    }

    private func verifySavedLibrary(_ app: XCUIApplication) async throws {
        let ticket = documentRow("QA corrected ticket", in: app)
        let insurance = documentRow("QA reviewed insurance", in: app)
        try await wait("Saved document titles did not persist", app: app) { ticket.exists && insurance.exists }
        try check(ticket.label.contains("Ticket") && ticket.label.contains("Alex Example")
                    && !ticket.label.contains("Expires") && !ticket.label.contains("Expired"),
                  app: app, "Ticket metadata did not persist with its chosen person and no expiry")
        try check(insurance.label.contains("Insurance") && !insurance.label.contains("Alex Example")
                    && (insurance.label.contains("Expires") || insurance.label.contains("Expired")),
                  app: app, "Insurance metadata did not persist with the explicit date and unassigned person")
        let checkOriginals = app.buttons["Check all 3 originals"]
        try await reveal(checkOriginals, app: app, navigation: "Coast weekend")
        checkOriginals.tap()
        try await wait("The three complete originals did not verify", app: app) { app.staticTexts["3 of 3 originals verified"].exists }
    }

    private func reveal(_ element: XCUIElement, app: XCUIApplication, navigation: String) async throws {
        for _ in 0..<10 {
            let bar = app.navigationBars[navigation]
            try check(bar.exists, app: app, "Expected navigation is missing: \(navigation)")
            var viewport = app.frame.intersection(CGRect(x: bar.frame.minX, y: bar.frame.maxY,
                width: bar.frame.width, height: max(0, app.frame.maxY - bar.frame.maxY))).insetBy(dx: 6, dy: 8)
            for obstruction in app.tabBars.allElementsBoundByIndex + app.keyboards.allElementsBoundByIndex
                where obstruction.exists && obstruction.isHittable && obstruction.frame.minY > viewport.minY {
                viewport.size.height = max(0, min(viewport.maxY, obstruction.frame.minY - 8) - viewport.minY)
            }
            let frame = element.exists ? element.frame : .null
            if element.exists && element.isHittable && !frame.isEmpty && viewport.contains(frame) { return }
            let candidates = app.collectionViews.allElementsBoundByIndex + app.scrollViews.allElementsBoundByIndex
            let container = candidates.reversed().first {
                $0.exists && $0.isHittable && $0.frame.width <= bar.frame.width + 32
                    && $0.frame.intersection(viewport).height > 100
            }
            guard let container else { throw failure("No active scroll container for \(navigation)", app: app) }
            viewport = viewport.intersection(container.frame).insetBy(dx: 8, dy: 8)
            try check(viewport.height > 80, app: app, "No safe scroll viewport for \(navigation)")
            let upwards = frame.isNull || frame.midY > viewport.midY
            let distance = min(140, viewport.height * 0.45)
            let start = container.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: viewport.midX - container.frame.minX, dy: viewport.midY - container.frame.minY))
            start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: upwards ? -distance : distance)),
                        withVelocity: .slow, thenHoldForDuration: 0.2)
            try await Task.sleep(for: .milliseconds(100))
        }
        throw failure("Required control did not become fully reachable in \(navigation): \(element.identifier)", app: app)
    }

    private func wait(_ message: String, app: XCUIApplication, springboard: XCUIApplication? = nil,
                      condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(15))
        repeat {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(100))
        } while ContinuousClock.now < deadline
        capture(app, message, springboard: springboard)
        throw BatchTestFailure(message: message)
    }

    private func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw failure(message, app: app) }
    }

    private func failure(_ message: String, app: XCUIApplication) -> BatchTestFailure {
        capture(app, message)
        return BatchTestFailure(message: message)
    }

    private func capture(_ app: XCUIApplication, _ name: String, springboard: XCUIApplication? = nil) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let tree = XCTAttachment(string: app.debugDescription + (springboard.map { "\nSPRINGBOARD\n" + $0.debugDescription } ?? ""))
        tree.name = name + " — accessibility hierarchy"
        tree.lifetime = .keepAlways
        add(tree)
    }

    private struct BatchTestFailure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
