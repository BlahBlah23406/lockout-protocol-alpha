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
    }

    @Published private(set) var current: Info?
    private var windows: [NSWindow] = []

    var isBlocking: Bool { current != nil }

    func show(bundleId: String, appName: String, reason: String) {
        guard current == nil else { return }   // one block at a time
        let info = Info(bundleId: bundleId, appName: appName, reason: reason)
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
                appName: appName, reason: reason,
                onOverride: { [weak self] in self?.finishOverride() },
                onQuit: { [weak self] in self?.finishQuit() })
            w.contentView = NSHostingView(rootView: view)
            w.setFrame(screen.frame, display: true)
            w.makeKeyAndOrderFront(nil)
            windows.append(w)
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    /// "Override" — keep using the app. Grants a 5-minute override and tears down the overlay.
    /// Requires the passcode when one is set (enforced in BlockView).
    func finishOverride() {
        if let info = current { Overrides.grant(info.bundleId) }
        teardown()
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
