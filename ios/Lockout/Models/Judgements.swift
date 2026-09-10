import Foundation

/// Append-only record of what the app decided, in the same JSONL format as the other ports so a
/// mixed log reads without special cases.
///
/// iOS logs a different shape of event, since there is no per-screen verdict:
///
///     verdict "shield_plan"  action "blocked"  — an app the plan shut
///     verdict "shield_plan"  action "allowed"  — an app the plan left open
///     verdict "off_task"     action "blocked"  — the user hit a shield
///     feedback "false_alarm"                    — they unshielded it
///
/// The last pairing is free training data: nobody unshields an app they agreed should be shut.
enum Judgements {

    static let maxLines = 20_000

    private static let queue = DispatchQueue(label: "com.lockoutprotocol.lockout.judgements")

    static var fileURL: URL {
        SessionStore.containerDirectory().appendingPathComponent("judgements.jsonl")
    }

    /// One row per app in the plan, matching the (task, app) pairs the desktop clients log.
    static func recordSessionStart(_ session: FocusSession, plan: ShieldPlan.Decision,
                                   provider: String) {
        for token in plan.shield {
            append(row(session: session, app: token, verdict: "shield_plan",
                       reason: plan.reasoning, action: "blocked", provider: provider))
        }
        for token in plan.allow {
            append(row(session: session, app: token, verdict: "shield_plan",
                       reason: plan.reasoning, action: "allowed", provider: provider))
        }
    }

    /// The user opened a shielded app and met the shield.
    @discardableResult
    static func recordShieldHit(_ session: FocusSession, app: String,
                                appName: String, provider: String) -> String {
        let jid = "j_\(Int(Date().timeIntervalSince1970 * 1000))"
        var r = row(session: session, app: app, verdict: "off_task",
                    reason: "\(appName) is shielded for this session", action: "blocked",
                    provider: provider)
        r["id"] = jid
        r["app_name"] = appName
        append(r)
        return jid
    }

    /// An unshield carries the same information as a "false alarm" tap elsewhere.
    static func recordUnshield(_ judgementId: String, note: String = "") {
        append([
            "id": "\(judgementId)#fb",
            "ts": Date().timeIntervalSince1970,
            "ref": judgementId,
            "feedback": "false_alarm",
            "feedback_at": Date().timeIntervalSince1970,
            "feedback_note": note.isEmpty
                ? "unshielded on iOS — the shield plan shut an app the task needed"
                : String(note.prefix(300)),
        ])
    }

    private static func row(session: FocusSession, app: String, verdict: String,
                            reason: String, action: String, provider: String) -> [String: Any] {
        [
            "id": "j_\(Int(Date().timeIntervalSince1970 * 1000))_\(abs(app.hashValue) % 100000)",
            "ts": Date().timeIntervalSince1970,
            "session_id": session.id,
            "task": session.task,
            "app": app,
            "app_name": "",
            // No window title exists here; inventing one would poison the learner's patterns.
            "window_title": "",
            "verdict": verdict,
            "reason": String(reason.prefix(500)),
            // No per-screen confidence exists; 0 means "no opinion".
            "confidence": 0,
            "action": action,
            "provider": provider,
            "platform": "ios",
            "feedback": NSNull(),
            "feedback_at": NSNull(),
            "feedback_note": NSNull(),
        ]
    }

    private static func append(_ row: [String: Any]) {
        queue.async {
            guard var data = try? JSONSerialization.data(withJSONObject: row) else { return }
            data.append(0x0A)
            let url = fileURL
            if let handle = try? FileHandle(forWritingTo: url) {
                defer { try? handle.close() }
                try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            } else {
                try? data.write(to: url, options: .atomic)
            }
        }
    }

    /// Fold the shield extension's spool file into the log on next launch.
    static func drainSpool() {
        queue.async {
            let spool = SessionStore.containerDirectory()
                .appendingPathComponent("shield_spool.jsonl")
            guard let text = try? String(contentsOf: spool, encoding: .utf8) else { return }
            for line in text.split(separator: "\n") {
                guard let data = line.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else { continue }
                var forwarded = obj
                forwarded["platform"] = "ios"
                guard var encoded = try? JSONSerialization.data(withJSONObject: forwarded)
                else { continue }
                encoded.append(0x0A)
                if let handle = try? FileHandle(forWritingTo: fileURL) {
                    defer { try? handle.close() }
                    try? handle.seekToEnd()
                    try? handle.write(contentsOf: encoded)
                } else {
                    try? encoded.write(to: fileURL, options: .atomic)
                }
            }
            try? FileManager.default.removeItem(at: spool)
        }
    }

    static func trim() {
        queue.async {
            guard let text = try? String(contentsOf: fileURL, encoding: .utf8) else { return }
            let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
            guard lines.count > maxLines else { return }
            let kept = lines.suffix(maxLines).joined(separator: "\n") + "\n"
            try? kept.write(to: fileURL, atomically: true, encoding: .utf8)
        }
    }

    /// There is no `adb pull` on iOS, so the app exports the log itself via a share sheet.
    static func exportURL() -> URL? {
        FileManager.default.fileExists(atPath: fileURL.path) ? fileURL : nil
    }
}
