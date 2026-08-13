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
        super.onResume()
        // Always-on: ensure the monitor is running whenever accessibility is granted.
        prefs.monitoringEnabled = true
        HeartbeatWorker.schedule(this)
        if (ForegroundApp.accessibilityConnected && !MonitorService.isRunning) {
            MonitorService.start(this)
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
            addView(Lcars.header(this@MainActivity, "Guardian · LCARS", Lcars.ORANGE))
            addView(status)
            // Live activity log, front and centre.
            addView(Lcars.body(this@MainActivity, "ACTIVITY (live)").apply {
                setTextColor(Lcars.BLUE); letterSpacing = 0.15f
            })
            addView(log)
            addView(Lcars.pill(this@MainActivity, "Open full log", next()) { startActivity(Intent(this@MainActivity, LogActivity::class.java)) })
            addView(Lcars.spacer(this@MainActivity, 16))
            // Main controls.
            addView(Lcars.pill(this@MainActivity, "🔔 Set up alerts", Lcars.GOLD) { startActivity(Intent(this@MainActivity, NotifyActivity::class.java)) })
            addView(Lcars.pill(this@MainActivity, "Select apps to monitor", next()) { startActivity(Intent(this@MainActivity, SettingsActivity::class.java).putExtra("tab", "apps")) })
            addView(Lcars.pill(this@MainActivity, "Edit guidelines", next()) { startActivity(Intent(this@MainActivity, GuidelinesActivity::class.java)) })
            addView(Lcars.pill(this@MainActivity, "Change passcode", Lcars.LILAC) { startActivity(Intent(this@MainActivity, ChangePinActivity::class.java)) })
            addView(Lcars.pill(this@MainActivity, "AI · advanced settings", next()) { startActivity(Intent(this@MainActivity, SettingsActivity::class.java)) })
            addView(Lcars.spacer(this@MainActivity, 16))
            addView(Lcars.pill(this@MainActivity, "Setup · permissions", Lcars.BLUE) { startActivity(Intent(this@MainActivity, SetupActivity::class.java)) })
            // Drill: shows the real block screen so you can confirm it can't be swiped away.
            // Passes no package, so Dismiss just sends you Home instead of closing anything.
            addView(Lcars.pill(this@MainActivity, "Test block screen (drill)", Lcars.RED) {
                BlockActivity.show(this@MainActivity, "", "DRILL — this is a test, nothing was flagged.")
            })
        }
        setContentView(ScrollView(this).apply { addView(container) })
    }

    private fun refresh() {
        fun ok(b: Boolean) = if (b) "● ONLINE" else "○ ——"
        status.text = buildString {
            appendLine("MODE         ${if (prefs.dryRun) "TEST (log only)" else "ARMED (blocks)"}")
            appendLine("MONITORING   ${ok(prefs.monitoringEnabled && MonitorService.isRunning)}")
            appendLine("SENSORS      ${ok(ForegroundApp.accessibilityConnected)}")
            appendLine("APPS WATCHED ${prefs.monitoredPackages.size}")
            append("ALERTS       ${if (prefs.pushEnabled) "push: ${prefs.ntfyTopic}" else "—"}")
        }
        val recent = EventLog.snapshot().takeLast(10)
        log.text = if (recent.isEmpty()) "No activity yet.\nOpen a monitored app to see checks here."
        else recent.joinToString("\n")
    }
}
