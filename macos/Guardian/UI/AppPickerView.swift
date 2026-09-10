import SwiftUI

/// Pick which apps are watched. Two jobs, one view: with no arguments it edits the saved default
/// watchlist; given a `selection` binding it becomes a session-scoped picker.
struct AppPickerView: View {
    /// When nil, the view edits `Prefs.monitoredApps` directly.
    var selection: Binding<Set<String>>?
    var title: String = "Monitored Apps"
    var subtitle: String = "Select what to watch"
    var note: String?

    @StateObject private var prefs = Prefs.shared
    @Environment(\.dismiss) private var dismiss

    private var binding: Binding<Set<String>> {
        selection ?? $prefs.monitoredApps
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            LcarsHeader(title: title, subtitle: subtitle)

            Text(note ?? "Lockout only screenshots + checks an app while it is the frontmost "
                       + "window — and only during a focus session. "
                       + "\(binding.wrappedValue.count) selected.")
                .font(.caption)
                .foregroundColor(LCARS.lilac)
                .fixedSize(horizontal: false, vertical: true)

            AppSelectList(selection: binding)

            LcarsButton(title: "Done", color: LCARS.orange) { dismiss() }
        }
        .padding(20)
        .frame(minWidth: 460, minHeight: 520)
        .background(LCARS.space)
    }
}
