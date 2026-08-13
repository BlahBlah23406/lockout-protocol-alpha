import SwiftUI

/// Set / change / remove the access + override passcode. Changing or removing requires the current
/// passcode (when one is already set), mirroring the Android ChangePinActivity.
struct PasscodeEditor: View {
    @ObservedObject private var prefs = Prefs.shared

    @State private var current = ""
    @State private var new1 = ""
    @State private var new2 = ""
    @State private var message = ""
    @State private var ok = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if prefs.pinSet {
                field("Current passcode", $current)
            }
            field("New passcode", $new1)
            field("Confirm new passcode", $new2)

            HStack {
                LcarsButton(title: prefs.pinSet ? "Update" : "Set passcode", color: LCARS.orange) {
                    save()
                }
                if prefs.pinSet {
                    LcarsButton(title: "Remove", color: LCARS.red) { remove() }
                }
            }
            if !message.isEmpty {
                Text(message).font(.caption).foregroundColor(ok ? LCARS.readout : LCARS.red)
            }
        }
    }

    private func field(_ label: String, _ text: Binding<String>) -> some View {
        SecureField(label, text: text).textFieldStyle(.roundedBorder)
    }

    private func save() {
        if prefs.pinSet, !prefs.checkPin(current) { fail("Current passcode is wrong"); return }
        guard !new1.isEmpty else { fail("Enter a new passcode"); return }
        guard new1 == new2 else { fail("New passcodes don't match"); return }
        prefs.setPin(new1)
        succeed("Passcode saved")
    }

    private func remove() {
        guard prefs.checkPin(current) else { fail("Current passcode is wrong"); return }
        prefs.clearPin()
        succeed("Passcode removed")
    }

    private func clearFields() { current = ""; new1 = ""; new2 = "" }
    private func fail(_ m: String) { message = m; ok = false }
    private func succeed(_ m: String) { message = m; ok = true; clearFields() }
}
