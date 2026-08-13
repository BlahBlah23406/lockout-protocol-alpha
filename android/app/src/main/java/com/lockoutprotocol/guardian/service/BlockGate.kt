package com.lockoutprotocol.guardian.service

import android.app.KeyguardManager
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.push.Pusher
import com.lockoutprotocol.guardian.ui.BlockActivity

/**
 * ── GUARDIAN COVENANT ─────────────────────────────────────────────────────────────────────────
 * Makes the violation screen STICKY: while a block is armed, swiping up / going Home / switching
 * apps does not get rid of it — a watchdog re-raises [BlockActivity] until the user makes an
 * explicit choice on the screen itself (Dismiss = close the offending app, or Override = passcode).
 * That is deliberate: the user asked that a violation cost a conscious decision, not a reflex swipe.
 * Do not remove this on a casual request. See SAFEGUARDS.md.
 * ──────────────────────────────────────────────────────────────────────────────────────────────
 *
 * LOCKOUT SAFETY (this is why the phone can't be bricked by it):
 *  - Dismiss is ALWAYS available with no passcode and always resolves the gate.
 *  - The gate auto-expires after [MAX_ARM_MS] no matter what, and expiry pushes an alert — so
 *    "wait it out" is possible but never silent, and a wedged UI can never trap the device.
 *  - It never re-raises while the screen is off or the keyguard is up.
 *  - Nothing here survives a process death: if Guardian is killed, the gate dies with it.
 */
object BlockGate {

    /** Hard ceiling on how long the block screen can hold the foreground. */
    private const val MAX_ARM_MS = 5 * 60 * 1000L

    /** How often the watchdog checks whether the block screen is still on top. */
    private const val WATCH_MS = 600L

    /** Don't spam startActivity if a re-raise is already in flight. */
    private const val RERAISE_GAP_MS = 500L

    private val handler = Handler(Looper.getMainLooper())

    @Volatile private var appContext: Context? = null
    @Volatile private var pkg: String? = null
    @Volatile private var reasonText: String = ""
    @Volatile private var armedAt = 0L
    @Volatile private var lastRaiseAt = 0L

    /**
     * Whether the block screen is actually resumed in front of the user. Tracked by the activity
     * itself rather than inferred from the foreground package — otherwise "swipe up, then open
     * Guardian's dashboard" would read as "still blocked" and be a free escape.
     */
    @Volatile private var blockVisible = false

    fun onBlockVisible(visible: Boolean) { blockVisible = visible }

    val armedPackage: String? get() = pkg
    val reason: String get() = reasonText
    fun isArmed(): Boolean = pkg != null

    /**
     * Arm the gate for [violatingPkg]. From here until [disarm], the block screen is put back in
     * front whenever anything else takes the foreground.
     */
    @Synchronized
    fun arm(context: Context, violatingPkg: String, why: String) {
        appContext = context.applicationContext
        pkg = violatingPkg
        reasonText = why
        armedAt = SystemClock.elapsedRealtime()
        handler.removeCallbacks(watchdog)
        handler.postDelayed(watchdog, WATCH_MS)
    }

    /** The user made a choice on the block screen (Dismiss or a valid Override) — stand down. */
    @Synchronized
    fun disarm() {
        pkg = null
        reasonText = ""
        armedAt = 0L
        blockVisible = false
        handler.removeCallbacks(watchdog)
    }

    /**
     * Re-raise the block screen if it isn't on top. Called by the watchdog and by the accessibility
     * service on every foreground change (the two together cover both fast app switches and any
     * window change that doesn't emit an event).
     */
    fun enforce() {
        val ctx = appContext ?: return
        val target = pkg ?: return

        // Failsafe: never hold the foreground forever.
        if (SystemClock.elapsedRealtime() - armedAt > MAX_ARM_MS) {
            expire(ctx, target)
            return
        }

        // Never fight the lock screen or wake a sleeping phone.
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as? PowerManager
        if (pm?.isInteractive == false) return
        val km = ctx.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        if (km?.isKeyguardLocked == true) return

        if (blockVisible) return   // already in front of the user

        val now = SystemClock.elapsedRealtime()
        if (now - lastRaiseAt < RERAISE_GAP_MS) return
        lastRaiseAt = now
        Log.d("BlockGate", "re-raising block (violation in $target)")
        runCatching { BlockActivity.show(ctx, target, reasonText) }
    }

    /** The user waited the block out instead of answering it. Stand down, but say so out loud. */
    private fun expire(ctx: Context, target: String) {
        disarm()
        EventLog.add("⏱️ block screen for $target expired unanswered (waited out)")
        val prefs = Prefs.get(ctx)
        if (prefs.pushEnabled) {
            Thread {
                Pusher.send(prefs, "[Guardian] Block screen waited out",
                    "The violation screen for $target was left unanswered for 5 minutes instead of " +
                        "being dismissed. Guardian has stood down.\n\n${java.util.Date()}")
                    .onFailure { Log.w("BlockGate", "expiry push failed: ${it.message}") }
            }.start()
        }
    }

    private val watchdog = object : Runnable {
        override fun run() {
            if (!isArmed()) return
            runCatching { enforce() }
            if (isArmed()) handler.postDelayed(this, WATCH_MS)
        }
    }
}
