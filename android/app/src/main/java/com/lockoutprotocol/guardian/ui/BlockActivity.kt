package com.lockoutprotocol.guardian.ui

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.ScrollView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Judgements
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.data.learningEnabled
import com.lockoutprotocol.guardian.focus.SessionStore
import com.lockoutprotocol.guardian.push.Pusher
import com.lockoutprotocol.guardian.service.AppWatchAccessibilityService
import com.lockoutprotocol.guardian.service.BlockGate
import com.lockoutprotocol.guardian.service.Overrides
import com.lockoutprotocol.guardian.widget.FocusWidget
import kotlin.concurrent.thread

/**
 * Full-screen block shown over an off-task app (which stays alive in the background).
 *
 * This screen is STICKY: swiping up, pressing Home, Back, or switching apps does NOT get rid of it
 * — [BlockGate] puts it straight back. The only ways out are the buttons, and which buttons appear
 * is the entire difference between the two accountability levels a session can be started at:
 *
 *  - **Self-managed** — "Not now" closes the app; "I'm on task" waves the block away with no
 *    passcode. You are being interrupted and it is going in the log, but you are the one holding
 *    the line.
 *  - **Locked** — "Not now" still works with no passcode. What locked costs is the *override*: to
 *    keep using the app you need the passcode, and the partner is told either way.
 *
 * Safety: the no-passcode exit is present at EVERY level, it can never fail to release the gate,
 * and the gate self-expires after 5 minutes. This screen cannot lock anyone out of their phone —
 * see SAFEGUARDS.md. That is not negotiable, and a "locked" session does not change it.
 */
class BlockActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private var pkg: String = ""
    /** The task the user declared, or "" for a content-rules block, which has no session. */
    private var sessionTask: String = ""
    /** Whether this block came from a LOCKED session (passcode required to override). */
    private var locked: Boolean = false
    /** Ties a later "false alarm" tap back to the exact check that caused this block. */
    private var judgementId: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
        )
        setShowWhenLocked(true)
        setTurnScreenOn(true)

        prefs = Prefs.get(this)
        val reason = intent.getStringExtra(EXTRA_REASON).orEmpty()
        pkg = intent.getStringExtra(EXTRA_PKG).orEmpty()
        readSessionExtras(intent)

        // Hold the foreground until a button is pressed. Re-arming on a re-raise is harmless: the
        // gate keeps its original arm time, so the 5-minute failsafe can't be reset by bouncing.
        if (!BlockGate.isArmed()) BlockGate.arm(this, pkg, reason)

        buildUi(reason)
    }

    /** A re-raise while we're already alive (singleTask) lands here — just refresh the text. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra(EXTRA_PKG)?.takeIf { it.isNotBlank() }?.let { pkg = it }
        readSessionExtras(intent)
        buildUi(intent.getStringExtra(EXTRA_REASON).orEmpty())
    }

    private fun readSessionExtras(from: Intent) {
        sessionTask = from.getStringExtra(EXTRA_TASK).orEmpty()
        locked = from.getBooleanExtra(EXTRA_LOCKED, false)
        judgementId = from.getStringExtra(EXTRA_JUDGEMENT).orEmpty()
    }

    private fun buildUi(reason: String) {
        val isFocusBlock = sessionTask.isNotEmpty()

        // A passcode is only required for a LOCKED session (or a content-rules block, which keeps
        // the original behaviour). In a self-managed session the override is free by design — the
        // interruption and the log entry are the accountability, not a code.
        val needsPin = prefs.pinSet && (locked || !isFocusBlock)

        val root = Lcars.root(this).apply { gravity = Gravity.CENTER }

        if (isFocusBlock) {
            root.addView(Lcars.header(this, if (locked) "Locked session" else "Off task",
                Lcars.RED))
            root.addView(Lcars.titleBig(this, "Off Task", Lcars.RED))
            root.addView(Lcars.body(this, "YOU SAID YOU WERE:").apply {
                setTextColor(Lcars.LILAC); gravity = Gravity.CENTER; letterSpacing = 0.15f
            })
            root.addView(Lcars.body(this, sessionTask).apply {
                setTextColor(Lcars.GOLD); gravity = Gravity.CENTER; textSize = 18f
            })
        } else {
            root.addView(Lcars.header(this, "Violation", Lcars.RED))
            root.addView(Lcars.titleBig(this, "\u2298 Access Denied", Lcars.RED))
            root.addView(Lcars.body(this, "GUARDIAN SECURITY \u00b7 RED ALERT").apply {
                setTextColor(Lcars.RED); gravity = Gravity.CENTER; letterSpacing = 0.2f
            })
        }

        root.addView(Lcars.spacer(this, 20))
        root.addView(Lcars.panel(this, blockBody(reason, isFocusBlock, needsPin), Lcars.GOLD))

        val pin = Lcars.input(this, "Passcode to override", numeric = true, password = true)
            .apply { visibility = if (needsPin) View.VISIBLE else View.GONE }
        root.addView(pin)

        // The compliant exit is listed FIRST: going back to work should be the path of least
        // resistance, not the override.
        root.addView(Lcars.pill(this, "Not now \u00b7 close app", Lcars.ORANGE) { dismissAndClose() })

        val overrideLabel = if (needsPin) "Override" else "I'm on task \u00b7 keep using it"
        root.addView(Lcars.pill(this, overrideLabel, Lcars.RED) {
            if (!needsPin || prefs.checkPin(pin.text.toString())) {
                grantOverride()
            } else {
                Toast.makeText(this@BlockActivity, "Wrong passcode", Toast.LENGTH_SHORT).show()
            }
        })

        // Experimental: only when learning is on, and only for focus blocks.
        if (isFocusBlock && prefs.learningEnabled && judgementId.isNotEmpty()) {
            root.addView(Lcars.pill(this,
                "This was a false alarm \u2014 it IS part of my task", Lcars.BLUE) {
                Judgements.addFeedback(this, judgementId, Judgements.FB_FALSE_ALARM)
                EventLog.add("\ud83d\udcdd marked false alarm: $pkg")
                grantOverride()
            })
        }

        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun blockBody(reason: String, isFocusBlock: Boolean, needsPin: Boolean): String {
        val why = reason.ifEmpty { "This screen isn't part of the declared task." }
        val tail = when {
            !isFocusBlock && needsPin ->
                "Swiping away won't clear this. Dismiss to close the app \u2014 or Override with " +
                    "your passcode to keep using it until you leave it."
            !isFocusBlock ->
                "Swiping away won't clear this. Tap Dismiss to close the app."
            needsPin ->
                "Swiping away won't clear this. This session is LOCKED: overriding needs the " +
                    "passcode, and your accountability partner is notified either way. Closing " +
                    "the app needs no passcode."
            else ->
                "Swiping away won't clear this. This session is self-managed \u2014 nobody else " +
                    "is told. Overriding is logged and counted in your session summary."
        }
        return "$why\n\n$tail"
    }

    /**
     * "Override" — keep using the app. Also pauses the *session* briefly, not just this app: being
     * re-challenged 90 seconds after you deliberately said "yes, I need this" is how a monitor
     * teaches people to ignore it.
     */
    private fun grantOverride() {
        EventLog.add("\ud83d\udd13 override granted for $pkg")
        Overrides.grant(pkg)

        val session = SessionStore.current(this)
        if (session != null) {
            SessionStore.recordOverride(this)
            SessionStore.pause(this,
                minOf(300_000L, maxOf(session.intervalSeconds * 2_000L, 120_000L)))
            if (session.accountability.alertsPartner) {
                alertOverride(session.task, session.overrideCount + 1)
            }
        }
        BlockGate.disarm()
        FocusWidget.refresh(this)
        finish()
    }

    /**
     * A locked session that gets overridden is exactly the event a partner signed up to hear
     * about — the block itself is only half the story. Fire-and-forget on a background thread:
     * the override must not wait on the network, and a failed push must not trap the user here.
     */
    private fun alertOverride(task: String, count: Int) {
        val p = prefs
        val name = pkg.substringAfterLast('.')
        thread(name = "lockout-override-alert") {
            runCatching {
                Pusher.send(p, "[Lockout] Override used in $name",
                    "Task: $task\n\nThe block on $name was overridden with the passcode. " +
                        "That is override #$count this session.")
            }
        }
    }

    /** Close this overlay, then force-close the offending app and land on the home screen. */
    private fun dismissAndClose() {
        val a11y = AppWatchAccessibilityService.instance
        val p = pkg
        EventLog.add("✋ block dismissed — closing $p")
        // Release the gate FIRST so the watchdog doesn't re-raise us over the close.
        BlockGate.disarm()
        // Close the overlay so the offending app becomes the top Recents card.
        finish()
        if (a11y != null && p.isNotEmpty()) {
            a11y.forceClose(p)   // kill + clear its task + home (always ends on home)
        } else {
            startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    /**
     * Back does NOT dismiss — dismissing has to be a deliberate tap on the button, because that
     * button is what closes the offending app.
     */
    @Deprecated("Back is intentionally inert on the block screen")
    override fun onBackPressed() {
        Toast.makeText(this, "Choose Dismiss to close the app", Toast.LENGTH_SHORT).show()
    }

    override fun onResume() {
        super.onResume()
        BlockGate.onBlockVisible(true)
    }

    /** Home / swipe-up / recents / another app: let the gate put us straight back. */
    override fun onPause() {
        super.onPause()
        BlockGate.onBlockVisible(false)
        if (BlockGate.isArmed()) BlockGate.enforce()
    }

    companion object {
        private const val EXTRA_PKG = "pkg"
        private const val EXTRA_REASON = "reason"
        private const val EXTRA_TASK = "task"
        private const val EXTRA_LOCKED = "locked"
        private const val EXTRA_JUDGEMENT = "judgement"

        /**
         * Raise the block. [sessionTask] empty means a content-rules block (no session), which
         * keeps the original passcode-gated behaviour; [locked] carries the session's
         * accountability level so the screen shows the right exits.
         */
        fun show(
            ctx: Context,
            pkg: String,
            reason: String,
            sessionTask: String = "",
            locked: Boolean = false,
            judgementId: String = "",
        ) {
            ctx.startActivity(Intent(ctx, BlockActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                putExtra(EXTRA_PKG, pkg)
                putExtra(EXTRA_REASON, reason)
                putExtra(EXTRA_TASK, sessionTask)
                putExtra(EXTRA_LOCKED, locked)
                putExtra(EXTRA_JUDGEMENT, judgementId)
            })
        }
    }
}
