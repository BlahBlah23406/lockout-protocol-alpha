package com.lockoutprotocol.guardian.data

import android.content.Context
import com.lockoutprotocol.guardian.focus.FocusSession
import java.io.File
import org.json.JSONObject

/**
 * Append-only record of every focus check, and the user's feedback on it.
 *
 * One JSON object per line, appended and never rewritten, so a kill mid-write costs one line
 * rather than the file. The schema is shared with the Windows, macOS and iOS ports and with the
 * offline learner — change a field name in one place and you must change it in all four.
 *
 * It lives in the app's private storage. To feed it to the learner:
 * `adb shell run-as com.lockoutprotocol.guardian cat files/judgements.jsonl`.
 */
object Judgements {

    /** ~ a year of heavy use; trimmed from the front at launch when exceeded. */
    private const val MAX_LINES = 20_000
    private const val FILE_NAME = "judgements.jsonl"

    const val FB_FALSE_ALARM = "false_alarm"    // it blocked me and it was wrong
    const val FB_CORRECT = "correct"            // it blocked me and it was right

    /** Easily forgotten: a monitor tuned only on false alarms drifts towards never blocking. */
    const val FB_MISSED = "missed"

    private fun file(ctx: Context) = File(ctx.filesDir, FILE_NAME)

    /** Append one judgement and return its id, so a later feedback tap can find this exact row. */
    @Synchronized
    fun record(
        ctx: Context,
        session: FocusSession?,
        app: String,
        appName: String,
        screenTitle: String,
        verdict: String,
        reason: String,
        confidence: Double,
        action: String,
        provider: String,
    ): String {
        val jid = "j_${System.currentTimeMillis()}"
        append(ctx, JSONObject().apply {
            put("id", jid)
            put("ts", System.currentTimeMillis() / 1000.0)
            put("session_id", session?.id ?: "")
            put("task", session?.task ?: "")
            put("app", app)
            put("app_name", appName)
            put("window_title", screenTitle.take(300))
            put("verdict", verdict)
            put("reason", reason.take(500))
            put("confidence", Math.round(confidence * 1000) / 1000.0)
            put("action", action)
            put("provider", provider)
            put("feedback", JSONObject.NULL)
            put("feedback_at", JSONObject.NULL)
            put("feedback_note", JSONObject.NULL)
        })
        return jid
    }

    /** Written as a new row rather than an edit: rewriting a line in place means rewriting the
     *  whole file, which is not something to do while the monitor is appending to it. */
    @Synchronized
    fun addFeedback(ctx: Context, judgementId: String, feedback: String, note: String = ""): Boolean {
        if (feedback !in setOf(FB_FALSE_ALARM, FB_CORRECT, FB_MISSED)) return false
        append(ctx, JSONObject().apply {
            put("id", "$judgementId#fb")
            put("ts", System.currentTimeMillis() / 1000.0)
            put("ref", judgementId)
            put("feedback", feedback)
            put("feedback_at", System.currentTimeMillis() / 1000.0)
            put("feedback_note", note.take(300))
        })
        return true
    }

    private fun append(ctx: Context, row: JSONObject) {
        // Telemetry must never be able to break monitoring.
        runCatching { file(ctx).appendText(row.toString() + "\n") }
    }

    /** Read back the tail of the log, with feedback rows folded into the judgements they refer to. */
    fun readAll(ctx: Context, limit: Int = 2000): List<JSONObject> {
        val f = file(ctx)
        if (!f.exists()) return emptyList()
        val lines = runCatching { f.readLines() }.getOrDefault(emptyList())

        val rows = mutableListOf<JSONObject>()
        val indexById = mutableMapOf<String, Int>()

        for (line in lines.takeLast(limit * 2)) {
            val obj = runCatching { JSONObject(line) }.getOrNull()
                ?: continue         // a torn final line after a hard kill
            val ref = obj.optString("ref", "")
            if (ref.isNotEmpty()) {
                indexById[ref]?.let { idx ->
                    rows[idx].put("feedback", obj.opt("feedback"))
                    rows[idx].put("feedback_at", obj.opt("feedback_at"))
                    rows[idx].put("feedback_note", obj.opt("feedback_note"))
                }
                continue
            }
            obj.optString("id", "").takeIf(String::isNotEmpty)?.let { indexById[it] = rows.size }
            rows += obj
        }
        return rows.takeLast(limit)
    }

    /** Keep the file bounded. Called at launch, never on the hot path. */
    @Synchronized
    fun trim(ctx: Context) {
        runCatching {
            val f = file(ctx)
            if (!f.exists()) return
            val lines = f.readLines()
            if (lines.size <= MAX_LINES) return
            f.writeText(lines.takeLast(MAX_LINES).joinToString("\n") + "\n")
        }
    }

    data class Stats(val checks: Int, val offTask: Int, val blocked: Int, val falseAlarms: Int)

    /** Counts for the end-of-session summary. */
    fun sessionStats(ctx: Context, sessionId: String): Stats {
        var checks = 0
        var offTask = 0
        var blocked = 0
        var falseAlarms = 0
        for (row in readAll(ctx)) {
            if (row.optString("session_id") != sessionId) continue
            checks++
            if (row.optString("verdict") == "off_task") offTask++
            if (row.optString("action") == "blocked") blocked++
            if (row.optString("feedback") == FB_FALSE_ALARM) falseAlarms++
        }
        return Stats(checks, offTask, blocked, falseAlarms)
    }
}
