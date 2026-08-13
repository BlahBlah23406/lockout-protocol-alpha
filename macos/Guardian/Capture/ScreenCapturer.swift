import CoreGraphics
import Foundation
import ScreenCaptureKit

/// Grabs a single screenshot of the main display via ScreenCaptureKit's one-shot
/// `SCScreenshotManager.captureImage`. This is the macOS analogue of the Android
/// `AccessibilityService.takeScreenshot()` — one frame on demand, no continuous recording.
///
/// Requires the Screen Recording permission (TCC). The first capture attempt triggers the system
/// prompt; until granted, captures fail and the monitor treats the screen as "can't see".
enum ScreenCapturer {

    /// Capture the display that currently shows the frontmost app (defaults to the main display).
    /// Downscaled so uploads stay small/fast, matching the Android 720px cap.
    static func capture(maxWidth: Int = 1280) async -> CGImage? {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else { return nil }

            // Capture the whole display, excluding nothing (we want to see what the user sees).
            let filter = SCContentFilter(display: display, excludingWindows: [])

            let cfg = SCStreamConfiguration()
            let scale = min(1.0, Double(maxWidth) / Double(display.width))
            cfg.width = Int(Double(display.width) * scale)
            cfg.height = Int(Double(display.height) * scale)
            cfg.showsCursor = false
            cfg.captureResolution = .best

            return try await SCScreenshotManager.captureImage(
                contentFilter: filter, configuration: cfg)
        } catch {
            return nil
        }
    }

    /// Whether we currently hold Screen Recording permission. Best-effort: SCShareableContent
    /// throws / returns nothing without it.
    static func hasPermission() async -> Bool {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: true)
            return !content.displays.isEmpty
        } catch {
            return false
        }
    }
}
