package com.lockoutprotocol.guardian.tamper

import android.content.Context
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.push.Pusher
import kotlin.concurrent.thread

/**
 * One place to raise a "someone is tampering with Guardian" alert to the accountability contact.
 * The real enforcement in an accountability app is social: the moment a defense is touched, the
 * partner is notified. Fires the push off the main thread and de-dupes, since a single tamper
 * action (e.g. opening Guardian's app-info page) can trip several detectors at once.
 */
object TamperAlert {

    private const val DEDUPE_MS = 60_000L
    @Volatile private var lastAt = 0L

    /**
     * @param force skip the de-dupe window (used for genuinely distinct events like admin removal).
     */
    fun raise(context: Context, reason: String, force: Boolean = false) {
        val now = System.currentTimeMillis()
        synchronized(this) {
            if (!force && now - lastAt < DEDUPE_MS) return
            lastAt = now
        }
        val app = context.applicationContext
        val prefs = Prefs.get(app)
        EventLog.add("🛑 TAMPER — $reason")
        val title = "[Guardian] Tamper alert"
        val body = "$reason\n\nDevice: ${android.os.Build.MODEL}\n${java.util.Date()}"
        thread {
            runCatching { if (prefs.pushEnabled) Pusher.send(prefs, title, body) }
        }
    }
}
