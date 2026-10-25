import Foundation
import Observation
import TravelCore
import UIKit

/// A single unsaved editor survives privacy-driven view teardown in memory only.
/// It is never serialized and is discarded when its source changes or is removed.
@MainActor @Observable
final class DocumentEditDraft: Identifiable {
    let source: TravelDocument
    nonisolated let id: UUID
    var title: String
    var kind: DocumentKind
    var travelerID: UUID?
    var hasExpiry: Bool
    var expiryDate: Date

    init(document: TravelDocument) {
        source = document
        id = document.id
        title = document.title
        kind = document.kind
        travelerID = document.travelerID
        hasExpiry = document.expiryDate != nil
        expiryDate = document.expiryDate.map { TravelDate.local(from: $0) } ?? .now
    }
}

@MainActor @Observable
final class AppModel {
    var library = LibrarySnapshot.empty {
        didSet {
            invalidateStaleDocumentEdit()
            invalidateStaleBatchImport()
        }
    }
    private(set) var documentEditDraft: DocumentEditDraft?
    private(set) var batchImportDraft: BatchImportDraft?
    var readiness: [UUID: DocumentReadiness] = [:]
    var isBusy = false
    var errorMessage: String?
    var notice: String?
    let purchases = PurchaseManager()

    @ObservationIgnored private var repository: DocumentRepository?
    @ObservationIgnored private var batchPreparationTask: Task<Void, Never>?
    @ObservationIgnored private var batchBusyOwner: UUID?
    @ObservationIgnored private let temporaryRoot: URL
    @ObservationIgnored private let proEntitlement: (@MainActor () -> Bool)?
    @ObservationIgnored private let readExternalFile: @Sendable (URL, Int) async throws -> Data
    private static let documentLimit = 16 * 1024 * 1024
    private static let backupLimit = 96 * 1024 * 1024

    private var hasPro: Bool { proEntitlement?() ?? purchases.isPro }
    var canAddTrip: Bool { hasPro || library.trips.count < 1 }
    var canAddTraveler: Bool { hasPro || library.travelers.count < 2 }
    var canAddDocument: Bool { hasPro || library.documents.count < 8 }

    // Controllable inputs make suspension-point policy tests deterministic.
    // The app uses verified StoreKit rights and bounded, security-scoped reads.
    init(rootURL: URL? = nil,
         temporaryRootURL: URL? = nil,
         proEntitlement: (@MainActor () -> Bool)? = nil,
         readExternal: @escaping @Sendable (URL, Int) async throws -> Data = AppModel.readExternal) {
        self.proEntitlement = proEntitlement
        self.readExternalFile = readExternal
        let fm = FileManager.default
        let support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        temporaryRoot = temporaryRootURL ?? fm.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("TripfolioExports", isDirectory: true)
        // Abandoned presentation copies are disposable. A cleanup failure must
        // not prevent opening the independent, persistent document library.
        if fm.fileExists(atPath: temporaryRoot.path) { try? fm.removeItem(at: temporaryRoot) }
        do {
            var libraryURL = rootURL ?? support.appendingPathComponent("Tripfolio", isDirectory: true)
            #if DEBUG
            // UI automation uses a dedicated synthetic library. These flags are
            // absent from Release and never reset a user's real library.
            if rootURL == nil && ProcessInfo.processInfo.arguments.contains("--ui-testing-unlocked") {
                libraryURL = support.appendingPathComponent("TripfolioUITesting", isDirectory: true)
                if ProcessInfo.processInfo.arguments.contains("--ui-testing-reset"), fm.fileExists(atPath: libraryURL.path) {
                    try fm.removeItem(at: libraryURL)
                }
            }
            #endif
            repository = try DocumentRepository(rootURL: libraryURL)
        } catch {
            errorMessage = L10n.service("services.model.open.failed", defaultValue: "The local library could not be opened. Your existing files have not been replaced. \(error.localizedDescription)")
        }
    }

    func refresh() async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do { library = try await repository.load() }
        catch { errorMessage = error.localizedDescription }
    }

    func createTrip(title: String, departureDate: Date?) async {
        guard !isBusy, let repository else { return }
        guard canAddTrip else { errorMessage = L10n.service("services.model.free.trip", defaultValue: "Free includes one trip. Pro adds more trips; your existing documents remain available."); return }
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await repository.createTrip(title: title, departureDate: departureDate.map { TravelDate.stored(from: $0) })
            library = try await repository.load()
        } catch { errorMessage = error.localizedDescription }
    }

    func addTraveler(name: String) async {
        guard !isBusy, let repository else { return }
        guard canAddTraveler else { errorMessage = L10n.service("services.model.free.travelers", defaultValue: "Free includes two travelers. Pro adds more people."); return }
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await repository.addTraveler(name: name)
            library = try await repository.load()
        } catch { errorMessage = error.localizedDescription }
    }

    func updateTrip(id: UUID, title: String, departureDate: Date?) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await repository.updateTrip(id: id, title: title, departureDate: departureDate.map { TravelDate.stored(from: $0) })
            library = try await repository.load()
        } catch { errorMessage = error.localizedDescription }
    }

    func deleteTrip(id: UUID) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        let documents = library.documents.filter { $0.tripID == id }
        do {
            try await repository.deleteTrip(id: id)
            library = try await repository.load()
            clearTemporaryCopies()
            for document in documents {
                readiness[document.id] = nil
                ReminderService.cancel(documentID: document.id)
            }
        } catch { errorMessage = error.localizedDescription }
    }

    func updateTraveler(id: UUID, name: String) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await repository.updateTraveler(id: id, name: name)
            library = try await repository.load()
        } catch { errorMessage = error.localizedDescription }
    }

    func deleteTraveler(id: UUID) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await repository.deleteTraveler(id: id)
            library = try await repository.load()
        } catch { errorMessage = error.localizedDescription }
    }

    func beginEditingDocument(_ document: TravelDocument) {
        guard batchImportDraft == nil else {
            errorMessage = L10n.service("services.model.edit.finishBatch", defaultValue: "Finish or cancel the current file batch before editing a document.")
            return
        }
        guard !isBusy, library.documents.contains(document) else { return }
        if documentEditDraft?.source != document {
            documentEditDraft = DocumentEditDraft(document: document)
        }
    }

    func cancelDocumentEdit() { documentEditDraft = nil }

    func saveDocumentEdit() async {
        guard !isBusy, let draft = documentEditDraft else { return }
        invalidateStaleDocumentEdit()
        guard documentEditDraft === draft else {
            errorMessage = L10n.service("services.model.edit.documentChanged", defaultValue: "This document changed while you were editing. Open its current details and try again.")
            return
        }
        errorMessage = nil
        let saved = await updateDocument(id: draft.id, title: draft.title,
            travelerID: draft.travelerID, kind: draft.kind,
            expiryDate: draft.hasExpiry ? draft.expiryDate : nil)
        if saved, documentEditDraft === draft { documentEditDraft = nil }
    }

    private func invalidateStaleDocumentEdit() {
        guard let draft = documentEditDraft else { return }
        guard library.documents.contains(draft.source),
              draft.travelerID == nil || library.travelers.contains(where: { $0.id == draft.travelerID }) else {
            documentEditDraft = nil
            return
        }
    }

    @discardableResult
    func updateDocument(id: UUID, title: String, travelerID: UUID?, kind: DocumentKind, expiryDate: Date?) async -> Bool {
        guard !isBusy, let repository else { return false }
        isBusy = true
        defer { isBusy = false }
        do {
            try await repository.updateDocument(id: id, title: title, travelerID: travelerID, kind: kind, expiryDate: expiryDate.map { TravelDate.stored(from: $0) })
            library = try await repository.load()
            ReminderService.cancel(documentID: id)
            notice = L10n.service("services.model.edit.updated", defaultValue: "Details updated. Schedule the reminder again if needed.")
            return true
        } catch { errorMessage = error.localizedDescription; return false }
    }

    func importFile(url: URL, tripID: UUID, travelerID: UUID?, title: String, kind: DocumentKind, expiryDate: Date?) async {
        guard !isBusy, let repository else { return }
        guard canAddDocument else { errorMessage = L10n.service("services.model.free.documentsAccess", defaultValue: "Free includes eight documents. Pro adds more; viewing, export and recovery stay available."); return }
        isBusy = true
        defer { isBusy = false }
        do {
            try Task.checkCancellation()
            let data = try await readExternalFile(url, Self.documentLimit)
            try Task.checkCancellation()
            // A provider read can outlive a refund. Re-evaluate the current
            // quota before submitting a new storage transaction; existing
            // originals and recovery never depend on this addition right.
            guard canAddDocument else {
                errorMessage = L10n.service("services.model.free.documentsAccess", defaultValue: "Free includes eight documents. Pro adds more; viewing, export and recovery stay available.")
                return
            }
            _ = try await repository.importDocument(data: data, originalFilename: url.lastPathComponent, tripID: tripID, travelerID: travelerID, title: title, kind: kind, expiryDate: expiryDate.map { TravelDate.stored(from: $0) })
            library = try await repository.load()
            readiness = [:]
            notice = L10n.service("services.model.import.originalCopied", defaultValue: "Original copied into the local library. Run the offline check before you travel.")
        } catch is CancellationError {
            // No storage mutation was submitted; keep the current library.
        } catch { errorMessage = error.localizedDescription }
    }

    func importData(_ data: Data, filename: String, tripID: UUID, travelerID: UUID?, title: String, kind: DocumentKind, expiryDate: Date?) async {
        guard !isBusy, let repository else { return }
        guard canAddDocument else { errorMessage = L10n.service("services.model.free.documents", defaultValue: "Free includes eight documents. Pro adds more documents."); return }
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await repository.importDocument(data: data, originalFilename: filename, tripID: tripID, travelerID: travelerID, title: title, kind: kind, expiryDate: expiryDate.map { TravelDate.stored(from: $0) })
            library = try await repository.load()
            readiness = [:]
            notice = L10n.service("services.model.import.saved", defaultValue: "Document saved on this device.")
        } catch { errorMessage = error.localizedDescription }
    }

    func checkReadiness(tripID: UUID) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            let results = try await repository.verifyReadiness(tripID: tripID)
            for result in results { readiness[result.documentID] = result }
            let verified = results.filter { $0.state == .ready }.count
            notice = results.isEmpty ? L10n.service("services.model.readiness.empty", defaultValue: "Add documents before running an offline check.") : L10n.service("services.model.readiness.verified", defaultValue: "\(verified) of \(results.count) originals verified on this device. Review any missing or changed files, then open each document to confirm its contents are the ones you need.")
        } catch { errorMessage = error.localizedDescription }
    }

    func deleteDocument(id: UUID) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await repository.deleteDocument(id: id)
            library = try await repository.load()
            clearTemporaryCopies()
            readiness[id] = nil
            ReminderService.cancel(documentID: id)
        } catch { errorMessage = error.localizedDescription }
    }

    func makeBackup(documentIDs: Set<UUID>?) async -> URL? {
        guard !isBusy, let repository else { return nil }
        isBusy = true
        defer { isBusy = false }
        do {
            let data = try await repository.exportBackup(documentIDs: documentIDs)
            return try writeTemporary(data, filename: "Documents.tripbackup")
        } catch { errorMessage = error.localizedDescription; return nil }
    }

    func restoreBackup(url: URL) async {
        guard !isBusy, let repository else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try Task.checkCancellation()
            let data = try await readExternalFile(url, Self.backupLimit)
            try Task.checkCancellation()
            library = try await repository.restoreBackup(data)
            documentEditDraft = nil
            if let draft = batchImportDraft { discardBatchImport(draftID: draft.id) }
            readiness = [:]
            clearTemporaryCopies()
            ReminderService.cancelAll()
            notice = L10n.service("services.model.restore.completed", defaultValue: "Backup restored and originals verified. Schedule reminders again on this device.")
        } catch is CancellationError {
            // Preserve the library, readiness results, and unsaved editor.
        } catch { errorMessage = L10n.service("services.model.restore.failed", defaultValue: "Restore did not replace your library. \(error.localizedDescription)") }
    }

    func previewURL(documentID: UUID) async -> URL? {
        guard !isBusy, let repository,
              let document = library.documents.first(where: { $0.id == documentID }) else { return nil }
        isBusy = true
        defer { isBusy = false }
        do {
            let data = try await repository.documentData(id: documentID)
            let suffix = URL(fileURLWithPath: document.storedFilename).pathExtension
            return try writeTemporary(data, filename: "Document.\(suffix)")
        } catch { errorMessage = error.localizedDescription; return nil }
    }

    private func writeTemporary(_ data: Data, filename: String) throws -> URL {
        let fm = FileManager.default
        // Only one document/packet presentation can be active. Clear abandoned
        // copies before creating the next one, bounding cache use across a long
        // running session as well as on normal sheet dismissal.
        if fm.fileExists(atPath: temporaryRoot.path) { try fm.removeItem(at: temporaryRoot) }
        var directory = temporaryRoot.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: directory, withIntermediateDirectories: true,
                               attributes: [.protectionKey: FileProtectionType.complete])
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        let url = directory.appendingPathComponent(filename)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        return url
    }

    func removeTemporary(_ url: URL) {
        let parent = url.deletingLastPathComponent().standardizedFileURL
        guard parent.deletingLastPathComponent() == temporaryRoot.standardizedFileURL,
              UUID(uuidString: parent.lastPathComponent) != nil else { return }
        try? FileManager.default.removeItem(at: parent)
    }

    private func clearTemporaryCopies() {
        try? FileManager.default.removeItem(at: temporaryRoot)
    }

    nonisolated static func readExternal(_ url: URL, maximum: Int) async throws -> Data {
        try Task.checkCancellation()
        let read = Task.detached(priority: .userInitiated) {
            try Task.checkCancellation()
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true, let size = values.fileSize, size > 0, size <= maximum else {
                throw ImportError.unsupportedSize
            }
            // The provider may change a file after the metadata check. Bound the
            // read itself, so a racing or misreported file cannot fill memory.
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            var data = Data()
            while true {
                try Task.checkCancellation()
                let chunk = try handle.read(upToCount: min(1_024 * 1_024, maximum - data.count + 1)) ?? Data()
                if chunk.isEmpty { break }
                guard data.count + chunk.count <= maximum else { throw ImportError.unsupportedSize }
                data.append(chunk)
            }
            guard !data.isEmpty else { throw ImportError.unsupportedSize }
            return data
        }
        return try await withTaskCancellationHandler {
            let data = try await read.value
            try Task.checkCancellation()
            return data
        } onCancel: {
            read.cancel()
        }
    }

    private enum ImportError: LocalizedError {
        case unsupportedSize
        var errorDescription: String? { L10n.service("services.model.import.sizeError", defaultValue: "Choose a complete file. Documents are limited to 16 MB; backup files to 96 MB. Download cloud files in Files before importing if they are not available.") }
    }

    #if DEBUG
    func installSyntheticDemoIfEmpty() async {
        guard library.trips.isEmpty, !isBusy else { return }
        await createTrip(title: "Coast weekend", departureDate: Calendar.current.date(byAdding: .day, value: 14, to: .now))
        await addTraveler(name: "Alex Example")
        guard let trip = library.trips.first else { return }
        let pdf = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 595, height: 842)).pdfData { context in
            context.beginPage()
            // Localize authored captions when creating a new synthetic fixture;
            // persisted names, titles, codes and existing PDF bytes stay unchanged.
            let demoText = [
                L10n.service("services.demo.warning", defaultValue: "SYNTHETIC DEMO — NOT VALID FOR TRAVEL"),
                "",
                "Coast weekend",
                L10n.service("services.demo.reservation", defaultValue: "Sample reservation \("ABC-000")"),
                "Alex Example",
                "",
                L10n.service("services.demo.explanation", defaultValue: "This is a fictional fixture for screenshots and tests.")
            ].joined(separator: "\n")
            NSString(string: demoText).draw(in: CGRect(x: 40, y: 60, width: 500, height: 700), withAttributes: [.font: UIFont.systemFont(ofSize: 20)])
        }
        await importData(pdf, filename: "sample-reservation.pdf", tripID: trip.id, travelerID: library.travelers.first?.id, title: "Weekend reservation", kind: .booking, expiryDate: nil)
        await checkReadiness(tripID: trip.id)
    }
    #endif
}

extension AppModel {
    /// Entitlement only: phase/busy checks belong to each action. An existing
    /// reviewing draft remains readable after Pro changes, but cannot be saved.
    var canUseBatchImport: Bool { hasPro }

    var remainingLibraryBytes: Int {
        var remaining = DocumentRepository.maximumLibraryBytes
        for document in library.documents {
            guard document.byteCount >= 0, document.byteCount <= remaining else { return 0 }
            remaining -= document.byteCount
        }
        return remaining
    }

    func beginBatchImport(tripID: UUID) {
        guard !isBusy else { return }
        guard documentEditDraft == nil else {
            errorMessage = L10n.service("services.model.batch.finishEdit", defaultValue: "Finish or cancel the document edit before starting a file batch.")
            return
        }
        guard batchImportDraft == nil else {
            errorMessage = L10n.service("services.model.batch.finishCurrent", defaultValue: "Finish or cancel the current file batch before starting another.")
            return
        }
        guard canUseBatchImport else { errorMessage = BatchImportError.proRequired.localizedDescription; return }
        guard repository != nil, library.trips.contains(where: { $0.id == tripID }) else {
            errorMessage = RepositoryError.tripNotFound.localizedDescription
            return
        }
        batchImportDraft = BatchImportDraft(tripID: tripID, sourceLibrary: library)
    }

    func prepareBatchImport(urls: [URL], draftID: UUID) {
        guard let draft = batchImportDraft, draft.id == draftID,
              draft.phase == .choosing, !isBusy else { return }
        guard canUseBatchImport else { draft.errorMessage = BatchImportError.proRequired.localizedDescription; return }
        guard (1...10).contains(urls.count) else {
            draft.errorMessage = BatchImportError.invalidSelection.localizedDescription
            return
        }
        guard draft.sourceLibrary == library, library.trips.contains(where: { $0.id == draft.tripID }) else {
            invalidateStaleBatchImport()
            return
        }
        draft.errorMessage = nil
        draft.items = []
        draft.preparedCount = 0
        draft.selectedCount = urls.count
        draft.phase = .preparing
        batchBusyOwner = draftID
        isBusy = true
        batchPreparationTask = Task { [weak self] in
            await self?.prepareBatchFiles(urls, draftID: draftID)
        }
    }

    func cancelBatchImport(draftID: UUID) {
        guard let draft = batchImportDraft, draft.id == draftID,
              draft.phase != .committing else { return }
        discardBatchImport(draftID: draftID)
    }

    func confirmBatchItem(id: UUID) {
        guard let draft = batchImportDraft, draft.phase == .reviewing,
              let item = draft.items.first(where: { $0.id == id }) else { return }
        do {
            try item.validateMetadata(in: library)
            item.confirm()
            draft.errorMessage = nil
        } catch { draft.errorMessage = error.localizedDescription }
    }

    func removeBatchItem(id: UUID) {
        guard let draft = batchImportDraft, draft.phase == .reviewing else { return }
        draft.items.removeAll { $0.id == id }
        draft.preparedCount = draft.items.count
        draft.errorMessage = nil
    }

    func batchPreviewURL(itemID: UUID) -> URL? {
        guard let draft = batchImportDraft, draft.phase == .reviewing, !isBusy,
              let item = draft.items.first(where: { $0.id == itemID }) else { return nil }
        do {
            return try writeTemporary(item.originalData, filename: "Document.\(item.fileExtension)")
        } catch { draft.errorMessage = error.localizedDescription; return nil }
    }

    @discardableResult
    func commitBatchImport(draftID: UUID) async -> Bool {
        guard let draft = batchImportDraft, draft.id == draftID,
              draft.phase == .reviewing, !isBusy, let repository else { return false }
        guard canUseBatchImport else { draft.errorMessage = BatchImportError.proRequired.localizedDescription; return false }
        guard draft.sourceLibrary == library, library.trips.contains(where: { $0.id == draft.tripID }) else {
            invalidateStaleBatchImport()
            return false
        }
        guard draft.canSave else { draft.errorMessage = BatchImportError.reviewRequired.localizedDescription; return false }
        do {
            try Task.checkCancellation()
            var remaining = remainingLibraryBytes
            for item in draft.items {
                try item.validateMetadata(in: library)
                guard item.byteCount <= remaining else { throw BatchImportError.noSpace }
                remaining -= item.byteCount
            }
            let inputs = draft.items.map { $0.importInput() }
            draft.phase = .committing
            draft.errorMessage = nil
            batchBusyOwner = draftID
            isBusy = true
            defer {
                if batchBusyOwner == draftID {
                    batchBusyOwner = nil
                    isBusy = false
                }
            }
            // No suspension between the final entitlement/metadata checks and
            // submission. Cancellation after publication must not undo a save.
            let saved = try await repository.importDocuments(inputs, tripID: draft.tripID)
            var committed = draft.sourceLibrary
            committed.documents.append(contentsOf: saved)
            library = committed
            readiness = [:]
            notice = L10n.service("services.model.batch.saved", defaultValue: "\(saved.count) original files saved together on this device. Run the offline check before you travel.")
            // Use returned committed models instead of a fallible second load,
            // which could otherwise make a successful save look retryable.
            discardBatchImport(draftID: draftID)
            return true
        } catch is CancellationError {
            if batchImportDraft?.id == draftID {
                draft.phase = .reviewing
                draft.errorMessage = L10n.service("services.model.batch.cancelled", defaultValue: "Saving was cancelled before the batch was committed. No files were added.")
            }
            return false
        } catch {
            if batchImportDraft?.id == draftID {
                draft.phase = .reviewing
                draft.errorMessage = error.localizedDescription
            }
            return false
        }
    }

    private func prepareBatchFiles(_ urls: [URL], draftID: UUID) async {
        defer {
            if batchBusyOwner == draftID {
                batchPreparationTask = nil
                batchBusyOwner = nil
                isBusy = false
            }
        }
        do {
            for url in urls {
                try Task.checkCancellation()
                guard let draft = batchImportDraft, draft.id == draftID else { return }
                guard canUseBatchImport else { throw BatchImportError.proRequired }
                guard draft.sourceLibrary == library else { throw BatchImportError.libraryChanged }
                let used = draft.items.reduce(0) { $0 + $1.byteCount }
                let remaining = remainingLibraryBytes - used
                guard remaining > 0 else { throw BatchImportError.noSpace }
                let maximum = min(DocumentRepository.maximumDocumentBytes, remaining)
                let filename = url.lastPathComponent
                guard !filename.isEmpty, filename != ".", filename != "..", filename.utf8.count <= 255,
                      !filename.contains("/"), !filename.contains("\\"),
                      !filename.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else {
                    throw BatchImportError.invalidFilename
                }
                let data: Data
                do {
                    data = try await readExternalFile(url, maximum)
                } catch ImportError.unsupportedSize where maximum < DocumentRepository.maximumDocumentBytes {
                    throw BatchImportError.noSpace
                }
                try Task.checkCancellation()
                guard batchImportDraft?.id == draftID else { return }
                guard canUseBatchImport else { throw BatchImportError.proRequired }
                guard draft.sourceLibrary == library else { throw BatchImportError.libraryChanged }
                guard data.count <= DocumentRepository.maximumDocumentBytes else { throw RepositoryError.documentTooLarge }
                guard data.count <= remaining else { throw BatchImportError.noSpace }
                try await Self.validateBatchData(data)
                try Task.checkCancellation()
                guard batchImportDraft?.id == draftID else { return }
                guard canUseBatchImport else { throw BatchImportError.proRequired }
                guard draft.sourceLibrary == library else { throw BatchImportError.libraryChanged }
                draft.items.append(BatchImportItem(filename: filename, data: data))
                draft.preparedCount += 1
            }
            guard let draft = batchImportDraft, draft.id == draftID else { return }
            draft.phase = .reviewing
        } catch is CancellationError {
            if batchImportDraft?.id == draftID { discardBatchImport(draftID: draftID) }
        } catch {
            guard let draft = batchImportDraft, draft.id == draftID else { return }
            draft.items = []
            draft.preparedCount = 0
            draft.phase = .choosing
            draft.errorMessage = error.localizedDescription
        }
    }

    private func invalidateStaleBatchImport() {
        guard let draft = batchImportDraft, draft.phase != .committing,
              draft.sourceLibrary != library || !library.trips.contains(where: { $0.id == draft.tripID }) else { return }
        discardBatchImport(draftID: draft.id)
        errorMessage = BatchImportError.libraryChanged.localizedDescription
    }

    private func discardBatchImport(draftID: UUID) {
        guard let draft = batchImportDraft, draft.id == draftID else { return }
        batchPreparationTask?.cancel()
        batchPreparationTask = nil
        draft.items = []
        batchImportDraft = nil
        if batchBusyOwner == draftID {
            batchBusyOwner = nil
            isBusy = false
        }
    }

    nonisolated private static func validateBatchData(_ data: Data) async throws {
        let validation = Task.detached(priority: .userInitiated) {
            try Task.checkCancellation()
            try DocumentRepository.validateImportData(data)
            try Task.checkCancellation()
        }
        try await withTaskCancellationHandler {
            try await validation.value
        } onCancel: {
            validation.cancel()
        }
    }
}
