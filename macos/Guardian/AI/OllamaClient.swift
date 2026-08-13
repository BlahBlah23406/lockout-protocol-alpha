import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// A strict content-safety verdict from the vision model.
/// `undetermined` = the model could not be reached or its answer couldn't be parsed. Callers treat
/// that as "couldn't verify" and handle it safely (alert, never a hard block) — per user policy.
/// `transient` = a temporary server/network failure (HTTP 503/429/5xx, timeout) — the AI backend
/// being busy, NOT the user hiding anything. Callers log + skip it and never quit/hide an app on it.
struct Verdict {
    let violation: Bool
    let reason: String
    let raw: String
    var undetermined: Bool = false
    var transient: Bool = false
}

/// Sends a screenshot to an Ollama (Cloud) vision model and asks for a strict JSON verdict.
/// Uses the /api/chat endpoint with a JPEG image attached to the user message. Direct port of the
/// Android `OllamaClient`.
struct OllamaClient {

    let prefs: Prefs

    /// Snapshot of the bits of Prefs we need, so the network call can run off the main actor.
    struct Config {
        let baseUrl: String
        /// Keys to try, the one that last worked first (see `Prefs.apiKeys`).
        let apiKeys: [String]
        let model: String
        let guidelines: String
    }

    @MainActor
    func config() -> Config {
        Config(baseUrl: prefs.ollamaBaseUrl, apiKeys: prefs.apiKeys,
               model: prefs.ollamaModel, guidelines: prefs.guidelines)
    }

    func evaluate(_ image: CGImage, config cfg: Config) async -> Verdict {
        guard let b64 = Self.jpegBase64(image, quality: 0.8) else {
            return Verdict(violation: false, reason: "encode-failed", raw: "", undetermined: true)
        }

        let sys = Self.strictSystem

        let user = """
            GUIDELINES (prohibited content):
            \(cfg.guidelines)

            Classify the attached screenshot. Flag it if prohibited content is visible, if the \
            visible text shows the user is trying to access prohibited content, OR if the screen \
            shows an attempt to disable or evade Ollama or Guardian (case C). Ignore innocent/\
            incidental mentions, ordinary development work on Guardian or Ollama, and unselected \
            suggestions.
            """

        let payload: [String: Any] = [
            "model": cfg.model,
            "stream": false,
            "format": "json",
            // Keep the model warm between checks — avoids cold-start reloads that make the
            // occasional request take 10-30s+.
            "keep_alive": "20m",
            "messages": [
                ["role": "system", "content": sys],
                ["role": "user", "content": user, "images": [b64]],
            ],
            // num_predict caps output so the model can't ramble; we only need a tiny JSON verdict.
            "options": ["temperature": 0, "num_predict": 80],
        ]

        guard let url = URL(string: cfg.baseUrl.trimmedSlash() + "/api/chat"),
              let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return Verdict(violation: false, reason: "bad-request", raw: "", undetermined: true)
        }

        // Keys to try, the one that last worked first. When a key is out of quota (or rejected) we
        // immediately retry the same request with the other one and remember the switch, so the two
        // keys alternate as each runs out instead of one always being burned first.
        let keys = cfg.apiKeys.isEmpty ? [""] : cfg.apiKeys

        // Retry transient backend failures (503/5xx, timeouts) a few times before giving up, so a
        // momentarily-overloaded Ollama Cloud resolves to a TRANSIENT verdict (logged + skipped),
        // never a "can't see" that could hide/quit the app.
        var lastTransient = Verdict(violation: false, reason: "no attempt", raw: "",
                                    undetermined: true, transient: true)
        for attempt in 0..<Self.maxAttempts {
            if attempt > 0 {
                try? await Task.sleep(nanoseconds: Self.backoffNs * UInt64(attempt))
            }
            var exhausted = 0
            for (i, key) in keys.enumerated() {
                let result = await Self.request(url: url, body: body, key: key)
                if result.keyRejected {
                    exhausted += 1
                    continue                       // this key is out — try the other one right away
                }
                if result.verdict.transient {
                    lastTransient = result.verdict
                    break                          // back off, then start over at the active key
                }
                // Success (or a definite error) on this key: make it the one we start with next time.
                if i > 0 { await MainActor.run { prefs.promoteApiKey(key) } }
                return result.verdict
            }
            if exhausted == keys.count {
                // Every key is out of quota right now. Transient, never a block: the next tick retries.
                lastTransient = Verdict(violation: false,
                                        reason: "AI quota exhausted on all \(keys.count) key(s)",
                                        raw: "", undetermined: true, transient: true)
            }
        }
        return lastTransient
    }

    // MARK: - System prompt

    /// The classifier prompt. Deliberately strict: it flags when in doubt. Case (C) makes the
    /// monitoring self-defending — a visible attempt to disable it is itself a violation.
    static let strictSystem = """
        You are a STRICT content-safety classifier for a personal accountability app on the user's
        Mac. Its ONE purpose is to keep this user away from sexual and sexually-suggestive imagery,
        and to catch any attempt to go looking for it. When in doubt, you FLAG — err on the side of
        flagging, not permitting. You are given ONE computer screenshot and a list of GUIDELINES.

        Report a violation (true) when ANY of the following is true:
          (A) VISIBLE IMAGERY that is sexual or sexually suggestive. This is intentionally broad:
              pornography or explicit sexual acts; real nudity OR partial nudity; a woman or man in
              underwear, lingerie, a bikini, or swimwear; exposed or emphasised cleavage, breasts,
              midriff, buttocks, crotch, or bare thighs; see-through, wet, or tight clothing that
              sexualises the body; sexualised or provocative poses; close-ups of intimate body
              areas. If a reasonable person could find the image sexually arousing or masturbate to
              it, FLAG IT.
          (B) INTENT shown in visible TEXT — a search query, typed input, URL, video/page title, or
              an app/site being opened — that shows the user is trying to FIND or VIEW such content.
              This explicitly INCLUDES typing a search into Google, Google Images, an image site,
              YouTube, TikTok, Instagram, Reddit, or Pinterest where the query seeks sexual, nude,
              "hot", "sexy", bikini, lingerie, or otherwise provocative images or video of people;
              opening a site/app whose name denotes pornography; or navigating an image/video search
              clearly aimed at ogling people. Judge the INTENT behind the text, not only whether an
              explicit word is present.
          (C) TAMPERING — visible text or UI showing a concrete attempt to DISABLE or EVADE Ollama
              (the AI service that powers this monitoring) or Guardian itself. Flag only an actual
              action that would break the monitoring, such as: a command to stop, kill, unload, or
              uninstall the "ollama" process/service or Guardian (`pkill ollama`, `killall
              Guardian`, `ollama stop`, `launchctl bootout`); revoking, deleting, or replacing the
              Ollama API key, or repointing the server URL at a dead or fake endpoint; revoking
              Guardian's Screen Recording permission; or editing the hosts file, a firewall, DNS,
              proxy, or VPN to block ollama.com. Flag these even when no sexual content is present.

              Merely READING or WORKING WITH Ollama or Guardian is NOT tampering: the ollama.com
              website, docs, or model listings; an Ollama app window; the source code of either
              project (including this classifier prompt itself); a settings screen merely being
              viewed; or a terminal that mentions "ollama" without a disabling command.
              If you cannot point to a specific command or action that would actually break the
              monitoring, do NOT flag case (C) — this narrowing applies to case (C) only and does
              not soften cases (A) or (B) in any way.

        Respond false ONLY for genuinely innocent, non-sexual screens: the desktop, Dock, app
        windows, news, education, this app's own screens, ordinary chats/AI apps, code, maps,
        settings, email, shopping for non-sexual items, or a word appearing incidentally with no
        sexual intent — UNLESS the screen shows an actual attempt to disable Ollama or Guardian per
        case (C). But when imagery is even borderline sexual, FLAG IT — do NOT give the benefit of
        the doubt.

        When you flag based on text/intent (case B or C), the reason MUST quote the specific visible
        text. Never invent a reason.

        Respond with ONLY a compact JSON object, no markdown, no prose. Either:
        {"violation": false}
        or
        {"violation": true, "reason": "<specific visible content or quoted text>"}
        """

    /// One HTTP call with one key. `keyRejected` means "this key is out/invalid, try another".
    private struct Attempt {
        let verdict: Verdict
        var keyRejected: Bool = false
    }

    private static func request(url: URL, body: Data, key: String) async -> Attempt {
        var req = URLRequest(url: url, timeoutInterval: 90)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !key.isEmpty {
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        }
        req.httpBody = body

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            let text = String(data: data, encoding: .utf8) ?? ""
            if let http = resp as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
                if isKeyExhaustedCode(http.statusCode) {
                    return Attempt(verdict: Verdict(violation: false,
                                                    reason: "key rejected (HTTP \(http.statusCode))",
                                                    raw: text, undetermined: true, transient: true),
                                   keyRejected: true)
                }
                if isTransientCode(http.statusCode) {
                    return Attempt(verdict: Verdict(violation: false,
                                                    reason: "AI busy (HTTP \(http.statusCode))",
                                                    raw: text, undetermined: true, transient: true))
                }
                return Attempt(verdict: Verdict(violation: false,
                                                reason: "API error \(http.statusCode)",
                                                raw: text, undetermined: true))
            }
            return Attempt(verdict: parseVerdict(data))
        } catch {
            // Network drops / timeouts are transient too — keep retrying, never hide/quit on these.
            return Attempt(verdict: Verdict(violation: false,
                                            reason: "AI unreachable: \(error.localizedDescription)",
                                            raw: "", undetermined: true, transient: true))
        }
    }

    // Transient-failure retry policy (fixes the 503-closes-my-apps bug).
    static let maxAttempts = 3
    static let backoffNs: UInt64 = 800_000_000   // 0.8s

    /// HTTP codes we treat as temporary backend hiccups worth retrying (never a "can't see").
    static func isTransientCode(_ code: Int) -> Bool {
        code == 408 || code == 429 || code == 500 || code == 502 || code == 503 || code == 504
    }

    /// HTTP codes that mean THIS KEY can't be used right now — quota/credit exhausted (402/429) or
    /// the key being rejected outright (401/403) — as opposed to the backend being busy. These are
    /// what trigger the fail-over to the other key. Still never a block on their own: if every key
    /// is out, the verdict stays transient.
    static func isKeyExhaustedCode(_ code: Int) -> Bool {
        code == 401 || code == 402 || code == 403 || code == 429
    }

    /// Pure parse of an Ollama /api/chat response body into a `Verdict`. The model's content is
    /// expected to be a JSON object {"violation":bool,"reason":string}. Anything unparseable is
    /// marked undetermined (caller handles safely). Pure function for unit testing.
    static func parseVerdict(_ data: Data) -> Verdict {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let message = root["message"] as? [String: Any],
              let content = message["content"] as? String else {
            let s = String(data: data, encoding: .utf8) ?? ""
            return Verdict(violation: false, reason: "parse-failed", raw: s, undetermined: true)
        }
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let cdata = trimmed.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: cdata) as? [String: Any] else {
            return Verdict(violation: false, reason: "parse-failed", raw: content, undetermined: true)
        }
        let violation = obj["violation"] as? Bool ?? false
        let reason = obj["reason"] as? String ?? ""
        return Verdict(violation: violation, reason: reason, raw: content)
    }

    static func parseVerdict(_ body: String) -> Verdict {
        parseVerdict(Data(body.utf8))
    }

    /// Encode a CGImage to base64 JPEG (no line wrapping), matching the Android upload format.
    static func jpegBase64(_ image: CGImage, quality: CGFloat) -> String? {
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(
            out, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        let opts: [CFString: Any] = [kCGImageDestinationLossyCompressionQuality: quality]
        CGImageDestinationAddImage(dest, image, opts as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return (out as Data).base64EncodedString()
    }
}

private extension String {
    func trimmedSlash() -> String {
        var s = self
        while s.hasSuffix("/") { s.removeLast() }
        return s
    }
}
