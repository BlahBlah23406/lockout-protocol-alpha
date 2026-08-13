import AppKit
import SwiftUI

/// AI + alerts + blocking behaviour settings. Mirrors the Android SettingsActivity / NotifyActivity.
struct SettingsView: View {
    @StateObject private var prefs = Prefs.shared
    @Environment(\.dismiss) private var dismiss

    @State private var apiKey = ""
    @State private var apiKey2 = ""
    @State private var testResult = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            LcarsHeader(title: "Settings", subtitle: "AI · alerts · blocking")
                .padding(.bottom, 12)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    aiSection
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

    private var aiSection: some View {
        section("AI (Ollama Cloud)") {
            labeledField("Base URL", text: $prefs.ollamaBaseUrl)
            labeledField("Model", text: $prefs.ollamaModel)
            VStack(alignment: .leading, spacing: 4) {
                Text("API key").font(.caption).foregroundColor(LCARS.blue)
                SecureField("ollama cloud api key", text: $apiKey)
                    .textFieldStyle(.roundedBorder)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("API key 2 (backup)").font(.caption).foregroundColor(LCARS.blue)
                SecureField("second ollama cloud api key", text: $apiKey2)
                    .textFieldStyle(.roundedBorder)
            }
            Text("Get a key at ollama.com. Stored in your macOS Keychain. When one key runs out of quota Guardian switches to the other — and back again when that one runs out.")
                .font(.caption2).foregroundColor(LCARS.lilac.opacity(0.8))
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
