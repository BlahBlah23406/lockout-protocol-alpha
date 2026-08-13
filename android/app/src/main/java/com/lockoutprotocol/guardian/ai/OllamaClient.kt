package com.lockoutprotocol.guardian.ai

import android.graphics.Bitmap
import android.util.Base64
import com.lockoutprotocol.guardian.data.Prefs
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

/**
 * [undetermined] = the model could not be reached or its answer couldn't be parsed.
 * [transient]   = a temporary server/network failure (HTTP 503/429/5xx, timeout). This is the AI
 *                 backend being busy — NOT the user hiding something — so callers must NEVER close
 *                 an app because of it (that was the "kept closing my apps on a 503" bug).
 * Callers treat [undetermined] as "couldn't verify" and handle it safely (alert, never a hard
 * block); [transient] verdicts are simply logged and skipped.
 */
data class Verdict(
    val violation: Boolean,
    val reason: String,
    val raw: String,
    /**
     * WHY it was flagged, from [AlertPolicy]'s vocabulary (tamper / search / site / explicit /
     * suggestive). Drives whether the accountability contact is pushed — every violation still
     * blocks, but only deliberate ones are worth a notification. Blank/unknown = alert anyway.
     */
    val category: String = "",
    val undetermined: Boolean = false,
    val transient: Boolean = false
)

/**
 * Sends a screenshot to an Ollama (Cloud) vision model and asks for a strict JSON verdict.
 * Uses the /api/chat endpoint with an image attached to the user message.
 */
class OllamaClient(private val prefs: Prefs) {

    private val http = OkHttpClient.Builder()
        .callTimeout(90, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .build()

    fun evaluate(bitmap: Bitmap): Verdict {
        val b64 = bitmap.toJpegBase64(quality = 80)
        // NOTE: this prompt is DELIBERATELY strict — it is the enforcement half of an
        // accountability commitment. Softening it should be a deliberate, visible decision made
        // with your accountability partner, not a quiet edit. See SAFEGUARDS.md.
        //
        // Case (C) makes the monitoring self-defending: a visible attempt to disable it is itself
        // a violation. It fires only on a concrete disable/evade action, so ordinary reading about
        // Ollama or Guardian passes.
        val sys = """
            You are a STRICT content-safety classifier for a personal accountability app. Its ONE
            purpose is to keep this user away from sexual and sexually-suggestive imagery, and to
            catch any attempt to go looking for it. When in doubt, you FLAG — err on the side of
            flagging, not permitting. You are given ONE phone screenshot and a list of GUIDELINES.

            Report a violation (true) when ANY of the following is true:
              (A) VISIBLE IMAGERY that is sexual or sexually suggestive. This is intentionally broad:
                  pornography or explicit sexual acts; real nudity OR partial nudity; a woman or man
                  in underwear, lingerie, a bikini, or swimwear; exposed or emphasised cleavage,
                  breasts, midriff, buttocks, crotch, or bare thighs; see-through, wet, or tight
                  clothing that sexualises the body; sexualised or provocative poses; close-ups of
                  intimate body areas. If a reasonable person could find the image sexually arousing
                  or masturbate to it, FLAG IT.
              (B) INTENT shown in visible TEXT — a search query, typed input, URL, video/page title,
                  or an app/site being opened — that shows the user is trying to FIND or VIEW such
                  content. This explicitly INCLUDES typing a search into Google, Google Images, an
                  image site, YouTube, TikTok, Instagram, Reddit, or Pinterest where the query seeks
                  sexual, nude, "hot", "sexy", bikini, lingerie, or otherwise provocative images or
                  video of people; opening a site/app whose name denotes pornography; or navigating
                  an image/video search clearly aimed at ogling people. Judge the INTENT behind the
                  text, not only whether an explicit word is present.
              (C) TAMPERING — visible text or UI showing a concrete attempt to DISABLE or EVADE
                  Ollama (the AI service that powers this monitoring) or Guardian itself. Flag only
                  an actual action that would break the monitoring, such as: force-stopping,
                  uninstalling, or disabling Guardian, or revoking its accessibility / usage-access
                  / notification permissions; a terminal or shell command to stop, kill, or
                  uninstall the "ollama" process/service or Guardian; revoking, deleting, or
                  replacing the Ollama API key, or repointing the server URL at a dead or fake
                  endpoint; or changing hosts/DNS/firewall/proxy/VPN settings to block ollama.com.
                  Flag these even when no sexual content is present.

                  Merely READING or WORKING WITH Ollama or Guardian is NOT tampering: the
                  ollama.com website, docs, or model listings; an Ollama app or store listing; the
                  source code of either project (including this classifier prompt itself); or a
                  settings screen merely being viewed. If you cannot point to a specific action that would
                  actually break the monitoring, do NOT flag case (C) — this narrowing applies to
                  case (C) only and does not soften cases (A) or (B) in any way.

            Respond false ONLY for genuinely innocent, non-sexual screens: news, education, this app,
            ordinary chats, code, maps, settings, shopping for non-sexual items, or a word appearing
            incidentally with no sexual intent — UNLESS the screen shows an actual attempt to
            disable Ollama or Guardian per case (C). But when imagery is even borderline sexual,
            FLAG IT — do NOT give the benefit of the doubt.

            When you flag based on text/intent (case B or C), the reason MUST quote the specific
            visible text. Never invent a reason.

            When you flag, you MUST also classify HOW DELIBERATE it is with exactly one "category":
              "tamper"     — case (C): a concrete attempt to disable or evade Ollama or Guardian.
              "search"     — the user TYPED or SUBMITTED a search/query/URL seeking sexual or
                             suggestive imagery, or is looking at the results of such a search.
              "site"       — the screen is a site, app, page, profile, or feed whose PURPOSE is
                             sexual or suggestive imagery (porn sites, NSFW subreddits, "hot
                             girls" galleries, an explicit video player, etc.).
              "explicit"   — sexually explicit imagery is actually on screen: nudity, sexual acts,
                             sexual motion/video, or a close-up of intimate body areas.
              "suggestive" — everything milder or incidental: swimwear/underwear/lingerie in an ad
                             or thumbnail, cleavage/midriff/thighs in an ordinary photo, a
                             tight-clothing shot, a suggestive image the user scrolled past rather
                             than sought out. If the screen is otherwise ordinary (a normal feed,
                             a shop, a news page, a chat) and the flag is only about how someone is
                             dressed or posed, it is "suggestive".
            Choose "suggestive" whenever you are not confident the user was DELIBERATELY seeking or
            viewing the content. The stronger categories mean intent, not just skin.

            Respond with ONLY a compact JSON object, no markdown, no prose. Either:
            {"violation": false}
            or
            {"violation": true, "category": "<one of the five above>", "reason": "<specific visible content or quoted text>"}
        """.trimIndent()

        val user = "GUIDELINES (prohibited content):\n${prefs.guidelines}\n\n" +
            "Classify the attached screenshot. Flag it if prohibited content is visible, if " +
            "the visible text clearly shows the user is deliberately trying to access prohibited " +
            "content, OR if the screen shows an attempt to disable or evade Ollama or Guardian " +
            "(case C). Ignore innocent/incidental mentions, ordinary reading of Guardian or " +
            "Ollama material, and unselected suggestions. " +
            "If you flag it, you MUST include the \"category\" field."

        val payload = JSONObject().apply {
            put("model", prefs.ollamaModel)
            put("stream", false)
            put("format", "json")
            // Gemma 4 is a reasoning model; turn thinking OFF so it answers fast with clean JSON.
            put("think", false)
            // Keep the model warm between checks — avoids the cold-start reload that makes the
            // occasional request take 10-30s+ ("sometimes slow").
            put("keep_alive", "20m")
            put("messages", JSONArray().apply {
                put(JSONObject().apply { put("role", "system"); put("content", sys) })
                put(JSONObject().apply {
                    put("role", "user")
                    put("content", user)
                    put("images", JSONArray().apply { put(b64) })
                })
            })
            // num_predict caps output so the model can't ramble; we only need a tiny JSON verdict.
            put("options", JSONObject().apply {
                put("temperature", 0)
                put("num_predict", 80)
            })
        }

        val body = payload.toString()

        // Keys to try, the one that last worked first. When a key is out of quota (or rejected) we
        // immediately retry the same request with the other one and remember the switch, so the two
        // keys alternate as each runs out instead of one always being burned first.
        val keys = prefs.apiKeys.ifEmpty { listOf("") }

        // Retry transient backend failures (503/5xx, timeouts) a few times with backoff before
        // giving up. Ollama Cloud returns 503 when it's momentarily overloaded; that must resolve to
        // a TRANSIENT verdict (logged + skipped), never a "can't see" that could close the app.
        var lastTransient = Verdict(false, "no attempt", "", undetermined = true, transient = true)
        for (attempt in 0 until MAX_ATTEMPTS) {
            if (attempt > 0) {
                try { Thread.sleep(BACKOFF_MS * attempt) } catch (_: InterruptedException) {}
            }
            var exhausted = 0
            for ((i, key) in keys.withIndex()) {
                val attemptResult = request(body, key, attempt)
                if (attemptResult.keyRejected) {
                    exhausted++
                    Log.w("OllamaClient", "key ${i + 1}/${keys.size} rejected (${attemptResult.verdict.reason}) — trying the next key")
                    continue
                }
                val result = attemptResult.verdict
                if (result.transient) { lastTransient = result; break }  // backoff, then start over at the active key
                // Success (or a definite error) on this key: make it the one we start with next time.
                if (i > 0) prefs.promoteApiKey(key)
                return result
            }
            if (exhausted == keys.size) {
                // Every key is out of quota right now. Transient, never a block: the next tick retries.
                lastTransient = Verdict(false, "AI quota exhausted on all ${keys.size} key(s)", "",
                    undetermined = true, transient = true)
            }
        }
        return lastTransient
    }

    /** One HTTP call with one key. [Attempt.keyRejected] means "this key is out/invalid, try another". */
    private data class Attempt(val verdict: Verdict, val keyRejected: Boolean = false)

    private fun request(body: String, key: String, attempt: Int): Attempt {
        val req = Request.Builder()
            .url(prefs.ollamaBaseUrl.trimEnd('/') + "/api/chat")
            .apply { if (key.isNotBlank()) addHeader("Authorization", "Bearer $key") }
            .post(body.toRequestBody(JSON))
            .build()
        return try {
            http.newCall(req).execute().use { resp ->
                val respBody = resp.body?.string().orEmpty()
                when {
                    resp.isSuccessful -> Attempt(parse(respBody))
                    isKeyExhaustedCode(resp.code) ->
                        Attempt(Verdict(false, "key rejected (HTTP ${resp.code})", respBody,
                            undetermined = true, transient = true), keyRejected = true)
                    isTransientCode(resp.code) -> {
                        Log.w("OllamaClient", "transient API error ${resp.code} (attempt ${attempt + 1}/$MAX_ATTEMPTS)")
                        Attempt(Verdict(false, "AI busy (HTTP ${resp.code})", respBody, undetermined = true, transient = true))
                    }
                    else -> {
                        Log.e("OllamaClient", "API error ${resp.code}: $respBody")
                        Attempt(Verdict(false, "API error ${resp.code}", respBody, undetermined = true))
                    }
                }
            }
        } catch (e: Exception) {
            // Network drops / timeouts are transient too — keep retrying, never close on these.
            Log.w("OllamaClient", "request failed (attempt ${attempt + 1}/$MAX_ATTEMPTS): ${e.message}")
            Attempt(Verdict(false, "AI unreachable: ${e.message}", "", undetermined = true, transient = true))
        }
    }

    private fun parse(body: String): Verdict {
        val v = parseVerdict(body)
        if (v.undetermined) Log.e("OllamaClient", "JSON parse failed for body: $body")
        return v
    }

    private fun Bitmap.toJpegBase64(quality: Int): String {
        val out = ByteArrayOutputStream()
        compress(Bitmap.CompressFormat.JPEG, quality, out)
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }

    companion object {
        private val JSON = "application/json".toMediaType()

        // Transient-failure retry policy (fixes the 503-closes-my-apps bug).
        private const val MAX_ATTEMPTS = 3
        private const val BACKOFF_MS = 800L

        /** HTTP codes we treat as temporary backend hiccups worth retrying (never a "can't see"). */
        fun isTransientCode(code: Int): Boolean =
            code == 408 || code == 429 || code == 500 || code == 502 || code == 503 || code == 504

        /**
         * HTTP codes that mean THIS KEY can't be used right now — quota/credit exhausted (402/429)
         * or the key being rejected outright (401/403) — as opposed to the backend being busy. These
         * are what trigger the fail-over to the other key. Still never a block on their own: if every
         * key is out, the verdict stays transient.
         */
        fun isKeyExhaustedCode(code: Int): Boolean =
            code == 401 || code == 402 || code == 403 || code == 429

        /**
         * Pure parse of an Ollama /api/chat response body into a [Verdict]. The model's content is
         * expected to be a JSON object {"violation":bool,"reason":string}. Anything unparseable is
         * marked undetermined (caller fails closed). Extracted as a pure function for unit testing.
         */
        fun parseVerdict(body: String): Verdict {
            return try {
                val content = JSONObject(body).getJSONObject("message").getString("content")
                val obj = JSONObject(content.trim())
                Verdict(
                    violation = obj.optBoolean("violation", false),
                    reason = obj.optString("reason", ""),
                    category = AlertPolicy.normalize(obj.optString("category", "")),
                    raw = content
                )
            } catch (e: Exception) {
                Verdict(false, "parse-failed: ${e.message}", body, undetermined = true)
            }
        }
    }
}
