import AppKit

/// Watches which app becomes frontmost and raises the pledge window when the user opens
/// System Settings — the place where Screen Recording, Login Items, and the app itself can be
/// disabled. The macOS analogue of the Android `SettingsGuard`. Non-blocking: after pledging, the
/// user can still use Settings.
@MainActor
final class SettingsGuard {

    static let shared = SettingsGuard()

    private var observer: NSObjectProtocol?
    private let settingsBundleIds: Set<String> = [
        "com.apple.systempreferences",   // System Settings / System Preferences
        "com.apple.SystemSettings"
    ]

    private init() {}

    func start() {
        guard observer == nil else { return }
        observer = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil, queue: .main) { [weak self] note in
                guard let self else { return }
                let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
                Task { @MainActor in self.handle(app) }
            }
    }

    func stop() {
        if let observer { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        observer = nil
    }

    private func handle(_ app: NSRunningApplication?) {
        guard Prefs.shared.pledgeOnSettings,
              let id = app?.bundleIdentifier, settingsBundleIds.contains(id) else { return }
        PledgeController.shared.show()
    }
}
