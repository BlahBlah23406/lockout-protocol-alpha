package com.lockoutprotocol.guardian.data

import android.content.Context
import com.lockoutprotocol.guardian.ai.ProviderKind
import com.lockoutprotocol.guardian.ai.Providers
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.FocusSession

/**
 * Focus-mode settings, as extension properties on [Prefs], so the focus feature is one file to
 * read and one file to remove. They use the same encrypted preferences file via the small
 * accessors added to `Prefs` for this purpose.
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

// A preset id plus optional overrides: the preset gives a working default in one tap, the
// overrides let someone point at a gateway we've never heard of.

var Prefs.providerId: String
    get() = getString(FocusKeys.PROVIDER_ID, "ollama-cloud")
    set(v) {
        val preset = Providers.preset(v) ?: return
        putString(FocusKeys.PROVIDER_ID, v)
        // An Ollama model name carried over to Anthropic just 404s later.
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

/** Keys are omitted for a provider that doesn't need one, so a cloud key is never posted to a
 *  machine on the local network. */
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

/** Prefilled into the start screen and the widget. */
var Prefs.lastTask: String
    get() = getString(FocusKeys.FOCUS_TASK, "")
    set(v) = putString(FocusKeys.FOCUS_TASK, v.trim().take(400))

/** Standing notes appended to every check. Hand-written; the learner writes elsewhere. */
var Prefs.focusNotes: String
    get() = getString(FocusKeys.FOCUS_NOTES, "")
    set(v) = putString(FocusKeys.FOCUS_NOTES, v.take(1500))

/** The original content classifier, opt-in. Running both doubles the cost of a check. */
var Prefs.contentRulesEnabled: Boolean
    get() = getBool(FocusKeys.CONTENT_RULES, false)
    set(v) = putBool(FocusKeys.CONTENT_RULES, v)

/**
 * Experimental. Off by default: a self-control tool that learns from you can be taught to stop
 * stopping you. See `learner/README.md` for the anti-gaming design.
 */
var Prefs.learningEnabled: Boolean
    get() = getBool(FocusKeys.LEARNING, false)
    set(v) = putBool(FocusKeys.LEARNING, v)
