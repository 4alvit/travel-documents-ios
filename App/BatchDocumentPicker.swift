import Darwin
import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Owns only the regular, unlinked copies returned inside this app's temporary
/// directory. The model retains this lease until its last file read finishes.
final class BatchDocumentSelection: @unchecked Sendable {
    let urls: [URL]
    private let root: String
    private let copies: [Copy]
    private let lock = NSLock()
    private var disposed = false

    private struct Identity: Equatable {
        let device: dev_t
        let inode: ino_t
        init(_ value: stat) { device = value.st_dev; inode = value.st_ino }
    }

    private struct Copy {
        let components: [String]
        let directories: [Identity]
        let file: Identity
    }

    private init(urls: [URL], root: String, copies: [Copy]) {
        self.urls = urls
        self.root = root
        self.copies = copies
    }

    /// Validation never follows a returned symlink, and a partial rejection
    /// still disposes the other validated copies. Unknown paths stay untouched.
    static func capture(_ urls: [URL], temporaryDirectory: URL = FileManager.default.temporaryDirectory) throws -> BatchDocumentSelection {
        let canonicalRoot = temporaryDirectory.resolvingSymlinksInPath().standardizedFileURL.path
        let aliases = Set([canonicalRoot, temporaryDirectory.standardizedFileURL.path])
        var copies: [Copy] = []
        var accepted: [URL] = []
        var valid = (1...10).contains(urls.count)
        for url in urls {
            let path = url.standardizedFileURL.path
            guard url.isFileURL, url.host == nil || url.host == "" || url.host == "localhost",
                  let alias = aliases.first(where: { path.hasPrefix($0 + "/") }) else {
                valid = false
                continue
            }
            let components = String(path.dropFirst(alias.count + 1)).split(separator: "/").map(String.init)
            guard !components.isEmpty, components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
                  let copy = inspect(root: canonicalRoot, components: components) else {
                valid = false
                continue
            }
            copies.append(copy)
            accepted.append(URL(fileURLWithPath: canonicalRoot).appendingPathComponent(components.joined(separator: "/")))
        }
        let selection = BatchDocumentSelection(urls: accepted, root: canonicalRoot, copies: copies)
        guard valid else {
            selection.dispose()
            if !(1...10).contains(urls.count) { throw BatchImportError.invalidSelection }
            throw CocoaError(.fileReadNoPermission)
        }
        return selection
    }

    func dispose() {
        lock.lock()
        defer { lock.unlock() }
        guard !disposed else { return }
        disposed = true
        for copy in copies {
            // Reopen each component without following links and require the
            // captured directory/file identities before unlinking this leaf.
            guard let parent = Self.parent(root: root, components: copy.components,
                                           expected: copy.directories) else { continue }
            defer { close(parent.fd) }
            var value = stat()
            let name = copy.components.last!
            guard fstatat(parent.fd, name, &value, AT_SYMLINK_NOFOLLOW) == 0,
                  Self.isRegularCopy(value), Identity(value) == copy.file else { continue }
            _ = unlinkat(parent.fd, name, 0)
        }
    }

    deinit { dispose() }

    private static func isRegularCopy(_ value: stat) -> Bool {
        value.st_mode & S_IFMT == S_IFREG && value.st_nlink == 1
    }

    private static func inspect(root: String, components: [String]) -> Copy? {
        guard let parent = parent(root: root, components: components, expected: nil) else { return nil }
        defer { close(parent.fd) }
        var value = stat()
        guard fstatat(parent.fd, components.last!, &value, AT_SYMLINK_NOFOLLOW) == 0,
              isRegularCopy(value) else { return nil }
        return Copy(components: components, directories: parent.identities, file: Identity(value))
    }

    private static func parent(root: String, components: [String], expected: [Identity]?) -> (fd: Int32, identities: [Identity])? {
        var fd = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { return nil }
        var identities: [Identity] = []
        for component in [String?](arrayLiteral: nil) + components.dropLast().map(Optional.some) {
            if let component {
                let child = openat(fd, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
                close(fd)
                guard child >= 0 else { return nil }
                fd = child
            }
            var value = stat()
            guard fstat(fd, &value) == 0, value.st_mode & S_IFMT == S_IFDIR else {
                close(fd)
                return nil
            }
            identities.append(Identity(value))
        }
        guard expected == nil || expected == identities else { close(fd); return nil }
        return (fd, identities)
    }
}

@MainActor
struct BatchDocumentPicker: UIViewControllerRepresentable {
    @MainActor
    final class Session: Identifiable {
        let id = UUID()
        let draftID: UUID
        private(set) var active = true
        init(draftID: UUID) { self.draftID = draftID }
        func invalidate() { active = false }
    }

    let session: Session
    let completion: (Result<BatchDocumentSelection, Error>?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(session: session, completion: completion) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.pdf, .jpeg, .png], asCopy: true)
        picker.allowsMultipleSelection = true
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    static func dismantleUIViewController(_ uiViewController: UIDocumentPickerViewController, coordinator: Coordinator) {
        coordinator.session.invalidate()
    }

    @MainActor
    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let session: Session
        private let completion: (Result<BatchDocumentSelection, Error>?) -> Void
        private let capture: ([URL]) throws -> BatchDocumentSelection
        private var receivedSelection = false
        private var completed = false

        init(session: Session, capture: @escaping ([URL]) throws -> BatchDocumentSelection = { try .capture($0) },
             completion: @escaping (Result<BatchDocumentSelection, Error>?) -> Void) {
            self.session = session
            self.capture = capture
            self.completion = completion
        }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            // Duplicate callbacks must not acquire and delete an in-use lease.
            guard !receivedSelection else { return }
            receivedSelection = true
            let result = Result { try capture(urls) }
            guard session.active, !completed else {
                if case .success(let selection) = result { selection.dispose() }
                return
            }
            completed = true
            session.invalidate()
            completion(result)
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            guard session.active, !completed else { return }
            completed = true
            session.invalidate()
            completion(nil)
        }
    }
}
