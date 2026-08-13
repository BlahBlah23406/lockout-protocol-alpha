import SwiftUI

struct ContentView: View {
    @StateObject private var prefs = Prefs.shared
    @StateObject private var monitor = MonitorService.shared
    @StateObject private var log = EventLog.shared

    @State private var showSettings = false
    @State private var showApps = false
    @State private var showGuidelines = false

    /// Live Screen Recording (TCC) state, polled while the dashboard is open so the indicator stays
    /// accurate regardless of whether monitoring is currently running.
    @State private var screenRecOK = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            LcarsHeader(title: "Guardian", subtitle: "Accountability Monitor")

            statusPanel
            defensesPanel

            HStack(spacing: 10) {
                LcarsButton(title: monitor.isRunning ? "Stop" : "Start",
                            color: monitor.isRunning ? LCARS.red : LCARS.orange) {
                    monitor.isRunning ? monitor.stop() : monitor.start()
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
                statusRow("SELF-HEAL", prefs.monitoringEnabled, on: "watchdog + alerts armed",
                          off: "monitoring off")
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
                row("STATE", monitor.isRunning ? "MONITORING" : "STOPPED",
                    monitor.isRunning ? LCARS.readout : LCARS.red)
                row("MODE", prefs.dryRun ? "TEST (no blocking)" : "ARMED",
                    prefs.dryRun ? LCARS.gold : LCARS.red)
                row("ACTIVITY", monitor.status, LCARS.readout)
                row("WATCHING", "\(prefs.monitoredApps.count) app(s)", LCARS.readout)
                row("ACCESS", prefs.pinSet ? "passcode set" : "no passcode",
                    prefs.pinSet ? LCARS.readout : LCARS.lilac)
                row("MODEL", prefs.ollamaModel, LCARS.blue)
                row("ALERTS", prefs.pushEnabled ? "ntfy → \(prefs.ntfyTopic)" : "off", LCARS.lilac)
            }
        }
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
