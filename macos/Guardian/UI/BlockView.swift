import SwiftUI

/// The full-screen block screen content. Red-alert "ACCESS DENIED" with the reason. Two ways out:
///   • Dismiss — no passcode needed, but it QUITS the offending app (the compliant exit).
///   • Override — keep using the app; requires the passcode when one is set.
/// Mirrors the Android BlockActivity override/dismiss model.
struct BlockView: View {
    let appName: String
    let reason: String
    var onOverride: () -> Void
    var onQuit: () -> Void

    @ObservedObject private var prefs = Prefs.shared
    @State private var pin = ""
    @State private var wrong = false

    var body: some View {
        ZStack {
            LCARS.space.ignoresSafeArea()
            VStack(spacing: 22) {
                Spacer()
                Text("⊘ ACCESS DENIED")
                    .font(.system(size: 64, weight: .black, design: .rounded))
                    .foregroundColor(LCARS.red)
                    .kerning(2)

                VStack(spacing: 6) {
                    Text(appName.uppercased())
                        .font(.system(.title2, design: .rounded).weight(.heavy))
                        .foregroundColor(LCARS.gold)
                    Text(reason)
                        .font(.system(.title3, design: .monospaced))
                        .foregroundColor(LCARS.readout)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 680)
                }

                // ---- Override (keep using the app) — passcode-gated when one is set ----
                VStack(spacing: 12) {
                    if prefs.pinSet {
                        SecureField("Passcode to override", text: $pin)
                            .textFieldStyle(.plain)
                            .font(.system(.title2, design: .monospaced))
                            .multilineTextAlignment(.center)
                            .frame(width: 360, height: 52)
                            .background(LCARS.panel)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12)
                                .stroke(wrong ? LCARS.red : LCARS.blue.opacity(0.5), lineWidth: 2))
                            .onSubmit(tryOverride)
                        if wrong { Text("Wrong passcode").font(.callout).foregroundColor(LCARS.red) }
                    }
                    LcarsButton(title: "Override · keep using \(appName)", color: LCARS.orange,
                                action: tryOverride)
                        .frame(width: 380)
                }

                // ---- Dismiss (no code) — quits the offending app ----
                LcarsButton(title: "Dismiss · quit \(appName)", color: LCARS.red) { onQuit() }
                    .frame(width: 380)
                Text("Dismiss needs no passcode but closes \(appName).")
                    .font(.caption).foregroundColor(LCARS.lilac.opacity(0.8))

                Spacer()
                Text("GUARDIAN · accountability monitor")
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .foregroundColor(LCARS.lilac.opacity(0.7))
                    .padding(.bottom, 24)
            }
            .padding(40)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func tryOverride() {
        if !prefs.pinSet { onOverride(); return }     // no passcode → override is free
        if prefs.checkPin(pin) { onOverride() } else { wrong = true; pin = "" }
    }
}
