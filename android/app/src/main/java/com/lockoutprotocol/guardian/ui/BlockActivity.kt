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
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.service.AppWatchAccessibilityService
import com.lockoutprotocol.guardian.service.BlockGate
import com.lockoutprotocol.guardian.service.Overrides

/**
 * Full-screen block shown over a flagged app (which stays alive in the background).
 *
 * This screen is STICKY: swiping up, pressing Home, Back, or switching apps does NOT get rid of it
 * — [BlockGate] puts it straight back. The only ways out are the buttons:
 *  - DISMISS (no passcode, always available): force-closes the offending app. This is the intended
 *    exit — the violation has to cost a deliberate tap.
 *  - OVERRIDE (only shown when a passcode is set): keep using the app until it loses & regains focus.
 *
 * Safety: Dismiss can never fail to release the gate, and the gate self-expires after 5 minutes,
 * so this screen cannot lock anyone out of their phone.
 */
class BlockActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private var pkg: String = ""

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
        buildUi(intent.getStringExtra(EXTRA_REASON).orEmpty())
    }

    private fun buildUi(reason: String) {
        val title = Lcars.titleBig(this, "⊘ Access Denied", Lcars.RED)
        val subtitle = Lcars.body(this, "GUARDIAN SECURITY · RED ALERT").apply {
            setTextColor(Lcars.RED); gravity = Gravity.CENTER; letterSpacing = 0.2f
        }

        // Override is only a real choice when there's a passcode behind it. With no passcode it
        // would be a one-tap escape hatch, which defeats the point of the screen.
        val canOverride = prefs.pinSet
        val msg = Lcars.panel(this,
            "This screen was flagged as a guideline violation.\n\n$reason\n\n" +
                if (canOverride)
                    "Swiping away won't clear this. Dismiss to close the app — or Override with " +
                        "your passcode to keep using it until you leave it."
                else
                    "Swiping away won't clear this. Tap Dismiss to close the app.",
            Lcars.GOLD)

        val pin = Lcars.input(this, "Passcode to override", numeric = true, password = true).apply {
            visibility = if (canOverride) View.VISIBLE else View.GONE
        }
        val override = Lcars.pill(this, "Override", Lcars.GOLD) {
            if (prefs.checkPin(pin.text.toString())) {
                EventLog.add("🔓 override granted for $pkg")
                Overrides.grant(pkg)
                BlockGate.disarm()
                finish()
            } else {
                Toast.makeText(this@BlockActivity, "Wrong passcode", Toast.LENGTH_SHORT).show()
            }
        }.apply { visibility = if (canOverride) View.VISIBLE else View.GONE }

        val dismiss = Lcars.pill(this, "Dismiss (close app)", Lcars.RED) { dismissAndClose() }

        val root = Lcars.root(this).apply {
            gravity = Gravity.CENTER
            addView(Lcars.header(this@BlockActivity, "Violation", Lcars.RED))
            addView(title); addView(subtitle)
            addView(Lcars.spacer(this@BlockActivity, 24))
            addView(msg)
            addView(pin); addView(override); addView(dismiss)
        }
        setContentView(ScrollView(this).apply { addView(root) })
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

        fun show(ctx: Context, pkg: String, reason: String) {
            ctx.startActivity(Intent(ctx, BlockActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                putExtra(EXTRA_PKG, pkg)
                putExtra(EXTRA_REASON, reason)
            })
        }
    }
}
