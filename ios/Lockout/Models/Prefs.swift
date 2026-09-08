import FamilyControls
import Foundation

/// Settings, in the App Group's `UserDefaults` so the extensions can read what they need.
///
/// Secrets are the exception: API keys and the passcode hash go in the Keychain with an access
/// group, not into shared defaults. A shared defaults plist is readable by anything in the group,
/// and while that is only our own three extensions today, a key sitting in a plist is a key
/// waiting to be somewhere it shouldn't.
@MainActor
final class Prefs: ObservableObject {

    static let shared = Prefs()

    private let d: UserDefaults

    private init() {
        // Falls back to `.standard` if the App Group is missing, so a misconfigured build still
        // runs and `ShieldController.diagnose()` can explain why nothing is shielded.
        d = UserDefaults(suiteName: SessionStore.appGroup) ?? .standard
    }

    private enum K {
        static let providerId = "provider_id"
        static let providerUrl = "provider_base_url"
        static let providerModel = "provider_model"
        static let focusInterval = "focus_default_interval"
        static let focusAcc = "focus_default_accountability"
        static let focusMinutes = "focus_default_minutes"
        static let focusTask = "focus_last_task"
        static let focusNotes = "focus_extra_notes"
        static let selection = "saved_selection"
        static let ntfyServer = "ntfy_server"
        static let pushEnabled = "push_enabled"
        static let keySlot = "api_key_slot"
    }

    // MARK: - Provider

    var providerId: String {
        get { d.string(forKey: K.providerId) ?? "ollama-cloud" }
        set {
            guard let preset = Providers.preset(id: newValue) else { return }
            objectWillChange.send()
            d.set(newValue, forKey: K.providerId)
            // Switching provider rewrites URL + model. Keeping an Ollama model name after moving
            // to Anthropic just produces a 404 at the worst moment.
            d.set(preset.baseUrl, forKey: K.providerUrl)
            d.set(preset.model, forKey: K.providerModel)
        }
    }

    var providerBaseUrl: String {
        get { d.string(forKey: K.providerUrl) ?? Providers.preset(id: providerId)?.baseUrl ?? "" }
        set { objectWillChange.send(); d.set(newValue.trimmingCharacters(in: .whitespaces),
                                             forKey: K.providerUrl) }
    }

    var providerModel: String {
        get { d.string(forKey: K.providerModel) ?? Providers.preset(id: providerId)?.model ?? "" }
        set { objectWillChange.send(); d.set(newValue.trimmingCharacters(in: .whitespaces),
                                             forKey: K.providerModel) }
    }

    /// Keys are omitted for a provider that doesn't need one, so a cloud key can never be posted
    /// to a machine on the local network.
    func providerConfig() -> Providers.Config {
        let preset = Providers.preset(id: providerId) ?? Providers.presets[0]
        let keys = (preset.needsKey || providerId == "custom") ? apiKeys : []
        return Providers.Config(kind: preset.kind, baseUrl: providerBaseUrl,
                                model: providerModel, apiKeys: keys, label: preset.label)
    }

    // MARK: - API keys (Keychain)

    var apiKey: String {
        get { Keychain.get("api_key") ?? "" }
        set { objectWillChange.send(); Keychain.set("api_key", newValue) }
    }

    /// Backup key. When the active one runs out of quota the client fails over and remembers the
    /// switch, so the two alternate as each is exhausted rather than one being tried forever.
    var apiKey2: String {
        get { Keychain.get("api_key2") ?? "" }
        set { objectWillChange.send(); Keychain.set("api_key2", newValue) }
    }

    var activeKeySlot: Int {
        get { min(max(d.integer(forKey: K.keySlot), 0), 1) }
        set { d.set(min(max(newValue, 0), 1), forKey: K.keySlot) }
    }

    var apiKeys: [String] {
        let slots = [apiKey.trimmingCharacters(in: .whitespaces),
                     apiKey2.trimmingCharacters(in: .whitespaces)]
        let ordered = activeKeySlot == 1 ? slots.reversed().map { $0 } : slots
        var seen = Set<String>()
        return ordered.filter { !$0.isEmpty && seen.insert($0).inserted }
    }

    func promoteApiKey(_ key: String) {
        let trimmed = key.trimmingCharacters(in: .whitespaces)
        let slot: Int
        if trimmed == apiKey.trimmingCharacters(in: .whitespaces) { slot = 0 }
        else if trimmed == apiKey2.trimmingCharacters(in: .whitespaces) { slot = 1 }
        else { return }
        if activeKeySlot != slot { activeKeySlot = slot }
    }

    // MARK: - Passcode

    var pinSet: Bool { Keychain.get("pin_hash") != nil }

    func setPin(_ pin: String) {
        objectWillChange.send()
        Keychain.set("pin_hash", Keychain.sha256(pin))
    }

    func clearPin() {
        objectWillChange.send()
        Keychain.delete("pin_hash")
    }

    func checkPin(_ pin: String) -> Bool {
        guard let stored = Keychain.get("pin_hash") else { return false }
        return stored == Keychain.sha256(pin)
    }

    // MARK: - Focus defaults

    var focusInterval: Int {
        get {
            let stored = d.integer(forKey: K.focusInterval)
            return FocusSession.clampInterval(stored == 0 ? FocusSession.defaultInterval : stored)
        }
        set { objectWillChange.send()
              d.set(FocusSession.clampInterval(newValue), forKey: K.focusInterval) }
    }

    var focusAccountability: Accountability {
        get { Accountability(rawValue: d.string(forKey: K.focusAcc) ?? "") ?? .selfManaged }
        set { objectWillChange.send(); d.set(newValue.rawValue, forKey: K.focusAcc) }
    }

    var focusMinutes: Int {
        get {
            // `integer(forKey:)` returns 0 for both "unset" and a deliberate open-ended 0, so the
            // presence of the key is what distinguishes them.
            guard d.object(forKey: K.focusMinutes) != nil else { return 50 }
            return max(d.integer(forKey: K.focusMinutes), 0)
        }
        set { objectWillChange.send(); d.set(max(newValue, 0), forKey: K.focusMinutes) }
    }

    var lastTask: String {
        get { d.string(forKey: K.focusTask) ?? "" }
        set {
            objectWillChange.send()
            let cleaned = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            d.set(String(cleaned.prefix(400)), forKey: K.focusTask)
        }
    }

    /// Standing notes handed to the model with every plan — "Notion is where my notes live", that
    /// sort of thing. On iOS these matter more than elsewhere, because app *names* are all the
    /// model gets to work with.
    var focusNotes: String {
        get { d.string(forKey: K.focusNotes) ?? "" }
        set { objectWillChange.send(); d.set(String(newValue.prefix(1500)), forKey: K.focusNotes) }
    }

    /// The app selection, remembered between sessions so the picker isn't a chore every time.
    /// `FamilyActivitySelection` is `Codable`, which is the only reason this is possible — the
    /// tokens inside it are otherwise opaque.
    var savedSelection: FamilyActivitySelection {
        get {
            guard let data = d.data(forKey: K.selection),
                  let decoded = try? JSONDecoder().decode(FamilyActivitySelection.self, from: data)
            else { return FamilyActivitySelection() }
            return decoded
        }
        set {
            objectWillChange.send()
            guard let data = try? JSONEncoder().encode(newValue) else { return }
            d.set(data, forKey: K.selection)
        }
    }

    // MARK: - Alerts

    var ntfyServer: String {
        get { d.string(forKey: K.ntfyServer) ?? "https://ntfy.sh" }
        set { objectWillChange.send(); d.set(newValue, forKey: K.ntfyServer) }
    }

    var pushEnabled: Bool {
        get { d.object(forKey: K.pushEnabled) == nil ? true : d.bool(forKey: K.pushEnabled) }
        set { objectWillChange.send(); d.set(newValue, forKey: K.pushEnabled) }
    }

    /// Private alert code. Generated once and treated as the secret it is — anyone who knows it
    /// can read your alerts.
    var ntfyTopic: String {
        get {
            if let existing = Keychain.get("ntfy_topic"), !existing.isEmpty { return existing }
            let generated = "lockout-" + Self.randomToken(12)
            Keychain.set("ntfy_topic", generated)
            return generated
        }
        set { objectWillChange.send(); Keychain.set("ntfy_topic", newValue) }
    }

    private static func randomToken(_ n: Int) -> String {
        let chars = Array("abcdefghijklmnopqrstuvwxyz0123456789")
        return String((0..<n).map { _ in chars.randomElement()! })
    }
}
