package com.lockoutprotocol.guardian.ui

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.data.contentRulesEnabled
import com.lockoutprotocol.guardian.data.providerModel
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.SessionStore
import com.lockoutprotocol.guardian.service.ForegroundApp
import com.lockoutprotocol.guardian.service.MonitorService
import com.lockoutprotocol.guardian.tamper.HeartbeatWorker

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var status: TextView
    private lateinit var log: TextView

    private val handler = Handler(Looper.getMainLooper())
    private val ticker = object : Runnable {
        override fun run() {
            refresh()
            handler.postDelayed(this, 1500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        buildUi()
    }

    override fun onResume() {
        // Rebuilt rather than just refreshed: the primary button's label and colour depend on
        // whether a session is running, and a session can start or end while this is backgrounded.
        if (this::status.isInitialized) buildUi()
        super.onResume()
        HeartbeatWorker.schedule(this)
        // Session-scoped, not always-on. The service is only started when there is actually
        // something for it to do: a live session, or content rules deliberately switched on.
        // Starting it while idle would put a "monitoring" notification in the shade at a moment
        // when nothing is being watched, which is the app misrepresenting itself in the one place
        // Android guarantees the user will look.
        val shouldRun = SessionStore.isActive(this) || prefs.contentRulesEnabled
        prefs.monitoringEnabled = shouldRun
        if (shouldRun && ForegroundApp.accessibilityConnected && !MonitorService.isRunning) {
            MonitorService.start(this)
        } else if (!shouldRun && MonitorService.isRunning) {
            MonitorService.stop(this)
        }
        handler.post(ticker)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(ticker)
    }

    private fun buildUi() {
        status = Lcars.panel(this, "")
        log = Lcars.panel(this, "", Lcars.GOLD).apply { textSize = 12f }

        val P = Lcars.PALETTE
        var i = 0
        fun next() = P[i++ % P.size]

        val container = Lcars.root(this).apply {
            addView(Lcars.header(this@MainActivity, "Lockout Protocol", Lcars.ORANGE))
            addView(status)
            // The one thing this screen is for. Everything below is configuration.
            addView(sessionButton())
            // Live activity log, front and centre.
            addView(Lcars.body(this@MainActivity, "ACTIVITY (live)").apply {
                setTextColor(Lcars.BLUE); letterSpacing = 0.15f
            })
            addView(log)
            addView(Lcars.pill(this@MainActivity, "Open full log", next()) { startActivity(Intent(this@MainActivity, LogActivity::class.java)) })
            addView(Lcars.spacer(this@MainActivity, 16))
            // Main controls.
            addView(Lcars.pill(this@MainActivity, "🔔 Set up alerts", Lcars.GOLD) { startActivity(Intent(this@MainActivity, NotifyActivity::class.java)) })
            addView(Lcars.pill(this@MainActivity, "Default watchlist", next()) { AppPickerActivity.openForDefaults(this@MainActivity) })
            addView(Lcars.pill(this@MainActivity, "Content rules (optional)", next()) { startActivity(Intent(this@MainActivity, GuidelinesActivity::class.java)) })
            addView(Lcars.pill(this@MainActivity, "Change passcode", Lcars.LILAC) { startActivity(Intent(this@MainActivity, ChangePinActivity::class.java)) })
            addView(Lcars.pill(this@MainActivity, "Model provider · settings", next()) { startActivity(Intent(this@MainActivity, SettingsActivity::class.java)) })
            addView(Lcars.spacer(this@MainActivity, 16))
            addView(Lcars.pill(this@MainActivity, "Setup · permissions", Lcars.BLUE) { startActivity(Intent(this@MainActivity, SetupActivity::class.java)) })
            // Drill: shows the real block screen so you can confirm it can't be swiped away.
            // Passes no package, so Dismiss just sends you Home instead of closing anything.
            addView(Lcars.pill(this@MainActivity, "Test block screen (drill)", Lcars.RED) {
                // Passes no package, so "Not now" just sends you Home instead of closing anything.
                // It DOES pass a task, so the drill shows the focus block people will actually
                // meet rather than the content-rules one.
                BlockActivity.show(this@MainActivity, "",
                    "DRILL — this is a test, nothing was flagged.",
                    sessionTask = "(drill) whatever you declared",
                    locked = SessionStore.current(this@MainActivity)
                        ?.accountability?.requiresPasscodeToEnd ?: false)
            })
        }
        setContentView(ScrollView(this).apply { addView(container) })
    }

    /**
     * Start or open the session. Deliberately the first control on the screen: monitoring is no
     * longer a mode you leave running, it begins and ends with a session.
     */
    private fun sessionButton(): android.widget.Button {
        val session = SessionStore.current(this)
        val label = if (session == null) "Start a focus session" else "Session running \u00b7 open"
        val colour = if (session == null) Lcars.ORANGE else Lcars.GOLD
        return Lcars.pill(this, label, colour) { FocusStartActivity.open(this@MainActivity) }
    }

    private fun refresh() {
        fun ok(b: Boolean) = if (b) "● ONLINE" else "○ ——"
        val session = SessionStore.current(this)
        status.text = buildString {
            if (session == null) {
                appendLine("SESSION      none \u2014 nothing is being watched")
                appendLine("PRIVACY      no screenshots are taken while idle")
                appendLine("DEFAULTS     ${prefs.monitoredPackages.size} app(s) on the watchlist")
                if (prefs.contentRulesEnabled) {
                    appendLine("CONTENT      rules ON \u2014 screens checked outside sessions too")
                }
            } else {
                val locked = session.accountability == Accountability.LOCKED
                appendLine("TASK         ${session.task.take(44)}")
                appendLine("MODE         ${if (locked) "LOCKED (passcode to override)" else "self-managed"}"
                    + if (prefs.dryRun) "  [TEST]" else "")
                appendLine("TIME         ${session.remainingText}")
                appendLine("CHECKS       ${session.checks} run, ${session.offTaskCount} off-task, "
                    + "${session.overrideCount} override(s)")
                appendLine("WATCHING     ${session.watchlist(prefs.monitoredPackages).size} app(s) "
                    + "every ${session.intervalSeconds}s")
            }
            appendLine("SENSORS      ${ok(ForegroundApp.accessibilityConnected)}")
            appendLine("MODEL        ${prefs.providerModel.ifEmpty { "not set" }}")
            append("ALERTS       ${if (prefs.pushEnabled) "push: ${prefs.ntfyTopic}" else "—"}")
        }
        val recent = EventLog.snapshot().takeLast(10)
        log.text = if (recent.isEmpty()) "No activity yet.\nOpen a monitored app to see checks here."
        else recent.joinToString("\n")
    }
}
