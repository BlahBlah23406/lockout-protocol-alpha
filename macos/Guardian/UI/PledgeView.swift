import AppKit
import SwiftUI

/// The pledge gate, shown when System Settings is brought frontmost. Friction, not a lock: "I promise"
/// dismisses it and lets the user proceed; "I cannot" hides System Settings. The macOS analogue of
/// the Android `PledgeActivity`.
@MainActor
final class PledgeController: ObservableObject {

    static let shared = PledgeController()

    private var window: NSWindow?
    private var cooldownUntil = Date.distantPast

    var isShowing: Bool { window != nil }

    func show() {
        guard window == nil, Date() >= cooldownUntil else { return }

        let w = KeyableWindow(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 560),
            styleMask: [.borderless], backing: .buffered, defer: false)
        w.level = .screenSaver
        w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        w.isOpaque = true
        w.backgroundColor = NSColor(LCARS.space)
        w.hasShadow = true
        w.isReleasedWhenClosed = false
        w.center()

        let view = PledgeView(
            onSwear: { [weak self] in
                EventLog.shared.add("🤲 pledge taken — entered Settings")
                self?.dismiss()
            },
            onDecline: { [weak self] in
                EventLog.shared.add("🛡️ pledge declined — left Settings")
                Self.hideSystemSettings()
                self?.dismiss()
            })
        w.contentView = NSHostingView(rootView: view)
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        window = w
    }

    private func dismiss() {
        // Brief cooldown so re-focusing Settings doesn't immediately re-pop the pledge.
        cooldownUntil = Date().addingTimeInterval(30)
        window?.orderOut(nil)
        window?.close()
        window = nil
    }

    private static func hideSystemSettings() {
        for id in ["com.apple.systempreferences", "com.apple.SystemSettings"] {
            NSRunningApplication.runningApplications(withBundleIdentifier: id).forEach { $0.hide() }
        }
    }
}

struct PledgeView: View {
    var onSwear: () -> Void
    var onDecline: () -> Void

    var body: some View {
        ZStack {
            LCARS.space.ignoresSafeArea()
            VStack(spacing: 20) {
                RoundedRectangle(cornerRadius: 10).fill(LCARS.gold).frame(width: 90, height: 26)
                Text("PAUSE.")
                    .font(.system(size: 38, weight: .black, design: .rounded))
                    .foregroundColor(LCARS.orange).kerning(3)
                Text("Click “I promise” only if you genuinely commit not to use Settings to " +
                     "undermine Guardian — or ANY other blocking, filtering, or accountability " +
                     "system you have put in place (content blockers, DNS or network filters, " +
                     "Screen Time limits, router or browser restrictions, other accountability " +
                     "apps) — or their ability to execute their functions.")
                    .font(.system(.title3, design: .rounded))
                    .foregroundColor(LCARS.readout)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 12)

                LcarsButton(title: "I promise", color: LCARS.gold, action: onSwear)
                    .frame(width: 380)
                LcarsButton(title: "I cannot — take me back", color: LCARS.blue, action: onDecline)
                    .frame(width: 380)
            }
            .padding(40)
        }
        .frame(width: 560, height: 560)
    }
}
