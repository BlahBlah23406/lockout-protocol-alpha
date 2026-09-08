package com.lockoutprotocol.guardian.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.lockoutprotocol.guardian.App
import com.lockoutprotocol.guardian.ai.AlertPolicy
import com.lockoutprotocol.guardian.ai.OllamaClient
import com.lockoutprotocol.guardian.ai.Providers
import com.lockoutprotocol.guardian.capture.FrameQuality
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Judgements
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.data.contentRulesEnabled
import com.lockoutprotocol.guardian.data.focusNotes
import com.lockoutprotocol.guardian.data.learningEnabled
import com.lockoutprotocol.guardian.data.providerConfig
import com.lockoutprotocol.guardian.focus.FocusSession
import com.lockoutprotocol.guardian.focus.LearnedPolicy
import com.lockoutprotocol.guardian.focus.SessionStore
import com.lockoutprotocol.guardian.push.Pusher
import com.lockoutprotocol.guardian.ui.BlockActivity
import com.lockoutprotocol.guardian.ui.LockActivity
import com.lockoutprotocol.guardian.widget.FocusWidget
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The monitoring loop. Two modes meet here:
 *
 * **Focus mode** (the product). A session is running — the user declared a task like "revising
 * integration by parts" — so every `intervalSeconds` we screenshot whichever watched app is in
 * front and ask the model whether that screen belongs to that task.
 *
 * **Content rules** (opt-in, off by default). The original behaviour: an always-on classifier
 * checking screens against written content guidelines.
 *
 * The most important structural change: **when no session is running, no screenshot is taken at
 * all.** Not captured and discarded — never taken. On Android that matters more than anywhere
 * else, because this app holds an AccessibilityService that can read the screen, and "only while
 * you asked it to" is the difference between a tool people keep installed and one they don't.
 *
 * Cadence follows the session's interval rather than how fast the model answers. The old loop
 * fired again 1.2s after each reply, which is right for content safety (one frame of the wrong
 * thing matters) and wrong here: it would burn hundreds of calls an hour, and a phone's battery,
 * on a question whose answer changes over minutes.
 */
class MonitorService : Service() {

    private val scope = CoroutineScope(Dispatchers.Default + Job())
    private lateinit var prefs: Prefs
    private lateinit var ai: OllamaClient

    private var loopJob: Job? = null

    /** Auto-enrolls newly installed apps into the monitored set while the service is alive. */
    private val pkgReceiver = PackageInstallReceiver()

    /** Per-package throttle so persistently-unverifiable apps don't spam the alert channel. */
    private val lastAlertAt = ConcurrentHashMap<String, Long>()

    /**
     * When the next focus check is due, per package. Keyed by app so switching apps checks the new
     * one promptly instead of inheriting the previous app's countdown — the moment you switch into
     * a distraction is exactly the moment worth looking — while still rate-limiting each app so
     * flicking back and forth can't force a check storm.
     */
    private val nextCheckAt = ConcurrentHashMap<String, Long>()

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs.get(this)
        ai = OllamaClient(prefs)
        isRunning = true
        Judgements.trim(this)
        // New apps are monitored by default. Catch up on anything installed while we were down,
        // then listen live for future installs. This is a content-rules defence (installing a
        // fresh browser shouldn't be a free pass); in focus mode the watchlist is whatever the
        // user picked for the session, so a new install is simply not watched until they say so.
        AutoMonitor.syncNewInstalls(this)
        ContextCompat.registerReceiver(
            this, pkgReceiver,
            IntentFilter(Intent.ACTION_PACKAGE_ADDED).apply { addDataScheme("package") },
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(statusText()), type)
        // Loop runs CONTINUOUSLY for the life of the service. Detecting/blocking something must
        // never stop monitoring — each tick decides per-frame whether the current foreground app
        // is monitored, and simply skips if not.
        startLoop()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        // Any other start (boot, watchdog, foreground-change poke, START_STICKY restart) just
        // makes sure the loop is alive.
        if (loopJob == null || loopJob?.isActive == false) startLoop()
        return START_STICKY
    }

    private fun startLoop() {
        loopJob?.cancel()
        loopJob = scope.launch {
            while (isActive) {
                // tick() returns how long to wait. In focus mode that is the session's interval;
                // in content-rules mode it is the old response-driven floor.
                val wait = runCatching { tick() }.getOrElse {
                    // A crash in the loop is itself a bypass; log it and keep going.
                    EventLog.add("\u26a0\ufe0f monitor tick failed: ${it.message}")
                    IDLE_POLL_MS
                }
                delay(wait.coerceAtLeast(500L))
            }
        }
    }

    /** Do at most one unit of work. Returns how many milliseconds to wait before the next tick. */
    private suspend fun tick(): Long {
        val session = SessionStore.current(this)
        if (session != null) return focusTick(session)
        if (prefs.contentRulesEnabled) {
            return if (contentTick()) MIN_GAP_MS else IDLE_POLL_MS
        }
        // Nothing to do: no session, content rules off. Explicitly *not* capturing anything.
        return IDLE_POLL_MS
    }

    // ---- focus mode ------------------------------------------------------------------------

    private suspend fun focusTick(session: FocusSession): Long {
        val interval = session.intervalSeconds * 1000L

        if (session.isPaused) {
            val left = (session.pausedUntil - System.currentTimeMillis()).coerceAtLeast(0)
            return minOf(left + 500, interval)
        }

        val a11y = AppWatchAccessibilityService.instance
        if (a11y == null) {
            // Accessibility is our only capture path. Losing it is a real blind spot, reported by
            // the tamper guard — but it is never a block, and never a reason to stop the loop.
            Log.w("MonitorService", "accessibility service unavailable; skipping tick")
            return IDLE_POLL_MS
        }

        val fg = a11y.topAppPackage() ?: ForegroundApp.current
        val watchlist = session.watchlist(prefs.monitoredPackages)
        if (fg.isBlank() || fg !in watchlist) {
            // Not a watched app. In focus mode this is the normal, uninteresting case.
            return FOCUS_IDLE_POLL_MS
        }
        if (Overrides.isActive(fg)) return FOCUS_IDLE_POLL_MS

        val due = nextCheckAt[fg] ?: 0L
        val now = System.currentTimeMillis()
        if (now < due) return minOf(due - now, FOCUS_IDLE_POLL_MS)

        val screenTitle = a11y.topScreenTitle()
        val dry = prefs.dryRun

        // The learner can pre-allow a signature the user has repeatedly excused. Checked BEFORE
        // the capture, so a confirmed-fine screen costs no screenshot and no inference at all.
        if (prefs.learningEnabled) {
            val learned = LearnedPolicy.decide(this, session.task, fg, screenTitle)
            if (learned.preAllow) {
                EventLog.add("\u23e9 $fg skipped \u2014 you've confirmed this is part of the task")
                nextCheckAt[fg] = now + interval
                return interval
            }
        }

        val capStart = SystemClock.elapsedRealtime()
        var frame = a11y.captureScreenshot()
        if (frame == null) { delay(1200); frame = a11y.captureScreenshot() }
        val capMs = SystemClock.elapsedRealtime() - capStart

        if (frame == null) {
            handleUnverifiable(fg, "screen could not be captured", dry)
            nextCheckAt[fg] = System.currentTimeMillis() + interval
            return interval
        }
        if (FrameQuality.isUnreadable(frame)) {
            handleUnverifiable(fg, "screen is hidden (incognito or screenshot-protected)", dry)
            nextCheckAt[fg] = System.currentTimeMillis() + interval
            return interval
        }

        val cfg = prefs.providerConfig()
        val notes = extraNotes(session, fg, screenTitle)
        val aiStart = SystemClock.elapsedRealtime()
        val verdict = withContext(Dispatchers.IO) {
            Providers.evaluate(cfg, frame, session.task, shortName(fg), screenTitle,
                extraNotes = notes, onKeyWorked = { prefs.promoteApiKey(it) })
        }
        val aiMs = SystemClock.elapsedRealtime() - aiStart

        // Transient backend trouble is never evidence about the user: log, retry sooner, no block.
        if (verdict.transient) {
            EventLog.add("\u23f3 $fg \u2014 AI unavailable (${verdict.reason}) \u2014 skipped")
            nextCheckAt[fg] = System.currentTimeMillis() + TRANSIENT_RETRY_MS
            return TRANSIENT_RETRY_MS
        }

        nextCheckAt[fg] = System.currentTimeMillis() + interval

        if (verdict.undetermined) {
            handleUnverifiable(fg, "AI could not analyse (${verdict.reason})", dry)
            return interval
        }

        if (verdict.onTask) {
            SessionStore.recordCheck(this, offTask = false)
            Judgements.record(this, session, fg, shortName(fg), screenTitle, "on_task",
                verdict.reason, verdict.confidence, "allowed", cfg.describe())
            EventLog.add("\u2705 $fg on task (${capMs}ms cap, ${aiMs}ms ai)")
            FocusWidget.refresh(this)
            return interval
        }

        // Off task. The learner may have raised the confidence bar for this (app, task) pair after
        // repeated false alarms; below the bar we record it but don't interrupt.
        val threshold = if (prefs.learningEnabled) {
            LearnedPolicy.decide(this, session.task, fg, screenTitle).blockThreshold
        } else {
            0.0
        }
        val belowBar = threshold > 0.0 && verdict.confidence < threshold

        SessionStore.recordCheck(this, offTask = true)
        val action = if (dry || belowBar) "logged" else "blocked"
        val jid = Judgements.record(this, session, fg, shortName(fg), screenTitle, "off_task",
            verdict.reason, verdict.confidence, action, cfg.describe())

        when {
            belowBar -> EventLog.add(
                "\u2139\ufe0f $fg off task but only ${"%.2f".format(verdict.confidence)} sure " +
                    "(bar is ${"%.2f".format(threshold)}) \u2014 logged, not blocked")
            dry -> EventLog.add("\ud83d\udfe0 $fg WOULD BLOCK \u2014 off task (${aiMs}ms) \u2014 " +
                "${verdict.reason} [TEST]")
            else -> {
                EventLog.add("\ud83d\udeab $fg OFF TASK (${aiMs}ms) \u2014 ${verdict.reason}")
                enforceOffTask(session, fg, verdict.reason, jid)
            }
        }
        FocusWidget.refresh(this)
        return interval
    }

    /**
     * Standing notes handed to the classifier: the user's own, plus anything the experimental
     * learner has concluded. Both capped hard — a prompt suffix that grows without bound
     * eventually costs more than the screenshot does.
     */
    private fun extraNotes(session: FocusSession, pkg: String, title: String): String {
        val parts = mutableListOf(prefs.focusNotes.trim())
        if (prefs.learningEnabled) {
            // The learner is experimental; it must never be able to break a check.
            parts += runCatching {
                LearnedPolicy.promptSuffix(this, session.task, pkg, title)
            }.getOrDefault("")
        }
        return parts.filter { it.isNotEmpty() }.joinToString("\n").take(1500)
    }

    /**
     * Raise the block. What the block *offers* depends on the accountability level the session was
     * started at — read from the session, not from a global setting that could have drifted since.
     */
    private suspend fun enforceOffTask(
        session: FocusSession, pkg: String, reason: String, judgementId: String
    ) {
        prefs.lastViolationAt = System.currentTimeMillis()
        withContext(Dispatchers.Main) {
            BlockActivity.show(this@MonitorService, pkg, reason,
                sessionTask = session.task,
                locked = session.accountability.requiresPasscodeToEnd,
                judgementId = judgementId)
        }
        if (!session.accountability.alertsPartner) return
        sendAlert(pkg, "[Lockout] Off task in ${shortName(pkg)}",
            "Task: ${session.task}\n\n${shortName(pkg)} was blocked.\nReason: $reason",
            throttle = false)
    }

    // ---- content-rules mode (opt-in; the original behaviour) --------------------------------

    /** Returns true if a monitored app was on screen and was actually checked. */
    private suspend fun contentTick(): Boolean {
        val monitored = prefs.monitoredPackages

        val a11y = AppWatchAccessibilityService.instance
        if (a11y == null) {
            // Accessibility (our only capture path) is off — can't see anything; ask user to enable.
            Log.w("MonitorService", "accessibility service unavailable; skipping tick")
            return false
        }

        // Resolve the REAL foreground app (ignores keyboard / status bar / overlays).
        val fg = a11y.topAppPackage() ?: ForegroundApp.current
        Log.d("MonitorService", "tick fg=$fg onMonitored=${fg in monitored}")
        if (fg.isBlank() || fg !in monitored) return false

        // User overrode this app from the block screen — leave it alone until it loses & regains focus.
        if (Overrides.isActive(fg)) {
            Log.d("MonitorService", "override active for $fg, skipping")
            return false
        }

        // Grab a screenshot; retry once after the system's ~1s screenshot rate-limit window.
        val capStart = SystemClock.elapsedRealtime()
        var frame = a11y.captureScreenshot()
        if (frame == null) { delay(1200); frame = a11y.captureScreenshot() }
        val capMs = SystemClock.elapsedRealtime() - capStart
        Log.d("MonitorService", "capture frame=${frame?.width}x${frame?.height} for $fg (${capMs}ms)")
        val dry = prefs.dryRun
        EventLog.add("📷 screenshot $fg (${capMs}ms capture)${if (dry) " [TEST]" else ""}")
        toast("Screenshot: ${shortName(fg)}")

        // 1. Couldn't capture at all -> can't verify (safe handling, never an overlay).
        if (frame == null) {
            handleUnverifiable(fg, "screen could not be captured", dry)
            return true
        }

        // 2. Captured but blank/black -> incognito / FLAG_SECURE -> can't verify.
        if (FrameQuality.isUnreadable(frame)) {
            handleUnverifiable(fg, "screen is hidden (incognito or screenshot-protected)", dry)
            return true
        }

        // 3. Ask the AI (timed — this is the dominant cost).
        val aiStart = SystemClock.elapsedRealtime()
        val verdict = withContext(Dispatchers.IO) { ai.evaluate(frame) }
        val aiMs = SystemClock.elapsedRealtime() - aiStart
        Log.d("MonitorService", "AI Evaluation: pkg=$fg, violation=${verdict.violation}, undetermined=${verdict.undetermined}, reason=${verdict.reason} (${aiMs}ms, model=${prefs.ollamaModel})")
        when {
            verdict.violation -> {
                val cat = AlertPolicy.label(verdict.category)
                val notify = AlertPolicy.shouldAlert(verdict.category, prefs.alertOnSuggestive)
                if (dry) {
                    EventLog.add("🟠 $fg WOULD BLOCK & CLOSE [$cat, ${if (notify) "would alert" else "quiet"}] " +
                        "(${aiMs}ms) — ${verdict.reason} [TEST]")
                    toast("WOULD block: ${shortName(fg)} — ${verdict.reason}")
                } else {
                    EventLog.add("🚫 $fg VIOLATION [$cat${if (notify) "" else ", quiet"}] (${aiMs}ms) — ${verdict.reason}")
                    enforceViolation(fg, verdict.reason, cat, notify)
                }
            }
            // Transient backend hiccup (HTTP 503/429/5xx, timeout). This is the AI being busy, NOT
            // the user hiding anything — so we NEVER close the app here. Just log and move on; the
            // next tick retries. (This is the fix for "kept closing my other apps on a 503".)
            verdict.transient -> {
                EventLog.add("⏳ $fg AI busy — skipped (${aiMs}ms) — ${verdict.reason}")
                toast("AI busy, skipped: ${shortName(fg)}")
            }
            // AI reached but answer unparseable -> can't verify -> safe handling (alert only, no overlay).
            verdict.undetermined -> handleUnverifiable(fg, "AI could not analyse (${verdict.reason})", dry)
            else -> {
                EventLog.add("✅ $fg cleared (${aiMs}ms, ${prefs.ollamaModel})")
                toast("Cleared: ${shortName(fg)}")
            }
        }
        return true
    }

    /**
     * A monitored app's screen could NOT be verified (incognito/FLAG_SECURE black frame, capture
     * failure, or AI unreachable). This NEVER shows the PIN-locked overlay — that's the thing that
     * locked the phone. Instead it logs, alerts the accountability contact (throttled), and — only
     * if the user opted in — sends them Home (which is always escapable).
     */
    private suspend fun handleUnverifiable(pkg: String, why: String, dry: Boolean) {
        if (dry) {
            EventLog.add("🙈 $pkg CAN'T SEE — $why — would alert [TEST]")
            toast("Can't see: ${shortName(pkg)}")
            return
        }
        EventLog.add("🙈 $pkg CAN'T SEE — $why")
        if (prefs.alertOnUnverifiable) {
            sendAlert(pkg, "[Guardian] Couldn't verify $pkg (possible private/incognito)",
                "Guardian could not see what was on screen in $pkg ($why). This can happen with " +
                "incognito/private mode or screenshot-protected apps.", throttle = true)
        }
        if (prefs.closeUnverifiable) {
            withContext(Dispatchers.Main) {
                Toast.makeText(this@MonitorService, "Guardian closed ${shortName(pkg)} (can't verify)", Toast.LENGTH_SHORT).show()
            }
            AppWatchAccessibilityService.instance?.closeApp(pkg)
        }
    }

    private suspend fun toast(msg: String) = withContext(Dispatchers.Main) {
        Toast.makeText(this@MonitorService, msg, Toast.LENGTH_SHORT).show()
    }

    private fun shortName(pkg: String) = pkg.substringAfterLast('.')

    /**
     * Confirmed guideline violation: raise the block overlay over the app (it stays alive in the
     * background so Override can return to it). The overlay is STICKY — [BlockGate] keeps putting it
     * back until its Override/Dismiss buttons are actually pressed; Dismiss is what closes the app.
     *
     * [notify] comes from [AlertPolicy]: every violation blocks and is logged, but only the
     * deliberate ones (tampering / searched for it / a site for it / explicit on screen) push the
     * accountability contact. Mild incidental flags block quietly.
     */
    private suspend fun enforceViolation(
        pkg: String, reason: String, category: String, notify: Boolean
    ) {
        prefs.lastViolationAt = System.currentTimeMillis()
        withContext(Dispatchers.Main) {
            Toast.makeText(this@MonitorService, "Guardian flagged ${shortName(pkg)}", Toast.LENGTH_SHORT).show()
            BlockActivity.show(this@MonitorService, pkg, reason)
        }
        if (!notify) return
        sendAlert(pkg, "[Guardian] Flagged $pkg ($category)",
            "Guardian flagged the screen in $pkg.\n\nWhy it alerted: $category\nReason: $reason",
            throttle = false)
    }

    private suspend fun sendAlert(
        pkg: String, subject: String, body: String, throttle: Boolean
    ) {
        if (throttle) {
            val last = lastAlertAt[pkg] ?: 0L
            if (System.currentTimeMillis() - last < ALERT_THROTTLE_MS) return
            lastAlertAt[pkg] = System.currentTimeMillis()
        }
        val fullBody = "$body\n\n${java.util.Date()}"
        withContext(Dispatchers.IO) {
            // Primary: zero-setup push notification.
            if (prefs.pushEnabled) {
                Pusher.send(prefs, subject, fullBody)
                    .onFailure { Log.w("MonitorService", "push failed: ${it.message}") }
            }
        }
    }

    /**
     * What the persistent notification says. It has to be honest about whether anything is being
     * watched: a foreground-service notification that reads "Monitoring active" while no session
     * is running would be the app misrepresenting itself to the user, in the one place Android
     * guarantees they will see it.
     */
    private fun statusText(): String {
        val session = SessionStore.current(this)
        return when {
            session != null -> "Focus: ${session.task.take(40)} \u00b7 ${session.remainingText}"
            prefs.contentRulesEnabled -> "Content rules active"
            else -> "No session \u2014 nothing is being watched"
        }
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, LockActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, App.CHANNEL_SERVICE)
            .setContentTitle("Guardian")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
            .setOngoing(true)
            .setContentIntent(open)
            .build()
    }

    override fun onDestroy() {
        isRunning = false
        runCatching { unregisterReceiver(pkgReceiver) }
        loopJob?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        @Volatile var isRunning = false; private set

        private const val NOTIF_ID = 4242
        private const val ACTION_STOP = "action.stop"
        const val ACTION_UPDATE_FOREGROUND = "action.update_foreground"
        const val EXTRA_PKG = "pkg"

        // Floor between back-to-back checks while on a monitored app (respects the ~1s
        // accessibility screenshot rate limit and prevents a tight loop on instant errors).
        private const val MIN_GAP_MS = 1_200L
        // Lazier poll when no monitored app is on screen.
        private const val IDLE_POLL_MS = 2_500L

        // Focus mode: how often we re-check WHICH app is in front while not on a watched app.
        // Cheap (an accessibility node read, no capture, no inference) so it can be brisk.
        private const val FOCUS_IDLE_POLL_MS = 3_000L

        // After a transient backend failure, retry sooner than a full interval but not instantly.
        private const val TRANSIENT_RETRY_MS = 20_000L

        // Don't re-alert about the same unverifiable app more than once per 10 minutes.
        private const val ALERT_THROTTLE_MS = 10 * 60 * 1000L

        /** Start (or poke) the monitor. No projection consent needed anymore. */
        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, MonitorService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, MonitorService::class.java).apply { action = ACTION_STOP })
        }
    }
}
