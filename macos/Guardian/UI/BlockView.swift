import SwiftUI

/// The full-screen block, in its two accountability levels.
///
/// Which buttons appear is the whole difference between the levels:
///
/// - `.selfManaged` — "Not now" closes the app, "I'm on task" overrides. No passcode either way.
/// - `.locked` — "Not now" still needs no passcode. The override does, and the partner is told.
///
/// The passcode-free exit is present at every level. A monitor that can trap someone on their own
/// Mac is a bug — see `SAFEGUARDS.md`.
struct BlockView: View {
    let appName: String
    let reason: String
    /// nil for a content-rules block, which has no session and keeps the original behaviour.
    var session: FocusSession?
    var onOverride: () -> Void
    var onQuit: () -> Void
    var onFalseAlarm: (() -> Void)?

    @ObservedObject private var prefs = Prefs.shared
    @State private var pin = ""
    @State private var wrong = false

    private var isLocked: Bool { session?.accountability == .locked }
    private var needsPin: Bool { prefs.pinSet && (isLocked || session == nil) }

    var body: some View {
        ZStack {
            LCARS.space.ignoresSafeArea()
            VStack(spacing: 20) {
                Spacer()
                headline
                evidence
                passcodeField
                actions
                footnote
                Spacer()
                Text("LOCKOUT PROTOCOL · focus monitor")
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .foregroundColor(LCARS.lilac.opacity(0.7))
                    .padding(.bottom, 24)
            }
            .padding(40)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    // MARK: - Pieces

    @ViewBuilder private var headline: some View {
        if let session {
            VStack(spacing: 10) {
                Text("OFF TASK")
                    .font(.system(size: 64, weight: .black, design: .rounded))
                    .foregroundColor(LCARS.red)
                    .kerning(2)
                Text("YOU SAID YOU WERE:")
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .foregroundColor(LCARS.lilac)
                Text(session.task)
                    .font(.system(.title, design: .rounded).weight(.heavy))
                    .foregroundColor(LCARS.gold)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 760)
            }
        } else {
            Text("⊘ ACCESS DENIED")
                .font(.system(size: 64, weight: .black, design: .rounded))
                .foregroundColor(LCARS.red)
                .kerning(2)
        }
    }

    private var evidence: some View {
        VStack(spacing: 6) {
            Text(appName.uppercased())
                .font(.system(.title2, design: .rounded).weight(.heavy))
                .foregroundColor(LCARS.gold)
            Text(reason.isEmpty ? "not part of the declared task" : reason)
                .font(.system(.title3, design: .monospaced))
                .foregroundColor(LCARS.readout)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 680)
        }
    }

    @ViewBuilder private var passcodeField: some View {
        if needsPin {
            VStack(spacing: 8) {
                Text("PASSCODE TO OVERRIDE")
                    .font(.system(size: 10, design: .rounded).weight(.semibold))
                    .foregroundColor(LCARS.lilac)
                SecureField("Passcode", text: $pin)
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
        }
    }

    private var actions: some View {
        VStack(spacing: 10) {
            // Listed first: going back to work should be the path of least resistance.
            LcarsButton(title: "Not now · quit \(appName)", color: LCARS.orange) { onQuit() }
                .frame(width: 400)

            LcarsButton(title: needsPin ? "Override · keep using it"
                                        : "I'm on task · keep using \(appName)",
                        color: LCARS.red, action: tryOverride)
                .frame(width: 400)

            // Experimental, and only for focus blocks.
            if let onFalseAlarm, prefs.learningEnabled, session != nil {
                Button("This was a false alarm — it IS part of my task") {
                    onFalseAlarm()
                    onOverride()
                }
                .buttonStyle(.plain)
                .font(.callout)
                .underline()
                .foregroundColor(LCARS.blue)
                .padding(.top, 4)
            }
        }
    }

    private var footnote: some View {
        Text(footnoteText)
            .font(.caption)
            .foregroundColor(LCARS.lilac.opacity(0.85))
            .multilineTextAlignment(.center)
            .frame(maxWidth: 620)
    }

    private var footnoteText: String {
        guard session != nil else {
            return "Dismiss needs no passcode but closes \(appName)."
        }
        if needsPin {
            return "This session is LOCKED. Overriding needs the passcode and your accountability "
                 + "partner is notified either way. Quitting the app needs no passcode."
        }
        return "This session is self-managed — nobody else is told. Overriding is logged and "
             + "counted in your session summary."
    }

    private func tryOverride() {
        guard needsPin else { onOverride(); return }
        if prefs.checkPin(pin) { onOverride() } else { wrong = true; pin = "" }
    }
}
