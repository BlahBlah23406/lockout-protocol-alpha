import Foundation

/// Zero-setup push alerts via ntfy (https://ntfy.sh). No account, no password — the user just
/// subscribes the free ntfy app (or web) to their private topic code. We POST the alert text to
/// {server}/{topic}. The topic string is unguessable, so it doubles as the secret. Direct port of
/// the Android `Pusher`.
enum Pusher {

    struct Config {
        let enabled: Bool
        let server: String
        let topic: String
    }

    @discardableResult
    static func send(_ cfg: Config, title: String, message: String) async -> Result<Void, Error> {
        guard cfg.enabled else { return .failure(Err.disabled) }
        guard !cfg.topic.isEmpty else { return .failure(Err.noTopic) }

        let urlString = cfg.server.trimmedSlash() + "/" + cfg.topic
        guard let url = URL(string: urlString) else { return .failure(Err.badURL) }

        var req = URLRequest(url: url, timeoutInterval: 20)
        req.httpMethod = "POST"
        req.setValue(title.asciiHeader(), forHTTPHeaderField: "Title")
        req.setValue("high", forHTTPHeaderField: "Priority")
        req.setValue("rotating_light", forHTTPHeaderField: "Tags")
        req.httpBody = Data(message.utf8)

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
                let body = String(data: data, encoding: .utf8) ?? ""
                return .failure(Err.http("ntfy \(http.statusCode): \(body)"))
            }
            return .success(())
        } catch {
            return .failure(error)
        }
    }

    enum Err: LocalizedError {
        case disabled, noTopic, badURL, http(String)
        var errorDescription: String? {
            switch self {
            case .disabled: return "push disabled"
            case .noTopic: return "no topic"
            case .badURL: return "bad ntfy URL"
            case .http(let m): return m
            }
        }
    }
}

private extension String {
    /// ntfy header values must be ASCII; strip anything else so titles never break the request.
    func asciiHeader() -> String {
        let s = String(unicodeScalars.filter { (32...126).contains($0.value) })
        return s.isEmpty ? "Guardian" : s
    }
    func trimmedSlash() -> String {
        var s = self
        while s.hasSuffix("/") { s.removeLast() }
        return s
    }
}
