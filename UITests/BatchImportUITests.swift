import Foundation
import StoreKit
import StoreKitTest
import XCTest
import UIKit
import Vision

/// Functional coverage at standard text size. Batch import seeds named synthetic
/// PDFs into real Files and obtains Pro through local StoreKit. Paired recovery
/// phases use the existing demo fixture, remain Free, and export/restore through
/// real Files. Authentication bypass is confined to the existing Debug fixture.
/// Run serially, with a 300-second runner default and a 600-second maximum
/// for the complete batch workflow. Recovery phases retain their own allowances.
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
        executionTimeAllowance = 600
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
        app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset", "--demo", "--ui-testing-batch-diagnostics",
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
    // creates and verifies the exclusively owned empty folder. Export/restore
    // retain the file and library snapshot boundary. No StoreKit transaction is created.
    func testRecoveryPrepareFilesProvider() async throws {
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
        try await reachRecoveryLocalRoot(localTitle, navigation: navigation, location: location, browse: browse, app: app)
        let directory = picker.element.cells.matching(identifier: recoveryFolder + ", Folder")
        try check(directory.count == 0, app: app, "Owned folder already exists before fixture creation")
        capture(app, "Recovery prepare — real local Files provider before fixture shutdown")
        // Native New Folder/rename is not a product acceptance requirement.
        // The host creates only an exclusive empty run-UUID leaf after this
        // real provider initialization and proven fixture stop; never a backup.
        app.terminate()
        try await wait("Preparation fixture did not stop before host fixture creation", app: app) {
            app.state == .notRunning
        }
        // The existing defer remains cleanup on every success/failure path.
        // Host must now create and independently prove the exact folder empty.
    }


    func testNativeCreateOwnedFilesFolder() async throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["TRIPDOCKET_NATIVE_FOLDER_UI"] == "1",
                          "Opt in only for the owned native-folder fixture diagnostic")
        let token = environment["TRIPDOCKET_NATIVE_FOLDER_TOKEN"] ?? ""
        let ownedFolder = "TripDocket-Batch-QA-" + token
        guard UUID(uuidString: token)?.uuidString.lowercased() == token,
              environment["TRIPDOCKET_BATCH_FOLDER"] == ownedFolder else {
            throw BatchTestFailure(message: "Native folder creation requires its exact canonical owned token")
        }
        executionTimeAllowance = 180
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--demo"]
        app.launch()
        try await wait("The native-folder demo did not finish loading", app: app) {
            app.staticTexts["Coast weekend"].exists
        }
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 1, people: 1, documents: 1, app: app)
        try await presentRecoverySave(app)
        let navigation = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let picker = app.otherElements.matching(identifier: "Browse View (Picker)")
        try await wait("Native-folder Files picker did not open", app: app) {
            navigation.count == 1 && navigation.element.exists && picker.count == 1 && picker.element.exists
        }
        let localTitle = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        let browse = app.tabBars["DOC.browsingModeTabBar"].buttons.matching(NSPredicate(format: "label == %@", "Browse"))
        let location = app.cells.matching(NSPredicate(
            format: "identifier == %@ OR identifier == %@", "DOC.sidebar.item.On My iPhone", "DOC.sidebar.item.On My iPad"
        ))
        try await reachRecoveryLocalRoot(localTitle, navigation: navigation, location: location, browse: browse, app: app)
        let directory = picker.element.cells.matching(identifier: ownedFolder + ", Folder")
        try check(directory.count == 0, app: app, "Owned native folder already exists before creation")
        let more = navigation.element.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "OverflowBarButtonItem", "More"
        ))
        try await wait("Native-folder local root has no unique More action", app: app) {
            self.isRecoveryFolder(localTitle, navigation: navigation.element)
                && more.count == 1 && more.element.isEnabled && more.element.isHittable
        }
        more.element.tap()
        let newFolder = app.buttons.matching(NSPredicate(format: "label == %@", "New Folder"))
        try await wait("Native New Folder action is unavailable", app: app) {
            newFolder.count == 1 && newFolder.element.isEnabled && newFolder.element.isHittable
        }
        newFolder.element.tap()
        let files = picker.element.collectionViews.matching(identifier: "File View")
        let inlineNames = files.element.textViews.matching(identifier: "DOC.inlineRenameField")
        try await wait("Native folder-name editor is not unique and reachable", app: app) {
            files.count == 1 && inlineNames.count == 1
                && inlineNames.element.isEnabled && inlineNames.element.isHittable
        }
        // Files selects the default inline name. Do not collapse that selection
        // by tapping the editor; verify that typing replaced the complete value.
        inlineNames.element.typeText(ownedFolder)
        try check(inlineNames.count == 1 && inlineNames.element.value as? String == ownedFolder,
                  app: app, "Native folder name differs from the exact owned UUID name")
        let create = app.keyboards.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "Done", "done"
        ))
        try await wait("Native folder creation has no unique Done confirmation", app: app) {
            inlineNames.count == 1 && inlineNames.element.value as? String == ownedFolder
                && create.count == 1 && create.element.isEnabled && create.element.isHittable
        }
        capture(app, "Native folder exact name before the single Done")
        create.element.tap()
        // An updated folder-cell identifier must not masquerade as editor
        // dismissal. Check the live editor identifier independently of its cell.
        let remainingEditors = app.textViews.matching(identifier: "DOC.inlineRenameField")
        try await wait("Native folder confirmation did not end editing with the exact destination", app: app) {
            remainingEditors.count == 0
                && (self.isRecoveryFolder(ownedFolder, navigation: navigation.element)
                    || (directory.count == 1 && directory.element.isEnabled && directory.element.isHittable))
        }
        if !isRecoveryFolder(ownedFolder, navigation: navigation.element) {
            try check(directory.count == 1 && directory.element.isEnabled && directory.element.isHittable,
                      app: app, "Created native folder is not uniquely reachable")
            directory.element.tap()
        }
        try await wait("Native Files did not open the exact created folder", app: app) {
            remainingEditors.count == 0 && self.isRecoveryFolder(ownedFolder, navigation: navigation.element)
        }
        capture(app, "Native folder exact destination before host empty-folder verification")
        // Never tap Save: the host must independently prove this native-created
        // leaf empty after the fixture stops, before the separate seed phase.
        app.terminate()
        try await wait("Native-folder fixture did not stop before host verification", app: app) {
            app.state == .notRunning
        }
    }

    func testNativeSaveSeedsBothSyntheticOriginals() async throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1",
                          "Opt in only for the owned native-Save fixture diagnostic")
        let token = environment["TRIPDOCKET_NATIVE_SEED_TOKEN"] ?? ""
        guard UUID(uuidString: token)?.uuidString.lowercased() == token,
              environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token else {
            throw BatchTestFailure(message: "Native seed requires its exact canonical owned folder token")
        }
        executionTimeAllowance = 180
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--ui-testing-native-batch-seed",
                                                   "--ui-testing-native-batch-token", token]
        app.launch()
        for filename in filenames {
            let seed = app.buttons["nativeSeed." + filename]
            try await wait("Native seed source is unavailable", app: app) { seed.exists && seed.isHittable }
            seed.tap()
            let saveToFiles = app.descendants(matching: .any).matching(NSPredicate(
                format: "(elementType == %@ AND label == %@) OR (elementType == %@ AND identifier == %@ AND label == %@)",
                NSNumber(value: XCUIElement.ElementType.button.rawValue), "Save to Files",
                NSNumber(value: XCUIElement.ElementType.cell.rawValue), "actionGroupCell", "Save to Files"
            ))
            try await waitForStableShareAction(saveToFiles, app: app)
            saveToFiles.element.tap()
            let picker = try await openLocalFilesFolder(folder, app: app)
            let navigation = try await recoveryFilesNavigation(folder, picker: picker, app: app)
            let save = navigation.buttons["Save"]
            try await wait("Native seed destination Save is unavailable", app: app) {
                save.exists && save.isEnabled && save.isHittable
            }
            capture(app, "Native seed exact destination before Save — " + filename)
            save.tap()
            try await wait("Native seed Save did not finish", app: app) {
                !navigation.exists && seed.exists && seed.isHittable
            }
            capture(app, "Native seed returned after Save — " + filename)
        }
        // Host compares both exact destination bytes; completion alone is not proof.
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
        // The first share on a fresh simulator starts a remote service. Its
        // container can be present while it has no actions yet; allow that one
        // presentation to initialize without repeating Export or a share tap.
        try await waitForStableShareAction(saveToFiles, app: app)
        saveToFiles.element.tap()
    }

    private func waitForStableShareAction(_ actions: XCUIElementQuery, app: XCUIApplication) async throws {
        let header = app.navigationBars.matching(identifier: "UIActivityContentView")
        var previousFrames: [CGRect]?
        var previousIdentity: String?
        var stableObservations = 0
        // Remote share actions become hittable before the presentation finishes.
        // Require the same action and native header geometry on successive polls;
        // any unavailable, invalid, or changing state restarts convergence.
        try await wait("Share sheet action did not stabilize", app: app, timeout: .seconds(40)) {
            var frames: [CGRect]?
            var identity: String?
            if actions.count == 1, header.count == 1 {
                let action = actions.element
                if action.isEnabled, action.isHittable {
                    let bounds = app.frame
                    let candidate = [action.frame, header.element.frame]
                    if candidate.allSatisfy({ frame in
                        frame.origin.x.isFinite && frame.origin.y.isFinite && frame.width.isFinite && frame.height.isFinite
                            && frame.width > 0 && frame.height > 0 && bounds.contains(frame)
                    }) {
                        frames = candidate
                        identity = "\(action.elementType.rawValue):\(action.identifier):\(action.label)"
                    }
                }
            }
            if let frames, let identity {
                let unchanged = previousFrames.map { old in
                    zip(old, frames).allSatisfy { a, b in
                        abs(a.minX - b.minX) <= 0.5 && abs(a.minY - b.minY) <= 0.5
                            && abs(a.width - b.width) <= 0.5 && abs(a.height - b.height) <= 0.5
                    }
                } ?? false
                stableObservations = unchanged && identity == previousIdentity ? stableObservations + 1 : 1
                previousFrames = frames
                previousIdentity = identity
                return stableObservations >= 3
            }
            previousFrames = nil
            previousIdentity = nil
            stableObservations = 0
            return false
        }
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
        let selectionStarted = ContinuousClock.now
        files.element(boundBy: 0).tap()
        let replace = app.buttons["Replace library from backup"]
        // A single-file importer normally completes on selection. Some native
        // versions require Open; only accept that control within this picker.
        let open = picker.buttons.matching(NSPredicate(format: "label == %@", "Open")).firstMatch
        do {
            try await wait("File selection neither completed nor exposed Open", app: app) {
                replace.isHittable || (picker.exists && open.isHittable && open.isEnabled)
            }
        } catch let error as BatchTestFailure {
            // The unchanged wait already captured the failing screen and tree.
            captureRecoverySelectionFailure(app: app, picker: picker, navigation: fileNavigation,
                                            folder: recoveryFolder, files: files, replace: replace,
                                            open: open, started: selectionStarted)
            throw error
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
        let rendered = try await waitForRenderedSyntheticOriginal(app)
        let renderedScreenshot = XCTAttachment(screenshot: rendered.screenshot)
        renderedScreenshot.name = "Recovery restored original — accepted preview pixels"
        renderedScreenshot.lifetime = .keepAlways
        add(renderedScreenshot)
        let recognizedText = XCTAttachment(string: rendered.lines.joined(separator: "\n"))
        recognizedText.name = "Recovery restored original — recognized preview text"
        recognizedText.lifetime = .keepAlways
        add(recognizedText)
        capture(app, "Recovery restored original — inspect synthetic PDF pixels")
        let done = app.navigationBars["Original document"].buttons["Done"]
        try check(done.isHittable, app: app, "Restored original Done is not reachable")
        done.tap()
        // The host now compares the active catalog and original bytes against
        // its pre-reset snapshot. UI counts and a preview container are not it.
    }

    private struct RenderedOriginalEvidence {
        let screenshot: XCUIScreenshot
        let lines: [String]
    }

    private func waitForRenderedSyntheticOriginal(_ app: XCUIApplication) async throws -> RenderedOriginalEvidence {
        let deadline = ContinuousClock.now.advanced(by: .seconds(40))
        var lastObservation = "No preview observation completed"
        while ContinuousClock.now < deadline {
            if let rendered = renderedSyntheticOriginal(app, before: deadline, observe: { message in
                var bytes = Array(message.utf8.prefix(2048))
                while !bytes.isEmpty, String(bytes: bytes, encoding: .utf8) == nil { bytes.removeLast() }
                lastObservation = String(decoding: bytes, as: UTF8.self)
            }) { return rendered }
            if ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(100)) }
        }
        let error = failure("Restored original PDF content did not render", app: app)
        let observation = XCTAttachment(string: lastObservation)
        observation.name = "Recovery original preview — last observation"
        observation.lifetime = .keepAlways
        add(observation)
        throw error
    }

    private func renderedSyntheticOriginal(_ app: XCUIApplication,
                                           before deadline: ContinuousClock.Instant,
                                           observe: (String) -> Void = { _ in }) -> RenderedOriginalEvidence? {
        func read<T>(_ value: @autoclosure () -> T) -> T? {
            guard ContinuousClock.now < deadline else { return nil }
            return value()
        }
        observe("No unique visible preview within the observation deadline")
        guard ContinuousClock.now < deadline else { return nil }
        let previews = app.otherElements.matching(identifier: "QLPreviewControllerView")
        guard read(previews.count) == 1 else { return nil }
        let preview = previews.element
        guard read(preview.exists) == true, read(preview.isHittable) == true,
              let frame = read(preview.frame),
              [frame.minX, frame.minY, frame.width, frame.height].allSatisfy(\.isFinite),
              !frame.isEmpty, !frame.isNull, !frame.isInfinite,
              let appFrame = read(app.frame), appFrame.contains(frame) else { return nil }
        // Some Quick Look versions render the PDF without exposing its text to
        // accessibility. Read only fresh pixels from the visible preview itself.
        guard let screenshot = read(preview.screenshot()) else { return nil }
        observe("Preview screenshot unavailable or capture exceeded the observation deadline")
        guard let image = screenshot.image.cgImage, ContinuousClock.now < deadline else { return nil }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["en-US"]
        request.usesLanguageCorrection = false
        request.revision = VNRecognizeTextRequestRevision3
        do { try VNImageRequestHandler(cgImage: image, options: [:]).perform([request]) }
        catch {
            let failure = error as NSError
            observe("Vision error: domain=\(failure.domain), code=\(failure.code)")
            return nil
        }
        // A synchronous Vision call can overrun; late success is not accepted.
        observe("Vision completed after the observation deadline")
        guard ContinuousClock.now < deadline else { return nil }
        func normalized(_ text: String) -> String {
            let dashes = "‐‑‒–—−"
            let plain = String(text.map { dashes.contains($0) ? "-" : $0 })
            return plain.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        }
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
            .flatMap { $0.components(separatedBy: .newlines) }.map(normalized)
        observe("Recognized preview lines:\n" + lines.joined(separator: "\n"))
        let markers = ["SYNTHETIC DEMO - NOT VALID FOR TRAVEL", "Sample reservation ABC-000"]
        guard markers.allSatisfy({ marker in lines.filter { $0 == marker }.count == 1 }),
              ContinuousClock.now < deadline else { return nil }
        return RenderedOriginalEvidence(screenshot: screenshot, lines: lines)
    }

    private func reachRecoveryLocalRoot(_ localTitle: String, navigation: XCUIElementQuery,
                                        location: XCUIElementQuery, browse: XCUIElementQuery,
                                        app: XCUIApplication) async throws {
        let atRoot = { self.isRecoveryFolder(localTitle, navigation: navigation.element) }
        let enabledLocation = location.matching(NSPredicate(format: "enabled == true"))
        let enabledBrowse = browse.matching(NSPredicate(format: "enabled == true"))
        // Files may remove a route while automatically reaching its remembered
        // root. Query eligibility without reading attributes of a vanished row;
        // isHittable returns false for a missing element. Keep raw uniqueness so
        // a disabled duplicate cannot authorize an otherwise ambiguous route.
        let locationReady = {
            location.count == 1 && enabledLocation.count == 1 && enabledLocation.element.isHittable
        }
        let browseReady = {
            browse.count == 1 && enabledBrowse.count == 1 && enabledBrowse.element.isHittable
        }
        if !atRoot() {
            // The picker can reach its remembered local root while appearing.
            // Reconsider that verified destination during the same bounded wait.
            try await wait("Files preparation has no supported local route", app: app) {
                atRoot() || locationReady() || browseReady()
            }
            if !atRoot() && !locationReady() {
                try check(browseReady() || atRoot(), app: app, "Files preparation Browse action changed")
                if !atRoot() { enabledBrowse.element.tap() }
            }
            if !atRoot() {
                try await wait("Files preparation local location is unavailable", app: app) {
                    atRoot() || locationReady()
                }
                if !atRoot() {
                    try check(locationReady() || atRoot(), app: app, "Files preparation local location changed")
                    if !atRoot() { enabledLocation.element.tap() }
                }
            }
        }
        try await wait("Files preparation did not reach the local root", app: app) { atRoot() }
    }

    private func isRecoveryFolder(_ folder: String, navigation: XCUIElement) -> Bool {
        // This is a navigation-title marker, not the folder's row in its parent.
        // Files can expose its heading as an Actions Menu button. Match the
        // complete name and role so a back button or similarly named folder
        // cannot authorize a write/selection in the wrong destination.
        let titles = navigation.descendants(matching: .any).matching(NSPredicate(
            format: "(elementType == %@ AND label == %@) OR (elementType == %@ AND label == %@)",
            NSNumber(value: XCUIElement.ElementType.staticText.rawValue), folder,
            NSNumber(value: XCUIElement.ElementType.button.rawValue), folder + ", Actions Menu"
        ))
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
        executionTimeAllowance = phase == "prepare" ? 180 : 300
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
            let row = recoveryCountTarget(rows, typed: app.otherElements.matching(identifier: identifier))
            try await reveal(row, app: app, navigation: "Settings")
            try await wait("Incorrect or ambiguous Settings count for \(label); expected \(count)", app: app) {
                self.recoveryCountMatches(rows, row: row, identifier: identifier, label: label, count: count)
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
        let navigations = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let navigation = navigations.element
        try await wait("Files did not present its navigation", app: app) {
            navigations.count == 1 && navigation.exists
        }
        let pickers = app.otherElements.matching(identifier: "Browse View (Picker)")
        let picker = pickers.element
        let recents = app.otherElements.matching(identifier:
            "DOC.browsingRoot Source: com.apple.DocumentManager.RecentDocuments, Title: Recents")
        let tabs = app.tabBars.matching(identifier: "DOC.browsingModeTabBar")
        let browseActions = tabs.element.buttons.matching(NSPredicate(format: "label == %@", "Browse"))
        let browse = browseActions.element
        let browseReady = {
            tabs.count == 1 && browseActions.count == 1 && browse.isEnabled && browse.isHittable
        }
        let browserReady = { navigations.count == 1 && pickers.count == 1 && picker.exists }
        let recentsReady = {
            navigations.count == 1 && pickers.count == 0 && recents.count == 1 && recents.element.exists
                && self.isRecoveryFolder("Recents", navigation: navigation) && browseReady()
        }
        // A fresh importer can open Recents without the browser root used by
        // Save to Files. Leave only that positively identified
        // native screen before requiring the local-folder browser.
        try await wait("Files did not show its browser or supported Recents screen", app: app) {
            browserReady() || recentsReady()
        }
        let openedFromRecents = !browserReady()
        if openedFromRecents {
            try check(recentsReady(), app: app, "Native Files Recents route changed")
            browse.tap()
        }
        try await wait("The real Files picker root is missing", app: app) { browserReady() }
        let atDestination = {
            navigations.count == 1 && pickers.count == 1 && picker.exists
                && self.isRecoveryFolder(folder, navigation: navigation)
        }
        let directory = picker.cells.matching(identifier: folder + ", Folder").firstMatch
        // The captured native tab bar is a sibling of Browse View (Picker),
        // not its descendant. Its controls can appear after the root/navigation.
        let location = app.cells.matching(NSPredicate(
            format: "identifier == %@ OR identifier == %@", "DOC.sidebar.item.On My iPhone", "DOC.sidebar.item.On My iPad"
        )).firstMatch
        try await wait("Native Files navigation did not render its local browsing controls", app: app) {
            navigation.exists && picker.exists
                && (atDestination() || (directory.exists && directory.isHittable)
                    || (location.exists && location.isHittable)
                    || (!openedFromRecents && browseReady()))
        }
        // Files remembers its last directory across presentations. The exact
        // reachable heading is sufficient; do not look for a child with the
        // same name or navigate away from an already selected destination.
        if atDestination() { return picker }
        if !(directory.exists && directory.isHittable) {
            if !(location.exists && location.isHittable) {
                try check(!openedFromRecents && browseReady(), app: app, "Native Files Browse is unavailable")
                browse.tap()
            }
            // Browse can restore On My iPhone directly instead of showing
            // the locations sidebar. Wait for either observed destination.
            try await wait("Files did not show the exact fixture folder or its local location", app: app) {
                atDestination() || (directory.exists && directory.isHittable) || (location.exists && location.isHittable)
            }
            if atDestination() { return picker }
            if !(directory.exists && directory.isHittable) { location.tap() }
        }
        try await wait("The named synthetic Files folder is missing", app: app) {
            atDestination() || (directory.exists && directory.isHittable)
        }
        if !atDestination() { directory.tap() }
        try await wait("Files did not reach the exact synthetic folder", app: app) { atDestination() }
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
        capture(app, "Two synthetic originals selected in real Files", batchDiagnostic: true)
        open.tap()
        try await requireFilesDismissal(app, navigation: navigation, openedAt: .now)
    }

    private func requireFilesDismissal(_ app: XCUIApplication, navigation: XCUIElement,
                                      openedAt: ContinuousClock.Instant) async throws {
        do {
            try await wait("Files remained after opening the selection", app: app) { !navigation.exists }
        } catch let originalFailure as BatchTestFailure {
            // Diagnostic branch only: the original 15-second criterion already
            // failed and captured its PNG/AX. Observe once, with no further action.
            // The 30-second request cannot cap an in-flight XCTest RPC; the
            // unchanged 600/1200/2400-second case/driver/outer limits still apply.
            let observationStarted = ContinuousClock.now
            let disappeared = navigation.waitForNonExistence(timeout: 30)
            let observationFinished = ContinuousClock.now
            let timing = XCTAttachment(string: """
                originalDismissalCriterion=failed
                requestedObservationSeconds=30
                observationStartedSinceOpenReturned=\(openedAt.duration(to: observationStarted))
                observationFinishedSinceOpenReturned=\(openedAt.duration(to: observationFinished))
                observedElapsed=\(observationStarted.duration(to: observationFinished))
                navigationDisappeared=\(disappeared)
                acceptance=failed
                """)
            timing.name = "Files passive late observation — original failure retained"
            timing.lifetime = .keepAlways
            add(timing)
            capture(app, "Files after passive late observation — original failure retained", batchDiagnostic: true)
            // Neither a late disappearance nor unavailable diagnostic state
            // converts this run into a pass. Cancellation is not intercepted.
            throw originalFailure
        }
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
            let appFrame = app.frame
            let navigationFrame = bar.frame
            var viewport = appFrame.intersection(CGRect(x: navigationFrame.minX, y: navigationFrame.maxY,
                width: navigationFrame.width, height: max(0, appFrame.maxY - navigationFrame.maxY))).insetBy(dx: 6, dy: 8)
            for obstruction in app.tabBars.allElementsBoundByIndex + app.keyboards.allElementsBoundByIndex
                where obstruction.exists && obstruction.isHittable {
                let obstructionFrame = obstruction.frame
                if obstructionFrame.minY > viewport.minY {
                    viewport.size.height = max(0, min(viewport.maxY, obstructionFrame.minY - 8) - viewport.minY)
                }
            }
            let targetExists = element.exists
            let frame = targetExists ? element.frame : .null
            if targetExists && element.isHittable && !frame.isEmpty && viewport.contains(frame) { return }
            let candidates = app.collectionViews.allElementsBoundByIndex + app.scrollViews.allElementsBoundByIndex
            let container = revealContainer(candidates, navigationFrame: navigationFrame, viewport: viewport)
            guard let container else { throw failure("No active scroll container for \(navigation)", app: app) }
            let containerFrame = container.frame
            viewport = viewport.intersection(containerFrame).insetBy(dx: 8, dy: 8)
            try check(viewport.height > 80, app: app, "No safe scroll viewport for \(navigation)")
            let upwards = frame.isNull || frame.midY > viewport.midY
            let distance = min(140, viewport.height * 0.45)
            let start = container.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: viewport.midX - containerFrame.minX, dy: viewport.midY - containerFrame.minY))
            start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: upwards ? -distance : distance)),
                        withVelocity: .slow, thenHoldForDuration: 0.2)
            try await Task.sleep(for: .milliseconds(100))
        }
        throw failure("Required control did not become fully reachable in \(navigation): \(element.identifier)", app: app)
    }

    private func revealContainer(_ candidates: [XCUIElement], navigationFrame: CGRect,
                                 viewport: CGRect) -> XCUIElement? {
        // Keep the directly hittable path and its existing selection order.
        if let direct = candidates.reversed().first(where: {
            $0.exists && $0.isHittable && $0.frame.width <= navigationFrame.width + 32
                && $0.frame.intersection(viewport).height > 100
        }) { return direct }

        func finite(_ frame: CGRect) -> Bool {
            !frame.isNull && !frame.isInfinite && !frame.isEmpty
                && frame.origin.x.isFinite && frame.origin.y.isFinite
                && frame.width.isFinite && frame.height.isFinite
        }
        guard finite(navigationFrame), finite(viewport) else { return nil }
        // A presented native List and its covered parent can both retain
        // aligned geometry while their wrappers report non-hittable. Require
        // one container with a live, visible descendant before using its
        // geometry for the existing bounded drag.
        let wrappers = candidates.compactMap { candidate -> (XCUIElement, CGRect)? in
            guard candidate.exists else { return nil }
            let frame = candidate.frame
            guard finite(frame), frame.width <= navigationFrame.width + 32,
                  abs(frame.midX - navigationFrame.midX) < max(32, navigationFrame.width / 4),
                  frame.intersection(viewport).height > 100 else { return nil }
            return (candidate, frame)
        }
        let active = wrappers.filter { wrapper, frame in
            let descendants = wrapper.buttons.allElementsBoundByIndex + wrapper.staticTexts.allElementsBoundByIndex
            return descendants.contains(where: { child in
                guard child.exists, child.isHittable else { return false }
                let childFrame = child.frame
                guard finite(childFrame) else { return false }
                let visible = childFrame.intersection(frame).intersection(viewport)
                return !visible.isNull && visible.width >= min(44, childFrame.width)
                    && visible.height >= min(44, childFrame.height)
            })
        }
        guard active.count == 1 else { return nil }
        return active[0].0
    }

    private func recoveryCountTarget(_ rows: XCUIElementQuery, typed: XCUIElementQuery) -> XCUIElement {
        // Settings currently exposes count rows as Other. Keep the generic
        // query for another representation and for the global uniqueness gate.
        typed.count == 1 ? typed.element(boundBy: 0) : rows.firstMatch
    }

    private func recoveryCountMatches(_ rows: XCUIElementQuery, row: XCUIElement,
                                      identifier: String, label: String, count: Int) -> Bool {
        // A typed handle must not hide a duplicate identifier on another type.
        // Read label and value together from one current snapshot, never from
        // the preceding reveal observation or a previous wait iteration.
        guard rows.count == 1, row.isHittable, let snapshot = try? row.snapshot() else { return false }
        return snapshot.identifier == identifier && snapshot.label == label
            && (snapshot.value as? String) == String(count)
    }

    private func wait(_ message: String, app: XCUIApplication, springboard: XCUIApplication? = nil,
                      timeout: Duration = .seconds(15),
                      condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: timeout)
        repeat {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(100))
        } while ContinuousClock.now < deadline
        capture(app, message, springboard: springboard, batchDiagnostic: true)
        throw BatchTestFailure(message: message)
    }

    private func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw failure(message, app: app) }
    }

    private func failure(_ message: String, app: XCUIApplication) -> BatchTestFailure {
        capture(app, message, batchDiagnostic: true)
        return BatchTestFailure(message: message)
    }

    private func captureRecoverySelectionFailure(app: XCUIApplication, picker: XCUIElement,
                                                  navigation: XCUIElement, folder: String,
                                                  files: XCUIElementQuery, replace: XCUIElement,
                                                  open: XCUIElement, started: ContinuousClock.Instant) {
        let diagnosticStarted = ContinuousClock.now
        let deadline = diagnosticStarted.advanced(by: .seconds(8))
        var lines = ["elapsedSinceTap=\(started.duration(to: diagnosticStarted))"]
        // Schedule no further reads after this budget. An in-flight synchronous
        // XCTest query retains its own timeout; there is no polling or retry.
        @discardableResult
        func read<T>(_ name: String, _ value: @autoclosure () -> T) -> T? {
            guard ContinuousClock.now < deadline else {
                lines.append("\(name)=not sampled (diagnostic budget exhausted)")
                return nil
            }
            let result = value()
            lines.append("\(name)=\(result)")
            return result
        }
        func element(_ name: String, _ target: XCUIElement, includeSelection: Bool = false) {
            guard read("\(name).exists", target.exists) == true else { return }
            read("\(name).enabled", target.isEnabled)
            read("\(name).hittable", target.isHittable)
            if includeSelection {
                read("\(name).selected", target.isSelected)
                read("\(name).frame", target.frame)
            }
        }
        read("app.state.rawValue", app.state.rawValue)
        read("picker.exists", picker.exists)
        let navigationExists = read("navigation.exists", navigation.exists)
        var exactDestination: Bool?
        if navigationExists == false {
            exactDestination = false
        } else if navigationExists == true {
            let titles = navigation.descendants(matching: .any).matching(NSPredicate(
                format: "(elementType == %@ AND label == %@) OR (elementType == %@ AND label == %@)",
                NSNumber(value: XCUIElement.ElementType.staticText.rawValue), folder,
                NSNumber(value: XCUIElement.ElementType.button.rawValue), folder + ", Actions Menu"
            ))
            if let count = read("destinationTitles.count", titles.count) {
                exactDestination = count == 1
                    ? read("destinationTitle.hittable", titles.element(boundBy: 0).isHittable) : false
            }
        }
        lines.append("exactDestination=\(exactDestination.map(String.init) ?? "not sampled (diagnostic budget exhausted)")")
        if read("files.count", files.count) == 1 {
            element("file", files.element(boundBy: 0), includeSelection: true)
        }
        element("replace", replace)
        element("open", open)
        lines.append("diagnosticElapsed=\(diagnosticStarted.duration(to: .now))")
        let attachment = XCTAttachment(string: lines.joined(separator: "\n"))
        attachment.name = "Recovery file selection — failure state"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func capture(_ app: XCUIApplication, _ name: String, springboard: XCUIApplication? = nil,
                         batchDiagnostic: Bool = false) {
        if batchDiagnostic && app.launchArguments.contains("--ui-testing-batch-diagnostics") {
            var value = "unavailable"
            if let snapshot = try? app.snapshot() { value = batchImporterDiagnosticValue(snapshot) }
            let diagnostic = XCTAttachment(string: value)
            diagnostic.name = name + " — batch importer state"
            diagnostic.lifetime = .keepAlways
            add(diagnostic)
        }
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let tree = XCTAttachment(string: app.debugDescription + (springboard.map { "\nSPRINGBOARD\n" + $0.debugDescription } ?? ""))
        tree.name = name + " — accessibility hierarchy"
        tree.lifetime = .keepAlways
        add(tree)
    }

    private func batchImporterDiagnosticValue(_ root: any XCUIElementSnapshot) -> String {
        // One immutable snapshot avoids a count-to-live-value race during dismissal.
        // Traverse only a bounded number/depth of nodes and reject duplicates.
        var pending: [(any XCUIElementSnapshot, Int)] = [(root, 0)]
        var visited = 0
        var found: String?
        while let (node, depth) = pending.popLast() {
            visited += 1
            guard visited <= 1_024, depth <= 64 else { return "unavailable" }
            if node.elementType == .collectionView && node.identifier == "batch.importer" {
                guard found == nil, let value = node.value as? String,
                      value.utf8.count <= 128,
                      value.range(of: #"\Abatch-importer showsFiles=[01] callbackCount=(?:0|[1-9][0-9]?) resultKind=(?:none|success|failure) urlCount=(?:[0-9]|10|11) draftPhase=(?:choosing|preparing|reviewing|committing)\z"#,
                                  options: .regularExpression) != nil else { return "unavailable" }
                found = value
            }
            guard node.children.count <= 1_024 - visited - pending.count else { return "unavailable" }
            pending.append(contentsOf: node.children.map { ($0, depth + 1) })
        }
        return found ?? "unavailable"
    }

    private struct BatchTestFailure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
