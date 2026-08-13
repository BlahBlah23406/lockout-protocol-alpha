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
import com.lockoutprotocol.guardian.capture.FrameQuality
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.push.Pusher
import com.lockoutprotocol.guardian.ui.BlockActivity
import com.lockoutprotocol.guardian.ui.LockActivity
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
 * The always-on heart of Guardian. Runs the random-interval loop, grabs a screenshot via the
 * accessibility service (NO MediaProjection / no recording indicator), classifies it with
 * Ollama, and enforces blocks + alerts.
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

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs.get(this)
        ai = OllamaClient(prefs)
        isRunning = true
        // New apps are monitored by default. Catch up on anything installed while we were down,
        // then listen live for future installs.
        AutoMonitor.syncNewInstalls(this)
        ContextCompat.registerReceiver(
            this, pkgReceiver,
            IntentFilter(Intent.ACTION_PACKAGE_ADDED).apply { addDataScheme("package") },
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, NOTIF_ID, buildNotification("Monitoring active"), type)
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
                // Cadence is driven by the model: tick() captures and BLOCKS until qwen replies,
                // then we immediately loop and grab the next screenshot. tick() returns true when
                // it actually ran on a monitored app, so we keep a tiny floor between captures;
                // otherwise we poll more lazily.
                val active = runCatching { tick() }.getOrDefault(false)
                delay(if (active) MIN_GAP_MS else IDLE_POLL_MS)
            }
        }
    }

    /** Returns true if a monitored app was on screen and was actually checked. */
    private suspend fun tick(): Boolean {
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
