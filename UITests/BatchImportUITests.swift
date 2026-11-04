import Darwin
import notify
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
    @MainActor
    private static func nativeFolderRenameFrame(
        in snapshot: XCUIElementSnapshot, applicationSnapshot: XCUIElementSnapshot, localTitle: String,
        diagnostic: ((String) -> Void)? = nil
    ) -> CGRect? {
        @MainActor func nodes(_ root: XCUIElementSnapshot) -> [XCUIElementSnapshot]? {
            var result: [XCUIElementSnapshot] = []
            var pending: [(XCUIElementSnapshot, Int)] = [(root, 0)]
            while let (node, depth) = pending.popLast() {
                guard depth <= 96, result.count < 4_096 else { diagnostic?("tree-depth-or-count"); return nil }
                result.append(node)
                let children = node.children
                guard children.count <= 4_096 - result.count - pending.count else { diagnostic?("tree-children-count"); return nil }
                pending.append(contentsOf: children.reversed().map { ($0, depth + 1) })
            }
            return result
        }
        guard snapshot.elementType == .other, snapshot.identifier == "Browse View (Picker)",
              applicationSnapshot.elementType == .application,
              let all = nodes(snapshot), let environment = nodes(applicationSnapshot),
              !all.contains(where: { $0.identifier == "DOC.inlineRenameField" || $0.elementType == .keyboard }),
              !environment.contains(where: { $0.identifier == "DOC.inlineRenameField" || $0.elementType == .keyboard }) else { diagnostic?("snapshot-scope-or-editor-or-keyboard"); return nil }
        let pickers = all.filter { $0.elementType == .other && $0.identifier == "Browse View (Picker)" }
        let rootID = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " + localTitle
        let roots = all.filter { $0.elementType == .other && $0.identifier == rootID }
        let grids = all.filter { $0.elementType == .collectionView && $0.identifier == "File View" }
        let navigations = all.filter { $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }
        guard pickers.count == 1, roots.count == 1, grids.count == 1, navigations.count == 1,
              let pickerNodes = nodes(pickers[0]), let rootNodes = nodes(roots[0]),
              pickerNodes.filter({ $0.elementType == .other && $0.identifier == rootID }).count == 1,
              rootNodes.filter({ $0.elementType == .collectionView && $0.identifier == "File View" }).count == 1,
              rootNodes.filter({ $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }).count == 1,
              let gridNodes = nodes(grids[0]) else { diagnostic?("structure-counts-or-ancestry"); return nil }
        let cells = gridNodes.filter { $0.elementType == .cell }
        guard cells.count == 1, cells[0].identifier == "untitled folder, Folder",
              cells[0].label == "untitled folder, 0 items", cells[0].isEnabled else { diagnostic?("cell-count-or-name-or-enabled"); return nil }
        let frame = cells[0].frame
        let windows = applicationSnapshot.children.filter { $0.elementType == .window }
        guard [frame.minX, frame.minY, frame.width, frame.height].allSatisfy({ $0.isFinite }),
              !frame.isEmpty, grids[0].frame.contains(frame),
              windows.contains(where: { $0.frame.contains(frame) }) else { diagnostic?("window-or-containment-or-frame"); return nil }
        return frame
    }

    // While Files edits a folder name, its visible title can intentionally have
    // no hit point. Verify the editing hierarchy and geometry separately; all
    // navigation and action checks retain their normal hittability requirement.
    @MainActor
    private static func nativeFolderEditorFrame(
        in snapshot: XCUIElementSnapshot, applicationSnapshot: XCUIElementSnapshot,
        expectedName: String, localTitle: String,
        keyboardIntroduction: Bool = false,
        diagnostic: ((String) -> Void)? = nil
    ) -> CGRect? {
        @MainActor func nodes(_ root: XCUIElementSnapshot) -> [XCUIElementSnapshot]? {
            var result: [XCUIElementSnapshot] = []
            var pending: [(XCUIElementSnapshot, Int)] = [(root, 0)]
            while let (node, depth) = pending.popLast() {
                guard depth <= 96, result.count < 4_096 else { diagnostic?("tree-depth-or-count"); return nil }
                result.append(node)
                let children = node.children
                guard children.count <= 4_096 - result.count - pending.count else { diagnostic?("tree-children-count"); return nil }
                pending.append(contentsOf: children.reversed().map { ($0, depth + 1) })
            }
            return result
        }
        func visibleFrame(_ frame: CGRect) -> Bool {
            [frame.minX, frame.minY, frame.width, frame.height].allSatisfy { $0.isFinite }
                && frame.width > 0 && frame.height > 0
        }
        guard snapshot.elementType == .other, snapshot.identifier == "Browse View (Picker)",
              applicationSnapshot.elementType == .application,
              let all = nodes(snapshot), let environment = nodes(applicationSnapshot), !expectedName.isEmpty,
              !all.contains(where: { $0.identifier == "UIContinuousPathIntroductionView" }),
              environment.filter({ $0.elementType == .other && $0.identifier == "UIContinuousPathIntroductionView" }).count
                == (keyboardIntroduction ? 1 : 0),
              !environment.contains(where: { $0.elementType != .other && $0.identifier == "UIContinuousPathIntroductionView" }) else { diagnostic?("snapshot-scope-or-empty-name-or-keyboard-introduction"); return nil }
        let rootID = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " + localTitle
        let pickers = all.filter { $0.elementType == .other && $0.identifier == "Browse View (Picker)" }
        let roots = all.filter { $0.elementType == .other && $0.identifier == rootID }
        let grids = all.filter { $0.elementType == .collectionView && $0.identifier == "File View" }
        let navigations = all.filter { $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }
        let editors = all.filter { $0.elementType == .textView && $0.identifier == "DOC.inlineRenameField" }
        let keyboards = environment.filter { $0.elementType == .keyboard }
        let windows = applicationSnapshot.children.filter { $0.elementType == .window }
        guard pickers.count == 1, roots.count == 1, grids.count == 1, navigations.count == 1,
              editors.count == 1, keyboards.count == 1, !windows.isEmpty,
              let pickerNodes = nodes(pickers[0]), let rootNodes = nodes(roots[0]),
              pickerNodes.filter({ $0.elementType == .other && $0.identifier == rootID }).count == 1,
              rootNodes.filter({ $0.elementType == .collectionView && $0.identifier == "File View" }).count == 1,
              rootNodes.filter({ $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }).count == 1,
              let gridNodes = nodes(grids[0]), let navigationNodes = nodes(navigations[0]) else { diagnostic?("structure-counts-or-ancestry"); return nil }
        let cells = gridNodes.filter { $0.elementType == .cell }
        guard cells.count == 1, let cellNodes = nodes(cells[0]),
              cellNodes.filter({ $0.elementType == .textView && $0.identifier == "DOC.inlineRenameField" }).count == 1,
              editors[0].value as? String == expectedName, editors[0].isEnabled else { diagnostic?("cell-ancestry-or-editor-value"); return nil }
        let titles = navigationNodes.filter {
            ($0.elementType == .staticText && $0.label == localTitle)
                || ($0.elementType == .button && $0.label == localTitle + ", Actions Menu")
        }
        guard titles.count == 1,
              [grids[0].frame, navigations[0].frame, cells[0].frame, editors[0].frame,
               titles[0].frame, keyboards[0].frame].allSatisfy(visibleFrame),
              windows.allSatisfy({ visibleFrame($0.frame) }) else { diagnostic?("title-or-nonfinite-frame"); return nil }
        let window = windows.dropFirst().reduce(windows[0].frame) { $0.intersection($1.frame) }
        guard visibleFrame(window), window.contains(titles[0].frame), window.contains(editors[0].frame),
              window.contains(cells[0].frame), navigations[0].frame.contains(titles[0].frame),
              grids[0].frame.contains(editors[0].frame), grids[0].frame.contains(cells[0].frame),
              !keyboards[0].frame.intersects(editors[0].frame),
              !keyboards[0].frame.intersects(titles[0].frame) else { diagnostic?("window-or-containment-or-keyboard"); return nil }
        // The real inline editor extends beyond the folder cell's horizontal
        // bounds. Ownership is its ancestry; visible bounds are grid/window.
        return editors[0].frame
    }

    @MainActor
    private static func nativeFolderInitialState(
        in snapshot: XCUIElementSnapshot, applicationSnapshot: XCUIElementSnapshot,
        localTitle: String, diagnostic: ((String) -> Void)? = nil
    ) -> (ready: Bool, renameFrame: CGRect?) {
        // All alternatives must describe the same retained observations. Files
        // can enter inline editing while an accessibility query is in flight.
        for introduction in [false, true] {
            var reason: String?
            if nativeFolderEditorFrame(
                in: snapshot, applicationSnapshot: applicationSnapshot,
                expectedName: "untitled folder", localTitle: localTitle,
                keyboardIntroduction: introduction,
                diagnostic: { if reason == nil { reason = $0 } }
            ) != nil {
                return (true, nil)
            }
            diagnostic?("editor-\(introduction ? "with" : "without")-introduction: " + (reason ?? "unspecified"))
        }
        var reason: String?
        let frame = nativeFolderRenameFrame(
            in: snapshot, applicationSnapshot: applicationSnapshot, localTitle: localTitle,
            diagnostic: { if reason == nil { reason = $0 } }
        )
        if frame == nil { diagnostic?("rename: " + (reason ?? "unspecified")) }
        return (frame != nil, frame)
    }

    // Evidence storage only; none of these fields participate in readiness.
    // A new attempt clears partial inputs without erasing the last bound pair.
    private struct NativeFolderInitialObservation {
        var attempt = 0
        var stage = "not-sampled"
        var picker: XCUIElementSnapshot?
        var application: XCUIElementSnapshot?
        var lastBound: (attempt: Int, picker: XCUIElementSnapshot, application: XCUIElementSnapshot)?
        var acquisitionError: String?
        var errorTruncated = false
        var rejections: [String] = []

        mutating func begin() {
            attempt += 1
            stage = "started"
            picker = nil
            application = nil
            acquisitionError = nil
            errorTruncated = false
            rejections = []
        }

        mutating func failed(_ error: Error) {
            let description = String(describing: error)
            acquisitionError = String(description.prefix(512))
            errorTruncated = acquisitionError != description
        }

        func metadata() -> Data {
            let payload: [String: Any] = [
                "version": 1, "attempt": attempt, "acquisitionStage": String(stage.prefix(128)),
                "currentPickerPresent": picker != nil, "currentApplicationPresent": application != nil,
                "currentPairBound": lastBound?.attempt == attempt,
                "lastBoundAttempt": lastBound.map { $0.attempt as Any } ?? NSNull(),
                "acquisitionError": acquisitionError.map { $0 as Any } ?? NSNull(),
                "errorTruncated": errorTruncated,
                "alternativeFirstRejections": Array(rejections.prefix(3)).map { String($0.prefix(160)) },
                "snapshotScope": "Sequential existing picker/application observations; not atomic. Prior bound pair is not the current failed acquisition.",
                "limits": ["errorCharacters": 512, "stageCharacters": 128, "rejections": 3,
                           "rejectionCharacters": 160, "bytes": 16_384]
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
                  data.count <= 16_384 else {
                return Data(#"{"version":1,"truncation":"metadata-serialization-limit"}"#.utf8)
            }
            return data
        }
    }

    // Evidence only. Serialize the supplied immutable snapshot, never a fresh
    // query, and make incomplete trees/strings explicit rather than implying a
    // complete view of the remote Files hierarchy.
    @MainActor
    private static func nativeFolderSnapshotEvidence(
        _ snapshot: XCUIElementSnapshot?, observation: String, expectedName: String,
        localTitle: String, returnedFrame: CGRect?, liveFrame: CGRect?, reason: String?
    ) -> Data {
        func number(_ value: CGFloat) -> Any {
            value.isFinite ? Double(value) as Any : (value.isNaN ? "nan" : (value > 0 ? "+inf" : "-inf"))
        }
        func frame(_ value: CGRect?) -> Any {
            guard let value else { return NSNull() }
            return [number(value.minX), number(value.minY), number(value.width), number(value.height)]
        }
        var stringsTruncated = false
        func string(_ value: String) -> String {
            let prefix = String(value.prefix(128))
            if prefix != value { stringsTruncated = true }
            return prefix
        }
        var rows: [[String: Any]] = []
        var pending: [(XCUIElementSnapshot, Int, Int?)] = snapshot.map { [($0, 0, nil)] } ?? []
        var truncation: String? = nil
        var encodedBytes = 0
        while let (node, depth, parent) = pending.popLast() {
            guard depth <= 96, rows.count < 4_096 else { truncation = "depth-or-count"; break }
            let children = node.children
            let rawValue = node.value
            let row: [String: Any] = [
                "index": rows.count, "parent": parent.map { $0 as Any } ?? NSNull(), "depth": depth,
                "type": node.elementType.rawValue, "identifier": string(node.identifier),
                "label": string(node.label), "enabled": node.isEnabled, "frame": frame(node.frame),
                "valueType": rawValue == nil ? "nil" : (rawValue is String ? "string" : "non-string"),
                "value": (rawValue as? String).map { string($0) as Any } ?? NSNull(),
                "childCount": children.count
            ]
            guard let bytes = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]),
                  encodedBytes + bytes.count + 1 <= 1_040_000 else { truncation = "byte-limit"; break }
            encodedBytes += bytes.count + 1
            let index = rows.count
            rows.append(row)
            guard children.count <= 4_096 - rows.count - pending.count else { truncation = "children-count"; break }
            pending.append(contentsOf: children.reversed().map { ($0, depth + 1, index) })
        }
        let payload: [String: Any] = [
            "version": 1, "observation": string(observation), "expectedName": string(expectedName),
            "localTitle": string(localTitle), "helperReason": reason.map { string($0) as Any } ?? NSNull(),
            "helperReturnedFrame": frame(returnedFrame), "liveComparedFrame": frame(liveFrame),
            "snapshotPresent": snapshot != nil, "treeComplete": snapshot != nil && truncation == nil,
            "truncation": truncation.map { $0 as Any } ?? NSNull(), "stringsTruncated": stringsTruncated,
            "limits": ["nodes": 4_096, "depth": 96, "stringCharacters": 128, "bytes": 1_048_576],
            "nodes": rows
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              data.count <= 1_048_576 else {
            return Data(#"{"version":1,"treeComplete":false,"truncation":"serialization-limit"}"#.utf8)
        }
        return data
    }

    private let productID = "com.4alvit.tripfolio.pro"
    private var folder: String {
        ProcessInfo.processInfo.environment["TRIPDOCKET_BATCH_FOLDER"] ?? "TripDocket-Batch-QA"
    }
    private let filenames = ["synthetic-ticket.pdf", "synthetic-insurance.pdf"]

    func testRealFilesBatchRequiresEveryReviewAndPreservesOriginals() async throws {
        let caseStart = ContinuousClock().now
        let checkpoint = try combinedBatchMode(ProcessInfo.processInfo.environment)
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TRIPDOCKET_BATCH_UI"] == "1",
                          "Opt in with TRIPDOCKET_BATCH_UI=1 on the dedicated, fixture-seeded simulator")
        guard !folder.isEmpty, !folder.contains("/"), !folder.contains("\\") else {
            throw BatchTestFailure(message: "TRIPDOCKET_BATCH_FOLDER must name a single nonempty Files folder")
        }
        let nativeRoot = try nativeRootMode("batch")
        executionTimeAllowance = 600
        continueAfterFailure = false
        if let checkpoint {
            try await awaitBatchCheckpoint(checkpoint, until: caseStart.advanced(by: .seconds(600)))
        }
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
                               "--ui-testing-purchase-diagnostics",
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
        try await selectRealFiles(app, nativeRoot: nativeRoot)
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


    // Batch-only provider initialization. The temporary source UUID is not
    // the later seed UUID; no destination Save or producer marker occurs here.
    func testBatchPrepareFilesProviderDirectly() async throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["TRIPDOCKET_BATCH_PREPARE_UI"] == "1",
                          "Opt in only for the owned direct batch preparation")
        #if DEBUG && targetEnvironment(simulator)
        let debugSimulator = true
        #else
        let debugSimulator = false
        #endif
        let token = try Self.directPreparationToken(environment, debugSimulator: debugSimulator)
        let absentFolder = "TripDocket-Batch-Prepare-" + token
        executionTimeAllowance = 180
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--ui-testing-native-batch-seed",
                                                   "--ui-testing-native-batch-token", token]
        app.launch()
        let source = app.buttons.matching(identifier: "nativeSeed.synthetic-ticket.pdf")
        let failed = app.staticTexts["nativeSeed.failure"]
        try await wait("Direct preparation source is unavailable", app: app) {
            failed.exists || (source.count == 1 && source.element.isEnabled && source.element.isHittable)
        }
        try check(!failed.exists && source.count == 1 && source.element.isEnabled && source.element.isHittable,
                  app: app, "Direct preparation has no unique live native export source")
        capture(app, "Batch preparation — native exporter before opening Files; no Save performed")
        source.element.tap()
        // Cold Files service navigation appeared after the default 15s wait on Intel.
        let picker = try await openNativeFilesRoot(app, initialTimeout: .seconds(30))
        let saved = app.staticTexts.matching(NSPredicate(format: "identifier BEGINSWITH %@", "nativeSeed.saved."))
        try check(isNativeFilesRoot(app) && picker.cells.matching(identifier: absentFolder + ", Folder").count == 0
                  && saved.count == 0 && !failed.exists,
                  app: app, "Direct preparation lost its empty probe or exported a destination")
        capture(app, "Batch preparation — exact local Files root; no Save performed")
        app.terminate()
        try await wait("Direct preparation fixture did not stop before host verification", app: app) {
            app.state == .notRunning
        }
    }

    private static func directPreparationToken(_ environment: [String: String],
                                               debugSimulator: Bool) throws -> String {
        let token = environment["TRIPDOCKET_BATCH_PREPARE_TOKEN"] ?? ""
        let conflicting = ["TRIPDOCKET_RECOVERY_UI", "TRIPDOCKET_RECOVERY_PHASE", "TRIPDOCKET_RECOVERY_FOLDER",
                           "TRIPDOCKET_NATIVE_SEED_UI", "TRIPDOCKET_NATIVE_SEED_TOKEN",
                           "TRIPDOCKET_NATIVE_FOLDER_UI", "TRIPDOCKET_NATIVE_FOLDER_TOKEN",
                           "TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN",
                           "TRIPDOCKET_NATIVE_ROOT_UI", "TRIPDOCKET_NATIVE_ROOT_TOKEN",
                           "TRIPDOCKET_BATCH_UI", "TRIPDOCKET_BATCH_FOLDER",
                           "TRIPDOCKET_COMBINED_BATCH_UI", "TRIPDOCKET_BATCH_CHECKPOINT_SESSION"]
        guard debugSimulator, environment["TRIPDOCKET_BATCH_PREPARE_UI"] == "1",
              UUID(uuidString: token)?.uuidString.lowercased() == token,
              conflicting.allSatisfy({ environment[$0] == nil }) else {
            throw BatchTestFailure(message: "Direct preparation requires its isolated Debug Simulator token")
        }
        return token
    }

    private static func nativeFolderConfiguration(
        _ environment: [String: String], debugSimulator: Bool
    ) throws -> (token: String, sourceToken: String) {
        let token = environment["TRIPDOCKET_NATIVE_FOLDER_TOKEN"] ?? ""
        let sourceToken = environment["TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN"] ?? ""
        let conflicting = ["TRIPDOCKET_RECOVERY_UI", "TRIPDOCKET_RECOVERY_PHASE", "TRIPDOCKET_RECOVERY_FOLDER",
                           "TRIPDOCKET_BATCH_PREPARE_UI", "TRIPDOCKET_BATCH_PREPARE_TOKEN",
                           "TRIPDOCKET_NATIVE_SEED_UI", "TRIPDOCKET_NATIVE_SEED_TOKEN",
                           "TRIPDOCKET_NATIVE_ROOT_UI", "TRIPDOCKET_NATIVE_ROOT_TOKEN",
                           "TRIPDOCKET_BATCH_UI", "TRIPDOCKET_COMBINED_BATCH_UI",
                           "TRIPDOCKET_BATCH_CHECKPOINT_SESSION", "TRIPDOCKET_NATIVE_REOPEN_CONTROL"]
        guard debugSimulator, environment["TRIPDOCKET_NATIVE_FOLDER_UI"] == "1",
              UUID(uuidString: token)?.uuidString.lowercased() == token,
              UUID(uuidString: sourceToken)?.uuidString.lowercased() == sourceToken, sourceToken != token,
              environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token,
              conflicting.allSatisfy({ environment[$0] == nil }) else {
            throw BatchTestFailure(message: "Native folder creation requires its isolated Debug Simulator token")
        }
        return (token, sourceToken)
    }

    // The first-use keyboard introduction may appear as soon as Files opens
    // its inline editor, before any typing. Share one acknowledgement budget
    // across initial editing, explicit Rename, and the post-typing check.
    private func acknowledgeNativeFolderKeyboardIntroduction(
        _ app: XCUIApplication, expectedName: String, acknowledged: inout Bool
    ) async throws {
        let introduction = app.otherElements.matching(identifier: "UIContinuousPathIntroductionView")
        guard introduction.count != 0 else { return }
        let pickers = app.otherElements.matching(identifier: "Browse View (Picker)")
        let files = pickers.element.collectionViews.matching(identifier: "File View")
        let editors = files.element.textViews.matching(identifier: "DOC.inlineRenameField")
        let explanation = introduction.element.staticTexts.matching(NSPredicate(
            format: "label == %@", "Speed up your typing by sliding your finger across the letters to compose a word."
        ))
        let acknowledge = introduction.element.buttons.matching(NSPredicate(format: "label == %@", "Continue"))
        @MainActor func ready() throws -> Bool {
            guard !acknowledged, introduction.count == 1,
                  explanation.count == 1, explanation.element.isHittable,
                  acknowledge.count == 1, acknowledge.element.isEnabled, acknowledge.element.isHittable,
                  files.count == 1, files.element.cells.count == 1,
                  editors.count == 1, editors.element.isEnabled,
                  editors.element.value as? String == expectedName else { return false }
            let snapshots = try self.nativeFolderSnapshots(app)
            return Self.nativeFolderEditorFrame(
                in: snapshots.picker, applicationSnapshot: snapshots.application,
                expectedName: expectedName, localTitle: "On My iPhone", keyboardIntroduction: true
            ) == editors.element.frame
        }
        try check(try ready(), app: app, "Native keyboard introduction has no unique expected folder editor")
        capture(app, "Native keyboard introduction before the single Continue")
        try check(try ready(), app: app, "Native keyboard introduction changed before Continue")
        try Task.checkCancellation()
        acknowledged = true
        acknowledge.element.tap()
        try await wait("Native keyboard introduction did not dismiss back to the exact folder editor", app: app) {
            introduction.count == 0 && files.count == 1 && editors.count == 1
                && editors.element.isEnabled && editors.element.isHittable
                && editors.element.value as? String == expectedName
        }
    }

    func testNativeCreateOwnedFilesFolder() async throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["TRIPDOCKET_NATIVE_FOLDER_UI"] == "1",
                          "Opt in only for the owned native-folder fixture diagnostic")
        #if DEBUG && targetEnvironment(simulator)
        let debugSimulator = true
        #else
        let debugSimulator = false
        #endif
        let configuration = try Self.nativeFolderConfiguration(environment, debugSimulator: debugSimulator)
        let token = configuration.token
        let ownedFolder = "TripDocket-Batch-QA-" + token
        executionTimeAllowance = 180
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--ui-testing-native-batch-seed",
                                                   "--ui-testing-native-batch-token", configuration.sourceToken]
        app.launch()
        let source = app.buttons.matching(identifier: "nativeSeed.synthetic-ticket.pdf")
        let failed = app.staticTexts["nativeSeed.failure"]
        try await wait("Native-folder export source is unavailable", app: app) {
            failed.exists || (source.count == 1 && source.element.isEnabled && source.element.isHittable)
        }
        try check(!failed.exists && source.count == 1 && source.element.isEnabled && source.element.isHittable,
                  app: app, "Native-folder preparation has no unique live export source")
        capture(app, "Native folder — direct exporter before opening Files; no Save performed")
        source.element.tap()
        let picker = try await openNativeFilesRoot(app, initialTimeout: .seconds(30))
        let navigation = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let localTitle = "On My iPhone"
        let files = picker.collectionViews.matching(identifier: "File View")
        let directory = picker.cells.matching(identifier: ownedFolder + ", Folder")
        let saved = app.staticTexts.matching(NSPredicate(format: "identifier BEGINSWITH %@", "nativeSeed.saved."))
        try check(isNativeFilesRoot(app) && files.count == 1 && files.element.cells.count == 0
                  && directory.count == 0 && saved.count == 0 && !failed.exists,
                  app: app, "Native folder requires the empty local root and no exported destination")
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
        let inlineNames = files.element.textViews.matching(identifier: "DOC.inlineRenameField")
        let keyboardIntroduction = app.otherElements.matching(identifier: "UIContinuousPathIntroductionView")
        var keyboardIntroductionAcknowledged = false
        var renameFrame: CGRect?
        var initialObservation = NativeFolderInitialObservation()
        do {
            try await wait("Native folder has neither its editor nor a unique new untitled folder", app: app) {
                renameFrame = nil
                initialObservation.begin()
                do {
                    let snapshots = try self.nativeFolderSnapshots(app, diagnostic: { stage, picker, application in
                        initialObservation.stage = stage
                        initialObservation.picker = picker
                        initialObservation.application = application
                    })
                    initialObservation.lastBound = (initialObservation.attempt, snapshots.picker, snapshots.application)
                    let state = Self.nativeFolderInitialState(
                        in: snapshots.picker, applicationSnapshot: snapshots.application, localTitle: localTitle,
                        diagnostic: { initialObservation.rejections.append($0) }
                    )
                    renameFrame = state.renameFrame
                    return state.ready
                } catch {
                    initialObservation.failed(error)
                    return false
                }
            }
        } catch {
            recordNativeFolderInitialFailure(initialObservation, localTitle: localTitle)
            throw error
        }
        if let before = renameFrame {
            // The editor can appear after the initial observation selected the
            // unedited-folder route. Reclassify the existing fresh pair before
            // choosing any action; an unknown state still fails closed.
            let created = files.element.cells.matching(NSPredicate(
                format: "identifier == %@ AND label == %@",
                "untitled folder, Folder", "untitled folder, 0 items"
            ))
            capture(app, "Native folder initial Rename candidate before fresh state validation")
            let snapshots = try nativeFolderSnapshots(app)
            let currentState = Self.nativeFolderInitialState(
                in: snapshots.picker, applicationSnapshot: snapshots.application, localTitle: localTitle
            )
            try check(currentState.ready
                      && (currentState.renameFrame == nil || currentState.renameFrame == before),
                      app: app, "New native folder changed before Rename request")
            if currentState.renameFrame != nil {
                try check(isNativeFilesRoot(app) && files.count == 1 && files.element.cells.count == 1
                          && created.count == 1 && created.element.frame == before
                          && created.element.isEnabled && created.element.isHittable,
                          app: app, "New native folder changed before Rename request")
                try Task.checkCancellation()
                created.element.press(forDuration: 1)
                let rename = app.buttons.matching(NSPredicate(format: "label == %@", "Rename"))
                try await wait("Native folder context menu has no unique Rename action", app: app) {
                    rename.count == 1 && rename.element.isEnabled && rename.element.isHittable
                }
                try Task.checkCancellation()
                rename.element.tap()
                try await wait("Native folder Rename did not expose its real editor", app: app) {
                    keyboardIntroduction.count != 0 || (files.count == 1 && inlineNames.count == 1
                        && inlineNames.element.isEnabled && inlineNames.element.isHittable)
                }
            }
        }
        // One shared acknowledgement covers an initial editor, a late editor,
        // and an editor opened by Rename, before the unchanged pretype checks.
        try await acknowledgeNativeFolderKeyboardIntroduction(
            app, expectedName: "untitled folder", acknowledged: &keyboardIntroductionAcknowledged
        )
        // Files selects the default inline name. Do not collapse that selection
        // by tapping the editor; verify that typing replaced the complete value.
        let pretypeLiveReady = files.count == 1 && files.element.cells.count == 1
            && inlineNames.count == 1 && inlineNames.element.isEnabled && inlineNames.element.isHittable
        var pretypeSnapshot: XCUIElementSnapshot?
        var pretypeApplicationSnapshot: XCUIElementSnapshot?
        var pretypeReturnedFrame: CGRect?
        var pretypeLiveFrame: CGRect?
        var pretypeReason: String?
        var pretypeFramesMatch = false
        if pretypeLiveReady {
            let snapshots = try nativeFolderSnapshots(app)
            pretypeSnapshot = snapshots.picker
            pretypeApplicationSnapshot = snapshots.application
            pretypeReturnedFrame = Self.nativeFolderEditorFrame(
                in: snapshots.picker, applicationSnapshot: snapshots.application,
                expectedName: "untitled folder", localTitle: localTitle,
                diagnostic: { if pretypeReason == nil { pretypeReason = $0 } }
            )
            let frame = inlineNames.element.frame
            pretypeLiveFrame = frame
            pretypeFramesMatch = pretypeReturnedFrame == frame
        }
        if !pretypeLiveReady || !pretypeFramesMatch {
            recordNativeFolderSnapshot(
                pretypeSnapshot, observation: "pretype-actual-picker-input", localTitle: localTitle,
                returnedFrame: pretypeReturnedFrame, liveFrame: pretypeLiveFrame,
                reason: pretypeLiveReady ? (pretypeReason ?? "returned-frame-mismatch") : "live-precondition"
            )
            recordNativeFolderSnapshot(
                pretypeApplicationSnapshot, observation: "pretype-actual-application-input", localTitle: localTitle,
                returnedFrame: pretypeReturnedFrame, liveFrame: pretypeLiveFrame, reason: pretypeReason
            )
        }
        try check(pretypeLiveReady && pretypeFramesMatch,
                  app: app, "Native folder editor left the single newly created local folder")
        inlineNames.element.typeText(ownedFolder)
        try check(inlineNames.count == 1 && inlineNames.element.value as? String == ownedFolder,
                  app: app, "Native folder name differs from the exact owned UUID name")
        try await acknowledgeNativeFolderKeyboardIntroduction(
            app, expectedName: ownedFolder, acknowledged: &keyboardIntroductionAcknowledged
        )
        let endEditingSnapshots = try nativeFolderSnapshots(app)
        try check(files.count == 1 && inlineNames.count == 1
                  && inlineNames.element.isEnabled && inlineNames.element.isHittable
                  && inlineNames.element.value as? String == ownedFolder
                  && Self.nativeFolderEditorFrame(in: endEditingSnapshots.picker,
                                                   applicationSnapshot: endEditingSnapshots.application,
                                                   expectedName: ownedFolder,
                                                   localTitle: localTitle) == inlineNames.element.frame,
                  app: app, "Native folder editor is not ready for explicit end-editing")
        let beforeBlankSnapshots = try nativeFolderSnapshots(app)
        guard let before = nativeFolderBlankPoint(in: beforeBlankSnapshots.picker,
                                                  applicationSnapshot: beforeBlankSnapshots.application,
                                                  ownedFolder: ownedFolder, localTitle: localTitle) else {
            capture(app, "Native folder has no verified blank grid area")
            throw BatchTestFailure(message: "Native folder has no verified blank grid area")
        }
        capture(app, "Native folder exact name before the single blank-grid end-editing tap")
        let currentBlankSnapshots = try nativeFolderSnapshots(app)
        guard let current = nativeFolderBlankPoint(in: currentBlankSnapshots.picker,
                                                   applicationSnapshot: currentBlankSnapshots.application,
                                                   ownedFolder: ownedFolder, localTitle: localTitle),
              current.point == before.point, current.normalized == before.normalized,
              files.count == 1 && inlineNames.count == 1
                && inlineNames.element.isEnabled && inlineNames.element.isHittable
                && inlineNames.element.value as? String == ownedFolder else {
            throw BatchTestFailure(message: "Native folder blank grid area changed before end-editing")
        }
        files.element.coordinate(withNormalizedOffset: current.normalized).tap()
        // This fixture requests the native rename, then yields to the host's
        // mandatory no-follow proof of the exact empty leaf. Editor dismissal
        // is not its completion signal. The separate seed phase must navigate
        // the real folder before it can save either synthetic original.
        try check(saved.count == 0 && !failed.exists, app: app,
                  "Native-folder preparation unexpectedly exported a destination")
        capture(app, "Native folder rename requested; host empty-folder verification pending")
        // Never tap Save: the host must independently prove this native-created
        // leaf empty after the fixture stops, before the separate seed phase.
        app.terminate()
        try await wait("Native-folder fixture did not stop before host verification", app: app) {
            app.state == .notRunning
        }
    }

    func testNativeSaveSeedsBothSyntheticOriginals() async throws {
        let environment = ProcessInfo.processInfo.environment
        let checkpoint = try combinedBatchMode(environment)
        try XCTSkipUnless(environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1",
                          "Opt in only for the owned native-Save fixture diagnostic")
        let token = environment["TRIPDOCKET_NATIVE_SEED_TOKEN"] ?? ""
        guard UUID(uuidString: token)?.uuidString.lowercased() == token,
              environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token else {
            throw BatchTestFailure(message: "Native seed requires its exact canonical owned folder token")
        }
        let nativeRoot = try nativeRootMode("seed")
        let reopenValue = environment["TRIPDOCKET_NATIVE_REOPEN_CONTROL"]
        guard reopenValue == nil || reopenValue == "" || reopenValue == "1" else {
            throw BatchTestFailure(message: "Invalid native reopen control")
        }
        let reopenControl = reopenValue == "1"
        guard !reopenControl || (nativeRoot && checkpoint != nil) else {
            throw BatchTestFailure(message: "Native reopen control requires the owned combined root")
        }
        executionTimeAllowance = 180
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        defer { app.terminate() }
        app.launchArguments = recoveryArguments + ["--ui-testing-native-batch-seed",
                                                   "--ui-testing-native-batch-token", token,
                                                   "--ui-testing-batch-diagnostics"]
        if reopenControl {
            app.launchArguments += ["--ui-testing-native-reopen"]
        }
        app.launch()
        // Native Save writes both fixtures in one presentation. The callback
        // proves only returned URLs; the host must verify both files before main.
        let exportGroups = [filenames]
        for exportNames in exportGroups {
            let sourceIdentifier = "nativeSeed.exportBoth"
            let seed = app.buttons[sourceIdentifier]
            try await wait("Native seed source is unavailable", app: app) { seed.exists && seed.isEnabled && seed.isHittable }
            seed.tap()
            let picker: XCUIElement
            let navigation: XCUIElement
            if nativeRoot {
                picker = try await openNativeFilesRoot(app)
                navigation = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar").element
            } else {
                picker = try await openLocalFilesFolder(folder, app: app, initialNavigationTimeout: .seconds(30))
                navigation = try await recoveryFilesNavigation(folder, picker: picker, app: app)
            }
            let save = navigation.buttons["Save"]
            try await wait("Native seed destination Save is unavailable", app: app) {
                save.exists && save.isEnabled && save.isHittable
            }
            capture(app, "Native seed exact destination before Save — " + exportNames.joined(separator: ", "))
            if nativeRoot {
                try check(isNativeFilesRoot(app)
                          && navigation.buttons.matching(NSPredicate(format: "label == %@", "Save")).count == 1,
                          app: app, "Native seed left its verified local root or unique Save action")
            }
            save.tap()
            let verified = [app.staticTexts["nativeSeed.callbackVerified"]]
            let failed = app.staticTexts["nativeSeed.failure"]
            try await waitForNativeSeedExport(app, navigation: navigation, verified: verified,
                                              failed: failed, observeLateFailure: reopenControl)
            try check(!failed.exists && verified.allSatisfy { $0.exists }, app: app,
                      "Native seed export destination was not verified")
            let sourceNames = exportNames.sorted()
            let subsets = sourceNames.map { [$0] } + [sourceNames]
            let expectedValues = subsets.map {
                "sourceCount=\(sourceNames.count) sourceNames=\(sourceNames.joined(separator: ",")) "
                    + "verifiedCount=\($0.count) verifiedNames=\($0.joined(separator: ","))"
            }
            let callbackValue = verified[0].value as? String ?? ""
            try check(expectedValues.contains(callbackValue), app: app,
                      "Native seed callback verification evidence is invalid")
            print("BATCH_NATIVE_SEED_CALLBACK \(callbackValue)")
            capture(app, "Native seed returned URLs verified after Save — " + exportNames.joined(separator: ", "))
        }
        if reopenControl {
            // Diagnostic only: keep this AUT process alive after both exports.
            // The ordinary main case still runs after its normal termination.
            let reopen = app.buttons["nativeSeed.reopen"]
            try await wait("Same-process reopen control is unavailable", app: app) {
                reopen.exists && reopen.isEnabled && reopen.isHittable
            }
            capture(app, "Same-process native reopen before selection")
            reopen.tap()
            do {
                try await selectRealFiles(app, nativeRoot: true, observeLateFailure: false)
                let verified = app.staticTexts["nativeSeed.reopenVerified"]
                let failed = app.staticTexts["nativeSeed.reopenFailure"]
                try await wait("Same-process reopen did not verify both originals", app: app) {
                    verified.exists || failed.exists
                }
                try check(verified.exists && !failed.exists, app: app,
                          "Same-process reopen rejected the returned original bytes")
                capture(app, "Same-process native reopen verified both originals")
                print("BATCH_NATIVE_REOPEN result=verified")
            } catch {
                capture(app, "Same-process native reopen failed")
                throw error
            }
        }
        // Host compares both exact destination bytes; completion alone is not proof.
        if let checkpoint { try Self.recordBatchProducer(checkpoint) }
    }

    private func waitForNativeSeedExport(_ app: XCUIApplication, navigation: XCUIElement,
                                         verified: [XCUIElement], failed: XCUIElement,
                                         observeLateFailure: Bool) async throws {
        let terminal: @MainActor () -> Bool = {
            failed.exists || (!navigation.exists && verified.allSatisfy { $0.exists })
        }
        do {
            try await wait("Native seed export did not finish destination verification", app: app,
                           condition: terminal)
        } catch let originalFailure as BatchTestFailure {
            if observeLateFailure && !Task.isCancelled {
                // Diagnostic only: the original criterion already failed and
                // retained its evidence. Observe the same predicate without actions.
                // This deadline cannot interrupt an in-flight XCTest query/capture;
                // the unchanged 180-second case and outer limits still apply.
                let started = ContinuousClock.now
                let deadline = started.advanced(by: .seconds(45))
                var terminalObserved = false
                while ContinuousClock.now < deadline && !Task.isCancelled {
                    if terminal() { terminalObserved = true; break }
                    do { try await Task.sleep(for: .milliseconds(100)) }
                    catch { break }
                }
                let timing = XCTAttachment(string: """
                    originalExportCriterion=failed
                    requestedObservationSeconds=45
                    observedElapsed=\(started.duration(to: .now))
                    terminalObserved=\(terminalObserved)
                    cancelled=\(Task.isCancelled)
                    acceptance=failed
                    """)
                timing.name = "Native seed passive late observation — original failure retained"
                timing.lifetime = .keepAlways
                add(timing)
                if !Task.isCancelled {
                    capture(app, "Native seed after passive late observation — original failure retained",
                            batchDiagnostic: true)
                }
            }
            // A late callback, failure or diagnostic cancellation cannot pass
            // the original criterion or allow reopen/checkpoint/main to continue.
            throw originalFailure
        }
    }

    // Combined qualification preserves separate seed/main XCTest cases. This
    // process-local record is never a substitute for the host's real seed PASS.
    private struct BatchCheckpointIdentity: Equatable {
        let session: String
        let token: String
    }

    private enum BatchCheckpointState {
        case empty
        case produced(BatchCheckpointIdentity)
        case consumed
    }

    private static var batchCheckpointState: BatchCheckpointState = .empty

    private func combinedBatchMode(_ environment: [String: String]) throws -> BatchCheckpointIdentity? {
        #if DEBUG && targetEnvironment(simulator)
        let debugSimulator = true
        #else
        let debugSimulator = false
        #endif
        return try Self.combinedBatchConfiguration(environment, debugSimulator: debugSimulator)
    }

    private static func combinedBatchConfiguration(
        _ environment: [String: String], debugSimulator: Bool
    ) throws -> BatchCheckpointIdentity? {
        guard environment["TRIPDOCKET_COMBINED_BATCH_UI"] != nil
                || environment["TRIPDOCKET_BATCH_CHECKPOINT_SESSION"] != nil else { return nil }
        let session = environment["TRIPDOCKET_BATCH_CHECKPOINT_SESSION"] ?? ""
        let root = environment["TRIPDOCKET_NATIVE_ROOT_UI"] != nil
            || environment["TRIPDOCKET_NATIVE_ROOT_TOKEN"] != nil
        let nativeFolder = environment["TRIPDOCKET_NATIVE_FOLDER_UI"] != nil
            || environment["TRIPDOCKET_NATIVE_FOLDER_TOKEN"] != nil
        let token = environment[root ? "TRIPDOCKET_NATIVE_ROOT_TOKEN" : "TRIPDOCKET_NATIVE_FOLDER_TOKEN"] ?? ""
        guard debugSimulator, environment["TRIPDOCKET_COMBINED_BATCH_UI"] == "1",
              root != nativeFolder,
              environment["TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN"] == nil,
              let sessionID = UUID(uuidString: session), sessionID.uuidString == session,
              sessionID.uuid.6 & 0xf0 == 0x40, sessionID.uuid.8 & 0xc0 == 0x80,
              UUID(uuidString: token)?.uuidString.lowercased() == token,
              environment[root ? "TRIPDOCKET_NATIVE_ROOT_UI" : "TRIPDOCKET_NATIVE_FOLDER_UI"] == "1",
              environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1",
              environment["TRIPDOCKET_NATIVE_SEED_TOKEN"] == token,
              environment["TRIPDOCKET_BATCH_UI"] == "1",
              environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token else {
            throw BatchTestFailure(message: "Combined batch requires its exact Debug Simulator session and owned fixture")
        }
        return BatchCheckpointIdentity(session: session, token: token)
    }

    private static func recordBatchProducer(_ identity: BatchCheckpointIdentity) throws {
        guard case .empty = batchCheckpointState else {
            throw BatchTestFailure(message: "Combined batch producer was already recorded or consumed")
        }
        batchCheckpointState = .produced(identity)
    }

    private static func consumeBatchProducer(_ identity: BatchCheckpointIdentity) throws {
        guard case .produced(let actual) = batchCheckpointState, actual == identity else {
            throw BatchTestFailure(message: "Combined batch requires its matching producer in this test process")
        }
        batchCheckpointState = .consumed
    }

    private func awaitBatchCheckpoint(
        _ identity: BatchCheckpointIdentity, until caseDeadline: ContinuousClock.Instant
    ) async throws {
        try Task.checkCancellation()
        try Self.consumeBatchProducer(identity)
        let clock = ContinuousClock()
        let deadline = min(caseDeadline, clock.now.advanced(by: .seconds(60)))
        guard clock.now < deadline else {
            throw BatchTestFailure(message: "Combined batch checkpoint has no remaining case budget")
        }
        let nonce = UUID().uuidString
        let name = "com.4alvit.tripfolio.batch-checkpoint.\(identity.session).\(nonce)"
        var notificationToken: Int32 = 0
        guard notify_register_check(name, &notificationToken) == NOTIFY_STATUS_OK else {
            throw BatchTestFailure(message: "Cannot register combined batch checkpoint acknowledgement")
        }
        defer { _ = notify_cancel(notificationToken) }
        var state: UInt64 = 0
        guard notify_get_state(notificationToken, &state) == NOTIFY_STATUS_OK, state == 0 else {
            throw BatchTestFailure(message: "Combined batch checkpoint acknowledgement was not initially empty")
        }
        try Task.checkCancellation()
        guard clock.now < deadline else {
            throw BatchTestFailure(message: "Combined batch checkpoint setup exhausted its deadline")
        }
        print("TRIPDOCKET_BATCH_CHECKPOINT \(identity.session) \(identity.token) \(nonce)")
        fflush(nil)
        repeat {
            guard notify_get_state(notificationToken, &state) == NOTIFY_STATUS_OK else {
                throw BatchTestFailure(message: "Cannot read combined batch checkpoint acknowledgement")
            }
            try Task.checkCancellation()
            if clock.now >= deadline { break }
            if state == 1 { return }
            guard state == 0 else {
                throw BatchTestFailure(message: "Unexpected combined batch checkpoint acknowledgement")
            }
            let remaining = clock.now.duration(to: deadline)
            if remaining > .zero { try await Task.sleep(for: min(.milliseconds(100), remaining)) }
        } while clock.now < deadline
        throw BatchTestFailure(message: "Host did not acknowledge the combined batch checkpoint within its deadline")
    }

    @MainActor
    private func nativeFolderBlankPoint(
        in snapshot: XCUIElementSnapshot, applicationSnapshot: XCUIElementSnapshot,
        ownedFolder: String, localTitle: String
    ) -> (point: CGPoint, normalized: CGVector)? {
        @MainActor func nodes(_ root: XCUIElementSnapshot) -> [XCUIElementSnapshot] {
            var result: [XCUIElementSnapshot] = []
            var pending: [(XCUIElementSnapshot, Int)] = [(root, 0)]
            while let (node, depth) = pending.popLast() {
                guard depth <= 96, result.count < 4_096 else { return [] }
                result.append(node)
                let children = node.children
                guard children.count <= 4_096 - result.count - pending.count else { return [] }
                pending.append(contentsOf: children.reversed().map { ($0, depth + 1) })
            }
            return result
        }
        func finite(_ frame: CGRect) -> Bool {
            [frame.minX, frame.minY, frame.width, frame.height].allSatisfy { $0.isFinite }
                && frame.width >= 0 && frame.height >= 0
        }
        let all = nodes(snapshot)
        let environment = nodes(applicationSnapshot)
        let pickers = all.filter { $0.elementType == .other && $0.identifier == "Browse View (Picker)" }
        guard snapshot.elementType == .other, snapshot.identifier == "Browse View (Picker)",
              applicationSnapshot.elementType == .application, !environment.isEmpty,
              pickers.count == 1,
              !all.contains(where: { $0.identifier == "UIContinuousPathIntroductionView" }),
              !environment.contains(where: { $0.identifier == "UIContinuousPathIntroductionView" }) else { return nil }
        let pickerNodes = nodes(pickers[0])
        let rootIdentifier = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " + localTitle
        let roots = pickerNodes.filter { $0.elementType == .other && $0.identifier == rootIdentifier }
        guard roots.count == 1 else { return nil }
        let rootNodes = nodes(roots[0])
        guard rootNodes.filter({ $0.elementType == .collectionView && $0.identifier == "File View" }).count == 1,
              rootNodes.filter({ $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }).count == 1 else { return nil }
        let files = pickerNodes.filter { $0.elementType == .collectionView && $0.identifier == "File View" }
        let navigation = pickerNodes.filter {
            $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar"
        }
        let keyboards = environment.filter { $0.elementType == .keyboard }
        let windows = applicationSnapshot.children.filter { $0.elementType == .window }
        guard files.count == 1, navigation.count == 1, keyboards.count == 1, !windows.isEmpty,
              windows.allSatisfy({ finite($0.frame) && !$0.frame.isEmpty }) else { return nil }
        let titles = nodes(navigation[0]).filter {
            ($0.elementType == .staticText && $0.label == localTitle)
                || ($0.elementType == .button && $0.label == localTitle + ", Actions Menu")
        }
        let fileNodes = nodes(files[0])
        let editors = fileNodes.filter { $0.elementType == .textView && $0.identifier == "DOC.inlineRenameField" }
        let cells = fileNodes.filter { $0.elementType == .cell }
        let owners = cells.filter { cell in
            nodes(cell).contains { $0.elementType == .textView && $0.identifier == "DOC.inlineRenameField" }
        }
        guard titles.count == 1, editors.count == 1, editors[0].value as? String == ownedFolder,
              owners.count == 1 else { return nil }
        let frame = files[0].frame
        let keyboardFrame = keyboards[0].frame
        let navigationFrame = navigation[0].frame
        let ownerFrame = owners[0].frame
        guard [frame, keyboardFrame, navigationFrame, ownerFrame, editors[0].frame].allSatisfy(finite),
              !frame.isEmpty, !keyboardFrame.isEmpty, !navigationFrame.isEmpty, !ownerFrame.isEmpty else { return nil }
        let window = windows.dropFirst().reduce(windows[0].frame) { $0.intersection($1.frame) }
        let top = max(frame.minY, navigationFrame.maxY, ownerFrame.minY, window.minY)
        let bottom = min(frame.maxY, keyboardFrame.minY, ownerFrame.maxY, window.maxY)
        guard bottom > top else { return nil }
        let region = CGRect(x: max(frame.minX, window.minX), y: top,
                            width: min(frame.maxX, window.maxX) - max(frame.minX, window.minX),
                            height: bottom - top).insetBy(dx: 12, dy: 12)
        guard finite(region), !region.isEmpty else { return nil }
        // Containers describe the grid itself. Every other semantic node is an
        // exclusion, including cells, images, text, editors and action controls.
        let exclusions = pickerNodes.filter { node in
            if node.elementType == .collectionView || node.elementType == .scrollView { return false }
            if node.elementType == .other {
                if node.identifier == "Browse View (Picker)"
                    || node.identifier == rootIdentifier {
                    return false
                }
                return !node.identifier.isEmpty || !node.label.isEmpty || node.value != nil
            }
            return true
        }.map { $0.frame }
        guard exclusions.allSatisfy(finite) else { return nil }
        for xFraction: CGFloat in [0.5, 0.75, 0.25] {
            for yFraction: CGFloat in [0.5, 0.25, 0.75] {
                let point = CGPoint(x: region.minX + region.width * xFraction,
                                    y: region.minY + region.height * yFraction)
                let touch = CGRect(x: point.x - 11, y: point.y - 11, width: 22, height: 22)
                guard region.contains(touch),
                      !exclusions.contains(where: { !$0.isEmpty && $0.insetBy(dx: -8, dy: -8).intersects(touch) }) else { continue }
                return (point, CGVector(dx: (point.x - frame.minX) / frame.width,
                                       dy: (point.y - frame.minY) / frame.height))
            }
        }
        return nil
    }

    // Files is a remote view service. The app snapshot can expose its keyboard
    // and windows without exposing the picker subtree. Capture the two explicit
    // scopes and bind the remote snapshot to the still-unique live picker.
    // These are sequential observations, not an atomic combined hierarchy.
    @MainActor
    private func nativeFolderSnapshots(
        _ app: XCUIApplication,
        diagnostic: ((String, XCUIElementSnapshot?, XCUIElementSnapshot?) -> Void)? = nil
    ) throws -> (picker: XCUIElementSnapshot, application: XCUIElementSnapshot) {
        var stage = "foreground-unique-picker"
        var observedPicker: XCUIElementSnapshot?
        var observedApplication: XCUIElementSnapshot?
        defer { diagnostic?(stage, observedPicker, observedApplication) }
        let pickers = app.otherElements.matching(identifier: "Browse View (Picker)")
        guard app.state == .runningForeground, pickers.count == 1 else {
            throw BatchTestFailure(message: "Native folder requires one foreground Files picker")
        }
        stage = "picker-snapshot"
        let picker = try pickers.element.snapshot()
        observedPicker = picker
        stage = "application-snapshot"
        let application = try app.snapshot()
        observedApplication = application
        stage = "live-binding"
        guard picker.elementType == .other, picker.identifier == "Browse View (Picker)",
              application.elementType == .application, app.state == .runningForeground,
              pickers.count == 1, pickers.element.frame == picker.frame else {
            throw BatchTestFailure(message: "Native folder picker changed while observing its environment")
        }
        stage = "bound"
        return (picker, application)
    }

    private func presentRecoverySave(_ app: XCUIApplication, retryNavigation: Bool = false) async throws {
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
        // presentation to initialize without repeating Export or tapping an unready action.
        let proof = try await waitForStableShareAction(saveToFiles, app: app)
        if retryNavigation {
            try await openRecoveryFilesFromShare(saveToFiles, app: app, first: proof)
        } else {
            proof.action.tap()
        }
    }

    private func recordRecoveryShareTransition(_ message: String) {
        let attachment = XCTAttachment(string: message)
        attachment.name = "Recovery Save to Files transition"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func openRecoveryFilesFromShare(_ actions: XCUIElementQuery, app: XCUIApplication,
                                            first: (frames: [CGRect], identity: String, action: XCUIElement)) async throws {
        let started = ContinuousClock.now
        let retryAfter = started.advanced(by: .seconds(15))
        let deadline = started.advanced(by: .seconds(30))
        let navigations = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let pickers = app.otherElements.matching(identifier: "Browse View (Picker)")
        var retryAvailable = true
        var previous: (frames: [CGRect], identity: String, action: XCUIElement)?
        var stableObservations = 0
        func matches(_ left: (frames: [CGRect], identity: String, action: XCUIElement),
                     _ right: (frames: [CGRect], identity: String, action: XCUIElement)) -> Bool {
            left.identity == right.identity && left.frames.count == right.frames.count
                && zip(left.frames, right.frames).allSatisfy { a, b in
                    abs(a.minX - b.minX) <= 0.5 && abs(a.minY - b.minY) <= 0.5
                        && abs(a.width - b.width) <= 0.5 && abs(a.height - b.height) <= 0.5
                }
        }
        func record(_ message: String) {
            recordRecoveryShareTransition("elapsed=\(started.duration(to: ContinuousClock.now)); \(message)")
        }
        func disableRetry(_ reason: String) {
            if retryAvailable { record("retry disabled: " + reason) }
            retryAvailable = false
        }
        record("dispatch intent 1; identity=\(first.identity); frames=\(first.frames)")
        if ContinuousClock.now < deadline {
            try Task.checkCancellation()
            if ContinuousClock.now < deadline { first.action.tap() }
        }
        while ContinuousClock.now < deadline {
            let foreground = app.state == .runningForeground
            guard ContinuousClock.now < deadline else { break }
            let count = navigations.count
            guard ContinuousClock.now < deadline else { break }
            if foreground && count == 1 {
                let exists = navigations.element.exists
                guard ContinuousClock.now < deadline else { break }
                if exists { return }
            }
            if retryAvailable {
                let pickerCount = pickers.count
                guard ContinuousClock.now < deadline else { break }
                if !foreground || count != 0 || pickerCount != 0 {
                    disableRetry("foreground/share-only precondition changed")
                } else if let proof = shareActionObservation(actions, app: app, before: deadline) {
                    guard ContinuousClock.now < deadline else { break }
                    if !matches(proof, first) || previous.map({ !matches(proof, $0) }) == true {
                        disableRetry("action/header identity or geometry changed")
                    } else {
                        previous = proof
                        if ContinuousClock.now >= retryAfter { stableObservations += 1 }
                        if stableObservations >= 3 {
                            // Recheck after the final complete share observation. A partial
                            // picker, changed foreground state or late query forbids a tap.
                            let stillForeground = app.state == .runningForeground
                            guard ContinuousClock.now < deadline else { break }
                            let remainingNavigations = navigations.count
                            guard ContinuousClock.now < deadline else { break }
                            let remainingPickers = pickers.count
                            guard ContinuousClock.now < deadline else { break }
                            let stillShareOnly = stillForeground && remainingNavigations == 0 && remainingPickers == 0
                            retryAvailable = false
                            if stillShareOnly {
                                record("dispatch intent 2; identity=\(proof.identity); frames=\(proof.frames)")
                                guard ContinuousClock.now < deadline else { break }
                                try Task.checkCancellation()
                                guard ContinuousClock.now < deadline else { break }
                                proof.action.tap()
                            } else {
                                record("retry disabled: final share-only precondition changed")
                            }
                        }
                    }
                } else {
                    disableRetry("share observation missing, ambiguous, unavailable or incomplete")
                }
            }
            guard ContinuousClock.now < deadline else { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        record("polling deadline reached; in-flight XCTest work may have overrun")
        capture(app, "Files did not present its navigation", batchDiagnostic: true)
        throw BatchTestFailure(message: "Files did not present its navigation")
    }

    private func waitForStableShareAction(_ actions: XCUIElementQuery, app: XCUIApplication) async throws
        -> (frames: [CGRect], identity: String, action: XCUIElement) {
        let deadline = ContinuousClock.now.advanced(by: .seconds(40))
        var previousFrames: [CGRect]?
        var previousIdentity: String?
        var stableObservations = 0
        var ready: (frames: [CGRect], identity: String, action: XCUIElement)?
        // A single snapshot supplies a coherent action/header observation without
        // repeating remote attribute queries. Hittability still uses the live
        // query, constrained to that snapshot's exact action identity.
        try await wait("Share sheet action did not stabilize", app: app, timeout: .seconds(40)) {
            if let proof = shareActionObservation(actions, app: app, before: deadline) {
                let frames = proof.frames
                let identity = proof.identity
                let unchanged = previousFrames.map { old in
                    zip(old, frames).allSatisfy { a, b in
                        abs(a.minX - b.minX) <= 0.5 && abs(a.minY - b.minY) <= 0.5
                            && abs(a.width - b.width) <= 0.5 && abs(a.height - b.height) <= 0.5
                    }
                } ?? false
                stableObservations = unchanged && identity == previousIdentity ? stableObservations + 1 : 1
                previousFrames = frames
                previousIdentity = identity
                if stableObservations >= 3 { ready = proof; return true }
                return false
            }
            previousFrames = nil
            previousIdentity = nil
            stableObservations = 0
            return false
        }
        guard let ready else { throw BatchTestFailure(message: "Share action proof is missing") }
        return ready
    }

    private func shareActionObservation(_ actions: XCUIElementQuery, app: XCUIApplication,
                                        before deadline: ContinuousClock.Instant)
        -> (frames: [CGRect], identity: String, action: XCUIElement)? {
        if ContinuousClock.now < deadline, let snapshot = try? app.snapshot(),
           ContinuousClock.now < deadline {
            var pending: [(XCUIElementSnapshot, Int)] = [(snapshot, 0)]
            var visited = 0
            var complete = true
            var matchingActions: [XCUIElementSnapshot] = []
            var matchingHeaders: [XCUIElementSnapshot] = []
            while let (node, depth) = pending.popLast() {
                guard visited < 4_096, depth <= 64, ContinuousClock.now < deadline else {
                    complete = false
                    break
                }
                visited += 1
                if node.label == "Save to Files",
                   node.elementType == .button
                    || (node.elementType == .cell && node.identifier == "actionGroupCell") {
                    matchingActions.append(node)
                }
                if node.elementType == .navigationBar, node.identifier == "UIActivityContentView" {
                    matchingHeaders.append(node)
                }
                let children = node.children
                // Never accept a truncated tree: a later node may be a duplicate.
                guard children.count <= 4_096 - visited - pending.count else {
                    complete = false
                    break
                }
                pending.append(contentsOf: children.map { ($0, depth + 1) })
            }
            if complete, matchingActions.count == 1, matchingHeaders.count == 1 {
                let action = matchingActions[0]
                let bounds = snapshot.frame
                let candidate = [action.frame, matchingHeaders[0].frame]
                if action.isEnabled, ([bounds] + candidate).allSatisfy({ frame in
                    frame.origin.x.isFinite && frame.origin.y.isFinite && frame.width.isFinite && frame.height.isFinite
                        && frame.width > 0 && frame.height > 0 && bounds.contains(frame)
                }) {
                    let liveAction = actions.matching(NSPredicate(
                        format: "elementType == %@ AND identifier == %@ AND label == %@",
                        NSNumber(value: action.elementType.rawValue), action.identifier, action.label
                    )).element
                    if ContinuousClock.now < deadline, liveAction.isHittable, ContinuousClock.now < deadline {
                        let header = matchingHeaders[0]
                        let identity = "\(action.elementType.rawValue):\(action.identifier):\(action.label)"
                            + "|header:\(header.elementType.rawValue):\(header.identifier):\(header.label)"
                        return (candidate, identity, liveAction)
                    }
                }
            }
        }
        return nil
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
        var keyboardIntroductionAcknowledged = false
        name.tap()
        let emptyName = name.value as? String
        try check(emptyName == "" || emptyName == "Name or nickname", app: app,
                  "Add-person name field was not empty before typing")
        try await acknowledgeRecoveryPersonKeyboardIntroduction(
            app, expectedName: emptyName ?? "", acknowledged: &keyboardIntroductionAcknowledged
        )
        name.typeText("Recovery Sentinel")
        try await acknowledgeRecoveryPersonKeyboardIntroduction(
            app, expectedName: "Recovery Sentinel", acknowledged: &keyboardIntroductionAcknowledged
        )
        let confirm = alert.buttons["Add"]
        try check(confirm.isEnabled && confirm.isHittable
                  && name.value as? String == "Recovery Sentinel"
                  && app.otherElements.matching(identifier: "UIContinuousPathIntroductionView").count == 0,
                  app: app, "Add person cannot be confirmed")
        confirm.tap()
        try await wait("The unassigned person was not saved", app: app) {
            app.staticTexts["Recovery Sentinel"].exists && app.staticTexts["Alex Example"].exists
        }
        try await recoveryTab("Settings", app: app)
        try await recoveryFreeCard(app)
        try await recoveryCounts(trips: 1, people: 2, documents: 1, app: app)
        try await presentRecoverySave(app, retryNavigation: true)
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
        let picker = try await openLocalFilesFolder(recoveryFolder, app: app, retryRecoveryFolderEntry: true)
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
        try await wait("Files preparation did not reach the local root", app: app,
                       timeout: .seconds(30)) { atRoot() }
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


    // The first-use introduction can arrive when focus opens the keyboard or
    // while XCTest types. Acknowledge it only for this exact synthetic form,
    // sharing one action budget across both observations.
    private func acknowledgeRecoveryPersonKeyboardIntroduction(
        _ app: XCUIApplication, expectedName: String, acknowledged: inout Bool
    ) async throws {
        let introduction = app.otherElements.matching(identifier: "UIContinuousPathIntroductionView")
        guard introduction.count != 0 else { return }
        let alerts = app.alerts.matching(identifier: "Add a person")
        let names = alerts.element.textFields.matching(identifier: "Name or nickname")
        let explanation = introduction.element.staticTexts.matching(NSPredicate(
            format: "label == %@", "Speed up your typing by sliding your finger across the letters to compose a word."
        ))
        let acknowledge = introduction.element.buttons.matching(NSPredicate(format: "label == %@", "Continue"))
        @MainActor func expectedForm() -> Bool {
            app.state == .runningForeground && app.alerts.count == 1 && alerts.count == 1
                && alerts.element.textFields.count == 1 && names.count == 1
                && names.element.isEnabled && names.element.value as? String == expectedName
        }
        @MainActor func ready() -> Bool {
            !acknowledged && introduction.count == 1 && expectedForm()
                && explanation.count == 1 && explanation.element.isHittable
                && acknowledge.count == 1 && acknowledge.element.isEnabled && acknowledge.element.isHittable
        }
        @MainActor func geometry() throws -> (root: CGRect, introduction: CGRect, button: CGRect) {
            let root = app.frame, introductionFrame = introduction.element.frame
            let button = acknowledge.element.frame
            let valid = [root, introductionFrame, button].allSatisfy { frame in
                !frame.isEmpty && !frame.isNull && !frame.isInfinite
                    && [frame.minX, frame.minY, frame.width, frame.height].allSatisfy(\.isFinite)
            }
            try check(valid && root.contains(introductionFrame) && introductionFrame.contains(button),
                      app: app, "Keyboard Continue has no contained finite frame")
            return (root, introductionFrame, button)
        }
        try check(ready(), app: app, "Native keyboard introduction has no unique expected person form")
        let original = try geometry()
        capture(app, "Recovery person keyboard introduction before the single Continue")
        try check(ready(), app: app, "Recovery person form changed before Continue")
        let current = try geometry()
        try check(current.root == original.root && current.introduction == original.introduction
                    && current.button == original.button, app: app, "Keyboard Continue moved before the single action")
        // An element tap can make XCTest cancel the expected Add-person alert
        // as an interruption. Target only the freshly proved button's center
        // from the app origin; disappearance of the form still fails below.
        let target = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(
            dx: current.button.midX - current.root.minX, dy: current.button.midY - current.root.minY))
        try Task.checkCancellation()
        acknowledged = true
        target.tap()
        try await wait("Native keyboard introduction did not return to the expected person form", app: app) {
            introduction.count == 0 && expectedForm() && names.element.isHittable
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
        recordPurchaseObservation(app, session: session, point: .beforeTap)
        buy.tap()
        do {
            try await wait("No positively identified Xcode payment sheet appeared", app: app, springboard: springboard) {
                self.xcodeMarker(app).exists || self.xcodeMarker(springboard).exists
            }
        } catch {
            recordPurchaseObservation(app, session: session, point: .missingSheet)
            throw error
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

    private enum PurchaseObservationPoint: String { case beforeTap, missingSheet }

    private func recordPurchaseObservation(_ app: XCUIApplication, session: SKTestSession,
                                           point: PurchaseObservationPoint) {
        let elements = app.buttons.matching(identifier: "purchase.state")
        var state = "unknown-missing-or-unrecognized"
        if elements.count == 1, let value = elements.element(boundBy: 0).value as? String,
           value.utf8.count <= 192 {
            let stage = "(?:notStarted|entitlements|catalog|purchase|finish|sync|returned)"
            let pattern = "^purchase-state isPro=(?:true|false) isBusy=(?:true|false) load=" + stage
                + " purchase=" + stage + " restore=" + stage + "\\z"
            if value.range(of: pattern, options: .regularExpression) != nil { state = value }
        }
        let text = "purchase-observation observationOnly=true point=\(point.rawValue)\n"
            + "disableDialogs=\(session.disableDialogs) askToBuyEnabled=\(session.askToBuyEnabled) interruptedPurchasesEnabled=\(session.interruptedPurchasesEnabled)\n"
            + state
        let attachment = XCTAttachment(string: text)
        attachment.name = "Batch purchase state \(point.rawValue)"
        attachment.lifetime = .keepAlways
        add(attachment)
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

    private func nativeRootMode(_ mode: String) throws -> Bool {
        #if DEBUG && targetEnvironment(simulator)
        let debugSimulator = true
        #else
        let debugSimulator = false
        #endif
        return try Self.nativeRootConfiguration(ProcessInfo.processInfo.environment,
                                                mode: mode, debugSimulator: debugSimulator)
    }

    private static func nativeRootConfiguration(_ environment: [String: String], mode: String,
                                                debugSimulator: Bool) throws -> Bool {
        guard environment["TRIPDOCKET_NATIVE_ROOT_UI"] != nil
                || environment["TRIPDOCKET_NATIVE_ROOT_TOKEN"] != nil else { return false }
        let token = environment["TRIPDOCKET_NATIVE_ROOT_TOKEN"] ?? ""
        guard debugSimulator, environment["TRIPDOCKET_NATIVE_ROOT_UI"] == "1",
              UUID(uuidString: token)?.uuidString.lowercased() == token,
              environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token,
              (mode == "seed" && environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1"
                && environment["TRIPDOCKET_NATIVE_SEED_TOKEN"] == token)
                || (mode == "batch" && environment["TRIPDOCKET_BATCH_UI"] == "1") else {
            throw BatchTestFailure(message: "Native root fixture requires its exact Debug Simulator opt-in and owned token")
        }
        return true
    }

    private func isNativeFilesRoot(_ app: XCUIApplication) -> Bool {
        let navigations = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let pickers = app.otherElements.matching(identifier: "Browse View (Picker)")
        guard navigations.count == 1, pickers.count == 1, pickers.element.exists else { return false }
        let roots = pickers.element.otherElements.matching(identifier:
            "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone")
        guard roots.count == 1, roots.element.exists,
              pickers.element.collectionViews.matching(identifier: "File View").count == 1 else { return false }
        let rootNavigation = roots.element.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let grids = roots.element.collectionViews.matching(identifier: "File View")
        return rootNavigation.count == 1 && grids.count == 1 && grids.element.exists
            && isRecoveryFolder("On My iPhone", navigation: rootNavigation.element)
    }

    private func openNativeFilesRoot(_ app: XCUIApplication,
                                     initialTimeout: Duration = .seconds(15)) async throws -> XCUIElement {
        try check(UIDevice.current.userInterfaceIdiom == .phone, app: app,
                  "Native root fixture requires its selected iPhone")
        let navigations = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let pickers = app.otherElements.matching(identifier: "Browse View (Picker)")
        let recents = app.otherElements.matching(identifier:
            "DOC.browsingRoot Source: com.apple.DocumentManager.RecentDocuments, Title: Recents")
        let tabs = app.tabBars.matching(identifier: "DOC.browsingModeTabBar")
        let browse = tabs.element.buttons.matching(NSPredicate(format: "label == %@", "Browse"))
        let browseReady = { tabs.count == 1 && browse.count == 1 && browse.element.isEnabled && browse.element.isHittable }
        let browserReady = { navigations.count == 1 && pickers.count == 1 && pickers.element.exists }
        let recentsReady = {
            navigations.count == 1 && pickers.count == 0 && recents.count == 1 && recents.element.exists
                && self.isRecoveryFolder("Recents", navigation: navigations.element) && browseReady()
        }
        try await wait("Native root Files browser or supported Recents screen is missing", app: app,
                       timeout: initialTimeout) {
            // Classify one observation instead of rereading a changing browser
            // as Recents after an earlier navigation query found no match.
            guard navigations.count == 1 else { return false }
            let pickerCount = pickers.count
            if pickerCount == 1 { return pickers.element.exists }
            guard pickerCount == 0 else { return false }
            return recents.count == 1 && recents.element.exists
                && self.isRecoveryFolder("Recents", navigation: navigations.element) && browseReady()
        }
        if !browserReady() {
            try check(recentsReady(), app: app, "Native root Files Recents route changed")
            browse.element.tap()
        }
        try await wait("Native root Files browser is missing", app: app) { browserReady() }
        let location = app.cells.matching(identifier: "DOC.sidebar.item.On My iPhone")
        try await reachRecoveryLocalRoot("On My iPhone", navigation: navigations,
                                         location: location, browse: browse, app: app)
        try await wait("Native Files did not identify the exact local provider root", app: app) {
            self.isNativeFilesRoot(app)
        }
        return pickers.element
    }

    // One Recovery-only navigation retry may use this positive parent proof.
    // The two scopes are sequential observations, not an atomic UI snapshot.
    @MainActor
    private static func recoveryFolderParentGeometry(
        in snapshot: XCUIElementSnapshot, applicationSnapshot: XCUIElementSnapshot,
        folder: String, localTitle: String
    ) -> [CGRect]? {
        let prefix = "TripDocket-Recovery-"
        guard folder.hasPrefix(prefix),
              let token = UUID(uuidString: String(folder.dropFirst(prefix.count))),
              folder == prefix + token.uuidString.lowercased(),
              ["On My iPhone", "On My iPad"].contains(localTitle) else { return nil }
        @MainActor func nodes(_ root: XCUIElementSnapshot) -> [XCUIElementSnapshot]? {
            var result: [XCUIElementSnapshot] = []
            var pending: [(XCUIElementSnapshot, Int)] = [(root, 0)]
            while let (node, depth) = pending.popLast() {
                guard depth <= 96, result.count < 4_096 else { return nil }
                result.append(node)
                let children = node.children
                guard children.count <= 4_096 - result.count - pending.count else { return nil }
                pending.append(contentsOf: children.reversed().map { ($0, depth + 1) })
            }
            return result
        }
        func visible(_ frame: CGRect) -> Bool {
            [frame.minX, frame.minY, frame.width, frame.height].allSatisfy { $0.isFinite }
                && frame.width > 0 && frame.height > 0
        }
        guard snapshot.elementType == .other, snapshot.identifier == "Browse View (Picker)",
              applicationSnapshot.elementType == .application,
              let all = nodes(snapshot), let environment = nodes(applicationSnapshot) else { return nil }
        // Do not dismiss an overlay or infer that an editor is ready to navigate.
        for node in all + environment {
            if [.keyboard, .textField, .textView, .menu, .menuItem, .alert, .sheet, .popover].contains(node.elementType)
                || node.identifier == "DOC.inlineRenameField"
                || node.identifier == "UIContinuousPathIntroductionView" { return nil }
        }
        let rootID = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " + localTitle
        let pickers = all.filter { $0.identifier == "Browse View (Picker)" }
        let roots = all.filter { $0.identifier.hasPrefix("DOC.browsingRoot Source:") }
        let grids = all.filter { $0.elementType == .collectionView && $0.identifier == "File View" }
        let navigations = all.filter { $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }
        guard pickers.count == 1, roots.count == 1, roots[0].elementType == .other,
              roots[0].identifier == rootID, grids.count == 1, navigations.count == 1,
              let rootNodes = nodes(roots[0]), let gridNodes = nodes(grids[0]),
              let titleNodes = nodes(navigations[0]),
              rootNodes.filter({ $0.elementType == .collectionView && $0.identifier == "File View" }).count == 1,
              rootNodes.filter({ $0.elementType == .navigationBar && $0.identifier == "FullDocumentManagerViewControllerNavigationBar" }).count == 1 else { return nil }
        let cells = all.filter { $0.elementType == .cell && $0.identifier == folder + ", Folder" }
        let titles = titleNodes.filter {
            ($0.elementType == .staticText && $0.label == localTitle)
                || ($0.elementType == .button && $0.label == localTitle + ", Actions Menu")
        }
        let windows = applicationSnapshot.children.filter { $0.elementType == .window }
        guard cells.count == 1, cells[0].isEnabled, cells[0].label == folder + ", 1 item",
              gridNodes.filter({ $0.elementType == .cell && $0.identifier == folder + ", Folder" }).count == 1,
              titles.count == 1, !windows.isEmpty else { return nil }
        let geometry = [snapshot.frame, roots[0].frame, grids[0].frame, navigations[0].frame,
                        titles[0].frame] + windows.map(\.frame) + [cells[0].frame]
        guard geometry.allSatisfy(visible) else { return nil }
        let window = windows.dropFirst().reduce(windows[0].frame) { $0.intersection($1.frame) }
        guard visible(window), window.contains(cells[0].frame), window.contains(titles[0].frame),
              snapshot.frame.contains(cells[0].frame), roots[0].frame.contains(cells[0].frame),
              grids[0].frame.contains(cells[0].frame), navigations[0].frame.contains(titles[0].frame) else { return nil }
        return geometry
    }


    private func openLocalFilesFolder(_ folder: String, app: XCUIApplication,
                                      initialNavigationTimeout: Duration = .seconds(15),
                                      retryRecoveryFolderEntry: Bool = false) async throws -> XCUIElement {
        let navigations = app.navigationBars.matching(identifier: "FullDocumentManagerViewControllerNavigationBar")
        let navigation = navigations.element
        try await wait("Files did not present its navigation", app: app, timeout: initialNavigationTimeout) {
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
        guard retryRecoveryFolderEntry else {
            try await wait("Files did not reach the exact synthetic folder", app: app) { atDestination() }
            return picker
        }
        // Preserve the original post-tap destination budget. Synchronous AX
        // queries may return after it, but never authorize a late second tap.
        let destinationDeadline = ContinuousClock.now.advanced(by: .seconds(15))
        var retryAvailable = true
        let localTitle = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        var previousGeometry: [CGRect]?
        while ContinuousClock.now < destinationDeadline {
            if atDestination() { return picker }
            if retryAvailable {
                guard ContinuousClock.now < destinationDeadline else { break }
                let observed = try? nativeFolderSnapshots(app)
                let geometry = observed.flatMap {
                    Self.recoveryFolderParentGeometry(in: $0.picker, applicationSnapshot: $0.application,
                                                      folder: folder, localTitle: localTitle)
                }
                if let geometry {
                    if let previousGeometry {
                        // A changed/ambiguous state consumes eligibility too.
                        // Never restart a stability sequence later in this wait.
                        retryAvailable = false
                        if geometry == previousGeometry {
                            guard ContinuousClock.now < destinationDeadline else { break }
                            if atDestination() { return picker }
                            guard ContinuousClock.now < destinationDeadline else { break }
                            let final = try? nativeFolderSnapshots(app)
                            let finalGeometry = final.flatMap {
                                Self.recoveryFolderParentGeometry(in: $0.picker, applicationSnapshot: $0.application,
                                                                  folder: folder, localTitle: localTitle)
                            }
                            guard ContinuousClock.now < destinationDeadline else { break }
                            if atDestination() { return picker }
                            guard ContinuousClock.now < destinationDeadline else { break }
                            let roots = picker.otherElements.matching(identifier:
                                "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " + localTitle)
                            let grids = roots.element.collectionViews.matching(identifier: "File View")
                            let directories = grids.element.cells.matching(identifier: folder + ", Folder")
                            let liveMatches = finalGeometry == geometry
                                && navigations.count == 1 && pickers.count == 1 && roots.count == 1 && grids.count == 1
                                && picker.frame == geometry[0] && roots.element.frame == geometry[1]
                                && grids.element.frame == geometry[2] && navigation.frame == geometry[3]
                                && isRecoveryFolder(localTitle, navigation: navigation)
                                && directories.count == 1 && directories.element.exists
                                && directories.element.isEnabled && directories.element.isHittable
                                && directories.element.frame == geometry.last && app.state == .runningForeground
                            guard ContinuousClock.now < destinationDeadline else { break }
                            if atDestination() { return picker }
                            if liveMatches, ContinuousClock.now < destinationDeadline {
                                print("Recovery folder navigation: one guarded retry in original destination budget")
                                directories.element.tap()
                            }
                        }
                    } else { previousGeometry = geometry }
                } else { retryAvailable = false }
            }
            if ContinuousClock.now < destinationDeadline {
                try await Task.sleep(for: .milliseconds(100))
            }
        }
        throw failure("Files did not reach the exact synthetic folder", app: app)
    }

    private func selectRealFiles(_ app: XCUIApplication, nativeRoot: Bool,
                                 observeLateFailure: Bool = true) async throws {
        let navigation = app.navigationBars["FullDocumentManagerViewControllerNavigationBar"].firstMatch
        let picker: XCUIElement
        if nativeRoot {
            picker = try await openNativeFilesRoot(app)
        } else {
            picker = try await openLocalFilesFolder(folder, app: app)
        }
        for filename in filenames {
            let basename = (filename as NSString).deletingPathExtension
            let matchingFiles = picker.cells.matching(NSPredicate(format: "label BEGINSWITH %@", basename))
            let file = matchingFiles.firstMatch
            try await wait("Missing selectable real Files original: \(filename)", app: app) { file.exists && file.isHittable }
            if nativeRoot {
                try check(isNativeFilesRoot(app) && matchingFiles.count == 1,
                          app: app, "Batch selection left its verified local root or unique original")
            }
            file.tap()
            try check(navigation.exists, app: app, "Files closed before both originals could be selected")
        }
        let openActions = picker.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", "Open", "Open ("))
        let open = openActions.firstMatch
        try await wait("Files did not expose Open after selecting both originals", app: app) { open.exists && open.isEnabled && open.isHittable }
        capture(app, "Two synthetic originals selected in real Files", batchDiagnostic: true)
        if nativeRoot {
            try check(isNativeFilesRoot(app) && openActions.count == 1,
                      app: app, "Batch selection left its verified local root or unique Open action")
        }
        open.tap()
        try await requireFilesDismissal(app, navigation: navigation, openedAt: .now,
                                        observeLateFailure: observeLateFailure)
    }

    private func requireFilesDismissal(_ app: XCUIApplication, navigation: XCUIElement,
                                      openedAt: ContinuousClock.Instant,
                                      observeLateFailure: Bool = true) async throws {
        do {
            try await wait("Files remained after opening the selection", app: app) { !navigation.exists }
        } catch let originalFailure as BatchTestFailure {
            // The seed control keeps its original 180-second allowance. Its
            // failed 15-second criterion already retained the current PNG/AX.
            guard observeLateFailure else { throw originalFailure }
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

    private func recordNativeFolderInitialFailure(_ observation: NativeFolderInitialObservation, localTitle: String) {
        let metadata = XCTAttachment(string: String(decoding: observation.metadata(), as: UTF8.self))
        metadata.name = "Native folder initial readiness — last actual attempt"
        metadata.lifetime = .keepAlways
        add(metadata)
        recordNativeFolderSnapshot(observation.picker, observation: "initial-current-picker-input",
                                   localTitle: localTitle, returnedFrame: nil, liveFrame: nil,
                                   reason: "See initial readiness metadata; this may be a partial/unbound acquisition.")
        recordNativeFolderSnapshot(observation.application, observation: "initial-current-application-input",
                                   localTitle: localTitle, returnedFrame: nil, liveFrame: nil,
                                   reason: "See initial readiness metadata; this may be a partial/unbound acquisition.")
        if let prior = observation.lastBound, prior.attempt != observation.attempt {
            recordNativeFolderSnapshot(prior.picker, observation: "initial-prior-bound-picker-input",
                                       localTitle: localTitle, returnedFrame: nil, liveFrame: nil,
                                       reason: "Prior bound attempt \(prior.attempt); NOT current failed acquisition.")
            recordNativeFolderSnapshot(prior.application, observation: "initial-prior-bound-application-input",
                                       localTitle: localTitle, returnedFrame: nil, liveFrame: nil,
                                       reason: "Prior bound attempt \(prior.attempt); NOT current failed acquisition.")
        }
    }

    private func recordNativeFolderSnapshot(
        _ snapshot: XCUIElementSnapshot?, observation: String, localTitle: String,
        returnedFrame: CGRect?, liveFrame: CGRect?, reason: String?
    ) {
        let data = Self.nativeFolderSnapshotEvidence(
            snapshot, observation: observation, expectedName: "untitled folder", localTitle: localTitle,
            returnedFrame: returnedFrame, liveFrame: liveFrame, reason: reason
        )
        let attachment = XCTAttachment(string: String(decoding: data, as: UTF8.self))
        attachment.name = "Native folder snapshot evidence — " + observation
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
