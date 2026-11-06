import SwiftUI
import VisionKit
import UIKit
import QuickLook

struct DocumentScanner: UIViewControllerRepresentable {
    var onComplete: (Result<Data, Error>) -> Void
    var onCancel: () -> Void

    static var isSupported: Bool { VNDocumentCameraViewController.isSupported }

    func makeUIViewController(context: Context) -> VNDocumentCameraViewController {
        let controller = VNDocumentCameraViewController()
        controller.delegate = context.coordinator
        return controller
    }
    func updateUIViewController(_ uiViewController: VNDocumentCameraViewController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    @MainActor final class Coordinator: NSObject, @preconcurrency VNDocumentCameraViewControllerDelegate {
        let parent: DocumentScanner
        init(parent: DocumentScanner) { self.parent = parent }

        func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
            parent.onCancel()
        }
        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFailWithError error: Error) {
            parent.onComplete(.failure(error))
        }
        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFinishWith scan: VNDocumentCameraScan) {
            guard scan.pageCount > 0, scan.pageCount <= 25 else {
                parent.onComplete(.failure(ScanError.pageLimit))
                return
            }
            let pageBounds = CGRect(x: 0, y: 0, width: 612, height: 792)
            let renderer = UIGraphicsPDFRenderer(bounds: pageBounds)
            let data = renderer.pdfData { context in
                for index in 0..<scan.pageCount {
                    autoreleasepool {
                        context.beginPage()
                        let source = scan.imageOfPage(at: index)
                        // A bounded raster avoids embedding camera-sized pages in
                        // the PDF. The resulting PDF is the saved scan original.
                        let rasterScale = min(1, 2000 / max(source.size.width, source.size.height))
                        let rasterSize = CGSize(width: source.size.width * rasterScale, height: source.size.height * rasterScale)
                        let format = UIGraphicsImageRendererFormat()
                        format.scale = 1
                        format.opaque = true
                        let raster = UIGraphicsImageRenderer(size: rasterSize, format: format).image { renderer in
                            UIColor.white.setFill()
                            renderer.fill(CGRect(origin: .zero, size: rasterSize))
                            source.draw(in: CGRect(origin: .zero, size: rasterSize))
                        }
                        let image = raster.jpegData(compressionQuality: 0.85).flatMap(UIImage.init(data:)) ?? raster
                        let scale = min(pageBounds.width / image.size.width, pageBounds.height / image.size.height)
                        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
                        image.draw(in: CGRect(x: (pageBounds.width - size.width) / 2,
                            y: (pageBounds.height - size.height) / 2, width: size.width, height: size.height))
                    }
                }
            }
            guard data.count <= 16 * 1024 * 1024 else {
                parent.onComplete(.failure(ScanError.fileLimit))
                return
            }
            parent.onComplete(.success(data))
        }
    }

    enum ScanError: LocalizedError {
        case pageLimit, fileLimit
        var errorDescription: String? {
            switch self {
            case .pageLimit: L10n.service("services.scanner.pageLimit", defaultValue: "Scan between 1 and 25 pages at a time.")
            case .fileLimit: L10n.service("services.scanner.fileLimit", defaultValue: "This scan is larger than 16 MB. Try fewer pages.")
            }
        }
    }
}

struct DocumentPreview: UIViewControllerRepresentable {
    let url: URL
    func makeCoordinator() -> Coordinator { Coordinator(url: url) }
    func makeUIViewController(context: Context) -> QLPreviewController {
        let controller = QLPreviewController()
        controller.dataSource = context.coordinator
        return controller
    }
    func updateUIViewController(_ controller: QLPreviewController, context: Context) {}
    @MainActor final class Coordinator: NSObject, QLPreviewControllerDataSource {
        let url: URL
        init(url: URL) { self.url = url }
        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
        func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> any QLPreviewItem { url as NSURL }
    }
}

struct ExplicitShareSheet: UIViewControllerRepresentable {
    let url: URL
    var onComplete: @MainActor @Sendable () -> Void = {}
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        let completion = onComplete
        // A share extension can keep consuming the source after our scene
        // backgrounds. Clean up only after the system reports completion or
        // cancellation, never merely because the sheet disappeared.
        #if DEBUG
        let sharedURL = url
        let diagnostics = ShareLifecycleDiagnostics()
        diagnostics?.record(.handoff, url: sharedURL)
        #endif
        controller.completionWithItemsHandler = { activity, completed, _, error in
            #if DEBUG
            diagnostics?.record(.completion, url: sharedURL, activity: activity?.rawValue,
                                completed: completed, error: error.map { $0 as NSError })
            #endif
            Task { @MainActor in
                #if DEBUG
                diagnostics?.record(.cleanupBefore, url: sharedURL)
                #endif
                completion()
                #if DEBUG
                diagnostics?.record(.cleanupAfter, url: sharedURL)
                #endif
            }
        }
        return controller
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

#if DEBUG
/// Four value-only events per explicitly opted-in share; never reads the payload.
private final class ShareLifecycleDiagnostics: @unchecked Sendable {
    enum Stage: String { case handoff, completion, cleanupBefore, cleanupAfter }
    private let id: String
    private let started: TimeInterval
    private let lock = NSLock()
    // Only this counter is mutable, and every access holds lock.
    private var remaining = 4

    init?(arguments: [String] = ProcessInfo.processInfo.arguments) {
        guard arguments.contains("--ui-testing-share-diagnostics") else { return nil }
        id = UUID().uuidString
        started = ProcessInfo.processInfo.systemUptime
    }

    func record(_ stage: Stage, url: URL, activity: String? = nil,
                completed: Bool? = nil, error: NSError? = nil) {
        lock.lock()
        guard remaining > 0 else { lock.unlock(); return }
        remaining -= 1
        lock.unlock()
        let files = FileManager.default
        let attributes = try? files.attributesOfItem(atPath: url.path)
        var values: [String: Any] = [
            "v": 1, "id": id, "stage": stage.rawValue,
            "ms": Int(min(max(ProcessInfo.processInfo.systemUptime - started, 0), 86_400) * 1_000),
            "exists": files.fileExists(atPath: url.path),
            "readable": files.isReadableFile(atPath: url.path),
            "metadata_available": attributes != nil,
        ]
        if let size = attributes?[.size] as? NSNumber { values["bytes"] = size.int64Value }
        if let completed { values["completed"] = completed }
        if let activity {
            // Keep the native activity needed for this diagnosis; never log an
            // arbitrary extension identifier supplied by another application.
            values["activity"] = activity == "com.apple.DocumentManagerUICore.SaveToFiles"
                ? activity : "other"
        }
        if let error {
            let domains = [NSCocoaErrorDomain, NSPOSIXErrorDomain, NSOSStatusErrorDomain,
                           NSURLErrorDomain, "NSFileProviderErrorDomain", "UIActivityErrorDomain"]
            values["error_domain"] = domains.contains(error.domain) ? error.domain : "other"
            values["error_code"] = error.code
        }
        guard let data = try? JSONSerialization.data(withJSONObject: values, options: [.sortedKeys]),
              let line = String(data: data, encoding: .utf8) else { return }
        print("share-lifecycle " + line)
    }
}
#endif
