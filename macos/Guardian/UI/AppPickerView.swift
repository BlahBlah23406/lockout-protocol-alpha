import SwiftUI

/// Pick which apps Guardian monitors (always-on). Lists ALL installed apps, searchable. Guardian
/// only screenshots + checks an app while it is the frontmost window.
struct AppPickerView: View {
    @StateObject private var prefs = Prefs.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            LcarsHeader(title: "Monitored Apps", subtitle: "Select what to watch")

            Text("Guardian only screenshots + checks an app while it is the frontmost window. \(prefs.monitoredApps.count) selected.")
                .font(.caption)
                .foregroundColor(LCARS.lilac)

            AppSelectList(selection: $prefs.monitoredApps)

            LcarsButton(title: "Done", color: LCARS.orange) { dismiss() }
        }
        .padding(20)
        .background(LCARS.space)
    }
}
