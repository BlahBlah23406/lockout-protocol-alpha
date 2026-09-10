import SwiftUI

/// The menu-bar popover: start a session, or see the one running.
///
/// The whole start flow fits here — nothing about declaring "revising integration by parts, 50
/// minutes" needs a window — and the dashboard becomes the secondary destination.
struct MenuBarView: View {
    @StateObject private var monitor = MonitorService.shared
    @StateObject private var prefs = Prefs.shared
    @StateObject private var sessions = SessionStore.shared
    @Environment(\.openWindow) private var openWindow

    /// Actions that need the passcode when the running session is locked.
    private enum PendingAction { case endSession, quit }
    @State private var pending: PendingAction?
    @State private var confirmPin = ""
    @State private var confirmWrong = false

    @State private var composing = false
    /// Repaints the countdown once a second while the popover is open — and only while it is open.
    @State private var now = Date()
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider().overlay(LCARS.blue.opacity(0.3))

            if pending != nil {
                confirmPrompt
            } else if composing {
                FocusStartForm(onStarted: { composing = false },
                               onCancel: { composing = false })
            } else if let session = sessions.current {
                activeSession(session)
            } else {
                idle
            }
        }
        .padding(14)
        .frame(width: 340)
        .background(LCARS.space)
        .onReceive(ticker) { now = $0 }
    }

    // MARK: - Header

    private var header: some View {
        let session = sessions.current
        let locked = session?.accountability == .locked
        // Grey when nothing is running: the icon should never suggest it is watching when it
        // isn't.
        let tint = session == nil ? LCARS.lilac : (locked ? LCARS.red : LCARS.readout)

        return HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 5).fill(tint).frame(width: 26, height: 16)
            VStack(alignment: .leading, spacing: 0) {
                Text("LOCKOUT")
                    .font(.system(.subheadline, design: .rounded).weight(.heavy))
                    .foregroundColor(LCARS.gold)
                Text(statusLine(session))
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundColor(tint)
            }
            Spacer()
            Circle().fill(tint).frame(width: 9, height: 9)
        }
    }

    private func statusLine(_ session: FocusSession?) -> String {
        guard let session else { return "NO SESSION · NOT WATCHING" }
        let mode = session.accountability == .locked ? "LOCKED" : "IN FOCUS"
        return prefs.dryRun ? "\(mode) · TEST" : mode
    }

    // MARK: - Idle

    private var idle: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Nothing is being watched. No screenshots are taken until you start a session.")
                .font(.caption)
                .foregroundColor(LCARS.readout)
                .fixedSize(horizontal: false, vertical: true)

            if !prefs.lastTask.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("LAST TIME")
                        .font(.system(size: 9, design: .monospaced).weight(.bold))
                        .foregroundColor(LCARS.blue)
                    Text(prefs.lastTask)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(LCARS.gold)
                        .fixedSize(horizontal: false, vertical: true)
                }
                LcarsButton(title: "Start that again", color: LCARS.gold) { startLast() }
                    .frame(maxWidth: .infinity)
            }

            LcarsButton(title: "New focus session…", color: LCARS.orange) { composing = true }
                .frame(maxWidth: .infinity)
            footerLinks
        }
    }

    /// Run the same session again: same task, same settings.
    private func startLast() {
        let session = FocusSession(task: prefs.lastTask,
                                   plannedMinutes: prefs.focusMinutes,
                                   intervalSeconds: prefs.focusInterval,
                                   accountability: prefs.focusAccountability,
                                   providerId: prefs.providerId)
        // The same guard the form applies: open-ended + locked is never created silently.
        guard !(session.accountability == .locked && session.plannedMinutes == 0),
              !session.watchlist(defaults: prefs.monitoredApps).isEmpty else {
            composing = true
            return
        }
        sessions.start(session)
        monitor.start()
    }

    // MARK: - Active session

    private func activeSession(_ session: FocusSession) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(session.task)
                .font(.system(.callout, design: .monospaced))
                .foregroundColor(LCARS.gold)
                .fixedSize(horizontal: false, vertical: true)

            VStack(spacing: 2) {
                readout("TIME", session.remainingText)
                readout("CHECKS", "\(session.checks) (\(session.offTaskCount) off-task)")
                readout("EVERY", "\(session.intervalSeconds)s")
                readout("APPS", "\(session.watchlist(defaults: prefs.monitoredApps).count) watched")
                if session.overrideCount > 0 {
                    readout("OVERRIDES", "\(session.overrideCount)")
                }
                readout("STATUS", monitor.status)
            }
            .padding(8)
            .background(LCARS.panel)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            LcarsButton(title: "End session", color: LCARS.red) {
                protectedAction(.endSession)
            }
            .frame(maxWidth: .infinity)
            footerLinks
        }
    }

    private func readout(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text(label)
                .font(.system(size: 9, design: .monospaced).weight(.bold))
                .foregroundColor(LCARS.blue)
                .frame(width: 62, alignment: .leading)
            Text(value)
                .font(.system(size: 9, design: .monospaced))
                .foregroundColor(LCARS.readout)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var footerLinks: some View {
        HStack(spacing: 8) {
            LcarsButton(title: "Dashboard", color: LCARS.blue) {
                AppActivation.showMainWindow(openWindow)
            }
            LcarsButton(title: "Quit", color: LCARS.lilac) { protectedAction(.quit) }
        }
    }

    // MARK: - Passcode gate

    private var confirmPrompt: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(pending == .quit
                 ? "Enter passcode to quit during a locked session"
                 : "Enter passcode to end this locked session")
                .font(.caption).foregroundColor(LCARS.gold)
                .fixedSize(horizontal: false, vertical: true)
            SecureField("Passcode", text: $confirmPin)
                .textFieldStyle(.roundedBorder)
                .onSubmit(runPending)
            if confirmWrong { Text("Wrong passcode").font(.caption2).foregroundColor(LCARS.red) }
            HStack {
                LcarsButton(title: "Confirm", color: LCARS.orange, action: runPending)
                LcarsButton(title: "Cancel", color: LCARS.lilac) { clearPending() }
            }
        }
    }

    /// A locked session holds its own exit: the passcode stops you quietly cancelling the
    /// commitment, not using the Mac.
    private func protectedAction(_ action: PendingAction) {
        let locked = sessions.current?.accountability.requiresPasscodeToEnd ?? false
        if prefs.pinSet && locked {
            pending = action; confirmPin = ""; confirmWrong = false
        } else {
            perform(action)
        }
    }

    private func runPending() {
        guard prefs.checkPin(confirmPin) else { confirmWrong = true; confirmPin = ""; return }
        if let p = pending { perform(p) }
        clearPending()
    }

    private func clearPending() {
        pending = nil; confirmPin = ""; confirmWrong = false
    }

    private func perform(_ action: PendingAction) {
        switch action {
        case .endSession:
            sessions.end(reason: "ended by user")
            monitor.stop()
        case .quit:
            // Quitting mid-session is the one bypass macOS cannot prevent; AppDelegate tells the
            // partner on the way out.
            NSApp.terminate(nil)
        }
    }
}
