import AppKit
import SwiftUI

/// Model provider, focus defaults, alerts, blocking, tamper resistance, passcode.
struct SettingsView: View {
    @StateObject private var prefs = Prefs.shared
    @Environment(\.dismiss) private var dismiss

    @State private var apiKey = ""
    @State private var apiKey2 = ""
    @State private var testResult = ""
    @State private var providerResult = ""
    @State private var providerOK = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            LcarsHeader(title: "Settings", subtitle: "Model · alerts · blocking")
                .padding(.bottom, 12)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    aiSection
                    focusSection
                    alertsSection
                    blockingSection
                    tamperSection
                    passcodeSection
                }
                .padding(.bottom, 12)
            }

            HStack {
                LcarsButton(title: "Send test alert", color: LCARS.lilac) {
                    Task { await sendTest() }
                }
                LcarsButton(title: "Done", color: LCARS.orange) {
                    saveKeys()
                    dismiss()
                }
            }
            if !testResult.isEmpty {
                Text(testResult).font(.caption).foregroundColor(LCARS.readout).padding(.top, 6)
            }
        }
        .padding(20)
        .background(LCARS.space)
        .onAppear {
            apiKey = prefs.ollamaApiKey
            apiKey2 = prefs.ollamaApiKey2
        }
    }

    // MARK: - Sections

    /// Provider picker.
    ///
    /// A list of radio-style rows rather than a dropdown, on purpose: which model sees your screen
    /// every two minutes is the most consequential setting in this app, and it deserves to be
    /// visible all at once with its trade-off written next to it — not hidden behind a click.
    private var aiSection: some View {
        section("Model provider") {
            ForEach(Providers.presets) { preset in
                Button {
                    prefs.providerId = preset.id
                    providerResult = "Provider changed — press Test connection."
                    providerOK = true
                } label: {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: prefs.providerId == preset.id
                              ? "largecircle.fill.circle" : "circle")
                            .foregroundColor(prefs.providerId == preset.id ? LCARS.gold : LCARS.lilac)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(preset.label)
                                .font(.system(.caption, design: .rounded).weight(.semibold))
                                .foregroundColor(LCARS.gold)
                            Text(preset.hint)
                                .font(.caption2).foregroundColor(LCARS.readout)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .buttonStyle(.plain)
            }

            labeledField("Base URL", text: $prefs.providerBaseUrl)
            labeledField("Model", text: $prefs.providerModel)

            VStack(alignment: .leading, spacing: 4) {
                Text("API key").font(.caption).foregroundColor(LCARS.blue)
                SecureField("api key", text: $apiKey).textFieldStyle(.roundedBorder)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("API key 2 (backup)").font(.caption).foregroundColor(LCARS.blue)
                SecureField("second api key", text: $apiKey2).textFieldStyle(.roundedBorder)
            }
            Text("Keys live in your macOS Keychain and are never sent to a local provider. When "
                 + "one key runs out of quota the app switches to the other — and back when that "
                 + "one runs out. A local provider needs no key at all.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.8))
                .fixedSize(horizontal: false, vertical: true)

            HStack {
                LcarsButton(title: "Test connection", color: LCARS.blue) {
                    Task { await testProvider() }
                }
                Spacer()
            }
            if !providerResult.isEmpty {
                Text(providerResult)
                    .font(.caption2)
                    .foregroundColor(providerOK ? LCARS.readout : LCARS.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// Focus session defaults — what the start form is prefilled with. Every one of these can
    /// still be changed per session.
    private var focusSection: some View {
        section("Focus session defaults") {
            HStack {
                Text("Check every").font(.caption).foregroundColor(LCARS.blue)
                Picker("", selection: $prefs.focusInterval) {
                    Text("30s").tag(30); Text("1m").tag(60); Text("2m").tag(120)
                    Text("5m").tag(300); Text("10m").tag(600)
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 260)
            }
            HStack {
                Text("Session length").font(.caption).foregroundColor(LCARS.blue)
                Picker("", selection: $prefs.focusMinutes) {
                    Text("25m").tag(25); Text("50m").tag(50); Text("90m").tag(90)
                    Text("open").tag(0)
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 260)
            }
            Picker("Accountability", selection: $prefs.focusAccountability) {
                ForEach(Accountability.allCases, id: \.self) { Text($0.title).tag($0) }
            }
            .pickerStyle(.radioGroup)

            VStack(alignment: .leading, spacing: 4) {
                Text("Standing notes for the classifier").font(.caption).foregroundColor(LCARS.blue)
                TextEditor(text: $prefs.focusNotes)
                    .font(.system(.caption, design: .monospaced))
                    .frame(height: 54)
                    .scrollContentBackground(.hidden)
                    .background(LCARS.panel)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text("Added to every check, whatever the task. Good for facts the model can't "
                     + "see: \"my course PDFs open in Safari\", \"Notion is where my notes live\".")
                    .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.8))
                    .fixedSize(horizontal: false, vertical: true)
            }

            Toggle("Also enforce content rules (the original always-on classifier)",
                   isOn: $prefs.contentRulesEnabled)
                .font(.caption).foregroundColor(LCARS.readout)
            Text("Off by default. When on, the content guidelines are checked outside focus "
                 + "sessions too — which means screenshots are taken outside sessions.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.8))
                .fixedSize(horizontal: false, vertical: true)

            Toggle("Experimental: learn from \"false alarm\" presses", isOn: $prefs.learningEnabled)
                .font(.caption).foregroundColor(LCARS.readout)
            Text("Adds a False alarm button to block screens and applies what the learner "
                 + "concludes. Status: \(LearnedPolicy.status()). See learner/README.md — "
                 + "including how it stops you teaching it to leave you alone.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.8))
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var alertsSection: some View {
        section("Alerts (ntfy push)") {
            Toggle("Push alerts enabled", isOn: $prefs.pushEnabled)
                .toggleStyle(.switch).tint(LCARS.orange).foregroundColor(LCARS.readout)
            labeledField("ntfy server", text: $prefs.ntfyServer)
            VStack(alignment: .leading, spacing: 4) {
                Text("Your private alert code (subscribe to this in the ntfy app):")
                    .font(.caption).foregroundColor(LCARS.blue)
                HStack {
                    Text(prefs.ntfyTopic)
                        .font(.system(.body, design: .monospaced)).foregroundColor(LCARS.gold)
                        .textSelection(.enabled)
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(prefs.ntfyTopic, forType: .string)
                    }.buttonStyle(.plain).foregroundColor(LCARS.blue).font(.caption)
                }
            }
        }
    }

    private var blockingSection: some View {
        section("Blocking behaviour") {
            Text("On a violation Guardian raises a full-screen block over everything; dismiss it with your passcode (or a button if no passcode is set).")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.85))
            Toggle("TEST MODE (log only, never block)", isOn: $prefs.dryRun)
                .toggleStyle(.switch).tint(LCARS.gold).foregroundColor(LCARS.readout)
            Toggle("Alert when a screen can't be verified", isOn: $prefs.alertOnUnverifiable)
                .toggleStyle(.switch).tint(LCARS.orange).foregroundColor(LCARS.readout)
            Toggle("Also hide app when it can't be verified", isOn: $prefs.closeUnverifiable)
                .toggleStyle(.switch).tint(LCARS.orange).foregroundColor(LCARS.readout)
        }
    }

    private var tamperSection: some View {
        section("Tamper resistance") {
            Text("Guardian can't stop an admin from revoking permissions on macOS, but it makes doing so loud and self-healing: it alerts your contact and relaunches itself.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.85))
            Toggle("Show the pledge screen when System Settings opens", isOn: $prefs.pledgeOnSettings)
                .toggleStyle(.switch).tint(LCARS.gold).foregroundColor(LCARS.readout)
            Toggle("Relaunch Guardian at login (persistence)", isOn: $prefs.relaunchAtLogin)
                .toggleStyle(.switch).tint(LCARS.orange).foregroundColor(LCARS.readout)
                .disabled(prefs.keepAlive)
                .onChange(of: prefs.relaunchAtLogin) { _, _ in Persistence.apply() }
            Toggle("Keep alive — relaunch within ~10s if quit or killed", isOn: $prefs.keepAlive)
                .toggleStyle(.switch).tint(LCARS.gold).foregroundColor(LCARS.readout)
                .onChange(of: prefs.keepAlive) { _, _ in Persistence.apply() }
            Text("Keep-alive is the strongest: quitting Guardian won't stick. Turn it off here (behind your passcode) before quitting for a legitimate reason. Guardian also alerts your contact if Screen Recording is revoked or it's quit.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.7))
        }
    }

    private var passcodeSection: some View {
        section("Passcode") {
            Text("Protects opening Guardian and dismissing a block screen. Leave blank for none.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.85))
            PasscodeEditor()
        }
    }

    // MARK: - Helpers

    private func section<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased())
                .font(.system(.subheadline, design: .rounded).weight(.heavy))
                .foregroundColor(LCARS.gold)
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LCARS.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func labeledField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundColor(LCARS.blue)
            TextField(label, text: text).textFieldStyle(.roundedBorder)
        }
    }

    /// Commit both key fields. Editing a key resets the fail-over to start at the first one.
    /// Ask the configured endpoint whether it is actually there, so a user finds out their local
    /// Ollama isn't running *now* rather than 40 minutes into a session.
    private func testProvider() async {
        saveKeys()
        providerResult = "Testing…"
        providerOK = true
        let cfg = prefs.providerConfig()
        if let problem = await Providers.reachability(cfg) {
            providerResult = "\u{2717}  " + problem
            providerOK = false
        } else {
            providerResult = "\u{2713}  \(cfg.model) is reachable at \(cfg.baseUrl)"
            providerOK = true
        }
    }

    private func saveKeys() {
        let changed = apiKey != prefs.ollamaApiKey || apiKey2 != prefs.ollamaApiKey2
        prefs.ollamaApiKey = apiKey
        prefs.ollamaApiKey2 = apiKey2
        if changed { prefs.activeApiKeySlot = 0 }
    }

    private func sendTest() async {
        saveKeys()
        let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer, topic: prefs.ntfyTopic)
        let result = await Pusher.send(cfg, title: "Guardian test", message: "✅ Test alert from Guardian (macOS).")
        switch result {
        case .success: testResult = "Test alert sent to \(prefs.ntfyTopic)."
        case .failure(let e): testResult = "Failed: \(e.localizedDescription)"
        }
    }
}
