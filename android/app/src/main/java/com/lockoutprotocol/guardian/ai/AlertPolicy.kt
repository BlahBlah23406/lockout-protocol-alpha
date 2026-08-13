package com.lockoutprotocol.guardian.ai

/**
 * ── GUARDIAN COVENANT ─────────────────────────────────────────────────────────────────────────
 * Decides which violations are worth waking the accountability contact.
 *
 * EVERY violation still blocks and is still written to the on-device activity log — this only
 * controls the push. The user's rule: notify when they were TAMPERING or DELIBERATELY looking
 * (searched for it, sat on a site for it, explicit content actually on screen); stay quiet for
 * the mild/incidental flags (a swimwear ad, a thumbnail they scrolled past) that were drowning
 * the real alerts in noise.
 *
 * [ALWAYS_ALERT] is deliberately NOT configurable — no setting can silence tampering, a search,
 * a porn site, or explicit content. Only "suggestive" is user-tunable. Do not widen the silent
 * set on a casual request. See SAFEGUARDS.md.
 * ──────────────────────────────────────────────────────────────────────────────────────────────
 */
object AlertPolicy {

    const val TAMPER = "tamper"
    const val SEARCH = "search"
    const val SITE = "site"
    const val EXPLICIT = "explicit"
    const val SUGGESTIVE = "suggestive"

    /** Deliberate acts. These ALWAYS push, regardless of settings. */
    val ALWAYS_ALERT = setOf(TAMPER, SEARCH, SITE, EXPLICIT)

    /** The full vocabulary the model is allowed to answer with. */
    val KNOWN = ALWAYS_ALERT + SUGGESTIVE

    /**
     * Map whatever the model wrote onto our vocabulary. Anything unrecognised comes back blank,
     * which [shouldAlert] treats as "alert anyway" — an unclassified violation must never be
     * silently swallowed.
     */
    fun normalize(raw: String?): String {
        val c = raw?.trim()?.lowercase().orEmpty()
        if (c.isEmpty()) return ""
        if (c in KNOWN) return c
        // Common near-misses from a model that didn't copy the label exactly.
        return when {
            c.startsWith("tamper") || c.contains("ollama") || c.contains("guardian") -> TAMPER
            c.contains("search") || c.contains("query") || c.contains("intent") -> SEARCH
            c.contains("site") || c.contains("website") || c.contains("porn") -> SITE
            c.contains("explicit") || c.contains("nudity") || c.contains("sexual_act") -> EXPLICIT
            c.contains("suggestive") || c.contains("mild") || c.contains("incidental") -> SUGGESTIVE
            else -> ""
        }
    }

    /**
     * Should this violation push the accountability contact?
     * @param category already run through [normalize]
     * @param alertOnSuggestive user setting; when false, mild/incidental flags block quietly.
     */
    fun shouldAlert(category: String, alertOnSuggestive: Boolean): Boolean = when {
        category in ALWAYS_ALERT -> true
        category == SUGGESTIVE -> alertOnSuggestive
        else -> true   // unknown/blank: we couldn't tell, so we tell.
    }

    /** Short human label for the activity log. */
    fun label(category: String): String = when (category) {
        TAMPER -> "tampering"
        SEARCH -> "searched for it"
        SITE -> "on a site for it"
        EXPLICIT -> "explicit on screen"
        SUGGESTIVE -> "suggestive"
        else -> "unclassified"
    }
}
