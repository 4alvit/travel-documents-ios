import Foundation
import CoreGraphics
import ImageIO
import Vision

/// Local, optional OCR. The result is a suggestion, never authoritative metadata.
enum OCRService {
    enum OCRFailure: LocalizedError {
        case unreadable, noText, unsupportedSize
        var errorDescription: String? {
            switch self {
            case .unreadable: L10n.service("services.ocr.unreadable", defaultValue: "This file could not be read for text recognition. You can still import it and enter its details yourself.")
            case .noText: L10n.service("services.ocr.noText", defaultValue: "No text was found. You can enter the document details yourself.")
            case .unsupportedSize: L10n.service("services.ocr.unsupportedSize", defaultValue: "Choose a complete file no larger than 16 MB. Download cloud files in Files before trying text recognition.")
            }
        }
    }

    static func recognizeText(at url: URL) async throws -> String {
        let data = try await Task.detached(priority: .userInitiated) {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let maximum = 16 * 1024 * 1024
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true, let size = values.fileSize,
                  size > 0, size <= maximum else { throw OCRFailure.unsupportedSize }
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            guard let data = try handle.read(upToCount: maximum + 1), data.count <= maximum else {
                throw OCRFailure.unsupportedSize
            }
            return data
        }.value
        return try await recognizeText(in: data)
    }

    static func recognizeText(in data: Data) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            try Task.checkCancellation()
            let images = try imagesForRecognition(data)
            var pages: [String] = []
            for image in images {
                try Task.checkCancellation()
                let request = VNRecognizeTextRequest()
                request.recognitionLevel = .accurate
                request.usesLanguageCorrection = true
                // A document's language is independent of the app's language.
                // Ask this request/revision for supported identifiers; retain
                // English and Russian whenever available instead of guessing
                // unsupported locale identifiers or forcing one UI language.
                let supported = try request.supportedRecognitionLanguages()
                let preferred = ["en", "ru"].flatMap { language in
                    supported.filter { Locale(identifier: $0).language.languageCode?.identifier == language }
                }
                if !preferred.isEmpty { request.recognitionLanguages = preferred }
                request.automaticallyDetectsLanguage = true
                let handler = VNImageRequestHandler(cgImage: image, options: [:])
                try handler.perform([request])
                let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
                if !text.isEmpty { pages.append(text) }
            }
            let text = pages.joined(separator: "\n\n")
            guard !text.isEmpty else { throw OCRFailure.noText }
            return text
        }.value
    }

    private static func imagesForRecognition(_ data: Data) throws -> [CGImage] {
        if let source = CGImageSourceCreateWithData(data as CFData, nil),
           let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: 1800,
            kCGImageSourceCreateThumbnailWithTransform: true
           ] as CFDictionary) {
            return [image]
        }
        guard let provider = CGDataProvider(data: data as CFData),
              let document = CGPDFDocument(provider), document.numberOfPages > 0 else {
            throw OCRFailure.unreadable
        }
        // Bound recognition work and memory; the imported original is never changed.
        return try (1...min(document.numberOfPages, 3)).map { index in
            guard let page = document.page(at: index) else { throw OCRFailure.unreadable }
            let bounds = page.getBoxRect(.mediaBox)
            guard bounds.width > 0, bounds.height > 0 else { throw OCRFailure.unreadable }
            let scale = min(1800 / max(bounds.width, bounds.height), 2)
            let width = max(1, Int(bounds.width * scale))
            let height = max(1, Int(bounds.height * scale))
            guard let context = CGContext(data: nil, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
                throw OCRFailure.unreadable
            }
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: width, height: height))
            context.concatenate(page.getDrawingTransform(.mediaBox,
                rect: CGRect(x: 0, y: 0, width: width, height: height), rotate: 0, preserveAspectRatio: true))
            context.drawPDFPage(page)
            guard let image = context.makeImage() else { throw OCRFailure.unreadable }
            return image
        }
    }
}
