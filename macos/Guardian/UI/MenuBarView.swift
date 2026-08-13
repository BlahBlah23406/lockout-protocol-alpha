import SwiftUI

/// The menu-bar popover. Shows monitor status and lets you open the main window, start/stop
/// monitoring, or quit (the last two behind the passcode, when one is set).
struct MenuBarView: View {
    @StateObject private var monitor = MonitorService.shared
    @StateObject private var prefs = Prefs.shared
    @Environment(\.openWindow) private var openWindow

    // Passcode confirmation for protected actions (stop / quit) when a passcode is set.
    private enum PendingAction { case stop, quit }
    @State private var pending: PendingAction?
    @State private var confirmPin = ""
    @State private var confirmWrong = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider().overlay(LCARS.blue.opacity(0.3))

            if pending != nil { confirmPrompt } else { footer }
        }
        .padding(14)
        .frame(width: 340)
        .background(LCARS.space)
    }

    // MARK: - Passcode confirm for protected actions

    private var confirmPrompt: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Enter passcode to \(pending == .quit ? "quit" : "stop") Guardian")
                .font(.caption).foregroundColor(LCARS.gold)
            SecureField("Passcode", text: $confirmPin)
                .textFieldStyle(.roundedBorder)
                .onSubmit(runPending)
            if confirmWrong { Text("Wrong passcode").font(.caption2).foregroundColor(LCARS.red) }
            HStack {
                LcarsButton(title: "Confirm", color: LCARS.orange, action: runPending)
                LcarsButton(title: "Cancel", color: LCARS.lilac) {
                    pending = nil; confirmPin = ""; confirmWrong = false
                }
            }
        }
    }

    private func protectedAction(_ action: PendingAction) {
        if prefs.pinSet { pending = action; confirmPin = ""; confirmWrong = false }
        else { perform(action) }
    }

    private func runPending() {
        guard prefs.checkPin(confirmPin) else { confirmWrong = true; confirmPin = ""; return }
        if let p = pending { perform(p) }
        pending = nil; confirmPin = ""; confirmWrong = false
    }

    private func perform(_ action: PendingAction) {
        switch action {
        case .stop: monitor.stop()
        case .quit: NSApp.terminate(nil)
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 5).fill(LCARS.orange).frame(width: 26, height: 16)
            VStack(alignment: .leading, spacing: 0) {
                Text("GUARDIAN")
                    .font(.system(.subheadline, design: .rounded).weight(.heavy))
                    .foregroundColor(LCARS.gold)
                Text(monitor.isRunning ? (prefs.dryRun ? "MONITORING · TEST" : "MONITORING · ARMED")
                                       : "STOPPED")
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundColor(monitor.isRunning ? LCARS.readout : LCARS.red)
            }
            Spacer()
            Circle().fill(monitor.isRunning ? LCARS.readout : LCARS.red).frame(width: 9, height: 9)
        }
    }

    // MARK: - Footer

    private var footer: some View {
        HStack(spacing: 8) {
            LcarsButton(title: monitor.isRunning ? "Stop" : "Start",
                        color: monitor.isRunning ? LCARS.red : LCARS.orange) {
                if monitor.isRunning { protectedAction(.stop) } else { monitor.start() }
            }
            LcarsButton(title: "Open", color: LCARS.blue) {
                AppActivation.showMainWindow(openWindow)
            }
            LcarsButton(title: "Quit", color: LCARS.lilac) {
                protectedAction(.quit)
            }
        }
    }
}
