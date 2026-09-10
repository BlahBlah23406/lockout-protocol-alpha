import Foundation

/// Push alerts via ntfy: no account, no email server, your partner subscribes a free app to a
/// private topic.
///
/// No dependency on `Prefs` or any actor, so the shield action extension can send from its own
/// process with the app not running.
enum Pusher {

    struct Config: Sendable {
        let enabled: Bool
        let server: String
        let topic: String
    }

    /// For the extensions, which can't reach the app's `Prefs`.
    static func configFromShared() -> Config {
        let defaults = UserDefaults(suiteName: SessionStore.appGroup) ?? .standard
        let enabled = defaults.object(forKey: "push_enabled") == nil
            ? true : defaults.bool(forKey: "push_enabled")
        return Config(enabled: enabled,
                      server: defaults.string(forKey: "ntfy_server") ?? "https://ntfy.sh",
                      topic: Keychain.get("ntfy_topic") ?? "")
    }

    /// Returns nil on success, or a reason. Never throws.
    @discardableResult
    static func send(_ cfg: Config, title: String, message: String) async -> String? {
        guard cfg.enabled else { return "alerts are switched off" }
        guard !cfg.topic.isEmpty else { return "no alert code is set" }
        guard let url = URL(string: cfg.server.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                            + "/" + cfg.topic) else {
            return "the ntfy server URL isn't valid"
        }

        var req = URLRequest(url: url, timeoutInterval: 20)
        req.httpMethod = "POST"
        req.httpBody = Data(message.utf8)
        // ntfy header values must be ASCII; one em dash would otherwise break the request.
        req.setValue(asciiHeader(title), forHTTPHeaderField: "Title")
        req.setValue("high", forHTTPHeaderField: "Priority")
        req.setValue("rotating_light", forHTTPHeaderField: "Tags")

        do {
            let (_, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            return (200...299).contains(code) ? nil : "ntfy returned HTTP \(code)"
        } catch {
            return "couldn't reach \(cfg.server)"
        }
    }

    private static func asciiHeader(_ s: String) -> String {
        let filtered = s.unicodeScalars.filter { $0.value >= 32 && $0.value <= 126 }
        let out = String(String.UnicodeScalarView(filtered))
        return out.isEmpty ? "Lockout" : out
    }
}
