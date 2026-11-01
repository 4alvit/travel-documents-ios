import CoreGraphics
import ImageIO
import Foundation

// Deterministic, opaque 1024-pixel vector drawing, independent of Retina scale.
let output = CommandLine.arguments[1]
let context = CGContext(data: nil, width: 1024, height: 1024, bitsPerComponent: 8,
    bytesPerRow: 4096, space: CGColorSpace(name: CGColorSpace.sRGB)!,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
let teal = CGColor(red: 0.04, green: 0.31, blue: 0.31, alpha: 1)
func rounded(_ rect: CGRect, radius: CGFloat, color: CGColor) {
    context.setFillColor(color)
    context.addPath(CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius, transform: nil))
    context.fillPath()
}
context.setFillColor(teal)
context.fill(CGRect(x: 0, y: 0, width: 1024, height: 1024))
rounded(CGRect(x: 236, y: 206, width: 586, height: 648), radius: 58,
    color: CGColor(red: 0.23, green: 0.53, blue: 0.49, alpha: 1))
rounded(CGRect(x: 186, y: 166, width: 586, height: 648), radius: 58,
    color: CGColor(red: 0.98, green: 0.96, blue: 0.87, alpha: 1))
context.setStrokeColor(teal)
context.setLineWidth(20)
context.strokeEllipse(in: CGRect(x: 358, y: 438, width: 240, height: 240))
context.setLineWidth(14)
context.strokeEllipse(in: CGRect(x: 418, y: 438, width: 120, height: 240))
context.move(to: CGPoint(x: 366, y: 558))
context.addLine(to: CGPoint(x: 590, y: 558))
context.strokePath()
rounded(CGRect(x: 326, y: 318, width: 308, height: 28), radius: 14, color: teal)
rounded(CGRect(x: 392, y: 257, width: 176, height: 22), radius: 11, color: teal)
let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: output) as CFURL, "public.png" as CFString, 1, nil)!
CGImageDestinationAddImage(destination, context.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("Could not write icon") }
