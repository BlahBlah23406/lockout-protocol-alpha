import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Model providers for the focus classifier.
///
/// The request shape differs per provider; the retry and key fail-over policy is shared, because
/// the rule it enforces — a backend problem must never look like the user being off task —
/// applies equally to all of them.
enum ProviderKind: String, Codable, Sendable {
    case ollama, openai, anthropic, custom
}

/// One entry in the settings picker.
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

    /// `custom` is `openai` with the URL field unlocked, listed separately so the picker can say
    /// "anything OpenAI-compatible".
    static let presets: [ProviderPreset] = [
        .init(id: "ollama-local", kind: .ollama, label: "Ollama (on this Mac)",
              baseUrl: "http://127.0.0.1:11434", model: "qwen3-vl:8b", needsKey: false,
              hint: "Free and fully private — nothing leaves this machine. Needs Ollama installed "
                  + "and a vision model pulled (`ollama pull qwen3-vl:8b`)."),
        .init(id: "ollama-cloud", kind: .ollama, label: "Ollama Cloud",
              baseUrl: "https://ollama.com", model: "gemma4:31b-cloud", needsKey: true,
              hint: "Hosted Ollama. Works on any Mac, including one that can't run a vision "
                  + "model itself."),
        .init(id: "openai", kind: .openai, label: "OpenAI",
              baseUrl: "https://api.openai.com", model: "gpt-4.1-mini", needsKey: true,
              hint: "Any OpenAI vision model."),
        .init(id: "anthropic", kind: .anthropic, label: "Anthropic (Claude)",
              baseUrl: "https://api.anthropic.com", model: "claude-haiku-4-5-20251001",
              needsKey: true,
              hint: "Haiku is the right size here — the check is a one-line yes/no, run hundreds "
                  + "of times a session."),
        .init(id: "lmstudio", kind: .custom, label: "LM Studio (on this Mac)",
              baseUrl: "http://127.0.0.1:1234/v1", model: "qwen2.5-vl-7b", needsKey: false,
              hint: "LM Studio's local server. Start it from LM Studio's Developer tab."),
        .init(id: "custom", kind: .custom, label: "Anything OpenAI-compatible",
              baseUrl: "", model: "", needsKey: false,
              hint: "llama.cpp, vLLM, OpenRouter, Groq, Together, a company gateway — paste the "
                  + "base URL that ends in /v1."),
    ]

    static func preset(id: String) -> ProviderPreset? { presets.first { $0.id == id } }

    // MARK: - Verdict

    /// One focus check.
    ///
    /// `undetermined` (unreadable answer or screen) and `transient` (backend busy, unreachable, or
    /// out of quota) are kept distinct from an off-task answer, and neither ever blocks.
    struct Verdict: Sendable {
        var onTask: Bool = true
        var reason: String = ""
        /// The model's own 0–1 self-report. Not treated as calibrated.
        var confidence: Double = 0
        var raw: String = ""
        var undetermined: Bool = false
        var transient: Bool = false

        /// True only for a clean, readable "this is not the declared task" answer.
        var offTask: Bool { !onTask && !undetermined && !transient }
    }

    /// Immutable snapshot, so the network call can run off the main actor.
    struct Config: Sendable {
        let kind: ProviderKind
        let baseUrl: String
        let model: String
        /// Keys to try, the one that last worked first. Empty for a local provider.
        let apiKeys: [String]
        let label: String

        var describe: String { "\(kind.rawValue):\(model)" }
    }

    // MARK: - The classifier prompt

    /// Biased towards "on task", which is the opposite of the content-safety classifier. The
    /// asymmetry follows from what a mistake costs: a missed frame of browsing costs seconds, a
    /// false alarm interrupts real work and gets the app uninstalled. It also counts supporting
    /// work as on-task, because almost nothing real happens inside a single app.
    static let focusSystem = """
        You decide whether ONE screenshot shows a person working on the task they declared.

        You are given: the user's own description of what they sat down to do, the name of the app \
        in front, its window title, and one screenshot. Answer with a single JSON object.

        DEFAULT TO on_task. You are the interruption in someone's working day, so you must be sure \
        before you say no. If a screen is plausibly part of the declared work — even indirectly — \
        it is on task.

        Count as ON TASK:
          - The obvious: the document, editor, problem set, spreadsheet, or tool the task names.
          - SUPPORTING WORK, which is most of real work: searching the web for the topic, reading \
        documentation or a tutorial, watching an instructional video, a forum or Q&A thread about \
        the subject, a study-group chat, email or a message thread about the task, note-taking, a \
        calculator, a file manager, a password prompt, a download, a print dialog.
          - Setup and friction: an app still loading, a login screen, a settings page, an update \
        prompt, an empty new tab, a desktop or lock screen, this monitoring app's own windows.
          - Anything ambiguous, unreadable, or that you simply cannot connect either way.

        Count as OFF TASK only when the screen is CLEARLY unrelated to the declared task AND is \
        recognisably leisure or a different job: an entertainment video or show with no connection \
        to the topic, a game being played, a social feed being scrolled, shopping, sports scores, \
        memes, unrelated news, or focused work on a plainly different project.

        Judge the SCREEN, not the app. YouTube showing a lecture on the topic is on task; YouTube \
        showing a gaming stream is off task. A browser is neither good nor bad — read what is in it.

        When you say off_task, `reason` MUST quote the specific visible text or name the specific \
        visible content that decided it. Never invent a reason, and never guess at what is off-screen.

        `confidence` is how sure you are of the answer you gave, from 0.0 to 1.0. Be honest and use \
        the low end freely — a 0.4 is far more useful to us than a falsely confident 0.9.

        If the screenshot is blank, encrypted, DRM-protected, or otherwise unreadable, return \
        {"unreadable": true} instead of guessing.

        Respond with ONLY compact JSON, no markdown and no prose. One of:
        {"on_task": true, "confidence": 0.9}
        {"on_task": false, "reason": "<specific visible evidence>", "confidence": 0.8}
        {"unreadable": true}
        """

    /// App name and title are supplied as text as well as being visible in the image: a small
    /// vision model reads a given string far more reliably than a 12px title bar.
    static func userPrompt(task: String, appName: String, windowTitle: String,
                           extraNotes: String = "") -> String {
        var parts = [
            "THE USER'S DECLARED TASK, in their own words:",
            "    \(task.isEmpty ? "(none given)" : task)",
            "",
            "App in front: \(appName.isEmpty ? "unknown" : appName)",
            "Window title: \(windowTitle.isEmpty ? "(none)" : windowTitle)",
        ]
        let notes = extraNotes.trimmingCharacters(in: .whitespacesAndNewlines)
        if !notes.isEmpty {
            parts += ["", "PREVIOUSLY CONFIRMED BY THE USER — treat these as settled:", notes]
        }
        parts += ["", "Is this screen part of that task? Answer in JSON."]
        return parts.joined(separator: "\n")
    }

    // MARK: - Parsing (pure — driven directly by the tests)

    /// Small models fence their JSON even when told not to, so fences are stripped rather than
    /// discarding an otherwise good answer.
    static func parseFocusJSON(_ content: String) -> Verdict {
        var text = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("```") {
            if let firstNewline = text.firstIndex(of: "\n") {
                text = String(text[text.index(after: firstNewline)...])
            } else {
                text = ""
            }
            if text.hasSuffix("```") { text = String(text.dropLast(3)) }
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return Verdict(reason: "parse-failed", raw: content, undetermined: true)
        }

        if obj["unreadable"] as? Bool == true {
            return Verdict(reason: "screen unreadable", raw: text, undetermined: true)
        }

        // A missing answer is a failure to answer, not a "no".
        guard let onTask = obj["on_task"] as? Bool else {
            return Verdict(reason: "no on_task field", raw: text, undetermined: true)
        }

        let confidence = min(max((obj["confidence"] as? NSNumber)?.doubleValue ?? 0, 0), 1)
        return Verdict(onTask: onTask, reason: obj["reason"] as? String ?? "",
                       confidence: confidence, raw: text)
    }

    /// Pull the assistant's text out of a provider's envelope, then parse it.
    static func parseResponse(kind: ProviderKind, body: Data) -> Verdict {
        let raw = String(data: body, encoding: .utf8) ?? ""
        guard let root = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else {
            return Verdict(reason: "parse-failed", raw: String(raw.prefix(400)), undetermined: true)
        }

        let content: String?
        switch kind {
        case .ollama:
            content = (root["message"] as? [String: Any])?["content"] as? String
        case .anthropic:
            content = (root["content"] as? [[String: Any]])?
                .first { $0["type"] as? String == "text" }?["text"] as? String
        case .openai, .custom:
            content = ((root["choices"] as? [[String: Any]])?.first?["message"]
                as? [String: Any])?["content"] as? String
        }

        guard let content else {
            return Verdict(reason: "parse-failed", raw: String(raw.prefix(400)), undetermined: true)
        }
        return parseFocusJSON(content)
    }

    // MARK: - Request building

    static func jpegBase64(_ image: CGImage, quality: CGFloat = 0.8) -> String? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(
            data, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, image,
                                   [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return (data as Data).base64EncodedString()
    }

    struct BuiltRequest {
        let url: URL
        let payload: [String: Any]
        let extraHeaders: [String: String]
    }

    static func buildRequest(_ cfg: Config, base64Image b64: String,
                             system: String, user: String) -> BuiltRequest? {
        let base = cfg.baseUrl.hasSuffix("/") ? String(cfg.baseUrl.dropLast()) : cfg.baseUrl

        switch cfg.kind {
        case .ollama:
            guard let url = URL(string: base + "/api/chat") else { return nil }
            return BuiltRequest(url: url, payload: [
                "model": cfg.model,
                "stream": false,
                "format": "json",
                // At a 2-minute interval a cold model reload costs more than the inference.
                "keep_alive": "20m",
                "messages": [
                    ["role": "system", "content": system],
                    ["role": "user", "content": user, "images": [b64]],
                ],
                "options": ["temperature": 0, "num_predict": 160],
            ], extraHeaders: [:])

        case .anthropic:
            guard let url = URL(string: base + "/v1/messages") else { return nil }
            return BuiltRequest(url: url, payload: [
                "model": cfg.model,
                "max_tokens": 200,
                "temperature": 0,
                "system": system,
                "messages": [["role": "user", "content": [
                    ["type": "image",
                     "source": ["type": "base64", "media_type": "image/jpeg", "data": b64]],
                    ["type": "text", "text": user],
                ]]],
            ], extraHeaders: ["anthropic-version": "2023-06-01"])

        case .openai, .custom:
            // A URL that already ends in /v1 is left alone; appending a second is the most
            // common way people misconfigure this.
            let prefix = base.hasSuffix("/v1") ? base : base + "/v1"
            guard let url = URL(string: prefix + "/chat/completions") else { return nil }
            return BuiltRequest(url: url, payload: [
                "model": cfg.model,
                "max_tokens": 200,
                "temperature": 0,
                "response_format": ["type": "json_object"],
                "messages": [
                    ["role": "system", "content": system],
                    ["role": "user", "content": [
                        ["type": "text", "text": user],
                        ["type": "image_url",
                         "image_url": ["url": "data:image/jpeg;base64,\(b64)"]],
                    ]],
                ],
            ], extraHeaders: [:])
        }
    }

    /// Providers disagree about where the key goes; that is the whole difference in auth.
    static func authHeaders(_ cfg: Config, key: String) -> [String: String] {
        guard !key.isEmpty else { return [:] }
        return cfg.kind == .anthropic ? ["x-api-key": key] : ["Authorization": "Bearer \(key)"]
    }

    // MARK: - Transport + the never-block-on-a-hiccup policy

    static let maxAttempts = 3
    static let backoffSeconds: Double = 0.8
    static let requestTimeout: TimeInterval = 90

    /// Temporary backend trouble, worth retrying. Never evidence about the user.
    static func isTransientCode(_ code: Int) -> Bool {
        [408, 429, 500, 502, 503, 504].contains(code)
    }

    /// This key is out of credit or rejected — fail over to the next. If every key is out the
    /// verdict stays transient: being out of API credit must never cost the user a block.
    static func isKeyExhaustedCode(_ code: Int) -> Bool {
        [401, 402, 403, 429].contains(code)
    }

    private struct Attempt {
        let verdict: Verdict
        var keyRejected = false
    }

    private static func perform(kind: ProviderKind, url: URL, body: Data,
                                headers: [String: String]) async -> Attempt {
        var req = URLRequest(url: url, timeoutInterval: requestTimeout)
        req.httpMethod = "POST"
        req.httpBody = body
        for (k, v) in headers { req.setValue(v, forHTTPHeaderField: k) }

        do {
            let (data, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let text = String(data: data, encoding: .utf8) ?? ""
            if isKeyExhaustedCode(code) {
                return Attempt(verdict: Verdict(reason: "key rejected (HTTP \(code))",
                                                raw: String(text.prefix(400)),
                                                undetermined: true, transient: true),
                               keyRejected: true)
            }
            if isTransientCode(code) {
                return Attempt(verdict: Verdict(reason: "AI busy (HTTP \(code))",
                                                raw: String(text.prefix(400)),
                                                undetermined: true, transient: true))
            }
            if !(200...299).contains(code) {
                return Attempt(verdict: Verdict(reason: "API error \(code)",
                                                raw: String(text.prefix(400)), undetermined: true))
            }
            return Attempt(verdict: parseResponse(kind: kind, body: data))
        } catch {
            // A local Ollama that isn't running lands here.
            return Attempt(verdict: Verdict(reason: "AI unreachable: \(error.localizedDescription)",
                                            undetermined: true, transient: true))
        }
    }

    /// Run one focus check.
    static func evaluate(_ cfg: Config, image: CGImage, task: String, appName: String,
                         windowTitle: String, extraNotes: String = "",
                         onKeyWorked: (@Sendable (String) -> Void)? = nil) async -> Verdict {
        guard !cfg.model.isEmpty else {
            return Verdict(reason: "no model configured", undetermined: true)
        }
        guard let b64 = jpegBase64(image) else {
            return Verdict(reason: "encode-failed", undetermined: true)
        }

        let user = userPrompt(task: task, appName: appName, windowTitle: windowTitle,
                              extraNotes: extraNotes)
        guard let built = buildRequest(cfg, base64Image: b64, system: focusSystem, user: user),
              let body = try? JSONSerialization.data(withJSONObject: built.payload) else {
            return Verdict(reason: "bad-request", undetermined: true)
        }

        let keys = cfg.apiKeys.isEmpty ? [""] : cfg.apiKeys
        var lastTransient = Verdict(reason: "no attempt", undetermined: true, transient: true)

        for attempt in 0..<maxAttempts {
            if attempt > 0 {
                try? await Task.sleep(nanoseconds: UInt64(backoffSeconds * Double(attempt) * 1e9))
            }
            var exhausted = 0
            for (i, key) in keys.enumerated() {
                var headers = ["Content-Type": "application/json"]
                headers.merge(built.extraHeaders) { _, new in new }
                headers.merge(authHeaders(cfg, key: key)) { _, new in new }

                let result = await perform(kind: cfg.kind, url: built.url, body: body,
                                           headers: headers)
                if result.keyRejected {
                    exhausted += 1
                    continue                        // this key is out — try the next immediately
                }
                if result.verdict.transient {
                    lastTransient = result.verdict
                    break                           // back off, then start again at the first key
                }
                if i > 0 { onKeyWorked?(key) }
                return result.verdict
            }
            if exhausted == keys.count {
                lastTransient = Verdict(reason: "all \(keys.count) key(s) rejected or out of quota",
                                        undetermined: true, transient: true)
            }
        }
        return lastTransient
    }

    /// "Can I talk to this at all?" probe for the settings screen. Nil when fine, or a
    /// human-readable problem.
    static func reachability(_ cfg: Config) async -> String? {
        guard !cfg.baseUrl.isEmpty else { return "no server URL set" }
        guard !cfg.model.isEmpty else { return "no model set" }
        if cfg.kind == .anthropic { return nil }    // no free unauthenticated probe

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
            if cfg.kind == .ollama && cfg.baseUrl.contains("127.0.0.1") {
                return "Ollama doesn't seem to be running on this Mac (start it, then retry)"
            }
            return "could not reach \(cfg.baseUrl): \(error.localizedDescription)"
        }
    }
}
