package com.lockoutprotocol.guardian.ui

import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.ai.Providers
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.data.contentRulesEnabled
import com.lockoutprotocol.guardian.data.focusAccountability
import com.lockoutprotocol.guardian.data.focusInterval
import com.lockoutprotocol.guardian.data.focusMinutes
import com.lockoutprotocol.guardian.data.focusNotes
import com.lockoutprotocol.guardian.data.learningEnabled
import com.lockoutprotocol.guardian.data.providerBaseUrl
import com.lockoutprotocol.guardian.data.providerConfig
import com.lockoutprotocol.guardian.data.providerId
import com.lockoutprotocol.guardian.data.providerModel
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.LearnedPolicy
import com.lockoutprotocol.guardian.push.Pusher
import kotlin.concurrent.thread

class SettingsActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        if (intent.getStringExtra("tab") == "apps") buildAppPicker() else buildSettings()
    }

    // ---------- Provider + focus + alerts ----------
    private fun buildSettings() {
        val olUrl = field("Server base URL", prefs.providerBaseUrl)
        val olKey = field("API key", prefs.ollamaApiKey, password = true)
        val olKey2 = field("API key 2 (backup — used when the first runs out)",
            prefs.ollamaApiKey2, password = true)
        val olModel = field("Model", prefs.providerModel)
        val hb = field("Heartbeat URL (optional — see server/)", prefs.heartbeatUrl)
        val blockMode = field("Block mode: overlay | close", prefs.blockMode)
        val notes = field("Standing notes for the classifier (optional)", prefs.focusNotes)

        val contentRules = CheckBox(this).apply {
            text = "Also enforce content rules (the original always-on classifier). Off by " +
                "default — when on, screens are checked outside focus sessions too."
            isChecked = prefs.contentRulesEnabled
        }
        val learning = CheckBox(this).apply {
            text = "Experimental: learn from \"false alarm\" taps — ${LearnedPolicy.status(this@SettingsActivity)}"
            isChecked = prefs.learningEnabled
        }

        val dryRun = CheckBox(this).apply {
            text = "TEST MODE — log/toast verdicts only, never block (uncheck to ARM blocking)"
            isChecked = prefs.dryRun
        }
        val alertSuggestive = CheckBox(this).apply {
            text = "Also notify me for MILD flags (swimwear ads, thumbnails scrolled past). " +
                "Off = they still block + get logged, just quietly. Tampering, searches, porn " +
                "sites and explicit content ALWAYS notify."
            isChecked = prefs.alertOnSuggestive
        }
        val alertUnverifiable = CheckBox(this).apply {
            text = "Alert me when a monitored app can't be seen (incognito / private mode)"
            isChecked = prefs.alertOnUnverifiable
        }
        val closeUnverifiable = CheckBox(this).apply {
            text = "Also send me Home when a monitored app can't be seen (escapable, no lockout)"
            isChecked = prefs.closeUnverifiable
        }
        val pledgeOnSettings = CheckBox(this).apply {
            text = "Show the pledge screen when the Settings app is opened"
            isChecked = prefs.pledgeOnSettings
        }
        val guardSelf = CheckBox(this).apply {
            text = "Self-guard: bounce out of Guardian's disable/uninstall pages + alert my contact"
            isChecked = prefs.guardSelf
        }

        val save = Button(this).apply {
            text = "Save"
            setOnClickListener {
                prefs.dryRun = dryRun.isChecked
                prefs.alertOnUnverifiable = alertUnverifiable.isChecked
                prefs.alertOnSuggestive = alertSuggestive.isChecked
                prefs.closeUnverifiable = closeUnverifiable.isChecked
                prefs.pledgeOnSettings = pledgeOnSettings.isChecked
                prefs.guardSelf = guardSelf.isChecked
                prefs.contentRulesEnabled = contentRules.isChecked
                prefs.learningEnabled = learning.isChecked
                prefs.focusNotes = notes.text.toString()
                prefs.providerBaseUrl = olUrl.text.toString().trim()
                // Editing either key resets the fail-over to start at the first one.
                val newKey = olKey.text.toString().trim()
                val newKey2 = olKey2.text.toString().trim()
                if (newKey != prefs.ollamaApiKey || newKey2 != prefs.ollamaApiKey2) {
                    prefs.activeApiKeySlot = 0
                }
                prefs.ollamaApiKey = newKey
                prefs.ollamaApiKey2 = newKey2
                prefs.providerModel = olModel.text.toString().trim()
                    .ifBlank { Providers.preset(prefs.providerId)?.model ?: Prefs.DEFAULT_MODEL }
                prefs.heartbeatUrl = hb.text.toString().trim()
                prefs.blockMode = blockMode.text.toString().trim().ifBlank { "overlay" }
                toast("Saved")
            }
        }
        val providerResult = TextView(this).apply { textSize = 12f }
        val testProvider = Button(this).apply {
            text = "Test model connection"
            setOnClickListener {
                // Save first, so the probe tests what was just typed. Off the main thread,
                // because a dead server takes the full connect timeout.
                prefs.providerBaseUrl = olUrl.text.toString().trim()
                prefs.providerModel = olModel.text.toString().trim()
                prefs.ollamaApiKey = olKey.text.toString().trim()
                providerResult.text = "Testing…"
                val cfg = prefs.providerConfig()
                thread {
                    val problem = runCatching { Providers.reachability(cfg) }
                        .getOrElse { it.message ?: "failed" }
                    runOnUiThread {
                        providerResult.text = if (problem == null) {
                            "\u2713  ${cfg.model} is reachable at ${cfg.baseUrl}"
                        } else {
                            "\u2717  $problem"
                        }
                    }
                }
            }
        }

        val test = Button(this).apply {
            text = "Send test alert"
            setOnClickListener {
                thread {
                    val r = runCatching {
                        Pusher.send(prefs, "[Guardian] Test alert",
                            "If you got this, Guardian alerts are set up correctly.")
                    }
                    runOnUiThread { toast(if (r.isSuccess) "Sent" else "Failed: ${r.exceptionOrNull()?.message}") }
                }
            }
        }

        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
            addView(TextView(this@SettingsActivity).apply { text = "Settings"; textSize = 24f })

            addView(sectionLabel("Model provider"))
            addView(TextView(this@SettingsActivity).apply {
                text = "Which model sees your screen every couple of minutes is the most " +
                    "consequential setting here, so every option and its trade-off is listed " +
                    "rather than hidden in a dropdown."
                textSize = 11f
            })
            addView(providerPicker())
            listOf(olUrl, olModel, olKey, olKey2).forEach { addView(it) }
            addView(TextView(this@SettingsActivity).apply {
                text = "Keys are stored in the encrypted preferences file and are never sent to " +
                    "a provider that doesn't need one. When one key runs out of quota the app " +
                    "switches to the other — and back when that one runs out."
                textSize = 11f
            })
            addView(testProvider); addView(providerResult)

            addView(sectionLabel("Focus session defaults"))
            addView(defaultsRow())
            addView(notes)
            addView(contentRules)
            addView(learning)

            addView(sectionLabel("Blocking + alerts"))
            listOf(hb, blockMode).forEach { addView(it) }
            addView(dryRun); addView(alertSuggestive)
            addView(alertUnverifiable); addView(closeUnverifiable)
            addView(pledgeOnSettings); addView(guardSelf)
            addView(save); addView(test)
        }
        setContentView(ScrollView(this).apply { addView(col) })
    }

    // ---------- App picker ----------
    /** Moved to [AppPickerActivity]; this entry point stays for callers still sending
     *  `tab=apps`. */
    private fun buildAppPicker() {
        AppPickerActivity.openForDefaults(this)
        finish()
    }

    private fun sectionLabel(text: String) = TextView(this).apply {
        this.text = text.uppercase()
        textSize = 13f
        setPadding(0, 32, 0, 8)
    }

    /** Tapping a row rewrites the URL and model fields, so the screen is rebuilt. That discards
     *  unsaved edits, which is why it only happens on an explicit tap. */
    private fun providerPicker(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        Providers.presets.forEach { preset ->
            val chosen = prefs.providerId == preset.id
            addView(Lcars.pill(this@SettingsActivity,
                (if (chosen) "\u25c9 " else "\u25cb ") + preset.label,
                if (chosen) Lcars.GOLD else Lcars.BLUE) {
                prefs.providerId = preset.id
                buildSettings()
            })
            addView(TextView(this@SettingsActivity).apply {
                text = preset.hint
                textSize = 11f
                setPadding(24, 0, 0, 8)
            })
        }
    }

    /** Interval / length / accountability chips — the same three the start screen offers. */
    private fun defaultsRow(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL

        addView(TextView(this@SettingsActivity).apply { text = "Check every"; textSize = 12f })
        addView(chips(listOf(60 to "1m", 120 to "2m", 300 to "5m", 600 to "10m"),
            prefs.focusInterval) { prefs.focusInterval = it; buildSettings() })

        addView(TextView(this@SettingsActivity).apply { text = "Session length"; textSize = 12f })
        addView(chips(listOf(25 to "25m", 50 to "50m", 90 to "90m", 0 to "open"),
            prefs.focusMinutes) { prefs.focusMinutes = it; buildSettings() })

        addView(TextView(this@SettingsActivity).apply { text = "Accountability"; textSize = 12f })
        Accountability.entries.forEach { level ->
            val chosen = prefs.focusAccountability == level
            addView(Lcars.pill(this@SettingsActivity,
                (if (chosen) "\u25c9 " else "\u25cb ") + level.title,
                if (chosen) Lcars.GOLD else Lcars.BLUE) {
                prefs.focusAccountability = level
                buildSettings()
            })
        }
    }

    private fun chips(choices: List<Pair<Int, String>>, current: Int,
                      onPick: (Int) -> Unit): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            choices.forEach { (value, label) ->
                addView(Lcars.pill(this@SettingsActivity, label,
                    if (value == current) Lcars.GOLD else Lcars.BLUE) { onPick(value) })
            }
        }

    private fun field(hint: String, value: String, number: Boolean = false, password: Boolean = false) =
        EditText(this).apply {
            this.hint = hint
            setText(value)
            inputType = when {
                number -> InputType.TYPE_CLASS_NUMBER
                password -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                else -> InputType.TYPE_CLASS_TEXT
            }
        }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
