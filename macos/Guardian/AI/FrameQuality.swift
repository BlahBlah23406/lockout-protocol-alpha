import CoreGraphics
import Foundation

/// Heuristic: is this frame essentially blank/uniform — i.e. there is nothing for the AI to see?
///
/// A failed capture, a screen-recording-protected window, or a solid wallpaper can come back as a
/// near-uniform frame. In those cases we cannot verify the content, so the caller handles it as
/// "can't see" (alert, never a hard block). Mirrors the Android `FrameQuality`.
enum FrameQuality {

    static func isUnreadable(_ image: CGImage) -> Bool {
        isUnreadableLuminance(sampleLuminance(image))
    }

    /// Coarse 32×32 grid sample of luminance (0...255).
    static func sampleLuminance(_ image: CGImage) -> [Int] {
        let w = image.width, h = image.height
        guard w > 0, h > 0 else { return [] }

        // Render into a known RGBA8 buffer so pixel reads are well-defined.
        let cols = min(32, w), rows = min(32, h)
        let bytesPerPixel = 4
        let bytesPerRow = cols * bytesPerPixel
        var buffer = [UInt8](repeating: 0, count: rows * bytesPerRow)
        let space = CGColorSpaceCreateDeviceRGB()
        guard let ctx = CGContext(
            data: &buffer, width: cols, height: rows, bitsPerComponent: 8,
            bytesPerRow: bytesPerRow, space: space,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return [] }
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: cols, height: rows))

        var lums = [Int]()
        lums.reserveCapacity(rows * cols)
        var i = 0
        while i < buffer.count {
            let r = Int(buffer[i]), g = Int(buffer[i + 1]), b = Int(buffer[i + 2])
            lums.append((r * 299 + g * 587 + b * 114) / 1000)
            i += bytesPerPixel
        }
        return lums
    }

    /// Pure heuristic over sampled luminance values (0...255). Extracted so it is unit-testable.
    static func isUnreadableLuminance(_ lums: [Int]) -> Bool {
        if lums.isEmpty { return true }
        var nearBlack = 0
        var sum: Int64 = 0
        var sumSq: Int64 = 0
        for lum in lums {
            if lum < 16 { nearBlack += 1 }
            sum += Int64(lum)
            sumSq += Int64(lum * lum)
        }
        let n = Double(lums.count)
        let mean = Double(sum) / n
        let variance = Double(sumSq) / n - mean * mean
        let blackFraction = Double(nearBlack) / n
        return blackFraction > 0.995 || variance < 4.0
    }
}
