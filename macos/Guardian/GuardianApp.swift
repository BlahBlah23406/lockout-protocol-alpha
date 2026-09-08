import SwiftUI
import UserNotifications

@main
struct GuardianApp: App {

    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // Main dashboard window. Closing it hides the Dock icon (see AppDelegate) but keeps
        // Guardian running in the background via the menu-bar item.
        WindowGroup(id: AppActivation.mainWindowID) {
            RootView()
                .frame(minWidth: 720, minHeight: 560)
                .background(LCARS.space)
                .preferredColorScheme(.dark)
        }
        .windowResizability(.contentSize)

        // The menu-bar item is the front door: start a session, see the one running, end it.
        // `MenuBarExtra` keeps the app alive with no window open, which is what makes the
        // "start a session in three seconds" flow possible at all.
        MenuBarExtra("Lockout Protocol", systemImage: "eye.fill") {
            MenuBarView()
        }
        .menuBarExtraStyle(.window)
    }
}

/// Centralizes how we show the main window + flip the Dock icon on/off.
enum AppActivation {
    static let mainWindowID = "guardian-main"

    /// Bring the main window forward, restoring the Dock icon + app menu.
    @MainActor
    static func showMainWindow(_ openWindow: OpenWindowAction) {
        NSApp.setActivationPolicy(.regular)
        openWindow(id: mainWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Local-notification permission (used for on-screen violation alerts).
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        // Resume monitoring (mirrors Android always-on resume), and arm
        // the tamper/self-guard layers.
        Task { @MainActor in
            SafetyCovenant.check()                              // alert if safeguards were weakened
            Emulators.syncMonitoredApps()             // watch every emulated device on this Mac
            Judgements.trim()                                   // keep the judgement log bounded
            // Resume a session that was running when we were last killed. Without this,
            // force-quitting would silently cancel a locked session — which would make the
            // "locked" level worth nothing.
            if SessionStore.shared.isActive || Prefs.shared.monitoringEnabled {
                MonitorService.shared.start()
            }
            Persistence.apply()                                 // login item and/or KeepAlive agent
            TamperGuard.shared.start()                          // Screen Recording revoke + watchdog
            SettingsGuard.shared.start()                        // pledge gate on System Settings
        }

        // When the dashboard window closes, drop the Dock icon and keep running in the background.
        NotificationCenter.default.addObserver(
            self, selector: #selector(windowWillClose(_:)),
            name: NSWindow.willCloseNotification, object: nil)
    }

    /// Keep running after the window is closed — the menu-bar item stays alive.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// Quitting Guardian is a bypass — notify the accountability contact on the way out. We don't
    /// block the quit (that would be user-hostile and macOS can't reliably enforce it); the login
    /// item brings Guardian back at the next login.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        // Quitting mid-session is the one bypass macOS cannot prevent, so a locked session at
        // least tells the partner on the way out. The login item brings the app back next login.
        if let session = SessionStore.shared.stored, session.accountability.alertsPartner {
            TamperAlert.raise(
                "Lockout Protocol was quit on this Mac during a locked session "
                + "(\"\(session.task)\") — monitoring stopped.", force: true)
        } else if Prefs.shared.monitoringEnabled {
            TamperAlert.raise(
                "Lockout Protocol was quit on this Mac — monitoring is stopped until it relaunches.",
                force: true)
        }
        return .terminateNow
    }

    /// Clicking the Dock icon (when visible) reopens the dashboard.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { NSApp.setActivationPolicy(.regular) }
        return true
    }

    @objc private func windowWillClose(_ note: Notification) {
        guard let closing = note.object as? NSWindow, isDashboard(closing) else { return }
        // After this window finishes closing, if no dashboard windows remain, hide from the Dock.
        DispatchQueue.main.async {
            let stillOpen = NSApp.windows.contains { $0.isVisible && self.isDashboard($0) }
            if !stillOpen { NSApp.setActivationPolicy(.accessory) }
        }
    }

    /// The dashboard is a normal titled window (excludes the menu-bar popover / status windows).
    private func isDashboard(_ w: NSWindow) -> Bool {
        w.styleMask.contains(.titled) && w.canBecomeMain && !w.styleMask.contains(.nonactivatingPanel)
    }
}
