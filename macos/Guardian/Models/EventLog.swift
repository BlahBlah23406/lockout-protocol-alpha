import Foundation

/// In-memory, observable activity log shown live in the dashboard. Mirrors the Android `EventLog`:
/// each screenshot + AI verdict gets a timestamped line. Keeps the most recent entries.
@MainActor
final class EventLog: ObservableObject {

    static let shared = EventLog()

    struct Entry: Identifiable {
        let id = UUID()
        let time: Date
        let text: String
    }

    @Published private(set) var entries: [Entry] = []

    private let maxEntries = 500
    private let fmt: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    func add(_ text: String) {
        entries.append(Entry(time: Date(), text: text))
        if entries.count > maxEntries {
            entries.removeFirst(entries.count - maxEntries)
        }
    }

    func clear() { entries.removeAll() }

    func formatted(_ e: Entry) -> String { "\(fmt.string(from: e.time))  \(e.text)" }

    /// Nonisolated convenience so background tasks can log without hopping context manually.
    nonisolated static func log(_ text: String) {
        Task { @MainActor in EventLog.shared.add(text) }
    }
}
