package com.lockoutprotocol.guardian.ui

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.data.focusAccountability
import com.lockoutprotocol.guardian.data.focusInterval
import com.lockoutprotocol.guardian.data.focusMinutes
import com.lockoutprotocol.guardian.data.lastTask
import com.lockoutprotocol.guardian.data.providerId
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.FocusSession
import com.lockoutprotocol.guardian.focus.SessionStore
import com.lockoutprotocol.guardian.service.MonitorService
import com.lockoutprotocol.guardian.widget.FocusWidget

/**
 * "What are you working on?" — the start screen, and the target of the home-screen widget.
 *
 * Shallow on purpose: one text field, two rows of chips, a radio pair, one button, all prefilled.
 * When a session is already running it shows that instead, so a widget tap never lands somewhere
 * useless. The accountability picker is the exception: its consequences are spelled out next to
 * each option rather than left in the docs.
 */
class FocusStartActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    private lateinit var taskInput: EditText
    private var minutes = 60
    private var interval = FocusSession.DEFAULT_INTERVAL
    private var accountability = Accountability.SELF
    private var extraApps: Set<String> = emptySet()
    private var allowedApps: Set<String> = emptySet()

    private lateinit var error: TextView
    private lateinit var warning: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        minutes = prefs.focusMinutes
        interval = prefs.focusInterval
        accountability = prefs.focusAccountability
        render()
    }

    override fun onResume() {
        super.onResume()
        // A session can end on its own (time's up) while this screen sits in the background.
        render()
    }

    private fun render() {
        val session = SessionStore.current(this)
        if (session != null) runningView(session) else startForm()
    }

    // ---- running session --------------------------------------------------------------------

    private fun runningView(session: FocusSession) {
        val locked = session.accountability == Accountability.LOCKED
        val colour = if (locked) Lcars.RED else Lcars.GOLD

        val root = Lcars.root(this).apply {
            addView(Lcars.header(this@FocusStartActivity,
                if (locked) "Locked session" else "In focus", colour))
            addView(Lcars.titleBig(this@FocusStartActivity,
                if (locked) "Locked" else "In Focus", colour))
            addView(Lcars.body(this@FocusStartActivity, "YOU SAID YOU WERE:").apply {
                setTextColor(Lcars.LILAC); letterSpacing = 0.15f
            })
            addView(Lcars.body(this@FocusStartActivity, session.task).apply {
                setTextColor(Lcars.GOLD); textSize = 18f
            })
            addView(Lcars.spacer(this@FocusStartActivity, 16))
            addView(Lcars.panel(this@FocusStartActivity, buildString {
                appendLine(session.remainingText)
                appendLine("${session.checks} checks, ${session.offTaskCount} off-task")
                appendLine("every ${session.intervalSeconds}s")
                appendLine("${session.watchlist(prefs.monitoredPackages).size} app(s) watched")
                if (session.overrideCount > 0) appendLine("${session.overrideCount} override(s)")
            }.trim(), Lcars.BLUE))
            addView(Lcars.spacer(this@FocusStartActivity, 12))
            addView(Lcars.pill(this@FocusStartActivity, "End session", Lcars.RED) {
                requestEnd(session)
            })
            addView(Lcars.pill(this@FocusStartActivity, "Close", Lcars.LILAC) { finish() })
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    /** Ending a locked session early costs the passcode: it stops you quietly cancelling the
     *  commitment, not using the phone. */
    private fun requestEnd(session: FocusSession) {
        if (!session.accountability.requiresPasscodeToEnd || !prefs.pinSet) {
            endSession()
            return
        }
        val pin = Lcars.input(this, "Passcode to end this locked session",
            numeric = true, password = true)
        val root = Lcars.root(this).apply {
            addView(Lcars.header(this@FocusStartActivity, "End session", Lcars.RED))
            addView(Lcars.panel(this@FocusStartActivity,
                "This session is locked. Enter your passcode to end it early.", Lcars.GOLD))
            addView(pin)
            addView(Lcars.pill(this@FocusStartActivity, "Confirm", Lcars.RED) {
                if (prefs.checkPin(pin.text.toString())) {
                    endSession()
                } else {
                    Toast.makeText(this@FocusStartActivity, "Wrong passcode",
                        Toast.LENGTH_SHORT).show()
                }
            })
            addView(Lcars.pill(this@FocusStartActivity, "Back", Lcars.LILAC) { render() })
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun endSession() {
        SessionStore.end(this, "ended by user")
        MonitorService.stop(this)
        FocusWidget.refresh(this)
        EventLog.add("⏹️ focus session ended by user")
        finish()
    }

    // ---- start form -------------------------------------------------------------------------

    private fun startForm() {
        taskInput = Lcars.input(this, "e.g. revising integration by parts for Friday's test")
            .apply { setText(prefs.lastTask) }

        error = Lcars.body(this, "").apply { setTextColor(Lcars.RED); visibility = View.GONE }
        warning = Lcars.body(this, "").apply { setTextColor(Lcars.GOLD); textSize = 11f }

        val root = Lcars.root(this).apply {
            addView(Lcars.header(this@FocusStartActivity, "Focus session", Lcars.ORANGE))
            addView(Lcars.body(this@FocusStartActivity, "I AM WORKING ON").apply {
                setTextColor(Lcars.GOLD); letterSpacing = 0.15f
            })
            addView(Lcars.body(this@FocusStartActivity,
                "Plain English. The model reads this exactly as you write it — be specific.")
                .apply { setTextColor(Lcars.LILAC); textSize = 11f })
            addView(taskInput)

            addView(chipRow("FOR", DURATIONS, { minutes }, { minutes = it; refreshWarning() }))
            addView(chipRow("CHECK EVERY", INTERVALS, { interval }, { interval = it }))
            addView(Lcars.body(this@FocusStartActivity,
                "Each check is one screenshot and one model call, so the interval is also your " +
                    "cost dial — and your battery dial.")
                .apply { setTextColor(Lcars.LILAC); textSize = 11f })

            addView(Lcars.spacer(this@FocusStartActivity, 12))
            addView(Lcars.body(this@FocusStartActivity, "ACCOUNTABILITY").apply {
                setTextColor(Lcars.GOLD); letterSpacing = 0.15f
            })
            Accountability.entries.forEach { level -> addView(accountabilityRow(level)) }
            addView(warning)

            addView(Lcars.spacer(this@FocusStartActivity, 12))
            addView(Lcars.body(this@FocusStartActivity, appsSummary()).apply {
                setTextColor(Lcars.READOUT); textSize = 12f
            })
            addView(Lcars.pill(this@FocusStartActivity, "Apps for this session only…",
                Lcars.BLUE) { editApps() })

            addView(Lcars.spacer(this@FocusStartActivity, 8))
            addView(error)
            addView(Lcars.pill(this@FocusStartActivity, "Start focus session", Lcars.ORANGE) {
                start()
            })
            addView(Lcars.pill(this@FocusStartActivity, "Cancel", Lcars.LILAC) { finish() })
        }
        setContentView(ScrollView(this).apply { addView(root) })
        refreshWarning()
    }

    /** A row of tappable value chips: the phone-sized equivalent of a radio group. */
    private fun chipRow(
        title: String,
        choices: List<Pair<Int, String>>,
        get: () -> Int,
        set: (Int) -> Unit,
    ): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.START
        }
        val wrapper = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(Lcars.body(this@FocusStartActivity, title).apply {
                setTextColor(Lcars.GOLD); letterSpacing = 0.15f; textSize = 12f
            })
        }
        choices.forEach { (value, label) ->
            row.addView(Lcars.pill(this, label,
                if (get() == value) Lcars.GOLD else Lcars.BLUE) {
                set(value)
                startForm()     // cheap, and keeps selection state in one place
            })
        }
        wrapper.addView(row)
        return wrapper
    }

    private fun accountabilityRow(level: Accountability): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(Lcars.pill(this@FocusStartActivity,
                (if (accountability == level) "◉ " else "○ ") + level.title,
                if (accountability == level) Lcars.GOLD else Lcars.BLUE) {
                accountability = level
                startForm()
            })
            addView(Lcars.body(this@FocusStartActivity, level.blurb).apply {
                setTextColor(Lcars.READOUT); textSize = 11f
            })
        }

    /** Warn about a locked session's missing prerequisites before it is started. */
    private fun refreshWarning() {
        if (accountability != Accountability.LOCKED) {
            warning.text = ""
            warning.visibility = View.GONE
            return
        }
        val problems = mutableListOf<String>()
        if (!prefs.pinSet) {
            problems += "no passcode is set yet — set one in Settings first, or overrides " +
                "will need no code at all"
        }
        if (!prefs.pushEnabled) {
            problems += "alerts are switched off, so nobody will actually be told"
        }
        warning.text = "⚠ " + if (problems.isEmpty()) {
            "Alerts go to your private link: ${prefs.ntfyTopic}"
        } else {
            problems.joinToString("; ")
        }
        warning.visibility = View.VISIBLE
    }

    // ---- per-session apps -------------------------------------------------------------------

    private fun currentSelection(): Set<String> =
        (prefs.monitoredPackages + extraApps) - allowedApps

    private fun appsSummary(): String {
        val bits = mutableListOf("${currentSelection().size} app(s) watched this session")
        if (extraApps.isNotEmpty()) bits += "+${extraApps.size} added today"
        if (allowedApps.isNotEmpty()) bits += "−${allowedApps.size} excused today"
        return bits.joinToString("  ·  ")
    }

    private fun editApps() {
        startActivityForResult(
            Intent(this, AppPickerActivity::class.java).apply {
                putStringArrayListExtra(AppPickerActivity.EXTRA_SELECTION,
                    ArrayList(currentSelection()))
                putExtra(AppPickerActivity.EXTRA_TITLE, "Apps for this session")
            },
            REQ_APPS)
    }

    @Deprecated("startActivityForResult is the shape the rest of this app already uses")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_APPS || data == null) return
        val selected = data.getStringArrayListExtra(AppPickerActivity.EXTRA_SELECTION)
            ?.toSet() ?: return
        // The delta against the saved defaults, not a copy: editing the defaults later should
        // still affect a session started before the edit.
        val defaults = prefs.monitoredPackages
        extraApps = selected - defaults
        allowedApps = defaults - selected
        startForm()
    }

    // ---- start ------------------------------------------------------------------------------

    private fun start() {
        val task = taskInput.text.toString().trim()
        if (task.length < 3) {
            showError("Tell it what you're working on first.")
            return
        }
        if (accountability == Accountability.LOCKED && minutes == 0) {
            // Open-ended + locked + a forgotten passcode is the one shape that could trap someone.
            showError("A locked session needs an end time — open-ended locked sessions " +
                "aren't allowed.")
            return
        }

        val session = FocusSession(
            task = task,
            plannedMinutes = minutes,
            intervalSeconds = FocusSession.clampInterval(interval),
            accountability = accountability,
            extraApps = extraApps,
            allowedApps = allowedApps,
            providerId = prefs.providerId,
        )
        if (session.watchlist(prefs.monitoredPackages).isEmpty()) {
            showError("No apps are being watched — pick some under 'Apps for this session', " +
                "or set a default watchlist in the dashboard.")
            return
        }

        // Remember the answers so next time is one tap.
        prefs.lastTask = task
        prefs.focusMinutes = minutes
        prefs.focusInterval = session.intervalSeconds
        prefs.focusAccountability = accountability

        SessionStore.start(this, session)
        MonitorService.start(this)
        FocusWidget.refresh(this)
        EventLog.add("▶︎ focus session started: $task (${accountability.id})")
        finish()
    }

    private fun showError(text: String) {
        error.text = text
        error.visibility = View.VISIBLE
    }

    companion object {
        /** Set when launched from the widget, which opens this screen prefilled rather than
         *  starting a session silently. */
        const val EXTRA_FROM_WIDGET = "from_widget"

        private const val REQ_APPS = 4711

        private val DURATIONS = listOf(25 to "25m", 50 to "50m", 90 to "90m", 0 to "open")
        private val INTERVALS = listOf(60 to "1m", 120 to "2m", 300 to "5m", 600 to "10m")

        fun open(ctx: Context) {
            ctx.startActivity(Intent(ctx, FocusStartActivity::class.java))
        }
    }
}
