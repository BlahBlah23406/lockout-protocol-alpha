import Foundation

/// Append-only record of every focus check, and the user's feedback on it.
///
/// One JSON object per line, appended and never rewritten, so a crash mid-write costs one line
/// rather than the file. The schema is shared with the Windows, Android and iOS ports and with the
/// offline learner — change a field name in one place and you must change it in all four.
enum Judgements {

    enum Feedback: String {
        case falseAlarm = "false_alarm"     // it blocked me and it was wrong
        case correct = "correct"            // it blocked me and it was right
        /// Easily forgotten: a monitor tuned only on false alarms drifts towards never blocking.
        case missed = "missed"
    }

    /// ~ a year of heavy use; trimmed from the front at launch.
    static let maxLines = 20_000

    private static let queue = DispatchQueue(label: "com.lockoutprotocol.guardian.judgements")

    static var fileURL: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        let dir = base.appendingPathComponent("LockoutProtocol", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("judgements.jsonl")
    }()

    /// Append one judgement and return its id, so a later feedback press can find this exact row.
    @discardableResult
    static func record(session: FocusSession?, app: String, appName: String, windowTitle: String,
                       verdict: String, reason: String, confidence: Double,
                       action: String, provider: String) -> String {
        let jid = "j_\(Int(Date().timeIntervalSince1970 * 1000))"
        append([
            "id": jid,
            "ts": Date().timeIntervalSince1970,
            "session_id": session?.id ?? "",
            "task": session?.task ?? "",
            "app": app,
            "app_name": appName,
            "window_title": String(windowTitle.prefix(300)),
            "verdict": verdict,
            "reason": String(reason.prefix(500)),
            "confidence": (confidence * 1000).rounded() / 1000,
            "action": action,
            "provider": provider,
            "feedback": NSNull(),
            "feedback_at": NSNull(),
            "feedback_note": NSNull(),
        ])
        return jid
    }

    /// Written as a new row rather than an edit: rewriting a line in place means rewriting the
    /// whole file, which is not something to do while the monitor is appending to it.
    static func addFeedback(_ judgementId: String, _ feedback: Feedback, note: String = "") {
        append([
            "id": "\(judgementId)#fb",
            "ts": Date().timeIntervalSince1970,
            "ref": judgementId,
            "feedback": feedback.rawValue,
            "feedback_at": Date().timeIntervalSince1970,
            "feedback_note": String(note.prefix(300)),
        ])
    }

    private static func append(_ row: [String: Any]) {
        queue.async {
            guard var data = try? JSONSerialization.data(withJSONObject: row) else { return }
            data.append(0x0A)
            if let handle = try? FileHandle(forWritingTo: fileURL) {
                defer { try? handle.close() }
                try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            } else {
                try? data.write(to: fileURL, options: .atomic)
            }
            // Telemetry must never be able to break monitoring.
        }
    }

    /// Read back the tail of the log, with feedback rows folded into the judgements they refer to.
    static func readAll(limit: Int = 2000) -> [[String: Any]] {
        guard let text = try? String(contentsOf: fileURL, encoding: .utf8) else { return [] }
        var rows: [[String: Any]] = []
        var indexById: [String: Int] = [:]

        for line in text.split(separator: "\n").suffix(limit * 2) {
            guard let data = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                continue        // a torn final line after a hard kill
            }
            if let ref = obj["ref"] as? String {
                if let idx = indexById[ref] {
                    rows[idx]["feedback"] = obj["feedback"]
                    rows[idx]["feedback_at"] = obj["feedback_at"]
                    rows[idx]["feedback_note"] = obj["feedback_note"]
                }
                continue
            }
            if let id = obj["id"] as? String { indexById[id] = rows.count }
            rows.append(obj)
        }
        return Array(rows.suffix(limit))
    }

    /// Keep the file bounded. Called at launch, never on the hot path.
    static func trim() {
        queue.async {
            guard let text = try? String(contentsOf: fileURL, encoding: .utf8) else { return }
            let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
            guard lines.count > maxLines else { return }
            let kept = lines.suffix(maxLines).joined(separator: "\n") + "\n"
            try? kept.write(to: fileURL, atomically: true, encoding: .utf8)
        }
    }

    /// Counts for the end-of-session summary.
    static func sessionStats(_ sessionId: String) -> (checks: Int, offTask: Int, blocked: Int,
                                                      falseAlarms: Int) {
        var checks = 0, offTask = 0, blocked = 0, falseAlarms = 0
        for row in readAll() where row["session_id"] as? String == sessionId {
            checks += 1
            if row["verdict"] as? String == "off_task" { offTask += 1 }
            if row["action"] as? String == "blocked" { blocked += 1 }
            if row["feedback"] as? String == Feedback.falseAlarm.rawValue { falseAlarms += 1 }
        }
        return (checks, offTask, blocked, falseAlarms)
    }
}
