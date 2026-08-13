import AppKit
import SwiftUI

/// Reusable searchable multi-select list of ALL installed apps. Used by the main app picker and
/// the menu-bar temp-session form.
struct AppSelectList: View {
    @Binding var selection: Set<String>
    var maxHeight: CGFloat = .infinity

    @State private var query = ""
    @State private var apps: [InstalledApps.App] = []

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                Text("\(selection.count) selected")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(LCARS.blue)
                Spacer()
                Button("All apps") { selection = Set(apps.map { $0.id }) }
                    .buttonStyle(.plain).font(.caption.weight(.bold)).foregroundColor(LCARS.orange)
                Button("None") { selection = [] }
                    .buttonStyle(.plain).font(.caption.weight(.bold)).foregroundColor(LCARS.lilac)
            }

            TextField("Search apps…", text: $query)
                .textFieldStyle(.roundedBorder)

            ReadoutPanel {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 3) {
                        ForEach(filtered) { app in
                            Toggle(isOn: binding(for: app.id)) {
                                HStack(spacing: 8) {
                                    Image(nsImage: icon(for: app.url))
                                        .resizable().frame(width: 18, height: 18)
                                    VStack(alignment: .leading, spacing: 0) {
                                        HStack(spacing: 6) {
                                            Text(app.name)
                                                .font(.system(.body, design: .rounded).weight(.semibold))
                                                .foregroundColor(LCARS.readout)
                                            // An emulated device is a whole other device inside a
                                            // window here — flagged so unticking one is deliberate.
                                            if Emulators.isEmulator(app.id) {
                                                Text("EMULATED DEVICE")
                                                    .font(.system(size: 8, design: .monospaced).weight(.bold))
                                                    .foregroundColor(LCARS.space)
                                                    .padding(.horizontal, 4).padding(.vertical, 1)
                                                    .background(LCARS.orange, in: Capsule())
                                            }
                                        }
                                        Text(app.id)
                                            .font(.system(size: 9, design: .monospaced))
                                            .foregroundColor(LCARS.blue.opacity(0.6))
                                    }
                                }
                            }
                            .toggleStyle(.checkbox)
                            .tint(LCARS.orange)
                        }
                        if filtered.isEmpty {
                            Text("— no matching apps —")
                                .font(.caption).foregroundColor(LCARS.readout.opacity(0.4))
                                .padding(.vertical, 8)
                        }
                    }
                }
            }
            .frame(minHeight: 120, maxHeight: maxHeight)
        }
        .onAppear { if apps.isEmpty { apps = InstalledApps.all() } }
    }

    private var filtered: [InstalledApps.App] {
        guard !query.isEmpty else { return apps }
        return apps.filter {
            $0.name.localizedCaseInsensitiveContains(query) ||
            $0.id.localizedCaseInsensitiveContains(query)
        }
    }

    private func binding(for id: String) -> Binding<Bool> {
        Binding(
            get: { selection.contains(id) },
            set: { on in if on { selection.insert(id) } else { selection.remove(id) } }
        )
    }

    private func icon(for url: URL) -> NSImage {
        let img = NSWorkspace.shared.icon(forFile: url.path)
        img.size = NSSize(width: 18, height: 18)
        return img
    }
}
