import Foundation
import CryptoKit
import Darwin
import CoreGraphics
import ImageIO

/// The repository is the sole writer of its root directory. A complete generation
/// is published by one atomic pointer write; incomplete generations are never read.
/// This provides transaction consistency across process interruptions. Files and
/// directories are flushed to reduce power-loss exposure, but OS/hardware flush
/// behavior is not a guarantee against physical storage failure or sudden power loss.
/// Backups are portable plaintext JSON containers, not encrypted vaults.
public actor DocumentRepository {
    public static let maximumDocumentBytes = 16 * 1_024 * 1_024
    public static let maximumLibraryBytes = 64 * 1_024 * 1_024
    public static let maximumBackupBytes = 96 * 1_024 * 1_024
    public static let maximumImportBatchCount = 10
    private static let maximumCatalogBytes = 2 * 1_024 * 1_024
    private static let maximumItems = 1_000
    private let rootURL: URL
    private let fileWriter: @Sendable (Data, URL) throws -> Void

    private struct Pointer: Codable {
        let formatVersion: Int
        let generation: String
    }

    private struct BackupOriginal: Codable {
        let documentID: UUID
        let data: Data
    }

    private struct BackupArchive: Codable {
        let formatVersion: Int
        let library: LibrarySnapshot
        let originals: [BackupOriginal]
    }

    public init(rootURL: URL) throws {
        try self.init(rootURL: rootURL, fileWriter: Self.writeProtected)
    }

    // Internal I/O injection lets tests fail writes with real Cocoa storage errors
    // at a deterministic transaction boundary; production always uses protected I/O.
    init(rootURL: URL, fileWriter: @escaping @Sendable (Data, URL) throws -> Void) throws {
        guard rootURL.isFileURL else { throw RepositoryError.storageUnavailable }
        self.rootURL = rootURL.standardizedFileURL
        self.fileWriter = fileWriter
        do {
            try FileManager.default.createDirectory(at: self.rootURL, withIntermediateDirectories: true)
            let values = try self.rootURL.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            guard values.isDirectory == true, values.isSymbolicLink != true else {
                throw RepositoryError.storageUnavailable
            }
            try Self.protect(self.rootURL)
            try Self.bootstrapEmptyPointer(at: self.rootURL, fileWriter: fileWriter)
        } catch {
            throw RepositoryError.storageUnavailable
        }
    }

    public func load() throws -> LibrarySnapshot {
        try current().library
    }

    /// Checks one complete original before the app offers it for confirmation.
    /// Import repeats this validation and also enforces the whole-library limit.
    public nonisolated static func validateImportData(_ data: Data) throws {
        guard data.count <= maximumDocumentBytes else { throw RepositoryError.documentTooLarge }
        _ = try fileExtension(for: data)
    }

    public func createTrip(title: String, departureDate: Date?) throws -> Trip {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validName(title), Self.validDate(departureDate) else { throw RepositoryError.invalidName }
        var state = try current()
        let trip = Trip(title: title, departureDate: departureDate)
        state.library.trips.append(trip)
        try commit(state.library, source: state.directory)
        return trip
    }

    public func addTraveler(name: String) throws -> Traveler {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validName(name) else { throw RepositoryError.invalidName }
        var state = try current()
        let traveler = Traveler(name: name)
        state.library.travelers.append(traveler)
        try commit(state.library, source: state.directory)
        return traveler
    }

    public func importDocument(data: Data, originalFilename: String, tripID: UUID,
                               travelerID: UUID?, title: String, kind: DocumentKind,
                               expiryDate: Date?) throws -> TravelDocument {
        let input = DocumentImportInput(data: data, originalFilename: originalFilename,
            travelerID: travelerID, title: title, kind: kind, expiryDate: expiryDate)
        return try importDocuments([input], tripID: tripID)[0]
    }

    /// Publishes the entire confirmed selection together and returns documents
    /// in input order. A validation, staging, or cancellation failure before
    /// publication preserves the prior library, with no successfully imported prefix.
    public func importDocuments(_ inputs: [DocumentImportInput], tripID: UUID) throws -> [TravelDocument] {
        try Task.checkCancellation()
        guard (1...Self.maximumImportBatchCount).contains(inputs.count) else {
            throw RepositoryError.invalidImportCount
        }
        var state = try current()
        guard state.library.trips.contains(where: { $0.id == tripID }) else {
            throw RepositoryError.missingReference
        }
        guard state.library.documents.count + inputs.count <= Self.maximumItems else {
            throw RepositoryError.libraryTooLarge
        }
        var total = state.library.documents.reduce(0) { $0 + $1.byteCount }
        for input in inputs {
            try Task.checkCancellation()
            guard input.data.count <= Self.maximumDocumentBytes else { throw RepositoryError.documentTooLarge }
            // Bound the complete request before parsing or staging any file.
            guard input.data.count <= Self.maximumLibraryBytes - total else { throw RepositoryError.libraryTooLarge }
            total += input.data.count
        }
        var documents: [TravelDocument] = []
        var originals: [UUID: Data] = [:]
        for input in inputs {
            try Task.checkCancellation()
            let title = input.title.trimmingCharacters(in: .whitespacesAndNewlines)
            guard Self.validName(title), Self.validFilename(input.originalFilename), Self.validDate(input.expiryDate) else {
                throw RepositoryError.invalidName
            }
            guard input.travelerID == nil || state.library.travelers.contains(where: { $0.id == input.travelerID }) else {
                throw RepositoryError.missingReference
            }
            let fileExtension = try Self.fileExtension(for: input.data)
            let id = UUID()
            let document = TravelDocument(id: id, tripID: tripID, travelerID: input.travelerID,
                title: title, kind: input.kind, expiryDate: input.expiryDate, originalFilename: input.originalFilename,
                storedFilename: id.uuidString.lowercased() + "." + fileExtension,
                byteCount: input.data.count, sha256: Self.hash(input.data))
            documents.append(document)
            originals[id] = input.data
        }
        state.library.documents.append(contentsOf: documents)
        try commit(state.library, source: state.directory, replacementData: originals)
        return documents
    }

    public func documentData(id: UUID) throws -> Data {
        let state = try current()
        guard let document = state.library.documents.first(where: { $0.id == id }),
              let directory = state.directory else { throw RepositoryError.documentNotFound }
        return try readOriginal(document, directory: directory)
    }

    public func verifyReadiness(tripID: UUID) throws -> [DocumentReadiness] {
        let state = try current()
        guard state.library.trips.contains(where: { $0.id == tripID }) else { throw RepositoryError.missingReference }
        return state.library.documents.filter { $0.tripID == tripID }.map { document in
            let readiness: ReadinessState
            do {
                guard let directory = state.directory else { throw RepositoryError.originalMissing }
                _ = try readOriginal(document, directory: directory)
                readiness = .ready
            } catch RepositoryError.originalMissing {
                readiness = .missing
            } catch RepositoryError.originalModified {
                readiness = .modified
            } catch {
                readiness = .unreadable
            }
            return DocumentReadiness(documentID: document.id, state: readiness)
        }
    }

    /// nil exports the entire library, including empty trips. An explicit selection
    /// exports only selected documents and their referenced trips and travelers.
    public func exportBackup(documentIDs: Set<UUID>?) throws -> Data {
        let state = try current()
        var selected = state.library
        if let documentIDs {
            guard documentIDs.isSubset(of: Set(selected.documents.map(\.id))) else {
                throw RepositoryError.documentNotFound
            }
            selected.documents = selected.documents.filter { documentIDs.contains($0.id) }
            let tripIDs = Set(selected.documents.map(\.tripID))
            let travelerIDs = Set(selected.documents.compactMap(\.travelerID))
            selected.trips = selected.trips.filter { tripIDs.contains($0.id) }
            selected.travelers = selected.travelers.filter { travelerIDs.contains($0.id) }
        }
        let originals = try selected.documents.map { document in
            guard let directory = state.directory else { throw RepositoryError.originalMissing }
            return BackupOriginal(documentID: document.id, data: try readOriginal(document, directory: directory))
        }
        let data = try Self.encode(BackupArchive(formatVersion: 1, library: selected, originals: originals))
        guard data.count <= Self.maximumBackupBytes else { throw RepositoryError.archiveTooLarge }
        return data
    }

    /// Replaces the whole library only after all complete originals have passed
    /// validation and the replacement generation has been durably written.
    @discardableResult
    public func restoreBackup(_ data: Data) throws -> LibrarySnapshot {
        guard data.count <= Self.maximumBackupBytes else { throw RepositoryError.archiveTooLarge }
        let archive: BackupArchive
        do {
            archive = try JSONDecoder().decode(BackupArchive.self, from: data)
        } catch {
            throw RepositoryError.invalidArchive
        }
        guard archive.formatVersion == 1 else { throw RepositoryError.unsupportedSchema }
        try Self.validate(archive.library)
        guard archive.originals.count == archive.library.documents.count else { throw RepositoryError.invalidArchive }
        var originals: [UUID: Data] = [:]
        for original in archive.originals {
            guard originals[original.documentID] == nil else { throw RepositoryError.duplicateIdentifier }
            guard original.data.count <= Self.maximumDocumentBytes else { throw RepositoryError.documentTooLarge }
            originals[original.documentID] = original.data
        }
        for document in archive.library.documents {
            guard let original = originals[document.id] else { throw RepositoryError.invalidArchive }
            try Self.validateOriginal(original, document: document)
        }
        // A corrupted old catalog need not prevent recovery from a good backup.
        try commit(archive.library, source: nil, replacementData: originals)
        return archive.library
    }

    public func deleteDocument(id: UUID) throws {
        var state = try current()
        guard state.library.documents.contains(where: { $0.id == id }) else { throw RepositoryError.documentNotFound }
        state.library.documents.removeAll { $0.id == id }
        try commit(state.library, source: state.directory)
    }

    /// Deletes the trip and its documents in one transaction. Travelers remain
    /// available for other trips. The caller must obtain deletion confirmation.
    public func deleteTrip(id: UUID) throws {
        var state = try current()
        guard state.library.trips.contains(where: { $0.id == id }) else { throw RepositoryError.tripNotFound }
        state.library.trips.removeAll { $0.id == id }
        state.library.documents.removeAll { $0.tripID == id }
        try commit(state.library, source: state.directory)
    }

    /// Removes the person while preserving every original. Associated documents
    /// become unassigned; no implicit cascading document deletion occurs.
    public func deleteTraveler(id: UUID) throws {
        var state = try current()
        guard state.library.travelers.contains(where: { $0.id == id }) else { throw RepositoryError.travelerNotFound }
        state.library.travelers.removeAll { $0.id == id }
        for index in state.library.documents.indices where state.library.documents[index].travelerID == id {
            state.library.documents[index].travelerID = nil
        }
        try commit(state.library, source: state.directory)
    }

    @discardableResult
    public func updateTrip(id: UUID, title: String, departureDate: Date?) throws -> Trip {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validName(title), Self.validDate(departureDate) else { throw RepositoryError.invalidName }
        var state = try current()
        guard let index = state.library.trips.firstIndex(where: { $0.id == id }) else { throw RepositoryError.tripNotFound }
        state.library.trips[index].title = title
        state.library.trips[index].departureDate = departureDate
        try commit(state.library, source: state.directory)
        return state.library.trips[index]
    }

    @discardableResult
    public func updateTraveler(id: UUID, name: String) throws -> Traveler {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validName(name) else { throw RepositoryError.invalidName }
        var state = try current()
        guard let index = state.library.travelers.firstIndex(where: { $0.id == id }) else { throw RepositoryError.travelerNotFound }
        state.library.travelers[index].name = name
        try commit(state.library, source: state.directory)
        return state.library.travelers[index]
    }

    /// Edits human-confirmed metadata only. IDs, trip assignment, import time,
    /// filenames, complete original bytes, and their recorded hash are immutable.
    @discardableResult
    public func updateDocument(id: UUID, title: String, travelerID: UUID?, kind: DocumentKind,
                               expiryDate: Date?) throws -> TravelDocument {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validName(title), Self.validDate(expiryDate) else { throw RepositoryError.invalidName }
        var state = try current()
        guard let index = state.library.documents.firstIndex(where: { $0.id == id }) else { throw RepositoryError.documentNotFound }
        guard travelerID == nil || state.library.travelers.contains(where: { $0.id == travelerID }) else {
            throw RepositoryError.missingReference
        }
        state.library.documents[index].title = title
        state.library.documents[index].travelerID = travelerID
        state.library.documents[index].kind = kind
        state.library.documents[index].expiryDate = expiryDate
        try commit(state.library, source: state.directory)
        return state.library.documents[index]
    }

    private func current() throws -> (library: LibrarySnapshot, directory: URL?) {
        let pointerURL = rootURL.appendingPathComponent("active.json")
        let pointerData: Data
        do {
            pointerData = try Self.readBoundedFile(pointerURL, maximum: 1_024)
        } catch {
            guard Self.isMissingFile(error) else { throw RepositoryError.invalidCatalog }
            // A missing pointer with surviving generations is corruption, not a
            // new empty library. Never overwrite or garbage-collect this evidence.
            guard let children = try? FileManager.default.contentsOfDirectory(at: rootURL,
                includingPropertiesForKeys: nil),
                  !children.contains(where: { UUID(uuidString: $0.lastPathComponent) != nil }) else {
                throw RepositoryError.invalidCatalog
            }
            return (.empty, nil)
        }
        do {
            let pointer = try JSONDecoder().decode(Pointer.self, from: pointerData)
            guard pointer.formatVersion == 1 else { throw RepositoryError.invalidCatalog }
            if pointer.generation == "empty" { return (.empty, nil) }
            guard UUID(uuidString: pointer.generation)?.uuidString.lowercased() == pointer.generation else {
                throw RepositoryError.invalidCatalog
            }
            let directory = rootURL.appendingPathComponent(pointer.generation, isDirectory: true)
            let directoryValues = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            guard directoryValues.isDirectory == true, directoryValues.isSymbolicLink != true else {
                throw RepositoryError.invalidCatalog
            }
            let catalogURL = directory.appendingPathComponent("catalog.json")
            let data = try Self.readBoundedFile(catalogURL, maximum: Self.maximumCatalogBytes)
            let library = try JSONDecoder().decode(LibrarySnapshot.self, from: data)
            try Self.validate(library)
            return (library, directory)
        } catch {
            throw RepositoryError.invalidCatalog
        }
    }

    private func readOriginal(_ document: TravelDocument, directory: URL) throws -> Data {
        let url = directory.appendingPathComponent(document.storedFilename)
        do {
            let data = try Self.readBoundedFile(url, maximum: Self.maximumDocumentBytes)
            try Self.validateOriginal(data, document: document)
            return data
        } catch RepositoryError.originalModified {
            throw RepositoryError.originalModified
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            throw RepositoryError.originalMissing
        } catch let error as NSError where error.domain == NSCocoaErrorDomain && error.code == NSFileNoSuchFileError {
            throw RepositoryError.originalMissing
        } catch {
            throw RepositoryError.unreadableOriginal
        }
    }

    private func commit(_ library: LibrarySnapshot, source: URL?, replacementData: [UUID: Data] = [:]) throws {
        try Task.checkCancellation()
        try Self.validate(library)
        let generation = UUID().uuidString.lowercased()
        let directory = rootURL.appendingPathComponent(generation, isDirectory: true)
        var published = false
        var publicationFlushed = false
        defer {
            if !published { try? FileManager.default.removeItem(at: directory) }
        }
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
            try Self.protect(directory)
            for document in library.documents {
                try Task.checkCancellation()
                let destination = directory.appendingPathComponent(document.storedFilename)
                if let data = replacementData[document.id] {
                    try Self.validateOriginal(data, document: document)
                    try fileWriter(data, destination)
                } else if let source {
                    // Copy only verified complete originals. A disk-full or damaged
                    // input aborts the transaction before publication.
                    let data = try readOriginal(document, directory: source)
                    try fileWriter(data, destination)
                } else {
                    throw RepositoryError.originalMissing
                }
            }
            try Task.checkCancellation()
            let catalog = try Self.encode(library)
            guard catalog.count <= Self.maximumCatalogBytes else { throw RepositoryError.libraryTooLarge }
            try fileWriter(catalog, directory.appendingPathComponent("catalog.json"))
            try Self.synchronizeDirectory(directory)
            let pointer = try Self.encode(Pointer(formatVersion: 1, generation: generation))
            let pendingPointer = rootURL.appendingPathComponent(".pending-" + generation + ".json")
            defer { try? FileManager.default.removeItem(at: pendingPointer) }
            try fileWriter(pointer, pendingPointer)
            try Self.synchronizeDirectory(rootURL)
            // This is the final cancellable boundary. A cancellation arriving
            // after publication cannot turn a committed transaction into failure.
            try Task.checkCancellation()
            // No throwing operation may follow the publication rename before
            // `published` is set: otherwise rollback could delete the live data.
            let result = pendingPointer.path.withCString { pendingPath in
                rootURL.appendingPathComponent("active.json").path.withCString { activePath in
                    Darwin.rename(pendingPath, activePath)
                }
            }
            guard result == 0 else { throw RepositoryError.saveFailed }
            published = true
            // After rename, failure must never remove the live generation or
            // pretend that the previous library remains active. Retain previous
            // generations if the post-publication directory flush is unavailable.
            publicationFlushed = (try? Self.synchronizeDirectory(rootURL)) != nil
        } catch let error as CancellationError {
            throw error
        } catch let error as RepositoryError {
            throw error
        } catch {
            throw RepositoryError.saveFailed
        }
        // Cleanup happens after publication. Failure only consumes space and does
        // not roll back or invalidate the newly committed generation.
        if publicationFlushed, let children = try? FileManager.default.contentsOfDirectory(at: rootURL,
            includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
            for child in children where child.lastPathComponent != generation {
                if UUID(uuidString: child.lastPathComponent) != nil {
                    try? FileManager.default.removeItem(at: child)
                }
            }
        }
    }

    private static func validate(_ library: LibrarySnapshot) throws {
        guard library.schemaVersion == 1 else { throw RepositoryError.unsupportedSchema }
        guard library.trips.count <= maximumItems, library.travelers.count <= maximumItems,
              library.documents.count <= maximumItems else { throw RepositoryError.libraryTooLarge }
        let tripIDs = Set(library.trips.map(\.id))
        let travelerIDs = Set(library.travelers.map(\.id))
        let documentIDs = Set(library.documents.map(\.id))
        guard tripIDs.count == library.trips.count, travelerIDs.count == library.travelers.count,
              documentIDs.count == library.documents.count,
              Set(library.documents.map(\.storedFilename)).count == library.documents.count else {
            throw RepositoryError.duplicateIdentifier
        }
        guard library.trips.allSatisfy({ validName($0.title) && validDate($0.departureDate) }),
              library.travelers.allSatisfy({ validName($0.name) }) else { throw RepositoryError.invalidName }
        var total = 0
        for document in library.documents {
            guard tripIDs.contains(document.tripID),
                  document.travelerID == nil || travelerIDs.contains(document.travelerID!) else {
                throw RepositoryError.missingReference
            }
            guard validName(document.title), validFilename(document.originalFilename),
                  validDate(document.expiryDate), validDate(document.importedAt) else {
                throw RepositoryError.invalidName
            }
            guard document.byteCount > 0, document.byteCount <= maximumDocumentBytes else {
                throw RepositoryError.documentTooLarge
            }
            guard document.sha256.utf8.count == 64,
                  document.sha256.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
                throw RepositoryError.invalidArchive
            }
            guard ["pdf", "jpg", "png"].contains(where: {
                document.storedFilename == document.id.uuidString.lowercased() + "." + $0
            }) else { throw RepositoryError.invalidArchive }
            total += document.byteCount // bounded item count and per-file size prevent overflow
            guard total <= maximumLibraryBytes else { throw RepositoryError.libraryTooLarge }
        }
    }

    private static func validateOriginal(_ data: Data, document: TravelDocument) throws {
        guard data.count == document.byteCount, hash(data) == document.sha256,
              let fileExtension = try? fileExtension(for: data),
              document.storedFilename.hasSuffix("." + fileExtension) else {
            throw RepositoryError.originalModified
        }
    }

    private static func fileExtension(for data: Data) throws -> String {
        if data.starts(with: Data("%PDF-".utf8)) {
            // CoreGraphics must be able to open every page, and the original
            // must contain a terminating EOF marker. A header alone is no file.
            guard data.suffix(1_024).range(of: Data("%%EOF".utf8)) != nil,
                  let provider = CGDataProvider(data: data as CFData),
                  let pdf = CGPDFDocument(provider), pdf.isUnlocked,
                  (1...500).contains(pdf.numberOfPages) else { throw RepositoryError.invalidFile }
            for pageNumber in 1...pdf.numberOfPages {
                guard let page = pdf.page(at: pageNumber) else { throw RepositoryError.invalidFile }
                let bounds = page.getBoxRect(.mediaBox)
                guard bounds.width.isFinite, bounds.height.isFinite,
                      bounds.width > 0, bounds.height > 0 else { throw RepositoryError.invalidFile }
            }
            return "pdf"
        }
        let fileExtension: String
        if data.starts(with: [0xFF, 0xD8, 0xFF]) { fileExtension = "jpg" }
        else if data.starts(with: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) { fileExtension = "png" }
        else { throw RepositoryError.unsupportedFileType }
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetStatus(source) == .statusComplete,
              CGImageSourceGetCount(source) == 1,
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let height = properties[kCGImagePropertyPixelHeight] as? NSNumber else {
            throw RepositoryError.invalidFile
        }
        let w = width.intValue, h = height.intValue
        guard w > 0, h > 0, w <= 16_384, h <= 16_384, w * h <= 32_000_000 else {
            throw RepositoryError.invalidFile
        }
        let options = [kCGImageSourceShouldCacheImmediately: true] as CFDictionary
        guard CGImageSourceCreateImageAtIndex(source, 0, options) != nil,
              CGImageSourceGetStatusAtIndex(source, 0) == .statusComplete else {
            throw RepositoryError.invalidFile
        }
        return fileExtension
    }

    private static func isMissingFile(_ error: Error) -> Bool {
        let cocoa = error as NSError
        return cocoa.domain == NSCocoaErrorDomain
            && (cocoa.code == NSFileReadNoSuchFileError || cocoa.code == NSFileNoSuchFileError)
    }

    /// A fresh store receives a valid empty active pointer before a transaction
    /// may create a generation. If its first transaction is interrupted, this
    /// pointer remains readable and the abandoned generation can be ignored.
    /// A missing pointer beside older generations remains ambiguous corruption;
    /// never bootstrap over it or discard potential committed user originals.
    private static func bootstrapEmptyPointer(at root: URL,
        fileWriter: @Sendable (Data, URL) throws -> Void) throws {
        let activeURL = root.appendingPathComponent("active.json")
        do {
            _ = try activeURL.resourceValues(forKeys: [.isRegularFileKey])
            return
        } catch {
            guard isMissingFile(error) else { throw error }
        }
        let children = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        guard !children.contains(where: { UUID(uuidString: $0.lastPathComponent) != nil }) else { return }
        let emptyPointer = try encode(Pointer(formatVersion: 1, generation: "empty"))
        try fileWriter(emptyPointer, activeURL)
        try synchronizeDirectory(root)
    }

    private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func validName(_ value: String) -> Bool {
        !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.count <= 200
            && value.utf8.count <= 800 && !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
    }

    private static func validFilename(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 255 && value != "." && value != ".."
            && !value.contains("/") && !value.contains("\\")
            && !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
    }

    private static func validDate(_ value: Date?) -> Bool {
        guard let value else { return true }
        return value.timeIntervalSinceReferenceDate.isFinite
    }

    private static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(value)
    }

    private static func readBoundedFile(_ url: URL, maximum: Int) throws -> Data {
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw RepositoryError.unreadableOriginal
        }
        guard let size = values.fileSize, size <= maximum else { throw RepositoryError.originalModified }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var result = Data()
        while true {
            let chunk = try handle.read(upToCount: min(1_024 * 1_024, maximum - result.count + 1)) ?? Data()
            if chunk.isEmpty { return result }
            guard result.count + chunk.count <= maximum else { throw RepositoryError.originalModified }
            result.append(chunk)
        }
    }

    private static func writeProtected(_ data: Data, to url: URL) throws {
        #if os(iOS)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        #else
        try data.write(to: url, options: [.atomic])
        #endif
        // Flush file data before publishing active.json. Atomic rename protects
        // readers from partial writes; sync reduces loss after an abrupt exit.
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.synchronize()
    }

    private static func synchronizeDirectory(_ url: URL) throws {
        let descriptor = url.path.withCString { Darwin.open($0, O_RDONLY) }
        guard descriptor >= 0 else { throw RepositoryError.saveFailed }
        defer { _ = Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else { throw RepositoryError.saveFailed }
    }

    private static func protect(_ url: URL) throws {
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: url.path)
        #endif
    }
}
