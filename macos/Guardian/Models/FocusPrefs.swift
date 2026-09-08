import Foundation

/// Focus-mode settings, kept as an extension so `Prefs.swift` stays the content-rules original and
/// the two concerns don't tangle.
///
/// These are UserDefaults-backed computed properties rather than `@Published` stored ones, because
/// an extension cannot add stored properties. Views observe `Prefs` and get updates because every
/// setter below announces `objectWillChange` *before* mutating — which is what the name says and
/// what SwiftUI's diffing expects. (`Prefs.swift`'s Keychain-backed properties announce after; that
/// happens to work because SwiftUI re-reads on the next runloop pass, but it isn't the contract, so
/// the new code doesn't copy it.)
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
    // Stored as a preset id plus optional overrides rather than a free-form blob: the preset gives
    // a first-run user a working default in one click, the overrides let a power user point at a
    // gateway we have never heard of.

    var providerId: String {
        get { defaults.string(forKey: FK.providerId) ?? "ollama-cloud" }
        set {
            guard let preset = Providers.preset(id: newValue) else { return }
            objectWillChange.send()
            defaults.set(newValue, forKey: FK.providerId)
            // Switching provider rewrites URL + model to that preset's defaults. Carrying an Ollama
            // model name over to Anthropic just produces a 404 forty minutes later.
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

    /// Snapshot for the monitor task. Keys are omitted entirely for a local provider, so a cloud
    /// key can never be accidentally sent to `127.0.0.1`.
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

    /// Prefilled into the start form — most sessions are a continuation of the last one.
    var lastTask: String {
        get { defaults.string(forKey: FK.focusTask) ?? "" }
        set {
            objectWillChange.send()
            let cleaned = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            defaults.set(String(cleaned.prefix(400)), forKey: FK.focusTask)
        }
    }

    /// Standing notes appended to every check — "my course PDFs open in Safari", that sort of
    /// thing. Hand-written; the learner writes to a separate file and never edits this.
    var focusNotes: String {
        get { defaults.string(forKey: FK.focusNotes) ?? "" }
        set {
            objectWillChange.send()
            defaults.set(String(newValue.prefix(1500)), forKey: FK.focusNotes)
        }
    }

    /// The original always-on content classifier, kept as an opt-in extra layer. Off by default:
    /// this is a focus tool now, and running both classifiers doubles the cost of every check.
    var contentRulesEnabled: Bool {
        get { defaults.bool(forKey: FK.contentRules) }
        set {
            objectWillChange.send()
            defaults.set(newValue, forKey: FK.contentRules)
        }
    }

    /// Experimental: capture "that was a false alarm" feedback and apply the learned policy. Off by
    /// default, because a self-control tool that learns from you can be taught to stop stopping
    /// you — see `learner/README.md` for the anti-gaming design.
    var learningEnabled: Bool {
        get { defaults.bool(forKey: FK.learning) }
        set {
            objectWillChange.send()
            defaults.set(newValue, forKey: FK.learning)
        }
    }
}
