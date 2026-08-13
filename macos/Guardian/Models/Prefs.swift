import CryptoKit
import Foundation

/// All configuration lives in UserDefaults; secrets (Ollama key, ntfy topic, PIN hash) live in the
/// macOS Keychain. Mirrors the Android `Prefs` (which used EncryptedSharedPreferences).
///
/// `ObservableObject` so SwiftUI views update live.
@MainActor
final class Prefs: ObservableObject {

    static let shared = Prefs()
    private let d = UserDefaults.standard

    // MARK: - Monitored apps (set of bundle identifiers)
    @Published var monitoredApps: Set<String> { didSet { d.set(Array(monitoredApps), forKey: K.monitored) } }

    // MARK: - Guidelines fed to the model
    @Published var guidelines: String { didSet { d.set(guidelines, forKey: K.guidelines) } }

    // MARK: - Blocking behaviour
    /// "hide" (send the app to the background — escapable) or "quit" (terminate the offending app).
    @Published var blockMode: String { didSet { d.set(blockMode, forKey: K.blockMode) } }

    /// Test/dry-run mode: evaluate + log verdicts but NEVER hide/quit anything. Default ON.
    @Published var dryRun: Bool { didSet { d.set(dryRun, forKey: K.dryRun) } }

    /// Push the accountability contact + log when a monitored app's screen can't be verified
    /// (capture failure, blank frame, or the AI being unreachable). Never quits. Default ON.
    @Published var alertOnUnverifiable: Bool { didSet { d.set(alertOnUnverifiable, forKey: K.alertUnver) } }

    /// Additionally hide the app when its screen can't be verified. Default OFF.
    @Published var closeUnverifiable: Bool { didSet { d.set(closeUnverifiable, forKey: K.closeUnver) } }

    // MARK: - Push notifications (ntfy — zero-setup alerts)
    @Published var ntfyServer: String { didSet { d.set(ntfyServer, forKey: K.ntfyServer) } }
    @Published var pushEnabled: Bool { didSet { d.set(pushEnabled, forKey: K.pushEnabled) } }

    /// Private alert code (ntfy topic). Auto-generated once; acts as a secret, so keep it private.
    var ntfyTopic: String {
        get {
            if let t = Keychain.get(K.ntfyTopic), !t.isEmpty { return t }
            let gen = "guardian-" + Self.randomToken(12)
            Keychain.set(K.ntfyTopic, gen)
            return gen
        }
        set { Keychain.set(K.ntfyTopic, newValue) }
    }

    // MARK: - Ollama Cloud
    @Published var ollamaBaseUrl: String { didSet { d.set(ollamaBaseUrl, forKey: K.ollamaUrl) } }
    @Published var ollamaModel: String { didSet { d.set(ollamaModel, forKey: K.ollamaModel) } }
    /// Secret — stored in Keychain, not UserDefaults.
    var ollamaApiKey: String {
        get { Keychain.get(K.ollamaKey) ?? "" }
        set { Keychain.set(K.ollamaKey, newValue); objectWillChange.send() }
    }

    /// Backup key. When the active key runs out of quota (or is rejected) `OllamaClient` falls over
    /// to the other one and `activeApiKeySlot` remembers the switch — so the two keys alternate as
    /// each is exhausted, rather than one being tried first forever.
    var ollamaApiKey2: String {
        get { Keychain.get(K.ollamaKey2) ?? "" }
        set { Keychain.set(K.ollamaKey2, newValue); objectWillChange.send() }
    }

    /// Which key is currently preferred: 0 = `ollamaApiKey`, 1 = `ollamaApiKey2`.
    var activeApiKeySlot: Int {
        get { min(max(d.integer(forKey: K.ollamaKeySlot), 0), 1) }
        set { d.set(min(max(newValue, 0), 1), forKey: K.ollamaKeySlot) }
    }

    /// The configured keys, active one first, blanks and duplicates removed. The client walks this
    /// list: the first key that isn't out of quota answers the request.
    var apiKeys: [String] {
        let slots = [ollamaApiKey.trimmed(), ollamaApiKey2.trimmed()]
        let ordered = activeApiKeySlot == 1 ? slots.reversed().map { $0 } : slots
        var seen = Set<String>()
        return ordered.filter { !$0.isEmpty && seen.insert($0).inserted }
    }

    /// Remember that `key` is the one currently working, so the next request starts there.
    func promoteApiKey(_ key: String) {
        let slot: Int
        switch key {
        case ollamaApiKey.trimmed(): slot = 0
        case ollamaApiKey2.trimmed(): slot = 1
        default: return
        }
        if activeApiKeySlot != slot { activeApiKeySlot = slot }
    }

    // MARK: - Access / override PIN (SHA-256 hash kept in Keychain)
    /// Gates opening Guardian AND dismissing a violation block screen. Optional — when unset, the
    /// app opens freely and a block screen can be dismissed with a plain button.
    var pinSet: Bool { Keychain.get(K.pin) != nil }
    func setPin(_ pin: String) { Keychain.set(K.pin, Self.sha256(pin)); objectWillChange.send() }
    func clearPin() { Keychain.delete(K.pin); objectWillChange.send() }
    func checkPin(_ pin: String) -> Bool {
        guard let h = Keychain.get(K.pin) else { return false }
        return h == Self.sha256(pin)
    }

    static func sha256(_ s: String) -> String {
        SHA256.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    // MARK: - Tamper resistance
    /// Show the pledge overlay whenever System Settings is brought frontmost.
    @Published var pledgeOnSettings: Bool { didSet { d.set(pledgeOnSettings, forKey: K.pledge) } }

    /// Last-known state of the Screen Recording (TCC) grant. The tamper guard compares against this
    /// so revoking it — the way monitoring is defeated on macOS — is detected and reported instead
    /// of failing silently.
    @Published var screenRecordingGranted: Bool { didSet { d.set(screenRecordingGranted, forKey: K.scrGranted) } }

    /// Keep Guardian running at login (persistence, so quitting/killing it isn't a lasting bypass).
    @Published var relaunchAtLogin: Bool { didSet { d.set(relaunchAtLogin, forKey: K.relaunch) } }

    /// Stronger persistence: a KeepAlive LaunchAgent that relaunches Guardian within ~10s of ANY
    /// exit (Quit / force-quit / crash), not just at login. Supersedes [relaunchAtLogin] when on.
    /// Defaults ON — quitting Guardian is a bypass, so the app resists it out of the box; turn it
    /// off from Settings ▸ Tamper resistance (behind the passcode) before quitting legitimately.
    @Published var keepAlive: Bool { didSet { d.set(keepAlive, forKey: K.keepAlive) } }

    // MARK: - Safety covenant (self-binding: make weakening the safeguards visible, not silent)
    /// Longest the guidelines have ever been; a big drop below this means they were gutted.
    @Published var guidelinesPeakLen: Int { didSet { d.set(guidelinesPeakLen, forKey: K.covPeak) } }
    /// True once monitoring has been armed (dry-run turned off) at least once.
    @Published var everArmed: Bool { didSet { d.set(everArmed, forKey: K.covArmed) } }

    // MARK: - Runtime state
    @Published var monitoringEnabled: Bool { didSet { d.set(monitoringEnabled, forKey: K.enabled) } }
    var lastViolationAt: Date? {
        get { (d.object(forKey: K.lastVio) as? Double).map { Date(timeIntervalSince1970: $0) } }
        set { d.set(newValue?.timeIntervalSince1970, forKey: K.lastVio) }
    }

    // MARK: - Init (hydrate from storage with defaults)

    private init() {
        let dd = UserDefaults.standard
        monitoredApps = Set(dd.stringArray(forKey: K.monitored) ?? [])
        guidelines = dd.string(forKey: K.guidelines) ?? Self.defaultGuidelines
        blockMode = dd.string(forKey: K.blockMode) ?? "hide"
        dryRun = dd.object(forKey: K.dryRun) as? Bool ?? true
        alertOnUnverifiable = dd.object(forKey: K.alertUnver) as? Bool ?? true
        closeUnverifiable = dd.object(forKey: K.closeUnver) as? Bool ?? false
        ntfyServer = dd.string(forKey: K.ntfyServer) ?? "https://ntfy.sh"
        pushEnabled = dd.object(forKey: K.pushEnabled) as? Bool ?? true
        ollamaBaseUrl = dd.string(forKey: K.ollamaUrl) ?? "https://ollama.com"
        ollamaModel = dd.string(forKey: K.ollamaModel) ?? Self.defaultModel
        monitoringEnabled = dd.object(forKey: K.enabled) as? Bool ?? false
        pledgeOnSettings = dd.object(forKey: K.pledge) as? Bool ?? true
        screenRecordingGranted = dd.object(forKey: K.scrGranted) as? Bool ?? false
        relaunchAtLogin = dd.object(forKey: K.relaunch) as? Bool ?? true
        keepAlive = dd.object(forKey: K.keepAlive) as? Bool ?? true
        guidelinesPeakLen = dd.integer(forKey: K.covPeak)
        everArmed = dd.object(forKey: K.covArmed) as? Bool ?? false

        // Remember once we've ever been armed, so the covenant can notice a later revert to TEST mode.
        if !dryRun { everArmed = true }
    }

    // MARK: - Keys

    private enum K {
        static let monitored = "monitored_apps"
        static let guidelines = "guidelines"
        static let blockMode = "block_mode"
        static let dryRun = "dry_run"
        static let alertUnver = "alert_unverifiable"
        static let closeUnver = "close_unverifiable"
        static let ntfyServer = "ntfy_server"
        static let ntfyTopic = "ntfy_topic"          // keychain
        static let pushEnabled = "push_enabled"
        static let ollamaUrl = "ollama_url"
        static let ollamaModel = "ollama_model"
        static let ollamaKey = "ollama_key"           // keychain
        static let ollamaKey2 = "ollama_key2"         // keychain
        static let ollamaKeySlot = "ollama_key_slot"
        static let pin = "pin_hash"                    // keychain
        static let enabled = "monitoring_enabled"
        static let lastVio = "last_violation_at"
        static let pledge = "pledge_on_settings"
        static let scrGranted = "screen_recording_granted"
        static let relaunch = "relaunch_at_login"
        static let keepAlive = "keep_alive_agent"
        static let covPeak = "covenant_guidelines_peak_len"
        static let covArmed = "covenant_ever_armed"
    }

    // Vision-capable Gemma 4 hosted on Ollama Cloud (multimodal, 256K context).
    static let defaultModel = "gemma4:31b-cloud"

    static let defaultGuidelines = """
        Prohibited content — anything sexual or sexually suggestive:
        - Pornography and sexually explicit imagery or acts.
        - Real nudity OR partial nudity.
        - Women or men in underwear, lingerie, bikinis, or swimwear.
        - Exposed or emphasised skin in sensual areas: cleavage, breasts, midriff, buttocks, crotch,
          or bare thighs; see-through, wet, or tight clothing that sexualises the body.
        - Sexualised or provocative poses, or close-ups of intimate areas.
        - Any image a person could reasonably be aroused by or masturbate to.

        Also flag INTENT: if a search query, typed text, URL, or title shows the user is trying to
        find or view such imagery — including searching Google, Google Images, an image site, or
        YouTube for sexual / nude / "hot" / "sexy" / bikini / lingerie content — flag it and quote
        the text.

        Ordinary clothed people, fashion, art, and educational/medical content are not violations on
        their own — but when an image is borderline, it is treated as a violation rather than given
        the benefit of the doubt.
        """

    private static func randomToken(_ n: Int) -> String {
        let chars = Array("abcdefghijklmnopqrstuvwxyz0123456789")
        return String((0..<n).map { _ in chars.randomElement()! })
    }
}

private extension String {
    func trimmed() -> String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
