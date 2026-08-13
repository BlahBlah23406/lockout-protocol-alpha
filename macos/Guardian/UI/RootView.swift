import SwiftUI

/// Wraps the dashboard behind the access passcode. A fresh window instance starts locked, so the
/// gate reappears every time you reopen Guardian (matching the Android LockActivity behavior).
struct RootView: View {
    @ObservedObject private var prefs = Prefs.shared
    @State private var unlocked = false

    var body: some View {
        Group {
            if prefs.pinSet && !unlocked {
                LockView { unlocked = true }
            } else {
                ContentView()
            }
        }
    }
}

/// Passcode gate shown before the dashboard.
struct LockView: View {
    var onUnlock: () -> Void

    @ObservedObject private var prefs = Prefs.shared
    @State private var pin = ""
    @State private var wrong = false

    var body: some View {
        ZStack {
            LCARS.space.ignoresSafeArea()
            VStack(spacing: 22) {
                RoundedRectangle(cornerRadius: 10).fill(LCARS.orange).frame(width: 90, height: 30)
                Text("GUARDIAN")
                    .font(.system(size: 40, weight: .black, design: .rounded))
                    .foregroundColor(LCARS.gold).kerning(3)
                Text("Enter passcode to unlock")
                    .font(.system(.body, design: .rounded)).foregroundColor(LCARS.lilac)

                SecureField("Passcode", text: $pin)
                    .textFieldStyle(.plain)
                    .font(.system(.title2, design: .monospaced))
                    .multilineTextAlignment(.center)
                    .frame(width: 320, height: 52)
                    .background(LCARS.panel)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12)
                        .stroke(wrong ? LCARS.red : LCARS.blue.opacity(0.5), lineWidth: 2))
                    .onSubmit(check)
                if wrong { Text("Wrong passcode").font(.callout).foregroundColor(LCARS.red) }

                LcarsButton(title: "Unlock", color: LCARS.orange, action: check).frame(width: 320)
            }
            .padding(40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func check() {
        if prefs.checkPin(pin) { onUnlock() } else { wrong = true; pin = "" }
    }
}
