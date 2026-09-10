import Foundation

/// Deciding which apps to shut for a declared task — the iOS replacement for the screen check.
///
/// The model is asked once, at the start of a session, which of the apps the user nominated should
/// be shut. That is coarser than the desktop's per-screen check (YouTube is either shut or open)
/// and strictly more private (nothing about the screen is captured at all).
///
/// `Fallback.plan` shields everything the user offered when the model can't be reached. Failing
/// closed is right here specifically, because unlike a block screen a shield cannot lock you out
/// of anything.
enum ShieldPlan {

    /// One app the user offered up. `token` is opaque — only the system can resolve it — and the
    /// label is whatever the picker chose to show, which may be nothing.
    struct Candidate: Sendable, Hashable {
        let token: String
        let label: String

        var describedLabel: String {
            label.trimmingCharacters(in: .whitespaces).isEmpty
                ? "(an app the system won't name)" : label
        }
    }

    struct Decision: Sendable {
        /// Tokens to shield for the session.
        var shield: [String]
        /// Tokens left open, shown in the UI so the user can correct them before starting.
        var allow: [String]
        var reasoning: String
        /// True when `Fallback` was used. Surfaced in the UI: a plan the model did not make must
        /// not be presented as one it did.
        var isFallback: Bool
    }

    // MARK: - Fallback

    enum Fallback {
        /// Shield everything offered. The strict choice, for the reason in the type doc — and
        /// nowhere else in this codebase.
        static func plan(_ candidates: [Candidate], why: String) -> Decision {
            Decision(shield: candidates.map(\.token),
                     allow: [],
                     reasoning: "Shielded everything you offered, because \(why). "
                              + "You can unshield individual apps before starting.",
                     isFallback: true)
        }
    }

    // MARK: - Prompt

    /// Biased towards shielding, which is the opposite of the screen classifier — because the
    /// costs are reversed. Nothing is being interrupted: the user nominated these apps and
    /// reviews the plan before it applies, so a wrong shield costs one tap and under-shielding
    /// costs the session.
    static let system = """
        You decide which of a person's apps should be shut while they do a task they have declared.

        You are given their own description of the task, and a list of apps they have ALREADY
        NOMINATED as candidates for shielding. Everything on the list is an app they are willing to
        have shut; your job is only to say which ones are actually needed for this particular task.

        SHIELD an app unless it is plausibly needed for the declared task. The person nominated
        these apps themselves, and they review your plan before it takes effect, so a shielded app
        they wanted costs one tap — while an unshielded distraction costs them the session.

        ALLOW an app when the declared task plausibly requires it:
          - The tool the task names, and the obvious companions of that tool.
          - Reference and communication that the task genuinely needs: a browser for research, a
            notes app, a mail or chat app when the task IS correspondence, a dictionary, a
            calculator, a cloud-drive app where the files live.
          - Anything you cannot identify. An app whose name means nothing to you might be the very
            tool they need, so say so in `reasoning` rather than guessing it is a game.

        Judge only from the task and the app names. You cannot see their screen and you must not
        pretend to: never claim to know what is inside an app.

        `reasoning` is one or two sentences the person will actually read on the confirmation
        screen. Say what you shielded and, briefly, why anything was left open.

        Respond with ONLY compact JSON, no markdown and no prose:
        {"shield": ["<app name>", ...], "allow": ["<app name>", ...], "reasoning": "<one or two sentences>"}

        Use the app names exactly as they were given to you. Every app you were given must appear
        in exactly one of the two lists.
        """

    static func userPrompt(task: String, candidates: [Candidate], extraNotes: String = "") -> String {
        var parts = [
            "THE TASK, in the user's own words:",
            "    \(task.isEmpty ? "(none given)" : task)",
            "",
            "APPS THEY HAVE OFFERED UP FOR SHIELDING:",
        ]
        parts += candidates.map { "    - \($0.describedLabel)" }

        let notes = extraNotes.trimmingCharacters(in: .whitespacesAndNewlines)
        if !notes.isEmpty {
            parts += ["", "STANDING NOTES FROM THE USER — treat these as settled:", notes]
        }
        parts += ["", "Which should be shut while they do that task? Answer in JSON."]
        return parts.joined(separator: "\n")
    }

    // MARK: - Parsing

    /// Map the model's answer back onto tokens. Strict in one direction: any candidate the model
    /// failed to mention, or named unrecognisably, is shielded. A dropped name must never silently
    /// become an open app.
    static func parse(_ content: String, candidates: [Candidate]) -> Decision? {
        var text = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("```") {
            if let newline = text.firstIndex(of: "\n") {
                text = String(text[text.index(after: newline)...])
            } else {
                text = ""
            }
            if text.hasSuffix("```") { text = String(text.dropLast(3)) }
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }

        let allowNames = (obj["allow"] as? [String]) ?? []
        let reasoning = (obj["reasoning"] as? String) ?? ""

        // Normalised, so casing or punctuation differences don't shield something needlessly.
        let allowKeys = Set(allowNames.map(normalise))
        var shield: [String] = []
        var allow: [String] = []
        for candidate in candidates {
            if allowKeys.contains(normalise(candidate.describedLabel))
                || allowKeys.contains(normalise(candidate.label)) {
                allow.append(candidate.token)
            } else {
                shield.append(candidate.token)
            }
        }

        return Decision(shield: shield, allow: allow,
                        reasoning: reasoning.isEmpty
                            ? "No reasoning given." : reasoning,
                        isFallback: false)
    }

    private static func normalise(_ s: String) -> String {
        s.lowercased().filter { $0.isLetter || $0.isNumber }
    }

    // MARK: - Entry point

    /// Never throws and never returns nil: a session must always be startable, model or no
    /// model.
    static func decide(task: String, candidates: [Candidate], config: Providers.Config,
                       extraNotes: String = "") async -> Decision {
        guard !candidates.isEmpty else {
            return Decision(shield: [], allow: [], reasoning: "No apps were offered.",
                            isFallback: false)
        }
        guard !config.model.isEmpty, !config.baseUrl.isEmpty else {
            return Fallback.plan(candidates, why: "no model is configured yet")
        }

        let user = userPrompt(task: task, candidates: candidates, extraNotes: extraNotes)
        let answer = await Providers.completeText(config, system: system, user: user)

        switch answer {
        case .success(let text):
            if let decision = parse(text, candidates: candidates) {
                return decision
            }
            return Fallback.plan(candidates, why: "the model's answer couldn't be read")
        case .failure(let problem):
            return Fallback.plan(candidates, why: problem)
        }
    }
}
