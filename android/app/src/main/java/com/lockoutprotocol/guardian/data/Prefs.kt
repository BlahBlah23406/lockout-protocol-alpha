package com.lockoutprotocol.guardian.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.security.MessageDigest

/**
 * All configuration + secrets live in an encrypted preferences file.
 * Nothing here is readable without the device keystore.
 */
class Prefs private constructor(private val sp: SharedPreferences) {

    // ---- PIN ----
    var pinHash: String?
        get() = sp.getString(K_PIN, null)
        set(v) = sp.edit().putString(K_PIN, v).apply()

    fun setPin(pin: String) { pinHash = sha256(pin) }
    fun checkPin(pin: String): Boolean = pinHash != null && pinHash == sha256(pin)
    fun clearPin() { pinHash = null }
    val pinSet: Boolean get() = pinHash != null

    // ---- Monitored apps (set of package names) ----
    var monitoredPackages: Set<String>
        get() = sp.getStringSet(K_PKGS, emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet(K_PKGS, v).apply()

    // ---- Locked apps (set of package names) ----
    var lockedPackages: Set<String>
        get() = sp.getStringSet(K_LOCKED, emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet(K_LOCKED, v).apply()

    /**
     * Baseline of user-launchable packages we've already "seen". Used to auto-enroll newly
     * installed apps into [monitoredPackages]: any package present now but not in here is a new
     * install and gets added to monitoring. Removing an app from monitoring requires unlocking
     * Guardian (the whole app is behind the passcode gate), so a fresh install can't dodge it.
     */
    var knownPackages: Set<String>
        get() = sp.getStringSet(K_KNOWN, emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet(K_KNOWN, v).apply()

    /**
     * One-time flag: the first run records the current app list as the baseline WITHOUT
     * auto-monitoring everything already installed (those stay user-managed via the picker).
     * Only apps installed after the baseline are auto-enrolled.
     */
    var autoMonitorBaselineDone: Boolean
        get() = sp.getBoolean(K_AUTO_BASE, false)
        set(v) = sp.edit().putBoolean(K_AUTO_BASE, v).apply()

    // ---- Guidelines text fed to the model ----
    var guidelines: String
        get() = sp.getString(K_GUIDE, DEFAULT_GUIDELINES) ?: DEFAULT_GUIDELINES
        set(v) = sp.edit().putString(K_GUIDE, v).apply()

    // ---- Blocking behaviour ----
    var blockMode: String   // "overlay" | "close"
        get() = sp.getString(K_BLOCK, "overlay") ?: "overlay"
        set(v) = sp.edit().putString(K_BLOCK, v).apply()

    /**
     * Fail closed when content can't be seen at all (FLAG_SECURE black frame / capture failure).
     * Default OFF — when on, an always-on monitor can lock you out of your own phone because
     * many normal/system screens read as "unreadable".
     */
    var blockWhenUnreadable: Boolean
        get() = sp.getBoolean(K_BLK_UNREAD, false)
        set(v) = sp.edit().putBoolean(K_BLK_UNREAD, v).apply()

    /** Fail closed when the AI couldn't be reached or its answer couldn't be parsed. Default OFF. */
    var blockWhenUndetermined: Boolean
        get() = sp.getBoolean(K_BLK_UNDET, false)
        set(v) = sp.edit().putBoolean(K_BLK_UNDET, v).apply()

    /**
     * When a monitored app's screen can't be verified (incognito / FLAG_SECURE black frame,
     * capture failure, or the AI being unreachable) — email the accountability contact + log it.
     * This is the SAFE way to catch incognito: it never shows a PIN-locked overlay, so it cannot
     * lock you out of your phone. Default ON.
     */
    var alertOnUnverifiable: Boolean
        get() = sp.getBoolean(K_ALERT_UNVER, true)
        set(v) = sp.edit().putBoolean(K_ALERT_UNVER, v).apply()

    /**
     * Also push the accountability contact for MILD/incidental flags (a swimwear ad, a thumbnail
     * scrolled past) — the ones that produce most of the false positives. Default OFF: those still
     * block and are still logged, they just don't notify. Deliberate flags (tampering, a search, a
     * site for it, explicit content on screen) ALWAYS notify and cannot be silenced from here —
     * see [com.lockoutprotocol.guardian.ai.AlertPolicy].
     */
    var alertOnSuggestive: Boolean
        get() = sp.getBoolean(K_ALERT_SUGG, false)
        set(v) = sp.edit().putBoolean(K_ALERT_SUGG, v).apply()

    /** Additionally send the user Home (escapable nudge) when a monitored app can't be seen. Default OFF. */
    var closeUnverifiable: Boolean
        get() = sp.getBoolean(K_CLOSE_UNVER, false)
        set(v) = sp.edit().putBoolean(K_CLOSE_UNVER, v).apply()

    // ---- Safety covenant (self-binding: make weakening the safeguards visible, not silent) ----
    /** Longest the guidelines have ever been. If they shrink far below this, they were gutted. */
    var guidelinesPeakLen: Int
        get() = sp.getInt(K_COV_PEAK, 0)
        set(v) = sp.edit().putInt(K_COV_PEAK, v).apply()

    /** True once monitoring has been armed (dry-run turned off) at least once. */
    var everArmed: Boolean
        get() = sp.getBoolean(K_COV_ARMED, false)
        set(v) = sp.edit().putBoolean(K_COV_ARMED, v).apply()

    /**
     * Test/dry-run mode: evaluate + log + toast verdicts but NEVER block or lock. Default ON so
     * the app can't lock you out until you've watched the log and deliberately armed it.
     */
    var dryRun: Boolean
        get() = sp.getBoolean(K_DRY_RUN, true)
        set(v) = sp.edit().putBoolean(K_DRY_RUN, v).apply()

    // ---- Push notifications (ntfy — zero-setup alerts) ----
    var ntfyServer: String
        get() = sp.getString(K_NTFY_SRV, "https://ntfy.sh") ?: "https://ntfy.sh"
        set(v) = sp.edit().putString(K_NTFY_SRV, v).apply()

    /** Private alert code (ntfy topic). Auto-generated once; acts as a secret, so keep it private. */
    var ntfyTopic: String
        get() {
            val t = sp.getString(K_NTFY_TOPIC, "") ?: ""
            if (t.isNotBlank()) return t
            val gen = "guardian-" + randomToken(12)
            ntfyTopic = gen
            return gen
        }
        set(v) = sp.edit().putString(K_NTFY_TOPIC, v).apply()

    var pushEnabled: Boolean
        get() = sp.getBoolean(K_PUSH_ON, true)
        set(v) = sp.edit().putBoolean(K_PUSH_ON, v).apply()

    // ---- Ollama Cloud ----
    var ollamaBaseUrl: String
        get() = sp.getString(K_OL_URL, "https://ollama.com") ?: "https://ollama.com"
        set(v) = sp.edit().putString(K_OL_URL, v).apply()
    var ollamaApiKey: String
        get() = sp.getString(K_OL_KEY, "") ?: ""
        set(v) = sp.edit().putString(K_OL_KEY, v).apply()

    /** Backup key. When the active key runs out of quota (or is rejected) the client falls over to
     *  the other one and [activeApiKeySlot] remembers the switch — so the two keys alternate as each
     *  is exhausted, rather than one being tried first forever. */
    var ollamaApiKey2: String
        get() = sp.getString(K_OL_KEY2, "") ?: ""
        set(v) = sp.edit().putString(K_OL_KEY2, v).apply()

    /** Which key is currently preferred: 0 = [ollamaApiKey], 1 = [ollamaApiKey2]. */
    var activeApiKeySlot: Int
        get() = sp.getInt(K_OL_KEY_SLOT, 0).coerceIn(0, 1)
        set(v) = sp.edit().putInt(K_OL_KEY_SLOT, v.coerceIn(0, 1)).apply()

    /**
     * The configured keys, active one first, blanks and duplicates removed. The client walks this
     * list: the first key that isn't out of quota answers the request.
     */
    val apiKeys: List<String>
        get() {
            val slots = listOf(ollamaApiKey.trim(), ollamaApiKey2.trim())
            val ordered = if (activeApiKeySlot == 1) slots.asReversed() else slots
            return ordered.filter { it.isNotBlank() }.distinct()
        }

    /** Remember that [key] is the one currently working, so the next request starts there. */
    fun promoteApiKey(key: String) {
        val slot = when (key) {
            ollamaApiKey.trim() -> 0
            ollamaApiKey2.trim() -> 1
            else -> return
        }
        if (activeApiKeySlot != slot) activeApiKeySlot = slot
    }

    var ollamaModel: String
        get() = sp.getString(K_OL_MODEL, DEFAULT_MODEL) ?: DEFAULT_MODEL
        set(v) = sp.edit().putString(K_OL_MODEL, v).apply()

    // ---- Heartbeat (optional tamper server) ----
    var heartbeatUrl: String get() = sp.getString(K_HB_URL, "") ?: ""
        set(v) = sp.edit().putString(K_HB_URL, v).apply()

    // ---- Runtime state ----
    var monitoringEnabled: Boolean get() = sp.getBoolean(K_ENABLED, false)
        set(v) = sp.edit().putBoolean(K_ENABLED, v).apply()
    var lastViolationAt: Long get() = sp.getLong(K_LASTVIO, 0)
        set(v) = sp.edit().putLong(K_LASTVIO, v).apply()

    // ---- Tamper resistance ----
    /**
     * Last-known state of Guardian's accessibility access. The heartbeat + service teardown compare
     * against this so a silent "accessibility turned off" (the way monitoring was defeated before)
     * is detected and reported to the accountability contact instead of failing quietly.
     */
    var accessibilityGranted: Boolean get() = sp.getBoolean(K_A11Y_GRANTED, false)
        set(v) = sp.edit().putBoolean(K_A11Y_GRANTED, v).apply()

    /** Show the pledge overlay whenever the system Settings app is opened. Default ON. */
    var pledgeOnSettings: Boolean get() = sp.getBoolean(K_PLEDGE, true)
        set(v) = sp.edit().putBoolean(K_PLEDGE, v).apply()

    /**
     * Self-guard: while accessibility is still on, detect the specific Settings screens used to
     * disable Guardian (its accessibility toggle, its App-info / force-stop / uninstall page) and
     * bounce out + alert. Only targets Guardian's own screens, so the rest of Settings stays usable.
     * Default ON.
     */
    var guardSelf: Boolean get() = sp.getBoolean(K_GUARD_SELF, true)
        set(v) = sp.edit().putBoolean(K_GUARD_SELF, v).apply()

    companion object {
        private const val FILE = "guardian_secure_prefs"
        private const val K_PIN = "pin_hash"
        private const val K_PKGS = "monitored_pkgs"
        private const val K_LOCKED = "locked_pkgs"
        private const val K_KNOWN = "known_pkgs"
        private const val K_AUTO_BASE = "auto_monitor_baseline_done"
        private const val K_GUIDE = "guidelines"
        private const val K_BLOCK = "block_mode"
        private const val K_BLK_UNREAD = "block_unreadable"
        private const val K_BLK_UNDET = "block_undetermined"
        private const val K_ALERT_UNVER = "alert_unverifiable"
        private const val K_ALERT_SUGG = "alert_suggestive"
        private const val K_CLOSE_UNVER = "close_unverifiable"
        private const val K_COV_PEAK = "covenant_guidelines_peak_len"
        private const val K_COV_ARMED = "covenant_ever_armed"
        private const val K_DRY_RUN = "dry_run"
        private const val K_NTFY_SRV = "ntfy_server"
        private const val K_NTFY_TOPIC = "ntfy_topic"
        private const val K_PUSH_ON = "push_enabled"

        private fun randomToken(n: Int): String {
            val chars = "abcdefghijklmnopqrstuvwxyz0123456789"
            return (1..n).map { chars.random() }.joinToString("")
        }
        private const val K_OL_URL = "ollama_url"
        private const val K_OL_KEY = "ollama_key"
        private const val K_OL_KEY2 = "ollama_key2"
        private const val K_OL_KEY_SLOT = "ollama_key_slot"
        private const val K_OL_MODEL = "ollama_model"
        // Vision-capable Gemma model hosted on Ollama Cloud.
        const val DEFAULT_MODEL = "gemma4:31b-cloud"

        private const val K_HB_URL = "hb_url"
        private const val K_ENABLED = "enabled"
        private const val K_LASTVIO = "last_violation"
        private const val K_A11Y_GRANTED = "a11y_granted"
        private const val K_PLEDGE = "pledge_on_settings"
        private const val K_GUARD_SELF = "guard_self"

        val DEFAULT_GUIDELINES = """
            Prohibited content — be STRICT. Flag anything sexual or sexually suggestive:
            - Pornography and sexually explicit imagery or acts.
            - Real nudity OR partial nudity.
            - Women or men in underwear, lingerie, bikinis, or swimwear.
            - Exposed or emphasised skin in sensual areas: cleavage, breasts, midriff, buttocks,
              crotch, or bare thighs; see-through, wet, or tight clothing that sexualises the body.
            - Sexualised or provocative poses, or close-ups of intimate areas.
            - Any image a person could reasonably be aroused by or masturbate to.

            Also flag INTENT: if a search query, typed text, URL, or title shows the user is trying
            to find or view such imagery — including searching Google, Google Images, an image site,
            or YouTube for sexual / nude / "hot" / "sexy" / bikini / lingerie content — flag it and
            quote the text.

            Only clearly innocent, non-sexual screens are allowed. When an image is even borderline
            sexual, treat it as a violation rather than giving the benefit of the doubt.
        """.trimIndent()

        @Volatile private var instance: Prefs? = null

        fun get(context: Context): Prefs = instance ?: synchronized(this) {
            instance ?: build(context.applicationContext).also { instance = it }
        }

        private fun build(ctx: Context): Prefs {
            val key = MasterKey.Builder(ctx)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            val sp = EncryptedSharedPreferences.create(
                ctx, FILE, key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
            return Prefs(sp)
        }

        fun sha256(s: String): String =
            MessageDigest.getInstance("SHA-256").digest(s.toByteArray())
                .joinToString("") { "%02x".format(it) }
    }
}
