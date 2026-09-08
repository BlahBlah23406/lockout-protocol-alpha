import SwiftUI

/// The main dashboard, reorganised around the focus session.
///
/// The top answers "is a session running, what did I say I was doing, and how is it going"; the
/// controls below start or end one. The old always-on Start/Stop pair is gone, because monitoring
/// is no longer a mode you leave running — it begins and ends with a session.
struct ContentView: View {
    @StateObject private var prefs = Prefs.shared
    @StateObject private var monitor = MonitorService.shared
    @StateObject private var sessions = SessionStore.shared
    @StateObject private var log = EventLog.shared

    @State private var showSettings = false
    @State private var showApps = false
    @State private var showGuidelines = false
    @State private var showStart = false
    @State private var endPin = ""
    @State private var endWrong = false
    @State private var askingToEnd = false
    /// Repaints the countdown while the dashboard is open.
    @State private var now = Date()
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    /// Live Screen Recording (TCC) state, polled while the dashboard is open so the indicator stays
    /// accurate regardless of whether monitoring is currently running.
    @State private var screenRecOK = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            LcarsHeader(title: "Lockout Protocol", subtitle: "Focus Monitor")

            statusPanel
            defensesPanel

            if askingToEnd { endSessionPrompt }

            HStack(spacing: 10) {
                LcarsButton(title: sessions.isActive ? "End session" : "Start focus session",
                            color: sessions.isActive ? LCARS.red : LCARS.orange) {
                    sessions.isActive ? requestEnd() : (showStart = true)
                }
                LcarsButton(title: prefs.dryRun ? "Arm (test mode on)" : "Test mode (armed)",
                            color: prefs.dryRun ? LCARS.gold : LCARS.red) {
                    prefs.dryRun.toggle()
                }
            }

            HStack(spacing: 10) {
                LcarsButton(title: "Apps", color: LCARS.blue) { showApps = true }
                LcarsButton(title: "Guidelines", color: LCARS.lilac) { showGuidelines = true }
                LcarsButton(title: "Settings", color: LCARS.blue) { showSettings = true }
            }

            activityLog
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LCARS.space)
        .sheet(isPresented: $showSettings) { SettingsView().frame(width: 560, height: 600) }
        .sheet(isPresented: $showApps) { AppPickerView().frame(width: 520, height: 600) }
        .sheet(isPresented: $showGuidelines) { GuidelinesView().frame(width: 560, height: 480) }
        .sheet(isPresented: $showStart) {
            VStack {
                LcarsHeader(title: "Focus Session", subtitle: "What are you working on?")
                FocusStartForm(onStarted: { showStart = false }, onCancel: { showStart = false })
            }
            .padding(20)
            .frame(width: 460)
            .background(LCARS.space)
        }
        .onReceive(ticker) { now = $0 }
        .task {
            while !Task.isCancelled {
                screenRecOK = await ScreenCapturer.hasPermission()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    /// Tamper-resistance readout: whether each defense layer is actually active right now.
    private var defensesPanel: some View {
        ReadoutPanel {
            VStack(alignment: .leading, spacing: 6) {
                Text("DEFENSES")
                    .font(.system(.caption, design: .rounded).weight(.heavy))
                    .foregroundColor(LCARS.gold)
                statusRow("SCREEN REC", screenRecOK, on: "granted",
                          off: "OFF — can't see screen", warn: true)
                statusRow("KEEP-ALIVE", KeepAliveAgent.isActive, on: "on — relaunches if quit",
                          off: "off", gold: true)
                statusRow("LOGIN ITEM", LaunchAtLogin.isEnabled, on: "on", off: "off")
                statusRow("PLEDGE", prefs.pledgeOnSettings, on: "on (System Settings)", off: "off")
                statusRow("SELF-HEAL", sessions.isActive, on: "watchdog + alerts armed",
                          off: "no session — idle")
            }
        }
    }

    /// One defense line: ●/○ marker, green when active, red/amber when a protection is down.
    private func statusRow(_ label: String, _ active: Bool, on: String, off: String,
                           warn: Bool = false, gold: Bool = false) -> some View {
        let color: Color = active ? (gold ? LCARS.gold : LCARS.readout)
                                   : (warn ? LCARS.red : LCARS.lilac)
        return row(label, "\(active ? "●" : "○") \(active ? on : off)", color)
    }

    private var statusPanel: some View {
        ReadoutPanel {
            VStack(alignment: .leading, spacing: 6) {
                if let session = sessions.current {
                    activeRows(session)
                } else {
                    idleRows
                }
            }
        }
    }

    @ViewBuilder private var idleRows: some View {
        row("SESSION", "none — nothing is being watched", LCARS.lilac)
        row("PRIVACY", "no screenshots are taken while idle", LCARS.readout)
        row("DEFAULTS", "\(prefs.monitoredApps.count) app(s) on the watchlist", LCARS.readout)
        row("PROVIDER", prefs.providerModel.isEmpty ? "not set" : prefs.providerModel, LCARS.blue)
        row("ACCESS", prefs.pinSet ? "passcode set" : "no passcode",
            prefs.pinSet ? LCARS.readout : LCARS.lilac)
        row("ALERTS", prefs.pushEnabled ? "ntfy → \(prefs.ntfyTopic)" : "off", LCARS.lilac)
    }

    @ViewBuilder private func activeRows(_ session: FocusSession) -> some View {
        let locked = session.accountability == .locked
        row("TASK", session.task, LCARS.gold)
        row("MODE", locked ? "LOCKED — passcode to override" : "self-managed",
            locked ? LCARS.red : LCARS.readout)
        row("TIME", session.remainingText + (prefs.dryRun ? "  [TEST — nothing is blocked]" : ""),
            prefs.dryRun ? LCARS.gold : LCARS.readout)
        row("CHECKS", "\(session.checks) run, \(session.offTaskCount) off-task, "
                    + "\(session.overrideCount) override(s)", LCARS.readout)
        row("EVERY", "\(session.intervalSeconds)s", LCARS.readout)
        row("WATCHING", "\(session.watchlist(defaults: prefs.monitoredApps).count) app(s)",
            LCARS.readout)
        row("ACTIVITY", monitor.status, LCARS.readout)
        row("PROVIDER", prefs.providerModel.isEmpty ? "not set" : prefs.providerModel, LCARS.blue)
    }

    /// Ending a locked session early is the commitment being broken, so it costs the passcode.
    private func requestEnd() {
        guard let session = sessions.current else { return }
        if prefs.pinSet && session.accountability.requiresPasscodeToEnd {
            askingToEnd = true
            endPin = ""
            endWrong = false
        } else {
            endSession()
        }
    }

    private func endSession() {
        sessions.end(reason: "ended by user")
        monitor.stop()
        askingToEnd = false
        endPin = ""
    }

    private var endSessionPrompt: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Enter passcode to end this locked session")
                .font(.caption).foregroundColor(LCARS.gold)
            HStack {
                SecureField("Passcode", text: $endPin)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 200)
                    .onSubmit(confirmEnd)
                LcarsButton(title: "Confirm", color: LCARS.orange, action: confirmEnd)
                LcarsButton(title: "Cancel", color: LCARS.lilac) { askingToEnd = false }
            }
            if endWrong { Text("Wrong passcode").font(.caption2).foregroundColor(LCARS.red) }
        }
    }

    private func confirmEnd() {
        if prefs.checkPin(endPin) { endSession() } else { endWrong = true; endPin = "" }
    }

    private func row(_ label: String, _ value: String, _ color: Color) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(.system(.caption, design: .monospaced).weight(.bold))
                .foregroundColor(LCARS.blue.opacity(0.8))
                .frame(width: 90, alignment: .leading)
            Text(value)
                .font(.system(.caption, design: .monospaced))
                .foregroundColor(color)
                .textSelection(.enabled)
            Spacer()
        }
    }

    private var activityLog: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("ACTIVITY LOG")
                    .font(.system(.caption, design: .rounded).weight(.heavy))
                    .foregroundColor(LCARS.gold)
                Spacer()
                Button("Clear") { log.clear() }
                    .font(.caption)
                    .foregroundColor(LCARS.blue)
                    .buttonStyle(.plain)
            }
            ReadoutPanel {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 2) {
                            ForEach(log.entries) { e in
                                Text(log.formatted(e))
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(LCARS.readout)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .id(e.id)
                            }
                            if log.entries.isEmpty {
                                Text("— no activity yet —")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(LCARS.readout.opacity(0.4))
                            }
                        }
                    }
                    .onChange(of: log.entries.count) { _, _ in
                        if let last = log.entries.last { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }
            .frame(maxHeight: .infinity)
        }
        .frame(maxHeight: .infinity)
    }
}
