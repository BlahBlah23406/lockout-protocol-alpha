import AppKit
import SwiftUI

/// A borderless NSWindow that can still become key (so its passcode field receives keystrokes).
final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

/// Shows a FULL-SCREEN, always-on-top block overlay across every display when a violation is
/// confirmed. The offending app is covered until the user dismisses it — with the passcode if one
/// is set, otherwise a plain button. Dismissing grants a short override so it won't re-block
/// immediately. This is the macOS analogue of the Android `BlockActivity`.
@MainActor
final class BlockController: ObservableObject {

    static let shared = BlockController()

    struct Info: Identifiable {
        let id = UUID()
        let bundleId: String
        let appName: String
        let reason: String
        /// nil for a content-rules block. The level is read from the session that was actually
        /// started, not from a global setting that could have drifted.
        var session: FocusSession?
        /// Ties a later "false alarm" press back to the exact check that caused this block.
        var judgementId: String = ""
    }

    @Published private(set) var current: Info?
    private var windows: [NSWindow] = []

    var isBlocking: Bool { current != nil }

    func show(bundleId: String, appName: String, reason: String,
              session: FocusSession? = nil, judgementId: String = "") {
        guard current == nil else { return }   // one block at a time
        let info = Info(bundleId: bundleId, appName: appName, reason: reason,
                        session: session, judgementId: judgementId)
        current = info

        // Make sure Guardian is active so the overlay is frontmost and can take keyboard focus.
        NSApp.setActivationPolicy(.regular)

        for screen in NSScreen.screens {
            let w = KeyableWindow(contentRect: screen.frame, styleMask: [.borderless],
                                  backing: .buffered, defer: false)
            w.level = .screenSaver                       // above the menu bar and other windows
            w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            w.isOpaque = true
            w.backgroundColor = .black
            w.hasShadow = false
            w.isReleasedWhenClosed = false
            let view = BlockView(
                appName: appName, reason: reason, session: session,
                onOverride: { [weak self] in self?.finishOverride() },
                onQuit: { [weak self] in self?.finishQuit() },
                onFalseAlarm: { [weak self] in self?.markFalseAlarm() })
            w.contentView = NSHostingView(rootView: view)
            w.setFrame(screen.frame, display: true)
            w.makeKeyAndOrderFront(nil)
            windows.append(w)
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Keep using the app. Pauses the whole session briefly, not just this app: being
    /// re-challenged 90 seconds after saying "yes, I need this" teaches people to ignore it.
    func finishOverride() {
        let info = current
        if let info { Overrides.grant(info.bundleId) }
        if let session = info?.session {
            let store = SessionStore.shared
            store.recordOverride()
            store.pause(seconds: min(300, max(Double(session.intervalSeconds) * 2, 120)))
            if session.accountability.alertsPartner {
                alertOverride(appName: info?.appName ?? "an app", session: session)
            }
        }
        teardown()
    }

    /// Record that this block was wrong, for the learner to pick up later.
    func markFalseAlarm() {
        guard let info = current, !info.judgementId.isEmpty else { return }
        Judgements.addFeedback(info.judgementId, .falseAlarm)
    }

    /// An override on a locked session is the event the partner signed up to hear about.
    private func alertOverride(appName: String, session: FocusSession) {
        let prefs = Prefs.shared
        let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer,
                                topic: prefs.ntfyTopic)
        let count = SessionStore.shared.current?.overrideCount ?? session.overrideCount
        Task {
            _ = await Pusher.send(cfg, title: "[Lockout] Override used in \(appName)",
                                  message: "Task: \(session.task)\n\nThe block on \(appName) was "
                                         + "overridden with the passcode. That is override "
                                         + "#\(count) this session.")
        }
    }

    /// "Dismiss" — the no-code, compliant exit: quit the offending app, then tear down the overlay.
    /// A short override covers the moment between sending the quit and the app actually closing.
    func finishQuit() {
        if let info = current {
            Overrides.grant(info.bundleId, seconds: 30)
            FrontmostApp.quit(bundleId: info.bundleId)
        }
        teardown()
    }

    private func teardown() {
        windows.forEach { $0.orderOut(nil); $0.close() }
        windows.removeAll()
        current = nil

        // If no dashboard window is open, drop back to a background (Dock-less) app.
        let dashboardOpen = NSApp.windows.contains {
            $0.isVisible && $0.styleMask.contains(.titled) && $0.canBecomeMain
        }
        if !dashboardOpen { NSApp.setActivationPolicy(.accessory) }
    }
}
