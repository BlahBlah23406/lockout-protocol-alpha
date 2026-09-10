import SwiftUI
import WidgetKit

/// The home-screen and Lock Screen widget: start a session, or see the one running.
///
/// It does not start a session itself — it deep-links into the app with the last task prefilled,
/// because the shield plan needs a confirmation step and a stray tap should never begin a locked
/// session.
struct FocusWidget: Widget {

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "com.lockoutprotocol.lockout.focus", provider: Provider()) {
            FocusWidgetView(entry: $0)
                .containerBackground(for: .widget) { Color(red: 0.05, green: 0.06, blue: 0.09) }
        }
        .configurationDisplayName("Focus session")
        .description("Start a focus session, or check the one already running.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular])
    }
}

// MARK: - Timeline

struct FocusEntry: TimelineEntry {
    let date: Date
    let task: String
    let remainingText: String
    let shieldedCount: Int
    let isLocked: Bool
    let isActive: Bool
}

struct Provider: TimelineProvider {

    func placeholder(in context: Context) -> FocusEntry {
        FocusEntry(date: Date(), task: "What are you working on?", remainingText: "",
                   shieldedCount: 0, isLocked: false, isActive: false)
    }

    func getSnapshot(in context: Context, completion: @escaping (FocusEntry) -> Void) {
        completion(entry())
    }

    /// Entries are precomputed one a minute, then a final "no session" one, because WidgetKit
    /// won't refresh on demand. The countdown then runs correctly without the app.
    func getTimeline(in context: Context, completion: @escaping (Timeline<FocusEntry>) -> Void) {
        guard let session = SharedSession.current() else {
            completion(Timeline(entries: [entry()], policy: .after(Date().addingTimeInterval(900))))
            return
        }

        var entries: [FocusEntry] = []
        let end = session.endsAt
        var cursor = Date()
        // Capped: an open-ended session has no end.
        for _ in 0..<60 {
            if let end, cursor >= end { break }
            entries.append(entryFor(session, at: cursor))
            cursor = cursor.addingTimeInterval(60)
        }
        if let end {
            entries.append(FocusEntry(date: end, task: "", remainingText: "", shieldedCount: 0,
                                      isLocked: false, isActive: false))
        }
        if entries.isEmpty { entries = [entry()] }
        completion(Timeline(entries: entries, policy: .atEnd))
    }

    private func entry() -> FocusEntry {
        guard let session = SharedSession.current() else {
            let last = (UserDefaults(suiteName: SessionStore.appGroup) ?? .standard)
                .string(forKey: "focus_last_task") ?? ""
            return FocusEntry(date: Date(),
                              task: last.isEmpty ? "What are you working on?" : last,
                              remainingText: "", shieldedCount: 0, isLocked: false,
                              isActive: false)
        }
        return entryFor(session, at: Date())
    }

    private func entryFor(_ session: FocusSession, at date: Date) -> FocusEntry {
        // For the entry's own date, not now, or every entry would show the same number.
        let remaining: String
        if let end = session.endsAt {
            let left = max(end.timeIntervalSince(date), 0)
            remaining = "\(Int(left) / 60)m left"
        } else {
            remaining = "open-ended"
        }
        return FocusEntry(date: date, task: session.task, remainingText: remaining,
                          shieldedCount: session.shieldedTokens.count,
                          isLocked: session.accountability == .locked, isActive: true)
    }
}

// MARK: - View

struct FocusWidgetView: View {
    let entry: FocusEntry
    @Environment(\.widgetFamily) private var family

    private var tint: Color {
        // Grey when nothing is shielded: the widget must never suggest a session is running when
        // one isn't.
        guard entry.isActive else { return Color(red: 0.8, green: 0.53, blue: 0.8) }
        return entry.isLocked ? Color(red: 0.88, green: 0.33, blue: 0.24)
                              : Color(red: 0.6, green: 0.9, blue: 0.79)
    }

    var body: some View {
        if family == .accessoryRectangular {
            accessory
        } else {
            full
        }
    }

    private var accessory: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(entry.isActive ? (entry.isLocked ? "LOCKED" : "IN FOCUS") : "NO SESSION")
                .font(.caption2.weight(.bold))
            Text(entry.isActive ? entry.remainingText : "nothing shielded")
                .font(.caption2)
            Text(entry.task).font(.caption2).lineLimit(1)
        }
        .widgetURL(URL(string: "lockout://start"))
    }

    private var full: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 4).fill(tint).frame(width: 18, height: 10)
                Text(entry.isActive ? (entry.isLocked ? "LOCKED" : "IN FOCUS") : "NO SESSION")
                    .font(.caption2.weight(.heavy))
                    .foregroundStyle(tint)
            }

            Text(entry.task)
                .font(.callout.weight(.semibold))
                .foregroundStyle(Color(red: 1, green: 0.8, blue: 0.4))
                .lineLimit(family == .systemSmall ? 2 : 3)

            Spacer(minLength: 0)

            if entry.isActive {
                Text(entry.remainingText)
                    .font(.caption.monospaced())
                    .foregroundStyle(Color(red: 0.6, green: 0.9, blue: 0.79))
                Text("\(entry.shieldedCount) app(s) shielded")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else {
                Text("Nothing is shielded")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text("Tap to start")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Color(red: 1, green: 0.6, blue: 0.4))
            }
        }
        // A deep link rather than an intent, so there is always a confirmation step.
        .widgetURL(URL(string: entry.isActive ? "lockout://session" : "lockout://start"))
    }
}

// MARK: - Bundle

@main
struct LockoutWidgetBundle: WidgetBundle {
    var body: some Widget {
        FocusWidget()
    }
}
