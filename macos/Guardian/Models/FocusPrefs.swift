import Foundation

/// Focus-mode settings, as an extension so `Prefs.swift` stays the content-rules original.
///
/// UserDefaults-backed computed properties rather than `@Published` stored ones, because an
/// extension cannot add stored properties. Every setter announces `objectWillChange` before
/// mutating, which is what the name says and what SwiftUI expects.
extension Prefs {

    enum FK {
        static let providerId = "provider_id"
        static let providerUrl = "provider_base_url"
        static let providerModel = "provider_model"
        static let focusInterval = "focus_default_interval"
        static let focusAcc = "focus_default_accountability"
        static let focusMinutes = "focus_default_minutes"
        static let focusTask = "focus_last_task"
        static let focusNotes = "focus_extra_notes"
        static let contentRules = "content_rules_enabled"
        static let learning = "learning_enabled"
    }

    private var defaults: UserDefaults { .standard }

    // MARK: - Provider
    //
    // A preset id plus optional overrides: the preset gives a working default in one click, the
    // overrides let someone point at a gateway we've never heard of.

    var providerId: String {
        get { defaults.string(forKey: FK.providerId) ?? "ollama-cloud" }
        set {
            guard let preset = Providers.preset(id: newValue) else { return }
            objectWillChange.send()
            defaults.set(newValue, forKey: FK.providerId)
            // An Ollama model name carried over to Anthropic just 404s later.
            defaults.set(preset.baseUrl, forKey: FK.providerUrl)
            defaults.set(preset.model, forKey: FK.providerModel)
        }
    }

    var providerBaseUrl: String {
        get {
            defaults.string(forKey: FK.providerUrl) ?? Providers.preset(id: providerId)?.baseUrl ?? ""
        }
        set {
            objectWillChange.send()
            defaults.set(newValue.trimmingCharacters(in: .whitespaces), forKey: FK.providerUrl)
        }
    }

    var providerModel: String {
        get {
            defaults.string(forKey: FK.providerModel) ?? Providers.preset(id: providerId)?.model ?? ""
        }
        set {
            objectWillChange.send()
            defaults.set(newValue.trimmingCharacters(in: .whitespaces), forKey: FK.providerModel)
        }
    }

    var providerNeedsKey: Bool { Providers.preset(id: providerId)?.needsKey ?? false }

    /// Keys are omitted for a local provider, so a cloud key is never sent to `127.0.0.1`.
    func providerConfig() -> Providers.Config {
        let preset = Providers.preset(id: providerId) ?? Providers.presets[0]
        let keys = (preset.needsKey || providerId == "custom") ? apiKeys : []
        return Providers.Config(kind: preset.kind, baseUrl: providerBaseUrl,
                                model: providerModel, apiKeys: keys, label: preset.label)
    }

    // MARK: - Focus session defaults

    var focusInterval: Int {
        get {
            let stored = defaults.integer(forKey: FK.focusInterval)
            return FocusSession.clampInterval(stored == 0 ? FocusSession.defaultInterval : stored)
        }
        set {
            objectWillChange.send()
            defaults.set(FocusSession.clampInterval(newValue), forKey: FK.focusInterval)
        }
    }

    var focusAccountability: Accountability {
        get { Accountability(rawValue: defaults.string(forKey: FK.focusAcc) ?? "") ?? .selfManaged }
        set {
            objectWillChange.send()
            defaults.set(newValue.rawValue, forKey: FK.focusAcc)
        }
    }

    var focusMinutes: Int {
        get {
            // `integer(forKey:)` returns 0 both for "unset" and for a deliberate open-ended 0, so
            // the presence of the key is what distinguishes them.
            guard defaults.object(forKey: FK.focusMinutes) != nil else { return 60 }
            return max(defaults.integer(forKey: FK.focusMinutes), 0)
        }
        set {
            objectWillChange.send()
            defaults.set(max(newValue, 0), forKey: FK.focusMinutes)
        }
    }

    /// Prefilled into the start form.
    var lastTask: String {
        get { defaults.string(forKey: FK.focusTask) ?? "" }
        set {
            objectWillChange.send()
            let cleaned = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            defaults.set(String(cleaned.prefix(400)), forKey: FK.focusTask)
        }
    }

    /// Standing notes appended to every check. Hand-written; the learner writes elsewhere.
    var focusNotes: String {
        get { defaults.string(forKey: FK.focusNotes) ?? "" }
        set {
            objectWillChange.send()
            defaults.set(String(newValue.prefix(1500)), forKey: FK.focusNotes)
        }
    }

    /// The original content classifier, opt-in. Running both doubles the cost of a check.
    var contentRulesEnabled: Bool {
        get { defaults.bool(forKey: FK.contentRules) }
        set {
            objectWillChange.send()
            defaults.set(newValue, forKey: FK.contentRules)
        }
    }

    /// Experimental. Off by default: a self-control tool that learns from you can be taught to
    /// stop stopping you. See `learner/README.md` for the anti-gaming design.
    var learningEnabled: Bool {
        get { defaults.bool(forKey: FK.learning) }
        set {
            objectWillChange.send()
            defaults.set(newValue, forKey: FK.learning)
        }
    }
}
