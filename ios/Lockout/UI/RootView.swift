import SwiftUI

/// The main screen: start a session, or see the one running.
///
/// Small on purpose. On iOS the app is not where you spend the session — the shield is — so this
/// only needs to answer "is one running, and how do I start or stop one".
struct RootView: View {
    @StateObject private var prefs = Prefs.shared
    @StateObject private var sessions = SessionStore.shared
    @StateObject private var shield = ShieldController.shared

    @State private var showingStart = false
    @State private var showingSettings = false
    @State private var askingToEnd = false
    @State private var pin = ""
    @State private var pinWrong = false
    @State private var authProblem = ""
    /// Repaints the countdown while the app is open.
    @State private var now = Date()
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            List {
                if !authProblem.isEmpty {
                    Section { Text(authProblem).foregroundStyle(.red).font(.callout) }
                }
                ForEach(shield.diagnose(), id: \.self) { problem in
                    Section { Text(problem).foregroundStyle(.orange).font(.callout) }
                }

                if let session = sessions.current {
                    activeSection(session)
                } else {
                    idleSection
                }

                Section {
                    Button("Settings") { showingSettings = true }
                }
            }
            .navigationTitle("Lockout Protocol")
            .sheet(isPresented: $showingStart) {
                FocusStartView(onStarted: { showingStart = false },
                               onCancel: { showingStart = false })
            }
            .sheet(isPresented: $showingSettings) { SettingsView() }
            .onReceive(ticker) { now = $0 }
            .task {
                if !shield.isAuthorized {
                    authProblem = await shield.requestAuthorization() ?? ""
                }
            }
        }
    }

    // MARK: - Idle

    private var idleSection: some View {
        Section {
            Button {
                showingStart = true
            } label: {
                Label("Start a focus session", systemImage: "play.circle.fill")
                    .font(.body.weight(.semibold))
            }
            if !prefs.lastTask.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("LAST TIME").font(.caption2).foregroundStyle(.secondary)
                    Text(prefs.lastTask).font(.callout)
                }
            }
        } header: {
            Text("No session")
        } footer: {
            Text("Nothing is shielded. This app can't see your screen — on iOS no app can — so "
                 + "while no session is running it knows nothing about what you're doing.")
        }
    }

    // MARK: - Active

    private func activeSection(_ session: FocusSession) -> some View {
        Group {
            Section {
                Text(session.task).font(.body.weight(.semibold))
                LabeledContent("Time") { Text(session.remainingText) }
                LabeledContent("Shielded") { Text("\(session.shieldedTokens.count) app(s)") }
                LabeledContent("Level") { Text(session.accountability.title) }
                if session.unshieldCount > 0 {
                    LabeledContent("Unshielded") { Text("\(session.unshieldCount)") }
                }
            } header: {
                Text(session.accountability == .locked ? "Locked session" : "In focus")
            }

            Section {
                if askingToEnd {
                    SecureField("Passcode to end this locked session", text: $pin)
                    if pinWrong { Text("Wrong passcode").foregroundStyle(.red).font(.caption) }
                    Button("Confirm") { confirmEnd() }
                    Button("Cancel", role: .cancel) { askingToEnd = false; pin = "" }
                } else {
                    Button("End session", role: .destructive) { requestEnd(session) }
                }
            } footer: {
                if session.accountability == .locked {
                    Text("A locked session's shields can only be lifted here — the shield screen "
                         + "itself can't ask for a passcode.")
                }
            }
        }
    }

    /// Ending a locked session early is the commitment being broken, so it costs the passcode.
    private func requestEnd(_ session: FocusSession) {
        if prefs.pinSet && session.accountability.requiresPasscodeToEnd {
            askingToEnd = true
            pin = ""
            pinWrong = false
        } else {
            endSession()
        }
    }

    private func confirmEnd() {
        if prefs.checkPin(pin) { endSession() } else { pinWrong = true; pin = "" }
    }

    private func endSession() {
        let wasLocked = sessions.current?.accountability.alertsPartner ?? false
        let task = sessions.current?.task ?? ""
        sessions.end(reason: "ended by user")
        shield.clear()
        shield.stopSchedule()
        askingToEnd = false
        pin = ""

        if wasLocked {
            // A locked session ended early is exactly the event a partner signed up to hear about.
            let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer,
                                    topic: prefs.ntfyTopic)
            Task { await Pusher.send(cfg, title: "[Lockout] Locked session ended early",
                                     message: "Task: \(task)\n\nThe session was ended before its "
                                            + "time was up, with the passcode.") }
        }
    }
}
