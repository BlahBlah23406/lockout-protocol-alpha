import AppKit

/// Knows which app is frontmost right now — the macOS equivalent of the Android
/// AccessibilityService foreground tracking. No special permission needed for this; NSWorkspace
/// reports the active app.
enum FrontmostApp {

    /// Prefix for the synthetic id given to a frontmost process that has NO bundle identifier —
    /// e.g. the Android SDK emulator, which is a bare `emulator` / `qemu-system-*` executable. Such
    /// a process used to be invisible here (nil bundle id → the monitor skipped the tick), which
    /// made an emulated Android device a blind spot. It is now identified as `proc:<executable>`.
    static let procPrefix = "proc:"

    /// Identifier of the frontmost (active) application: its bundle id, e.g. "com.google.Chrome",
    /// or `proc:<executable>` for a bundle-less process.
    static var bundleId: String? {
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        if let id = app.bundleIdentifier, !id.isEmpty { return id }
        guard let exe = app.executableURL?.lastPathComponent, !exe.isEmpty else { return nil }
        return procPrefix + exe
    }

    /// Title of the frontmost window of `bundleId`, or "" when unavailable.
    ///
    /// Used by the focus classifier, where the title is usually the single most informative signal
    /// on the screen — "Integration by parts | Khan Academy" settles a verdict that the pixels
    /// alone would leave ambiguous. It is passed to the model as text as well as being visible in
    /// the image, because small vision models read a supplied string far more reliably than they
    /// read a 12px title bar.
    ///
    /// `CGWindowListCopyWindowInfo` needs the Screen Recording grant to return window *names* (it
    /// returns the rest of the metadata without it), which the app already requires for capture.
    /// If the grant is missing this returns "" rather than failing the check — a missing title
    /// costs a little accuracy, never a block.
    static func windowTitle(for bundleId: String) -> String {
        let pids = Set(running(bundleId).map { $0.processIdentifier })
        guard !pids.isEmpty else { return "" }
        guard let windows = CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
            return ""
        }
        // The list is front-to-back, so the first match is the window actually being looked at.
        for window in windows {
            guard let pid = window[kCGWindowOwnerPID as String] as? pid_t, pids.contains(pid),
                  let name = window[kCGWindowName as String] as? String, !name.isEmpty else {
                continue
            }
            return String(name.prefix(300))
        }
        return ""
    }

    /// Running apps matching an identifier from `bundleId` — by bundle id, or by executable name
    /// for the synthetic `proc:` ids.
    static func running(_ identifier: String) -> [NSRunningApplication] {
        guard identifier.hasPrefix(procPrefix) else {
            return NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
        }
        let exe = String(identifier.dropFirst(procPrefix.count))
        return NSWorkspace.shared.runningApplications.filter {
            $0.executableURL?.lastPathComponent == exe
        }
    }

    /// The running NSRunningApplication for the frontmost app (used to hide / terminate it).
    static var current: NSRunningApplication? {
        NSWorkspace.shared.frontmostApplication
    }

    /// Human-friendly name for logs/toasts.
    static var localizedName: String? {
        NSWorkspace.shared.frontmostApplication?.localizedName
    }

    /// Short display name for a bundle id (best-effort), falling back to the last path component.
    static func shortName(for bundleId: String) -> String {
        if let app = running(bundleId).first, let name = app.localizedName {
            return name
        }
        if bundleId.hasPrefix(procPrefix) { return String(bundleId.dropFirst(procPrefix.count)) }
        return bundleId.components(separatedBy: ".").last ?? bundleId
    }

    /// Hide the app (send it to the background — escapable). Equivalent to Android `goHome()`.
    static func hide(bundleId: String) {
        running(bundleId).forEach { $0.hide() }
    }

    /// Terminate the offending app. The strongest "close" available. Equivalent to Android
    /// `closeApp()` (which sent home then killed the background process).
    static func quit(bundleId: String) {
        running(bundleId).forEach { $0.terminate() }
    }
}
