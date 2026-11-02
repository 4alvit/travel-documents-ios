import SwiftUI
#if DEBUG && targetEnvironment(simulator)
import Darwin
import Observation
import UIKit
#endif

@main
struct TripfolioApp: App {
    // Keep one model shared by this app's scenes, while allowing the injected
    // unit-test bundle to configure StoreKit before constructing any model.
    @State private var model: AppModel? = AppLaunch.isHostedUnitTest() ? nil : AppModel()

    var body: some Scene {
        WindowGroup {
            if let model {
                TripfolioRoot(model: model)
            } else {
                // The injected test bundle initializes local StoreKit before
                // any test creates an AppModel or PurchaseManager.
                Color.clear
            }
        }
    }
}

enum AppLaunch {
    static func isHostedUnitTest(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        #if DEBUG
        guard let path = environment["XCTestBundlePath"] else { return false }
        return URL(fileURLWithPath: path).lastPathComponent == "TripfolioTests.xctest"
        #else
        return false
        #endif
    }
}

private struct TripfolioRoot: View {
    let model: AppModel

    var body: some View {
        PrivacyLockView {
            Group {
                #if DEBUG && targetEnvironment(simulator)
                if let token = NativeBatchSeedFiles.token(ProcessInfo.processInfo.arguments) {
                    NativeBatchSeedView(token: token)
                } else {
                    RootView()
                }
                #else
                RootView()
                #endif
            }
                .environment(model)
                .tint(Color(red: 0.04, green: 0.40, blue: 0.38))
                .task {
                    await model.refresh()
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--demo") {
                        await model.installSyntheticDemoIfEmpty()
                    }
                    #endif
                }
                .task { await model.purchases.load() }
        }
        .environment(\.locale, L10n.formattingLocale())
    }
}

#if DEBUG && targetEnvironment(simulator)
// Diagnostic branch fixture only. These are the exact two driver-generated PDFs.
// Sources stay in this exclusive owned Simulator until its verified teardown:
// Export completion and a coordinated read verify each returned destination;
// the host independently checks both exact provider-root files before main.
@MainActor
private enum NativeBatchSeedFiles {
    enum Failure: Error { case invalid }
    static let fixtures: [(String, String)] = [
        ("synthetic-ticket.pdf", "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA2MTIgNzkyXSAvUmVzb3VyY2VzIDw8IC9Gb250IDw8IC9GMSA0IDAgUiA+PiA+PiAvQ29udGVudHMgNSAwIFIgPj4KZW5kb2JqCjQgMCBvYmoKPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhID4+CmVuZG9iago1IDAgb2JqCjw8IC9MZW5ndGggMTYzID4+CnN0cmVhbQpCVCAvRjEgMjAgVGYgNTQgNzMwIFRkIChTWU5USEVUSUMgVElDS0VUKSBUaiAwIC0zNiBUZCAoVHJpcERvY2tldCBiYXRjaCBVSSBRQSkgVGogMCAtMzYgVGQgKFNZTlRIRVRJQyAtIE5PVCBWQUxJRCBGT1IgVFJBVkVMKSBUaiAwIC0zNiBUZCAoTm8gcGVyc29uYWwgZGF0YSkgVGogRVQKZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAwMTIxIDAwMDAwIG4gCjAwMDAwMDAyNDcgMDAwMDAgbiAKMDAwMDAwMDMxNyAwMDAwMCBuIAp0cmFpbGVyCjw8IC9TaXplIDYgL1Jvb3QgMSAwIFIgPj4Kc3RhcnR4cmVmCjUzMAolJUVPRgo="),
        ("synthetic-insurance.pdf", "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA2MTIgNzkyXSAvUmVzb3VyY2VzIDw8IC9Gb250IDw8IC9GMSA0IDAgUiA+PiA+PiAvQ29udGVudHMgNSAwIFIgPj4KZW5kb2JqCjQgMCBvYmoKPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhID4+CmVuZG9iago1IDAgb2JqCjw8IC9MZW5ndGggMTY2ID4+CnN0cmVhbQpCVCAvRjEgMjAgVGYgNTQgNzMwIFRkIChTWU5USEVUSUMgSU5TVVJBTkNFKSBUaiAwIC0zNiBUZCAoVHJpcERvY2tldCBiYXRjaCBVSSBRQSkgVGogMCAtMzYgVGQgKFNZTlRIRVRJQyAtIE5PVCBWQUxJRCBGT1IgVFJBVkVMKSBUaiAwIC0zNiBUZCAoTm8gcGVyc29uYWwgZGF0YSkgVGogRVQKZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAwMTIxIDAwMDAwIG4gCjAwMDAwMDAyNDcgMDAwMDAgbiAKMDAwMDAwMDMxNyAwMDAwMCBuIAp0cmFpbGVyCjw8IC9TaXplIDYgL1Jvb3QgMSAwIFIgPj4Kc3RhcnR4cmVmCjUzMwolJUVPRgo=")
    ]
    static func token(_ arguments: [String]) -> String? {
        let flag = "--ui-testing-native-batch-seed"
        let key = "--ui-testing-native-batch-token"
        guard arguments.filter({ $0 == flag }).count == 1,
              arguments.filter({ $0 == key }).count == 1,
              let index = arguments.firstIndex(of: key), index + 1 < arguments.count else { return nil }
        let value = arguments[index + 1]
        guard UUID(uuidString: value)?.uuidString.lowercased() == value else { return nil }
        return value
    }
    static func create(_ token: String,
                       root: URL = FileManager.default.temporaryDirectory.resolvingSymlinksInPath()) throws -> [URL] {
        guard UUID(uuidString: token)?.uuidString.lowercased() == token,
              root.isFileURL, root.standardizedFileURL == root.resolvingSymlinksInPath().standardizedFileURL else {
            throw Failure.invalid
        }
        let parent = open(root.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard parent >= 0 else { throw Failure.invalid }
        defer { close(parent) }
        let name = "TripDocket-NativeSeed-" + token
        guard mkdirat(parent, name, 0o700) == 0 else { throw Failure.invalid }
        let directory = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard directory >= 0 else { throw Failure.invalid }
        defer { close(directory) }
        var identity = stat()
        guard fstat(directory, &identity) == 0 else { throw Failure.invalid }
        func verifyIdentity() throws {
            var current = stat()
            guard fstatat(parent, name, &current, AT_SYMLINK_NOFOLLOW) == 0,
                  current.st_dev == identity.st_dev, current.st_ino == identity.st_ino,
                  current.st_mode & S_IFMT == S_IFDIR else { throw Failure.invalid }
        }
        try verifyIdentity()
        let folder = root.appendingPathComponent(name, isDirectory: true)
        let files = try fixtures.map { filename, encoded in
            guard let data = Data(base64Encoded: encoded), data.count <= 1024 else { throw Failure.invalid }
            let file = openat(directory, filename, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
            guard file >= 0 else { throw Failure.invalid }
            defer { close(file) }
            let count = data.withUnsafeBytes { write(file, $0.baseAddress, $0.count) }
            guard count == data.count else { throw Failure.invalid }
            return folder.appendingPathComponent(filename)
        }
        try verifyIdentity()
        return files
    }
}

@MainActor
private struct NativeBatchSeedView: View {
    let token: String
    @State private var files: [URL] = []
    @State private var attempted = false
    @State private var failed = false
    @State private var exports: [String: NativeSeedExportSession] = [:]
    @State private var presentedExport: NativeSeedExportSession?

    private var unavailable: Bool { failed || exports.values.contains { $0.phase == .failed } }
    private var pending: Bool { exports.values.contains { $0.phase == .waiting || $0.phase == .verifying } }

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                if unavailable {
                    Text("Seed unavailable").accessibilityIdentifier("nativeSeed.failure")
                } else {
                    Text("Synthetic PDF export")
                }
                ForEach(files, id: \.lastPathComponent) { file in
                    Button(file.lastPathComponent) { beginExport(file) }
                        .accessibilityIdentifier("nativeSeed." + file.lastPathComponent)
                        .disabled(unavailable || pending || exports[file.lastPathComponent] != nil)
                    if exports[file.lastPathComponent]?.phase == .verified {
                        Text("Export verified")
                            .accessibilityIdentifier("nativeSeed.saved." + file.lastPathComponent)
                    }
                }
            }
            .navigationTitle("Native fixture seed")
            .sheet(item: $presentedExport) { request in
                NativeSeedExportPicker(request: request)
            }
        }
        .onChange(of: pending) { _, isPending in
            // Clear only presentation after the retained request is terminal.
            if !isPending { presentedExport = nil }
        }
        .task {
            guard !attempted else { return }
            attempted = true
            do { files = try NativeBatchSeedFiles.create(token) }
            catch { failed = true }
        }
    }

    private func beginExport(_ file: URL) {
        guard !unavailable, !pending, exports[file.lastPathComponent] == nil,
              let encoded = NativeBatchSeedFiles.fixtures.first(where: { $0.0 == file.lastPathComponent })?.1,
              let bytes = Data(base64Encoded: encoded) else { failed = true; return }
        let request = NativeSeedExportSession(source: file, expected: bytes)
        // Semantic ownership survives UIKit's automatic sheet dismissal.
        // There is no destination deletion; this Simulator is qualifier-owned.
        exports[file.lastPathComponent] = request
        presentedExport = request
    }
}

@MainActor
@Observable
private final class NativeSeedExportSession: Identifiable {
    enum Phase { case waiting, verifying, verified, failed }
    let id = UUID()
    let source: URL
    private let expected: Data
    private let read: @Sendable (URL, Int) async throws -> Data
    private(set) var phase: Phase = .waiting

    init(source: URL, expected: Data,
         read: @escaping @Sendable (URL, Int) async throws -> Data = AppModel.readExternal) {
        self.source = source
        self.expected = expected
        self.read = read
    }

    func receive(_ urls: [URL]) {
        // The first terminal delegate event owns the result. Duplicate or
        // late events cannot start another read or overwrite a failed export.
        guard phase == .waiting else { return }
        guard !expected.isEmpty, expected.count <= 1024, urls.count == 1,
              let destination = urls.first, destination.isFileURL,
              destination.host == nil || destination.host == "" || destination.host == "localhost",
              destination.lastPathComponent == source.lastPathComponent,
              destination.standardizedFileURL != source.standardizedFileURL else {
            phase = .failed
            return
        }
        phase = .verifying
        let read = self.read
        let expected = self.expected
        Task { [weak self] in
            let verified: Bool
            do {
                // Preserve the exact returned URL, including its access grant.
                // The production reader coordinates off-main, balances its
                // security scope, and bounds the full byte stream to1024 bytes.
                let bytes = try await read(destination, 1024)
                try Task.checkCancellation()
                verified = bytes == expected
            } catch {
                verified = false
            }
            guard let self, self.phase == .verifying else { return }
            self.phase = verified ? .verified : .failed
        }
    }

    func cancel() {
        guard phase == .waiting else { return }
        phase = .failed
    }
}

@MainActor
private struct NativeSeedExportPicker: UIViewControllerRepresentable {
    let request: NativeSeedExportSession

    func makeCoordinator() -> Coordinator { Coordinator(request: request) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forExporting: [request.source], asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let request: NativeSeedExportSession
        init(request: NativeSeedExportSession) { self.request = request }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            request.receive(urls)
        }
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            request.cancel()
        }
    }
}
#endif
