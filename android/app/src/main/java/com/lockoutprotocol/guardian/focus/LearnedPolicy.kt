package com.lockoutprotocol.guardian.focus

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.json.JSONObject

/**
 * Client side of the experimental false-alarm learner.
 *
 * The learner is offline Python at `learner/`; this reads the one artefact it produces and turns
 * it into extra prompt lines, a pre-allow, and a confidence threshold. The file is copied onto the
 * device by hand — see `learner/README.md`.
 *
 * Everything here fails soft: a missing, stale, corrupt or future-schema policy must leave the app
 * behaving exactly as it does with no learning at all.
 */
object LearnedPolicy {

    /** A policy claiming a newer schema is ignored rather than half-read: the parts we'd drop
     *  might be the safety limits. */
    private const val SUPPORTED_SCHEMA = 1

    /** The ceiling on how far learning may erode the monitor. It lives in the app so that
     *  hand-editing the generated file cannot lift it. */
    const val MAX_THRESHOLD = 0.85
    const val MAX_SUFFIX_CHARS = 1200
    private const val MAX_AGE_DAYS = 60L

    private const val FILE_NAME = "focus_policy.json"

    data class Decision(
        val promptSuffix: String = "",
        val preAllow: Boolean = false,
        val blockThreshold: Double = 0.0,
    )

    private var cachedModified: Long = -1
    private var cached: JSONObject? = null

    private fun file(ctx: Context) = File(ctx.filesDir, FILE_NAME)

    /** Read + cache the policy file, reloading only when it changes on disk. */
    @Synchronized
    fun load(ctx: Context): JSONObject? {
        val f = file(ctx)
        if (!f.exists()) {
            cachedModified = -1
            cached = null
            return null
        }
        val modified = f.lastModified()
        if (modified == cachedModified) return cached

        var data = runCatching { JSONObject(f.readText()) }.getOrNull()

        if (data != null && data.optInt("schema", -1) != SUPPORTED_SCHEMA) data = null
        // A policy learned two months ago describes a different person's week.
        if (data != null) {
            val generated = data.optDouble("generated_at", 0.0)
            val ageSeconds = System.currentTimeMillis() / 1000.0 - generated
            if (generated > 0 && ageSeconds > MAX_AGE_DAYS * 86_400) data = null
        }

        cachedModified = modified
        cached = data
        return data
    }

    /**
     * The one call the monitor makes. Always returns a usable value.
     *
     * The artefact carries a pre-expanded `decisions` map keyed by `"<task-phrasing>|<app>"`, so
     * every client is a string lookup rather than a reimplementation of the learner's clustering.
     */
    fun decide(ctx: Context, task: String, app: String, title: String = ""): Decision {
        val policy = load(ctx) ?: return Decision()
        val decisions = policy.optJSONObject("decisions") ?: return Decision()
        val entry = decisions.optJSONObject(lookupKey(task, app)) ?: return Decision()

        val suffix = entry.optString("prompt_suffix", "").take(MAX_SUFFIX_CHARS)
        val threshold = entry.optDouble("block_threshold", 0.0).coerceIn(0.0, MAX_THRESHOLD)
        var preAllow = entry.optBoolean("pre_allow", false)

        // An app-wide pre-allow with no title evidence would silently un-watch a whole app.
        if (preAllow) {
            val patterns = entry.optJSONArray("title_patterns")
            val count = patterns?.length() ?: 0
            preAllow = if (count == 0) {
                false
            } else {
                val lowered = title.lowercase()
                (0 until count).any { lowered.contains(patterns!!.optString(it).lowercase()) }
            }
        }

        return Decision(promptSuffix = suffix, preAllow = preAllow, blockThreshold = threshold)
    }

    fun promptSuffix(ctx: Context, task: String, app: String, title: String = ""): String =
        decide(ctx, task, app, title).promptSuffix

    /**
     * Must agree character for character with `learner/policy.py:lookup_key` and the Swift client,
     * or a learned policy silently never matches here. Lowercase, alphanumerics only, stopwords
     * and short words dropped, first four joined with "-". The app id is lower-cased too.
     */
    fun lookupKey(task: String, app: String): String {
        val stop = setOf("the", "a", "an", "my", "for", "on", "to", "of", "and", "in",
            "working", "work", "doing", "do", "some", "this", "that")
        val words = task.lowercase()
            .map { if (it.isLetterOrDigit()) it else ' ' }
            .joinToString("")
            .split(' ')
            .filter { it.isNotEmpty() && it !in stop && it.length > 2 }
            .take(4)
        return "${words.joinToString("-")}|${app.trim().lowercase()}"
    }

    /** One line for the settings screen, so "learning is on" is never an unverifiable claim. */
    fun status(ctx: Context): String {
        val policy = load(ctx) ?: return "no policy learned yet"
        val exemplars = policy.optInt("exemplar_count", 0)
        val signatures = policy.optInt("signature_count", 0)
        val generated = policy.optDouble("generated_at", 0.0)
        val stamp = if (generated > 0) {
            SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date((generated * 1000).toLong()))
        } else {
            "unknown date"
        }
        return "$exemplars exemplar(s), $signatures allowance(s), learned $stamp"
    }
}
