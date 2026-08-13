package com.lockoutprotocol.guardian.data

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Lightweight timestamped activity log for screenshots + AI analysis. Kept in memory (capped)
 * and mirrored to a file in app storage so it survives process restarts and can be viewed in-app.
 */
object EventLog {
    private const val MAX = 500
    private const val MAX_FILE_BYTES = 250_000L
    private val entries = ArrayDeque<String>()
    private var file: File? = null
    private val fmt = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US)

    fun init(ctx: Context) {
        if (file != null) return
        val f = File(ctx.filesDir, "event_log.txt")
        file = f
        runCatching {
            if (f.exists()) f.readLines().takeLast(MAX).forEach { entries.addLast(it) }
        }
    }

    @Synchronized
    fun add(msg: String) {
        val line = "${fmt.format(Date())}  $msg"
        entries.addLast(line)
        while (entries.size > MAX) entries.removeFirst()
        val f = file ?: return
        runCatching {
            if (f.length() > MAX_FILE_BYTES) f.writeText(entries.joinToString("\n") + "\n")
            else f.appendText(line + "\n")
        }
    }

    @Synchronized
    fun snapshot(): List<String> = entries.toList()

    @Synchronized
    fun clear() {
        entries.clear()
        runCatching { file?.writeText("") }
    }
}
