package com.lockoutprotocol.guardian.ai

import android.graphics.Bitmap
import android.util.Base64
import android.util.Log
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

/**
 * Pluggable model providers for the focus classifier.
 *
 * The content-safety classifier spoke to exactly one backend because it only ever had one job. A
 * focus monitor runs a check every couple of minutes for hours, so *whose* model it is and *where*
 * it runs becomes the user's decision. On a phone that matters twice over: someone may want the
 * request to go to a local Ollama on their own laptop over Wi-Fi (private, free) rather than to
 * anybody's cloud.
 *
 * The request shape differs per provider and is the easy part. The *policy* — retry, key fail-over,
 * and the rule that a backend hiccup NEVER blocks the user — is the hard-won part (see
 * [OllamaClient]) and lives once, here, shared by all four kinds.
 */
enum class ProviderKind { OLLAMA, OPENAI, ANTHROPIC, CUSTOM }

data class ProviderPreset(
    val id: String,
    val kind: ProviderKind,
    val label: String,
    val baseUrl: String,
    val model: String,
    val needsKey: Boolean,
    val hint: String,
)

/**
 * One focus check.
 *
 * The two escape hatches are load-bearing and deliberately distinct, because conflating them is
 * how a monitor ends up locking someone out of their own phone:
 *
 *  - [undetermined] — an answer we couldn't read, or a screen we couldn't read. Not the user's
 *    fault, not evidence of anything. Never a block.
 *  - [transient] — the backend was busy or unreachable (5xx, 429, timeout, out of quota). Also
 *    never a block; the next tick simply tries again.
 *
 * [confidence] is the model's own 0–1 self-report. Not treated as calibrated — used only as a
 * threshold input for the learner, and to word the log line honestly.
 */
data class FocusVerdict(
    val onTask: Boolean = true,
    val reason: String = "",
    val confidence: Double = 0.0,
    val raw: String = "",
    val undetermined: Boolean = false,
    val transient: Boolean = false,
) {
    /** True only for a clean, readable "this is not the declared task" answer. */
    val offTask: Boolean get() = !onTask && !undetermined && !transient
}

object Providers {

    private const val TAG = "Providers"

    /** Transient-failure retry policy, carried over unchanged: the AI being busy must never cost
     *  the user their session. */
    private const val MAX_ATTEMPTS = 3
    private const val BACKOFF_MS = 800L
    private const val TIMEOUT_SECONDS = 90L

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .build()
    }

    private val JSON = "application/json".toMediaType()

    /**
     * What the settings picker offers. `CUSTOM` is not a fourth code path — it is `OPENAI` with the
     * URL field unlocked. It exists as its own entry only so the picker can say "anything
     * OpenAI-compatible" out loud.
     *
     * Note the two local options point at a LAN address, not localhost: on a phone `127.0.0.1` is
     * the phone itself, which is not where anyone is running a vision model.
     */
    val presets: List<ProviderPreset> = listOf(
        ProviderPreset(
            "ollama-cloud", ProviderKind.OLLAMA, "Ollama Cloud",
            "https://ollama.com", "gemma4:31b-cloud", true,
            "Hosted Ollama. The simplest thing that works on a phone with no other hardware."
        ),
        ProviderPreset(
            "ollama-lan", ProviderKind.OLLAMA, "Ollama on my own computer",
            "http://192.168.1.10:11434", "qwen3-vl:8b", false,
            "Free and private — the screenshot goes to your own machine over Wi-Fi and no " +
                "further. Put your computer's LAN address in below, and start Ollama with " +
                "OLLAMA_HOST=0.0.0.0 so it accepts connections from the phone."
        ),
        ProviderPreset(
            "openai", ProviderKind.OPENAI, "OpenAI",
            "https://api.openai.com", "gpt-4.1-mini", true,
            "Any OpenAI vision model."
        ),
        ProviderPreset(
            "anthropic", ProviderKind.ANTHROPIC, "Anthropic (Claude)",
            "https://api.anthropic.com", "claude-haiku-4-5-20251001", true,
            "Haiku is the right size here — the check is a one-line yes/no, run hundreds of " +
                "times a session."
        ),
        ProviderPreset(
            "custom", ProviderKind.CUSTOM, "Anything OpenAI-compatible",
            "", "", false,
            "llama.cpp, vLLM, LM Studio, OpenRouter, Groq, Together, a company gateway — paste " +
                "the base URL that ends in /v1."
        ),
    )

    fun preset(id: String?): ProviderPreset? = presets.firstOrNull { it.id == id }

    /** Immutable snapshot so the network call can run off the main thread. */
    data class Config(
        val kind: ProviderKind,
        val baseUrl: String,
        val model: String,
        /** Keys to try, the one that last worked first. Empty for a local provider. */
        val apiKeys: List<String>,
        val label: String,
    ) {
        fun describe(): String = "${kind.name.lowercase()}:$model"
    }

    // ---------------------------------------------------------------------------------------
    // The classifier prompt
    // ---------------------------------------------------------------------------------------

    /**
     * This prompt is the product. Two things about it are deliberate:
     *
     * 1. It is BIASED TOWARDS "on task" — the exact opposite of the content-safety classifier,
     *    which flags when in doubt. That asymmetry follows from what a mistake costs. A missed
     *    frame of off-task scrolling costs ten seconds. A false alarm interrupts real work, and
     *    two or three of those in an afternoon and the app is uninstalled — at which point it
     *    protects nothing at all. A focus monitor that cries wolf is worse than none.
     *
     * 2. It counts SUPPORTING work as on-task. Almost nothing real happens inside one app: "math
     *    test prep" legitimately includes a YouTube lecture, a Reddit thread, a study-group chat,
     *    past papers, and the file manager you found them in. A classifier that only accepts a PDF
     *    viewer is measuring app choice, not focus.
     */
    val FOCUS_SYSTEM = """
        You decide whether ONE screenshot shows a person working on the task they declared.

        You are given: the user's own description of what they sat down to do, the name of the app
        in front, its screen title, and one phone screenshot. Answer with a single JSON object.

        DEFAULT TO on_task. You are the interruption in someone's working day, so you must be sure
        before you say no. If a screen is plausibly part of the declared work — even indirectly —
        it is on task.

        Count as ON TASK:
          - The obvious: the document, editor, problem set, spreadsheet, or tool the task names.
          - SUPPORTING WORK, which is most of real work: searching the web for the topic, reading
            documentation or a tutorial, watching an instructional video, a forum or Q&A thread
            about the subject, a study-group chat, email or a message thread about the task,
            note-taking, a calculator, a file manager, a password prompt, a download.
          - Setup and friction: an app still loading, a login screen, a settings page, an update
            prompt, an empty new tab, the home screen or lock screen, this monitoring app's own
            screens.
          - Anything ambiguous, unreadable, or that you simply cannot connect either way.

        Count as OFF TASK only when the screen is CLEARLY unrelated to the declared task AND is
        recognisably leisure or a different job: an entertainment video or show with no connection
        to the topic, a game being played, a social feed being scrolled, shopping, sports scores,
        memes, unrelated news, or focused work on a plainly different project.

        Judge the SCREEN, not the app. YouTube showing a lecture on the topic is on task; YouTube
        showing a gaming stream is off task. A browser is neither good nor bad — read what is in it.

        When you say off_task, `reason` MUST quote the specific visible text or name the specific
        visible content that decided it. Never invent a reason, and never guess at what is off-screen.

        `confidence` is how sure you are of the answer you gave, from 0.0 to 1.0. Be honest and use
        the low end freely — a 0.4 is far more useful to us than a falsely confident 0.9.

        If the screenshot is blank, encrypted, DRM-protected, or otherwise unreadable, return
        {"unreadable": true} instead of guessing.

        Respond with ONLY compact JSON, no markdown and no prose. One of:
        {"on_task": true, "confidence": 0.9}
        {"on_task": false, "reason": "<specific visible evidence>", "confidence": 0.8}
        {"unreadable": true}
    """.trimIndent()

    /**
     * The per-check message. App name and title are passed as text as well as being visible in the
     * image: small vision models read a supplied string far more reliably than they read small
     * on-screen text, and on a phone the screen title is often the only unambiguous signal.
     */
    fun userPrompt(task: String, appName: String, screenTitle: String, extraNotes: String = ""): String {
        val parts = mutableListOf(
            "THE USER'S DECLARED TASK, in their own words:",
            "    ${task.ifBlank { "(none given)" }}",
            "",
            "App in front: ${appName.ifBlank { "unknown" }}",
            "Screen title: ${screenTitle.trim().ifBlank { "(none)" }}",
        )
        val notes = extraNotes.trim()
        if (notes.isNotEmpty()) {
            // Where the learner's accumulated "you were wrong about this before" lines land.
            parts += listOf("", "PREVIOUSLY CONFIRMED BY THE USER — treat these as settled:", notes)
        }
        parts += listOf("", "Is this screen part of that task? Answer in JSON.")
        return parts.joinToString("\n")
    }

    // ---------------------------------------------------------------------------------------
    // Parsing (pure — driven directly by the unit tests)
    // ---------------------------------------------------------------------------------------

    /**
     * Turn the model's JSON text into a verdict. Small models fence their JSON even when told not
     * to (Gemma does it constantly), so fences are stripped rather than throwing away an otherwise
     * good answer.
     */
    fun parseFocusJson(content: String?): FocusVerdict {
        if (content == null) return FocusVerdict(reason = "parse-failed", undetermined = true)
        var text = content.trim()
        if (text.startsWith("```")) {
            text = text.substringAfter('\n', "")
            if (text.trimEnd().endsWith("```")) text = text.trimEnd().dropLast(3)
            text = text.trim()
        }

        val obj = runCatching { JSONObject(text) }.getOrNull()
            ?: return FocusVerdict(reason = "parse-failed", raw = content, undetermined = true)

        if (obj.optBoolean("unreadable", false)) {
            return FocusVerdict(reason = "screen unreadable", raw = text, undetermined = true)
        }

        // A missing or non-boolean answer is not a "no" — it is a failure to answer, and treating
        // it as a "no" would block people over a malformed reply.
        if (!obj.has("on_task") || obj.get("on_task") !is Boolean) {
            return FocusVerdict(reason = "no on_task field", raw = text, undetermined = true)
        }

        return FocusVerdict(
            onTask = obj.getBoolean("on_task"),
            reason = obj.optString("reason", ""),
            confidence = obj.optDouble("confidence", 0.0).coerceIn(0.0, 1.0),
            raw = text,
        )
    }

    /** Pull the assistant's text out of a provider's envelope, then parse it. */
    fun parseResponse(kind: ProviderKind, body: String): FocusVerdict {
        val root = runCatching { JSONObject(body) }.getOrNull()
            ?: return FocusVerdict(reason = "parse-failed", raw = body.take(400), undetermined = true)

        val content: String? = when (kind) {
            ProviderKind.OLLAMA ->
                root.optJSONObject("message")?.optString("content")
            ProviderKind.ANTHROPIC -> {
                val blocks = root.optJSONArray("content")
                (0 until (blocks?.length() ?: 0))
                    .map { blocks!!.optJSONObject(it) }
                    .firstOrNull { it?.optString("type") == "text" }
                    ?.optString("text")
            }
            ProviderKind.OPENAI, ProviderKind.CUSTOM ->
                root.optJSONArray("choices")?.optJSONObject(0)
                    ?.optJSONObject("message")?.optString("content")
        }

        return if (content.isNullOrEmpty()) {
            FocusVerdict(reason = "parse-failed", raw = body.take(400), undetermined = true)
        } else {
            parseFocusJson(content)
        }
    }

    // ---------------------------------------------------------------------------------------
    // Request building
    // ---------------------------------------------------------------------------------------

    fun Bitmap.toJpegBase64(quality: Int = 80): String {
        val out = ByteArrayOutputStream()
        compress(Bitmap.CompressFormat.JPEG, quality, out)
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }

    data class BuiltRequest(val url: String, val payload: JSONObject,
                            val extraHeaders: Map<String, String>)

    fun buildRequest(cfg: Config, b64: String, system: String, user: String): BuiltRequest {
        val base = cfg.baseUrl.trimEnd('/')

        return when (cfg.kind) {
            ProviderKind.OLLAMA -> BuiltRequest(
                "$base/api/chat",
                JSONObject().apply {
                    put("model", cfg.model)
                    put("stream", false)
                    put("format", "json")
                    // Keep the model resident between checks. At a 2-minute interval a cold reload
                    // each time would cost more than the inference does.
                    put("keep_alive", "20m")
                    put("messages", JSONArray().apply {
                        put(JSONObject().apply { put("role", "system"); put("content", system) })
                        put(JSONObject().apply {
                            put("role", "user")
                            put("content", user)
                            put("images", JSONArray().put(b64))
                        })
                    })
                    put("options", JSONObject().apply {
                        put("temperature", 0)
                        put("num_predict", 160)
                    })
                },
                emptyMap()
            )

            ProviderKind.ANTHROPIC -> BuiltRequest(
                "$base/v1/messages",
                JSONObject().apply {
                    put("model", cfg.model)
                    put("max_tokens", 200)
                    put("temperature", 0)
                    put("system", system)
                    put("messages", JSONArray().put(JSONObject().apply {
                        put("role", "user")
                        put("content", JSONArray().apply {
                            put(JSONObject().apply {
                                put("type", "image")
                                put("source", JSONObject().apply {
                                    put("type", "base64")
                                    put("media_type", "image/jpeg")
                                    put("data", b64)
                                })
                            })
                            put(JSONObject().apply { put("type", "text"); put("text", user) })
                        })
                    }))
                },
                mapOf("anthropic-version" to "2023-06-01")
            )

            ProviderKind.OPENAI, ProviderKind.CUSTOM -> {
                // A bare host gets /v1 appended; a URL that already ends in /v1 (LM Studio,
                // OpenRouter, most gateways) is left alone — appending a second one is the single
                // most common way people misconfigure this.
                val prefix = if (base.endsWith("/v1")) base else "$base/v1"
                BuiltRequest(
                    "$prefix/chat/completions",
                    JSONObject().apply {
                        put("model", cfg.model)
                        put("max_tokens", 200)
                        put("temperature", 0)
                        put("response_format", JSONObject().put("type", "json_object"))
                        put("messages", JSONArray().apply {
                            put(JSONObject().apply { put("role", "system"); put("content", system) })
                            put(JSONObject().apply {
                                put("role", "user")
                                put("content", JSONArray().apply {
                                    put(JSONObject().apply {
                                        put("type", "text"); put("text", user)
                                    })
                                    put(JSONObject().apply {
                                        put("type", "image_url")
                                        put("image_url", JSONObject()
                                            .put("url", "data:image/jpeg;base64,$b64"))
                                    })
                                })
                            })
                        })
                    },
                    emptyMap()
                )
            }
        }
    }

    /** Providers disagree about where the key goes; that is the entire difference in auth. */
    fun authHeaders(cfg: Config, key: String): Map<String, String> {
        if (key.isBlank()) return emptyMap()
        return if (cfg.kind == ProviderKind.ANTHROPIC) mapOf("x-api-key" to key)
        else mapOf("Authorization" to "Bearer $key")
    }

    // ---------------------------------------------------------------------------------------
    // Transport + the never-block-on-a-hiccup policy
    // ---------------------------------------------------------------------------------------

    /** Temporary backend trouble, worth retrying. Never evidence about the user. */
    fun isTransientCode(code: Int): Boolean = code in setOf(408, 429, 500, 502, 503, 504)

    /**
     * This *key* can't be used right now — out of credit (402/429) or rejected (401/403). Triggers
     * fail-over to the next key. If every key is out the verdict stays transient: being out of API
     * credit is our problem, and must never cost the user a block.
     */
    fun isKeyExhaustedCode(code: Int): Boolean = code in setOf(401, 402, 403, 429)

    /**
     * Reject an unusable config before anything else happens.
     *
     * Split out so it can be unit-tested without a `Bitmap` (which a plain JVM test can't build),
     * and because it is the guard for a whole class of failure: "our configuration is broken" must
     * cost the user nothing. Returns the verdict to hand back, or null when the config is fine.
     */
    fun validateConfig(cfg: Config): FocusVerdict? = when {
        cfg.model.isBlank() ->
            FocusVerdict(reason = "no model configured", undetermined = true)
        cfg.baseUrl.isBlank() ->
            FocusVerdict(reason = "no server URL configured", undetermined = true)
        else -> null
    }

    private data class Attempt(val verdict: FocusVerdict, val keyRejected: Boolean = false)

    private fun perform(cfg: Config, url: String, body: String,
                        headers: Map<String, String>): Attempt {
        val request = Request.Builder()
            .url(url)
            .post(body.toRequestBody(JSON))
            .apply { headers.forEach { (k, v) -> header(k, v) } }
            .build()
        return try {
            http.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                val code = response.code
                when {
                    isKeyExhaustedCode(code) -> Attempt(
                        FocusVerdict(reason = "key rejected (HTTP $code)", raw = text.take(400),
                            undetermined = true, transient = true),
                        keyRejected = true
                    )
                    isTransientCode(code) -> Attempt(
                        FocusVerdict(reason = "AI busy (HTTP $code)", raw = text.take(400),
                            undetermined = true, transient = true)
                    )
                    !response.isSuccessful -> Attempt(
                        FocusVerdict(reason = "API error $code", raw = text.take(400),
                            undetermined = true)
                    )
                    else -> Attempt(parseResponse(cfg.kind, text))
                }
            }
        } catch (e: IOException) {
            // An Ollama on the LAN that isn't reachable lands here — the laptop is asleep, or the
            // phone is on mobile data. Transient is right: the status line says so and the next
            // tick retries.
            Attempt(FocusVerdict(reason = "AI unreachable: ${e.message}",
                undetermined = true, transient = true))
        } catch (e: Exception) {
            Attempt(FocusVerdict(reason = "AI error: ${e.message}", undetermined = true,
                transient = true))
        }
    }

    /**
     * Run one focus check. Blocking — call it from a background dispatcher.
     * [onKeyWorked] is called when fail-over succeeded on a non-first key, so the next call can
     * start there.
     */
    fun evaluate(
        cfg: Config,
        bitmap: Bitmap,
        task: String,
        appName: String,
        screenTitle: String,
        extraNotes: String = "",
        sleep: (Long) -> Unit = { Thread.sleep(it) },
        onKeyWorked: ((String) -> Unit)? = null,
    ): FocusVerdict {
        validateConfig(cfg)?.let { return it }

        val b64 = runCatching { bitmap.toJpegBase64() }.getOrNull()
            ?: return FocusVerdict(reason = "encode-failed", undetermined = true)

        val user = userPrompt(task, appName, screenTitle, extraNotes)
        val built = runCatching { buildRequest(cfg, b64, FOCUS_SYSTEM, user) }.getOrNull()
            ?: return FocusVerdict(reason = "bad-request", undetermined = true)
        val body = built.payload.toString()

        val keys = cfg.apiKeys.ifEmpty { listOf("") }
        var lastTransient = FocusVerdict(reason = "no attempt", undetermined = true,
            transient = true)

        for (attempt in 0 until MAX_ATTEMPTS) {
            if (attempt > 0) sleep(BACKOFF_MS * attempt)
            var exhausted = 0
            for ((i, key) in keys.withIndex()) {
                val headers = buildMap {
                    put("Content-Type", "application/json")
                    putAll(built.extraHeaders)
                    putAll(authHeaders(cfg, key))
                }
                val result = perform(cfg, built.url, body, headers)
                if (result.keyRejected) {
                    exhausted += 1
                    continue                    // this key is out — try the next one immediately
                }
                if (result.verdict.transient) {
                    lastTransient = result.verdict
                    break                       // back off, then start again at the first key
                }
                if (i > 0) onKeyWorked?.invoke(key)
                return result.verdict
            }
            if (exhausted == keys.size) {
                lastTransient = FocusVerdict(
                    reason = "all ${keys.size} key(s) rejected or out of quota",
                    undetermined = true, transient = true)
            }
        }
        Log.d(TAG, "evaluate gave up transiently: ${lastTransient.reason}")
        return lastTransient
    }

    /**
     * Cheap "can I talk to this at all?" probe for the settings screen, so a user finds out that
     * their laptop's Ollama isn't reachable *now* rather than 40 minutes into a session.
     * Returns null when things look fine, or a human-readable problem. Blocking.
     */
    fun reachability(cfg: Config): String? {
        if (cfg.baseUrl.isBlank()) return "no server URL set"
        if (cfg.model.isBlank()) return "no model set"
        if (cfg.kind == ProviderKind.ANTHROPIC) return null   // no free unauthenticated probe

        val url = if (cfg.kind == ProviderKind.OLLAMA) {
            cfg.baseUrl.trimEnd('/') + "/api/tags"
        } else {
            val base = cfg.baseUrl.trimEnd('/')
            (if (base.endsWith("/v1")) base else "$base/v1") + "/models"
        }

        val request = Request.Builder().url(url).get()
            .apply { authHeaders(cfg, cfg.apiKeys.firstOrNull().orEmpty())
                .forEach { (k, v) -> header(k, v) } }
            .build()

        return try {
            http.newCall(request).execute().use { response ->
                if (response.code == 401 || response.code == 403) {
                    return "server reachable, but the API key was rejected"
                }
                if (!response.isSuccessful) return "server returned HTTP ${response.code}"
                val body = response.body?.string().orEmpty()
                // Reachable — now the more useful question: is the model actually there?
                if (!body.contains(cfg.model)) {
                    "server is up, but '${cfg.model}' was not in its model list"
                } else {
                    null
                }
            }
        } catch (e: Exception) {
            if (cfg.kind == ProviderKind.OLLAMA && !cfg.baseUrl.startsWith("https://")) {
                "couldn't reach ${cfg.baseUrl} — is the computer awake, on the same Wi-Fi, and " +
                    "running Ollama with OLLAMA_HOST=0.0.0.0?"
            } else {
                "could not reach ${cfg.baseUrl}: ${e.message}"
            }
        }
    }
}
