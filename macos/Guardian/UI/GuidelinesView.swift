import SwiftUI

/// Edit the prohibited-content guidelines fed to the model. Mirrors the Android GuidelinesActivity.
struct GuidelinesView: View {
    @StateObject private var prefs = Prefs.shared
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            LcarsHeader(title: "Guidelines", subtitle: "What counts as a violation")

            Text("Describe the content Guardian should flag. The AI sees each screenshot and these rules.")
                .font(.caption)
                .foregroundColor(LCARS.lilac)

            TextEditor(text: $text)
                .font(.system(.body, design: .monospaced))
                .foregroundColor(LCARS.readout)
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(LCARS.panel)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .frame(maxHeight: .infinity)

            HStack {
                LcarsButton(title: "Reset to default", color: LCARS.lilac) {
                    text = Prefs.defaultGuidelines
                }
                LcarsButton(title: "Save", color: LCARS.orange) {
                    prefs.guidelines = text
                    dismiss()
                }
            }
        }
        .padding(20)
        .background(LCARS.space)
        .onAppear { text = prefs.guidelines }
    }
}
