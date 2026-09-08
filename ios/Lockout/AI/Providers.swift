import Foundation

/// Pluggable model providers, text-only.
///
/// This is the iOS sibling of `macos/Guardian/AI/Providers.swift`, and the difference between them
/// is the whole iOS story in one line: **there is no image in the request.** The macOS version
/// posts a JPEG of the screen; this one posts a task description and a list of app names, because
/// iOS does not let an app see another app's screen and never will.
///
/// A pleasant consequence is that the model no longer needs to be multimodal, which widens the
/// choice a lot: any small text model will answer "which of these apps does 'math test prep'
/// need?" perfectly well, including ones that run on a phone.
///
/// The retry and key fail-over policy is carried over unchanged, because the reasoning behind it
/// is unchanged: a backend that is busy or out of credit is our problem, and must never silently
/// leave a session unprotected.
enum ProviderKind: String, Codable, Sendable {
    case ollama, openai, anthropic, custom
}

struct ProviderPreset: Identifiable, Sendable {
    let id: String
    let kind: ProviderKind
    let label: String
    let baseUrl: String
    let model: String
    let needsKey: Bool
    let hint: String
}

enum Providers {

    /// Note the local option points at a LAN address, not `127.0.0.1`: on a phone localhost is the
    /// phone, which is not where anyone is running a model server.
    static let presets: [ProviderPreset] = [
        .init(id: "ollama-cloud", kind: .ollama, label: "Ollama Cloud",
              baseUrl: "https://ollama.com", model: "gemma4:31b-cloud", needsKey: true,
              hint: "Hosted Ollama. The simplest thing that works with no other hardware."),
        .init(id: "ollama-lan", kind: .ollama, label: "Ollama on my own computer",
              baseUrl: "http://192.168.1.10:11434", model: "qwen3:8b", needsKey: false,
              hint: "Free and private — your task text goes to your own machine over Wi-Fi and no "
                  + "further. Needs Ollama started with OLLAMA_HOST=0.0.0.0 so the phone can "
                  + "reach it. No vision model needed on iOS."),
        .init(id: "openai", kind: .openai, label: "OpenAI",
              baseUrl: "https://api.openai.com", model: "gpt-4.1-mini", needsKey: true,
              hint: "Any OpenAI text model."),
        .init(id: "anthropic", kind: .anthropic, label: "Anthropic (Claude)",
              baseUrl: "https://api.anthropic.com", model: "claude-haiku-4-5-20251001",
              needsKey: true,
              hint: "Haiku is the right size — this is one short question per session."),
        .init(id: "custom", kind: .custom, label: "Anything OpenAI-compatible",
              baseUrl: "", model: "", needsKey: false,
              hint: "llama.cpp, vLLM, LM Studio, OpenRouter, Groq, a company gateway — paste the "
                  + "base URL that ends in /v1."),
    ]

    static func preset(id: String) -> ProviderPreset? { presets.first { $0.id == id } }

    struct Config: Sendable {
        let kind: ProviderKind
        let baseUrl: String
        let model: String
        /// Keys to try, the one that last worked first. Empty for a local provider.
        let apiKeys: [String]
        let label: String

        var describe: String { "\(kind.rawValue):\(model)" }
    }

    /// Either the assistant's text, or a human-readable reason there isn't any. Deliberately not
    /// an `Error`: every caller wants to *say* what went wrong to the user, not rethrow it.
    enum TextResult: Sendable {
        case success(String)
        case failure(String)
    }

    static let maxAttempts = 3
    static let backoffSeconds: Double = 0.8
    static let requestTimeout: TimeInterval = 60

    static func isTransientCode(_ code: Int) -> Bool {
        [408, 429, 500, 502, 503, 504].contains(code)
    }

    static func isKeyExhaustedCode(_ code: Int) -> Bool {
        [401, 402, 403, 429].contains(code)
    }

    // MARK: - Request building

    struct BuiltRequest {
        let url: URL
        let payload: [String: Any]
        let extraHeaders: [String: String]
    }

    static func buildRequest(_ cfg: Config, system: String, user: String) -> BuiltRequest? {
        let base = cfg.baseUrl.hasSuffix("/") ? String(cfg.baseUrl.dropLast()) : cfg.baseUrl

        switch cfg.kind {
        case .ollama:
            guard let url = URL(string: base + "/api/chat") else { return nil }
            return BuiltRequest(url: url, payload: [
                "model": cfg.model,
                "stream": false,
                "format": "json",
                "keep_alive": "20m",
                "messages": [
                    ["role": "system", "content": system],
                    ["role": "user", "content": user],
                ],
                "options": ["temperature": 0, "num_predict": 400],
            ], extraHeaders: [:])

        case .anthropic:
            guard let url = URL(string: base + "/v1/messages") else { return nil }
            return BuiltRequest(url: url, payload: [
                "model": cfg.model,
                "max_tokens": 500,
                "temperature": 0,
                "system": system,
                "messages": [["role": "user", "content": user]],
            ], extraHeaders: ["anthropic-version": "2023-06-01"])

        case .openai, .custom:
            // A URL that already ends in /v1 is left alone — appending a second one is the single
            // most common way people misconfigure this.
            let prefix = base.hasSuffix("/v1") ? base : base + "/v1"
            guard let url = URL(string: prefix + "/chat/completions") else { return nil }
            return BuiltRequest(url: url, payload: [
                "model": cfg.model,
                "max_tokens": 500,
                "temperature": 0,
                "response_format": ["type": "json_object"],
                "messages": [
                    ["role": "system", "content": system],
                    ["role": "user", "content": user],
                ],
            ], extraHeaders: [:])
        }
    }

    static func authHeaders(_ cfg: Config, key: String) -> [String: String] {
        guard !key.isEmpty else { return [:] }
        return cfg.kind == .anthropic ? ["x-api-key": key] : ["Authorization": "Bearer \(key)"]
    }

    // MARK: - Parsing

    /// Pull the assistant's text out of a provider's envelope.
    static func extractText(kind: ProviderKind, body: Data) -> String? {
        guard let root = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else {
            return nil
        }
        switch kind {
        case .ollama:
            return (root["message"] as? [String: Any])?["content"] as? String
        case .anthropic:
            return (root["content"] as? [[String: Any]])?
                .first { $0["type"] as? String == "text" }?["text"] as? String
        case .openai, .custom:
            return ((root["choices"] as? [[String: Any]])?.first?["message"]
                as? [String: Any])?["content"] as? String
        }
    }

    // MARK: - Transport

    private enum Attempt {
        case text(String)
        case transient(String)
        case keyRejected(String)
        case fatal(String)
    }

    private static func perform(_ cfg: Config, url: URL, body: Data,
                                headers: [String: String]) async -> Attempt {
        var req = URLRequest(url: url, timeoutInterval: requestTimeout)
        req.httpMethod = "POST"
        req.httpBody = body
        for (k, v) in headers { req.setValue(v, forHTTPHeaderField: k) }

        do {
            let (data, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if isKeyExhaustedCode(code) { return .keyRejected("key rejected (HTTP \(code))") }
            if isTransientCode(code) { return .transient("the model service is busy (HTTP \(code))") }
            guard (200...299).contains(code) else {
                return .fatal("the model service returned HTTP \(code)")
            }
            guard let text = extractText(kind: cfg.kind, body: data) else {
                return .fatal("the model's reply was in an unexpected shape")
            }
            return .text(text)
        } catch {
            if cfg.kind == .ollama, !cfg.baseUrl.hasPrefix("https://") {
                return .transient("your computer couldn't be reached — is it awake, on the same "
                                + "Wi-Fi, and running Ollama with OLLAMA_HOST=0.0.0.0?")
            }
            return .transient("the model service couldn't be reached")
        }
    }

    /// One text completion, with retry and key fail-over. Returns a reason on failure rather than
    /// throwing, because every caller shows that reason to the user.
    static func completeText(_ cfg: Config, system: String, user: String,
                             onKeyWorked: (@Sendable (String) -> Void)? = nil) async -> TextResult {
        guard let built = buildRequest(cfg, system: system, user: user) else {
            return .failure("the server URL isn't valid")
        }
        guard let body = try? JSONSerialization.data(withJSONObject: built.payload) else {
            return .failure("the request couldn't be built")
        }

        let keys = cfg.apiKeys.isEmpty ? [""] : cfg.apiKeys
        var lastProblem = "no attempt was made"

        for attempt in 0..<maxAttempts {
            if attempt > 0 {
                try? await Task.sleep(nanoseconds: UInt64(backoffSeconds * Double(attempt) * 1e9))
            }
            var exhausted = 0
            for (i, key) in keys.enumerated() {
                var headers = ["Content-Type": "application/json"]
                headers.merge(built.extraHeaders) { _, new in new }
                headers.merge(authHeaders(cfg, key: key)) { _, new in new }

                switch await perform(cfg, url: built.url, body: body, headers: headers) {
                case .text(let text):
                    if i > 0 { onKeyWorked?(key) }
                    return .success(text)
                case .keyRejected(let problem):
                    exhausted += 1
                    lastProblem = problem
                    continue
                case .transient(let problem):
                    lastProblem = problem
                case .fatal(let problem):
                    return .failure(problem)
                }
                break                       // transient: back off, then start at the first key
            }
            if exhausted == keys.count {
                lastProblem = "every API key is rejected or out of quota"
            }
        }
        return .failure(lastProblem)
    }

    /// Cheap "can I talk to this at all?" probe for the settings screen. nil means fine.
    static func reachability(_ cfg: Config) async -> String? {
        guard !cfg.baseUrl.isEmpty else { return "no server URL set" }
        guard !cfg.model.isEmpty else { return "no model set" }
        if cfg.kind == .anthropic { return nil }

        let urlString: String
        if cfg.kind == .ollama {
            urlString = cfg.baseUrl + "/api/tags"
        } else {
            let base = cfg.baseUrl.hasSuffix("/v1") ? cfg.baseUrl : cfg.baseUrl + "/v1"
            urlString = base + "/models"
        }
        guard let url = URL(string: urlString) else { return "the server URL isn't a valid URL" }

        var req = URLRequest(url: url, timeoutInterval: 8)
        for (k, v) in authHeaders(cfg, key: cfg.apiKeys.first ?? "") {
            req.setValue(v, forHTTPHeaderField: k)
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if code == 401 || code == 403 { return "server reachable, but the API key was rejected" }
            guard (200...299).contains(code) else { return "server returned HTTP \(code)" }
            let body = String(data: data, encoding: .utf8) ?? ""
            if !body.contains(cfg.model) {
                return "server is up, but '\(cfg.model)' was not in its model list"
            }
            return nil
        } catch {
            if cfg.kind == .ollama, !cfg.baseUrl.hasPrefix("https://") {
                return "couldn't reach \(cfg.baseUrl) — is the computer awake, on the same Wi-Fi, "
                     + "and running Ollama with OLLAMA_HOST=0.0.0.0?"
            }
            return "could not reach \(cfg.baseUrl)"
        }
    }
}
