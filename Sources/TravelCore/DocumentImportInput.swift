import Foundation

/// Complete bytes and user-confirmed metadata for one item in an atomic import.
/// The repository generates document IDs and stored filenames; filenames here
/// are display metadata only. All items in a request belong to one chosen trip.
public struct DocumentImportInput: Sendable {
    public let data: Data
    public let originalFilename: String
    public let travelerID: UUID?
    public let title: String
    public let kind: DocumentKind
    public let expiryDate: Date?

    public init(data: Data, originalFilename: String, travelerID: UUID? = nil,
                title: String, kind: DocumentKind, expiryDate: Date? = nil) {
        self.data = data
        self.originalFilename = originalFilename
        self.travelerID = travelerID
        self.title = title
        self.kind = kind
        self.expiryDate = expiryDate
    }
}
