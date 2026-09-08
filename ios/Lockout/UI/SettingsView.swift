import SwiftUI

/// Model provider, focus defaults, alerts, passcode.
struct SettingsView: View {
    @StateObject private var prefs = Prefs.shared
    @StateObject private var shield = ShieldController.shared
    @Environment(\.dismiss) private var dismiss

    @State private var key1 = ""
    @State private var key2 = ""
    @State private var newPin = ""
    @State private var probeResult = ""
    @State private var probeOK = true
    @State private var testResult = ""
    @State private var showingExport = false

    var body: some View {
        NavigationStack {
            Form {
                providerSection
                focusSection
                alertsSection
                passcodeSection
                dataSection
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { saveKeys(); dismiss() }
                }
            }
            .onAppear { key1 = prefs.apiKey; key2 = prefs.apiKey2 }
        }
    }

    // MARK: - Provider

    private var providerSection: some View {
        Section {
            ForEach(Providers.presets) { preset in
                Button {
                    prefs.providerId = preset.id
                    probeResult = "Provider changed — tap Test connection."
                    probeOK = true
                } label: {
                    HStack(alignment: .top) {
                        Image(systemName: prefs.providerId == preset.id
                              ? "largecircle.fill.circle" : "circle")
                        VStack(alignment: .leading, spacing: 2) {
                            Text(preset.label).font(.body.weight(.semibold))
                            Text(preset.hint).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .buttonStyle(.plain)
            }

            TextField("Server base URL", text: Binding(
                get: { prefs.providerBaseUrl }, set: { prefs.providerBaseUrl = $0 }))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Model", text: Binding(
                get: { prefs.providerModel }, set: { prefs.providerModel = $0 }))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            SecureField("API key", text: $key1)
            SecureField("API key 2 (backup)", text: $key2)

            Button("Test connection") { Task { await probe() } }
            if !probeResult.isEmpty {
                Text(probeResult).font(.caption)
                    .foregroundStyle(probeOK ? .secondary : .red)
            }
        } header: {
            Text("Model provider")
        } footer: {
            Text("On iOS the model never sees your screen — no app can. It only reads your typed "
                 + "task and the names of the apps you offered, so it doesn't need to be a vision "
                 + "model. Keys live in the Keychain.")
        }
    }

    private func probe() async {
        saveKeys()
        probeResult = "Testing…"
        probeOK = true
        let cfg = prefs.providerConfig()
        if let problem = await Providers.reachability(cfg) {
            probeResult = "✗  " + problem
            probeOK = false
        } else {
            probeResult = "✓  \(cfg.model) is reachable at \(cfg.baseUrl)"
            probeOK = true
        }
    }

    private func saveKeys() {
        let changed = key1 != prefs.apiKey || key2 != prefs.apiKey2
        prefs.apiKey = key1
        prefs.apiKey2 = key2
        // Editing either key resets the fail-over to start at the first one.
        if changed { prefs.activeKeySlot = 0 }
    }

    // MARK: - Focus

    private var focusSection: some View {
        Section {
            Picker("Session length", selection: Binding(
                get: { prefs.focusMinutes }, set: { prefs.focusMinutes = $0 })) {
                Text("25m").tag(25); Text("50m").tag(50); Text("90m").tag(90)
                Text("open").tag(0)
            }
            .pickerStyle(.segmented)

            Picker("Accountability", selection: Binding(
                get: { prefs.focusAccountability }, set: { prefs.focusAccountability = $0 })) {
                ForEach(Accountability.allCases, id: \.self) { Text($0.title).tag($0) }
            }

            TextField("Standing notes for the model", text: Binding(
                get: { prefs.focusNotes }, set: { prefs.focusNotes = $0 }), axis: .vertical)
                .lineLimit(2...4)
        } header: {
            Text("Focus defaults")
        } footer: {
            Text("Standing notes matter more here than on the desktop: app names are all the "
                 + "model gets to work with, so \"Notion is where my notes live\" is genuinely "
                 + "useful to it.")
        }
    }

    // MARK: - Alerts

    private var alertsSection: some View {
        Section {
            Toggle("Push alerts", isOn: Binding(
                get: { prefs.pushEnabled }, set: { prefs.pushEnabled = $0 }))
            TextField("ntfy server", text: Binding(
                get: { prefs.ntfyServer }, set: { prefs.ntfyServer = $0 }))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            LabeledContent("Your alert code") {
                Text(prefs.ntfyTopic).font(.caption.monospaced()).textSelection(.enabled)
            }
            Button("Send test alert") { Task { await sendTest() } }
            if !testResult.isEmpty { Text(testResult).font(.caption) }
        } header: {
            Text("Alerts")
        } footer: {
            Text("Your partner installs ntfy and subscribes to that exact code. It is the only "
                 + "secret — anyone who knows it can read your alerts, so don't post it anywhere.")
        }
    }

    private func sendTest() async {
        testResult = "Sending…"
        let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer,
                                topic: prefs.ntfyTopic)
        if let problem = await Pusher.send(cfg, title: "Lockout test",
                                           message: "Alerts are set up correctly.") {
            testResult = "Failed: \(problem)"
        } else {
            testResult = "Sent to \(prefs.ntfyTopic)."
        }
    }

    // MARK: - Passcode

    private var passcodeSection: some View {
        Section {
            SecureField(prefs.pinSet ? "Change passcode" : "Set a passcode", text: $newPin)
            Button(prefs.pinSet ? "Change" : "Set") {
                guard newPin.count >= 4 else { return }
                prefs.setPin(newPin)
                newPin = ""
            }
            .disabled(newPin.count < 4)
            if prefs.pinSet {
                Button("Remove passcode", role: .destructive) { prefs.clearPin() }
            }
        } header: {
            Text("Passcode")
        } footer: {
            Text("Only needed for locked sessions. Give it to your accountability partner, or use "
                 + "one you won't remember — that is the whole point of it.")
        }
    }

    // MARK: - Data

    private var dataSection: some View {
        Section {
            if let url = Judgements.exportURL() {
                ShareLink("Export decision log", item: url)
            } else {
                Text("No decisions logged yet.").foregroundStyle(.secondary)
            }
        } header: {
            Text("Data")
        } footer: {
            Text("The log of what was shielded and what you unshielded, as JSONL. Feeding it to "
                 + "learner/ is what lets the experimental learner stop shutting apps your tasks "
                 + "actually need. Nothing is uploaded — this is a file you choose to share.")
        }
    }
}
