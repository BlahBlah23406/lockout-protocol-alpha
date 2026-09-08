package com.lockoutprotocol.guardian.data

import android.content.Context
import com.lockoutprotocol.guardian.ai.ProviderKind
import com.lockoutprotocol.guardian.ai.Providers
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.FocusSession

/**
 * Focus-mode settings, as extension properties on [Prefs] so `Prefs.kt` stays the content-rules
 * original and the two concerns don't tangle.
 *
 * They read and write the same encrypted preferences file, via [Prefs.getString] / [Prefs.putString]
 * and friends — the small accessors added to `Prefs` for exactly this purpose. Keeping the keys
 * here rather than in `Prefs.kt` means the focus feature is one file to read and one file to
 * remove.
 */
object FocusKeys {
    const val PROVIDER_ID = "provider_id"
    const val PROVIDER_URL = "provider_base_url"
    const val PROVIDER_MODEL = "provider_model"
    const val FOCUS_INTERVAL = "focus_default_interval"
    const val FOCUS_ACC = "focus_default_accountability"
    const val FOCUS_MINUTES = "focus_default_minutes"
    const val FOCUS_TASK = "focus_last_task"
    const val FOCUS_NOTES = "focus_extra_notes"
    const val CONTENT_RULES = "content_rules_enabled"
    const val LEARNING = "learning_enabled"
}

// ---- Provider ------------------------------------------------------------------------------
//
// Stored as a preset id plus optional overrides rather than a free-form blob: the preset gives a
// first-run user a working default in one tap, the overrides let a power user point at a gateway
// we have never heard of.

var Prefs.providerId: String
    get() = getString(FocusKeys.PROVIDER_ID, "ollama-cloud")
    set(v) {
        val preset = Providers.preset(v) ?: return
        putString(FocusKeys.PROVIDER_ID, v)
        // Switching provider rewrites URL + model to that preset's defaults. Carrying an Ollama
        // model name over to Anthropic just produces a 404 forty minutes later.
        putString(FocusKeys.PROVIDER_URL, preset.baseUrl)
        putString(FocusKeys.PROVIDER_MODEL, preset.model)
    }

var Prefs.providerBaseUrl: String
    get() = getString(FocusKeys.PROVIDER_URL, Providers.preset(providerId)?.baseUrl ?: "")
    set(v) = putString(FocusKeys.PROVIDER_URL, v.trim())

var Prefs.providerModel: String
    get() = getString(FocusKeys.PROVIDER_MODEL, Providers.preset(providerId)?.model ?: "")
    set(v) = putString(FocusKeys.PROVIDER_MODEL, v.trim())

val Prefs.providerNeedsKey: Boolean
    get() = Providers.preset(providerId)?.needsKey ?: false

/**
 * Snapshot for the monitor coroutine. Keys are omitted entirely for a provider that doesn't need
 * one, so a cloud key can never be accidentally posted to a machine on the local network.
 */
fun Prefs.providerConfig(): Providers.Config {
    val preset = Providers.preset(providerId) ?: Providers.presets[0]
    val keys = if (preset.needsKey || providerId == "custom") apiKeys else emptyList()
    return Providers.Config(
        kind = preset.kind,
        baseUrl = providerBaseUrl,
        model = providerModel,
        apiKeys = keys,
        label = preset.label,
    )
}

// ---- Focus session defaults ----------------------------------------------------------------

var Prefs.focusInterval: Int
    get() = FocusSession.clampInterval(getInt(FocusKeys.FOCUS_INTERVAL, FocusSession.DEFAULT_INTERVAL))
    set(v) = putInt(FocusKeys.FOCUS_INTERVAL, FocusSession.clampInterval(v))

var Prefs.focusAccountability: Accountability
    get() = Accountability.from(getString(FocusKeys.FOCUS_ACC, Accountability.SELF.id))
    set(v) = putString(FocusKeys.FOCUS_ACC, v.id)

var Prefs.focusMinutes: Int
    get() = getInt(FocusKeys.FOCUS_MINUTES, 60).coerceAtLeast(0)
    set(v) = putInt(FocusKeys.FOCUS_MINUTES, v.coerceAtLeast(0))

/** Prefilled into the start screen and the widget — most sessions continue the last one. */
var Prefs.lastTask: String
    get() = getString(FocusKeys.FOCUS_TASK, "")
    set(v) = putString(FocusKeys.FOCUS_TASK, v.trim().take(400))

/**
 * Standing notes appended to every check — "my course PDFs open in Drive", that sort of thing.
 * Hand-written; the learner writes to a separate file and never edits this.
 */
var Prefs.focusNotes: String
    get() = getString(FocusKeys.FOCUS_NOTES, "")
    set(v) = putString(FocusKeys.FOCUS_NOTES, v.take(1500))

/**
 * The original always-on content classifier, kept as an opt-in extra layer. Off by default: this
 * is a focus tool now, and running both classifiers doubles the cost of every check.
 */
var Prefs.contentRulesEnabled: Boolean
    get() = getBool(FocusKeys.CONTENT_RULES, false)
    set(v) = putBool(FocusKeys.CONTENT_RULES, v)

/**
 * Experimental: capture "that was a false alarm" feedback and apply the learned policy. Off by
 * default, because a self-control tool that learns from you can be taught to stop stopping you —
 * see `learner/README.md` for the anti-gaming design.
 */
var Prefs.learningEnabled: Boolean
    get() = getBool(FocusKeys.LEARNING, false)
    set(v) = putBool(FocusKeys.LEARNING, v)
