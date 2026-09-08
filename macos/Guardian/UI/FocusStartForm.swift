import SwiftUI

/// "What are you working on?" — the start form.
///
/// Deliberately compact enough to live inside the menu-bar popover as well as the dashboard,
/// because a focus tool that takes two minutes to arm gets used on the days you least need it and
/// skipped on the days you do. The task field is prefilled with last time's answer and focused on
/// appear; everything else already has a working default from Settings.
///
/// The one place friction is added on purpose is the accountability picker: choosing "locked"
/// means handing your passcode to future-you-who-wants-to-stop, so the consequences are spelled
/// out next to the option rather than buried in a docs page.
struct FocusStartForm: View {
    var onStarted: () -> Void
    var onCancel: () -> Void

    @ObservedObject private var prefs = Prefs.shared
    @ObservedObject private var sessions = SessionStore.shared

    @State private var task = ""
    @State private var minutes = 60
    @State private var interval = FocusSession.defaultInterval
    @State private var accountability: Accountability = .selfManaged
    @State private var error = ""
    @State private var showingApps = false
    @State private var extraApps: Set<String> = []
    @State private var allowedApps: Set<String> = []
    @FocusState private var taskFocused: Bool

    private static let durations: [(Int, String)] = [(25, "25m"), (50, "50m"), (90, "90m"),
                                                     (0, "open")]
    private static let intervals: [(Int, String)] = [(30, "30s"), (60, "1m"), (120, "2m"),
                                                     (300, "5m"), (600, "10m")]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("I AM WORKING ON")
                .font(.system(size: 10, design: .rounded).weight(.heavy))
                .foregroundColor(LCARS.gold)

            TextEditor(text: $task)
                .font(.system(.caption, design: .monospaced))
                .frame(height: 54)
                .scrollContentBackground(.hidden)
                .background(LCARS.panel)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .focused($taskFocused)

            Text("Plain English. \"revising integration by parts for Friday's calc test\" works "
                 + "far better than \"study\".")
                .font(.system(size: 9))
                .foregroundColor(LCARS.lilac)
                .fixedSize(horizontal: false, vertical: true)

            HStack(alignment: .top, spacing: 10) {
                picker("FOR", Self.durations, $minutes)
                picker("EVERY", Self.intervals, $interval)
            }

            Text("Each check is one screenshot and one model call, so the interval is also your "
                 + "cost dial. A local model is free — check as often as you like.")
                .font(.system(size: 9))
                .foregroundColor(LCARS.lilac)
                .fixedSize(horizontal: false, vertical: true)

            accountabilityPicker
            appsRow

            if !error.isEmpty {
                Text(error).font(.caption2).foregroundColor(LCARS.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack {
                LcarsButton(title: "Start", color: LCARS.orange, action: start)
                LcarsButton(title: "Cancel", color: LCARS.lilac) { onCancel() }
            }
        }
        .onAppear {
            task = prefs.lastTask
            minutes = prefs.focusMinutes
            interval = prefs.focusInterval
            accountability = prefs.focusAccountability
            taskFocused = true
        }
        .sheet(isPresented: $showingApps) {
            AppPickerView(selection: Binding(
                get: { currentSelection },
                set: { applySelection($0) }),
                title: "Apps for this session",
                note: "Ticking an extra app watches it for this session only. Unticking one of "
                    + "your defaults excuses it for this session only. Neither edits your saved "
                    + "watchlist.")
        }
    }

    // MARK: - Pieces

    private func picker(_ title: String, _ choices: [(Int, String)],
                        _ binding: Binding<Int>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 9, design: .rounded).weight(.heavy))
                .foregroundColor(LCARS.gold)
            Picker("", selection: binding) {
                ForEach(choices, id: \.0) { Text($0.1).tag($0.0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
    }

    private var accountabilityPicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("ACCOUNTABILITY")
                .font(.system(size: 10, design: .rounded).weight(.heavy))
                .foregroundColor(LCARS.gold)
            ForEach(Accountability.allCases, id: \.self) { level in
                Button {
                    accountability = level
                } label: {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: accountability == level
                              ? "largecircle.fill.circle" : "circle")
                            .foregroundColor(accountability == level ? LCARS.gold : LCARS.lilac)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(level.title)
                                .font(.system(.caption, design: .rounded).weight(.semibold))
                                .foregroundColor(LCARS.gold)
                            Text(level.blurb)
                                .font(.system(size: 9))
                                .foregroundColor(LCARS.readout)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
            if let warning = lockedWarning {
                // Say the awkward part out loud before they commit, not after.
                Text("⚠ " + warning)
                    .font(.system(size: 9))
                    .foregroundColor(LCARS.gold)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var lockedWarning: String? {
        guard accountability == .locked else { return nil }
        var problems: [String] = []
        if !prefs.pinSet {
            problems.append("no passcode is set yet — set one in Settings first, or overrides "
                          + "will need no code at all")
        }
        if !prefs.pushEnabled {
            problems.append("alerts are switched off, so nobody will actually be told")
        }
        return problems.isEmpty ? "Alerts go to your private link: \(prefs.ntfyTopic)"
                                : problems.joined(separator: "; ")
    }

    private var appsRow: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("APPS")
                .font(.system(size: 10, design: .rounded).weight(.heavy))
                .foregroundColor(LCARS.gold)
            Text(appsSummary)
                .font(.system(size: 9, design: .monospaced))
                .foregroundColor(LCARS.readout)
            Button("Change apps for this session only…") { showingApps = true }
                .buttonStyle(.plain)
                .font(.system(size: 9).weight(.semibold))
                .foregroundColor(LCARS.blue)
        }
    }

    private var currentSelection: Set<String> {
        prefs.monitoredApps.union(extraApps).subtracting(allowedApps)
    }

    private var appsSummary: String {
        var bits = ["\(currentSelection.count) app(s) watched this session"]
        if !extraApps.isEmpty { bits.append("+\(extraApps.count) added today") }
        if !allowedApps.isEmpty { bits.append("−\(allowedApps.count) excused today") }
        return bits.joined(separator: "  ·  ")
    }

    /// Store the *delta* against the saved defaults, not a copy of the list. If you later edit your
    /// default watchlist mid-session, a session started before that edit still tracks it — which is
    /// what people expect, and what a snapshot would silently get wrong.
    private func applySelection(_ selected: Set<String>) {
        let defaults = prefs.monitoredApps
        extraApps = selected.subtracting(defaults)
        allowedApps = defaults.subtracting(selected)
    }

    // MARK: - Start

    private func start() {
        let trimmed = task.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else {
            error = "Tell it what you're working on first."
            return
        }
        guard !(accountability == .locked && minutes == 0) else {
            // An open-ended locked session plus a forgotten passcode is the one shape that could
            // genuinely trap someone. Refuse to create it.
            error = "A locked session needs an end time — open-ended locked sessions aren't allowed."
            return
        }

        let session = FocusSession(task: trimmed, plannedMinutes: minutes,
                                   intervalSeconds: interval, accountability: accountability,
                                   extraApps: extraApps, allowedApps: allowedApps,
                                   providerId: prefs.providerId)
        guard !session.watchlist(defaults: prefs.monitoredApps).isEmpty else {
            error = "No apps are being watched — pick some under 'Change apps', or set a default "
                  + "watchlist in the dashboard."
            return
        }

        // Remember the answers so next time is one keypress.
        prefs.lastTask = trimmed
        prefs.focusMinutes = minutes
        prefs.focusInterval = interval
        prefs.focusAccountability = accountability

        sessions.start(session)
        MonitorService.shared.start()
        onStarted()
    }
}
