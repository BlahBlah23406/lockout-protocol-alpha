package com.lockoutprotocol.guardian.focus

import android.content.Context
import com.lockoutprotocol.guardian.data.Prefs
import java.io.File
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

/**
 * Which accountability level a session was started at.
 *
 * This is the choice the whole product turns on, and the difference is *who holds the exit*:
 *
 *  - [SELF]   You can end the session or dismiss a block yourself, no passcode. The block still
 *             interrupts you and still goes in the log — the friction is the product — but you are
 *             the only one holding you to it. The honest default for most people.
 *  - [LOCKED] Ending the session early, or overriding a block, needs the passcode, and both fire
 *             an ntfy alert to your accountability partner's private link.
 *
 * Neither level can ever trap you: closing a blocked app is always passcode-free (SAFEGUARDS.md).
 * What "locked" costs is the *override*, not the escape.
 */
enum class Accountability(val id: String) {
    SELF("self"),
    LOCKED("locked");

    val title: String
        get() = when (this) {
            SELF -> "Self-managed"
            LOCKED -> "Locked"
        }

    val blurb: String
        get() = when (this) {
            SELF -> "It blocks you and logs it — but you can wave it away yourself. " +
                "No passcode, nobody is told. Start here."
            LOCKED -> "Overriding a block needs the passcode, and every block and override is " +
                "pushed to your accountability partner. Closing the app still always works."
        }

    /** Only a locked session holds its own exit. */
    val requiresPasscodeToEnd: Boolean get() = this == LOCKED
    val alertsPartner: Boolean get() = this == LOCKED

    companion object {
        fun from(id: String?): Accountability =
            entries.firstOrNull { it.id == id } ?: SELF     // fail towards the weaker mode
    }
}

/**
 * One declared stretch of work: a task in the user's own words, for a length of time, over a set
 * of apps, checked every [intervalSeconds].
 *
 * The app is organised around this rather than around an always-on mode, and that is a product
 * decision, not a refactor: **when no session is running, no screenshot is taken at all.** On
 * Android that matters more than anywhere else — the app holds an AccessibilityService that can
 * read the screen, and "only while you asked it to" is the difference between a tool people keep
 * installed and one they don't.
 */
data class FocusSession(
    val id: String = "fs_" + UUID.randomUUID().toString().take(10).lowercase(),
    val task: String,
    val startedAt: Long = System.currentTimeMillis(),
    /**
     * 0 means open-ended. Deliberately not offered for [Accountability.LOCKED] — an open-ended
     * locked session plus a forgotten passcode is the one shape that could genuinely trap someone.
     */
    val plannedMinutes: Int = 0,
    val intervalSeconds: Int = DEFAULT_INTERVAL,
    val accountability: Accountability = Accountability.SELF,
    /** One-off, this-session-only adjustments layered over the saved default watchlist. */
    val extraApps: Set<String> = emptySet(),
    val allowedApps: Set<String> = emptySet(),
    val providerId: String = "",
    var endedAt: Long? = null,
    var endedReason: String = "",
    var checks: Int = 0,
    var offTaskCount: Int = 0,
    var overrideCount: Int = 0,
    var pausedUntil: Long = 0L,
) {

    /**
     * The apps actually watched this session: your saved defaults, plus anything you added just for
     * today, minus anything you excused just for today.
     *
     * The exclusion is not a loophole — it is what makes a default list usable. If Slack is
     * normally a distraction but today's task *is* answering Slack, you shouldn't have to edit your
     * permanent settings and then forget to put them back.
     */
    fun watchlist(defaults: Set<String>): Set<String> =
        (defaults + extraApps) - allowedApps

    val isActive: Boolean get() = endedAt == null
    val elapsedMs: Long get() = (System.currentTimeMillis() - startedAt).coerceAtLeast(0)

    /** Milliseconds left, or null for an open-ended session. */
    val remainingMs: Long?
        get() = if (plannedMinutes <= 0) null
        else (plannedMinutes * 60_000L - elapsedMs).coerceAtLeast(0)

    val isOver: Boolean get() = remainingMs?.let { it <= 0 } ?: false
    val isPaused: Boolean get() = pausedUntil > System.currentTimeMillis()

    val remainingText: String
        get() {
            val left = remainingMs ?: return "open-ended"
            val mins = left / 60_000
            val secs = (left % 60_000) / 1000
            return "${mins}m ${secs.toString().padStart(2, '0')}s left"
        }

    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("task", task)
        put("started_at", startedAt)
        put("planned_minutes", plannedMinutes)
        put("interval_seconds", intervalSeconds)
        put("accountability", accountability.id)
        put("extra_apps", JSONArray(extraApps.toList()))
        put("allowed_apps", JSONArray(allowedApps.toList()))
        put("provider_id", providerId)
        put("ended_at", endedAt ?: JSONObject.NULL)
        put("ended_reason", endedReason)
        put("checks", checks)
        put("off_task_count", offTaskCount)
        put("override_count", overrideCount)
        put("paused_until", pausedUntil)
    }

    companion object {
        /**
         * Seconds between checks. Below a minute you pay for inference constantly and get
         * interrupted by transients; above five a real detour has already eaten the block it
         * should have stopped.
         */
        const val DEFAULT_INTERVAL = 120
        const val MIN_INTERVAL = 15
        const val MAX_INTERVAL = 3600

        fun clampInterval(seconds: Int): Int = seconds.coerceIn(MIN_INTERVAL, MAX_INTERVAL)

        private fun stringSet(o: JSONObject, key: String): Set<String> {
            val arr = o.optJSONArray(key) ?: return emptySet()
            return (0 until arr.length()).mapNotNull { arr.optString(it).takeIf(String::isNotEmpty) }
                .toSet()
        }

        fun fromJson(o: JSONObject): FocusSession = FocusSession(
            id = o.optString("id", "fs_unknown"),
            task = o.optString("task", ""),
            startedAt = o.optLong("started_at", System.currentTimeMillis()),
            plannedMinutes = o.optInt("planned_minutes", 0).coerceAtLeast(0),
            intervalSeconds = clampInterval(o.optInt("interval_seconds", DEFAULT_INTERVAL)),
            accountability = Accountability.from(o.optString("accountability")),
            extraApps = stringSet(o, "extra_apps"),
            allowedApps = stringSet(o, "allowed_apps"),
            providerId = o.optString("provider_id", ""),
        ).apply {
            endedAt = if (o.isNull("ended_at")) null else o.optLong("ended_at")
            endedReason = o.optString("ended_reason", "")
            checks = o.optInt("checks", 0)
            offTaskCount = o.optInt("off_task_count", 0)
            overrideCount = o.optInt("override_count", 0)
            pausedUntil = o.optLong("paused_until", 0L)
        }
    }
}

/**
 * The one active session, on disk, plus an append-only history of finished ones.
 *
 * Persistence is load-bearing, not a nicety: Android kills foreground services, and if a restart
 * silently cancelled a locked session then force-stopping the app would be a one-tap bypass and
 * "locked" would be worth nothing. The session file is the source of truth, so a relaunch — after
 * a crash, a kill, or a reboot — picks it back up where it was.
 */
object SessionStore {

    private const val SESSION_FILE = "focus_session.json"
    private const val HISTORY_FILE = "focus_history.jsonl"

    private var cached: FocusSession? = null
    private var loaded = false
    private val listeners = mutableListOf<() -> Unit>()

    private fun sessionFile(ctx: Context) = File(ctx.filesDir, SESSION_FILE)
    private fun historyFile(ctx: Context) = File(ctx.filesDir, HISTORY_FILE)

    fun subscribe(fn: () -> Unit) { listeners += fn }

    private fun notifyChanged() {
        listeners.toList().forEach { runCatching { it() } }
    }

    private fun load(ctx: Context) {
        if (loaded) return
        loaded = true
        cached = runCatching {
            val f = sessionFile(ctx)
            if (!f.exists()) return@runCatching null
            FocusSession.fromJson(JSONObject(f.readText())).takeIf { it.isActive }
        }.getOrNull()
    }

    /**
     * The live session, or null. Expiry is evaluated lazily on read so nothing depends on a timer
     * having fired — a phone that was in Doze past the end time still ends its session cleanly.
     */
    @Synchronized
    fun current(ctx: Context): FocusSession? {
        load(ctx)
        val s = cached ?: return null
        if (s.isOver) {
            end(ctx, "time's up")
            return null
        }
        return cached
    }

    fun isActive(ctx: Context): Boolean = current(ctx) != null

    @Synchronized
    fun start(ctx: Context, session: FocusSession): FocusSession {
        load(ctx)
        if (cached != null) end(ctx, "replaced by a new session")
        cached = session
        save(ctx)
        notifyChanged()
        return session
    }

    @Synchronized
    fun end(ctx: Context, reason: String = "ended") {
        load(ctx)
        val s = cached ?: return
        s.endedAt = System.currentTimeMillis()
        s.endedReason = reason
        runCatching { historyFile(ctx).appendText(s.toJson().toString() + "\n") }
        cached = null
        save(ctx)
        notifyChanged()
    }

    /**
     * Used by the block screen's override: stop checking for a bit so the user isn't re-blocked
     * mid-sentence while they finish what they said they needed to do.
     */
    @Synchronized
    fun pause(ctx: Context, millis: Long) {
        load(ctx)
        cached?.let {
            it.pausedUntil = System.currentTimeMillis() + millis.coerceAtLeast(0)
            save(ctx)
            notifyChanged()
        }
    }

    @Synchronized
    fun recordCheck(ctx: Context, offTask: Boolean) {
        load(ctx)
        cached?.let {
            it.checks += 1
            if (offTask) it.offTaskCount += 1
            save(ctx)
        }
    }

    @Synchronized
    fun recordOverride(ctx: Context) {
        load(ctx)
        cached?.let {
            it.overrideCount += 1
            save(ctx)
            notifyChanged()
        }
    }

    private fun save(ctx: Context) {
        runCatching {
            val f = sessionFile(ctx)
            val s = cached
            if (s == null) {
                f.delete()
            } else {
                // Write-then-rename: a kill mid-write must not leave a truncated session file,
                // because an unreadable session reads as "no session" and silently unlocks.
                val tmp = File(ctx.filesDir, "$SESSION_FILE.tmp")
                tmp.writeText(s.toJson().toString())
                tmp.renameTo(f)
            }
        }
    }

    /** Finished sessions, newest last. A torn final line after a hard kill is skipped, not fatal. */
    fun history(ctx: Context, limit: Int = 50): List<FocusSession> {
        val f = historyFile(ctx)
        if (!f.exists()) return emptyList()
        return runCatching {
            f.readLines().takeLast(limit).mapNotNull { line ->
                runCatching { FocusSession.fromJson(JSONObject(line)) }.getOrNull()
            }
        }.getOrDefault(emptyList())
    }

    /** Convenience for the widget and the start screen. */
    fun defaultsFor(ctx: Context): Set<String> = Prefs.get(ctx).monitoredPackages
}
