import AppKit
import CoreGraphics

/// Can anyone actually SEE the screen right now?
///
/// This exists because a sleeping/locked Mac is not a monitoring blind spot — it's a screen with
/// nothing on it. ScreenCaptureKit still "works" in that state, but it hands back a black frame (or
/// throws), which used to read as "Guardian can't see the screen" and fire an alert every single
/// time the display went to sleep. Nothing prohibited can be viewed on a dark or locked display, so
/// pausing is correct here — unlike incognito/protected windows, which stay a real blind spot and
/// must keep alerting. See SAFEGUARDS.md.
enum ScreenState {

    /// The main display is powered down (sleep, or the lid is shut).
    static var displayAsleep: Bool { CGDisplayIsAsleep(CGMainDisplayID()) != 0 }

    /// The login session is locked, or this session isn't the one on the physical console
    /// (fast user switching). Key names are the documented CGSession dictionary strings.
    static var locked: Bool {
        guard let d = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
        if let onConsole = d["kCGSSessionOnConsoleKey"] as? Bool, !onConsole { return true }
        if let isLocked = d["CGSSessionScreenIsLocked"] as? Bool, isLocked { return true }
        return false
    }

    /// Best-effort: a screen saver is covering the display.
    static var screenSaverRunning: Bool {
        ["com.apple.ScreenSaver.Engine", "com.apple.screensaver.engine", "com.apple.legacyScreenSaver"]
            .contains { !NSRunningApplication.runningApplications(withBundleIdentifier: $0).isEmpty }
    }

    /// True when there is a lit, unlocked screen a person could be looking at.
    static var isVisible: Bool { !displayAsleep && !locked && !screenSaverRunning }

    /// Short description of why the screen isn't visible, for the activity log.
    static var reason: String {
        if displayAsleep { return "asleep" }
        if locked { return "locked" }
        if screenSaverRunning { return "showing the screen saver" }
        return "visible"
    }
}
