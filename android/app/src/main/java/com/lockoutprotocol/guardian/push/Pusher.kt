package com.lockoutprotocol.guardian.push

import com.lockoutprotocol.guardian.data.Prefs
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Zero-setup push alerts via ntfy (https://ntfy.sh). No account, no password — the user just
 * subscribes the free ntfy app to their private topic code. We POST the alert text to
 * {server}/{topic}. The topic string is unguessable, so it doubles as the secret.
 */
object Pusher {

    private val client = OkHttpClient.Builder()
        .callTimeout(20, TimeUnit.SECONDS)
        .build()

    fun send(prefs: Prefs, title: String, message: String): Result<Unit> = runCatching {
        require(prefs.pushEnabled) { "push disabled" }
        val topic = prefs.ntfyTopic
        require(topic.isNotBlank()) { "no topic" }

        val url = prefs.ntfyServer.trimEnd('/') + "/" + topic
        val req = Request.Builder()
            .url(url)
            .addHeader("Title", title.toAsciiHeader())
            .addHeader("Priority", "high")
            .addHeader("Tags", "rotating_light")
            .post(message.toRequestBody("text/plain; charset=utf-8".toMediaType()))
            .build()

        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) error("ntfy ${resp.code}: ${resp.body?.string()}")
        }
    }

    /** ntfy header values must be ASCII; strip anything else so titles never break the request. */
    private fun String.toAsciiHeader(): String =
        filter { it.code in 32..126 }.ifBlank { "Guardian" }
}
