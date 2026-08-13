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
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.push.Pusher
import kotlin.concurrent.thread

class SettingsActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        if (intent.getStringExtra("tab") == "apps") buildAppPicker() else buildSettings()
    }

    // ---------- Alerts + AI settings ----------
    private fun buildSettings() {
        val olUrl = field("Ollama base URL", prefs.ollamaBaseUrl)
        val olKey = field("Ollama API key", prefs.ollamaApiKey, password = true)
        val olKey2 = field("Ollama API key 2 (backup — used when the first runs out)",
            prefs.ollamaApiKey2, password = true)
        val olModel = field("Ollama model", prefs.ollamaModel)
        val hb = field("Heartbeat URL (optional — see server/)", prefs.heartbeatUrl)
        val blockMode = field("Block mode: overlay | close", prefs.blockMode)

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
                prefs.ollamaBaseUrl = olUrl.text.toString().trim()
                // Editing either key resets the fail-over to start at the first one.
                val newKey = olKey.text.toString().trim()
                val newKey2 = olKey2.text.toString().trim()
                if (newKey != prefs.ollamaApiKey || newKey2 != prefs.ollamaApiKey2) {
                    prefs.activeApiKeySlot = 0
                }
                prefs.ollamaApiKey = newKey
                prefs.ollamaApiKey2 = newKey2
                prefs.ollamaModel = olModel.text.toString().trim().ifBlank { Prefs.DEFAULT_MODEL }
                prefs.heartbeatUrl = hb.text.toString().trim()
                prefs.blockMode = blockMode.text.toString().trim().ifBlank { "overlay" }
                toast("Saved")
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
            listOf(olUrl, olKey, olKey2, olModel, hb, blockMode).forEach { addView(it) }
            addView(dryRun); addView(alertSuggestive)
            addView(alertUnverifiable); addView(closeUnverifiable)
            addView(pledgeOnSettings); addView(guardSelf)
            addView(save); addView(test)
        }
        setContentView(ScrollView(this).apply { addView(col) })
    }

    // ---------- App picker ----------
    private fun buildAppPicker() {
        val pm = packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(intent, 0)
            .map { it.activityInfo.packageName to it.loadLabel(pm).toString() }
            .distinctBy { it.first }
            .filter { it.first != packageName }
            .sortedBy { it.second.lowercase() }

        val selected = prefs.monitoredPackages.toMutableSet()
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 48, 48, 48) }
        col.addView(TextView(this).apply { text = "Apps to monitor"; textSize = 24f })
        col.addView(TextView(this).apply {
            text = "Newly installed apps are monitored automatically. Unchecking one here removes " +
                "it — and this screen is behind your passcode, so removal requires signing in."
            textSize = 12f
            setPadding(0, 8, 0, 16)
        })

        apps.forEach { (pkg, label) ->
            col.addView(CheckBox(this).apply {
                text = "$label\n$pkg"
                isChecked = pkg in selected
                setOnCheckedChangeListener { _, c -> if (c) selected.add(pkg) else selected.remove(pkg) }
            })
        }
        col.addView(Button(this).apply {
            text = "Save selection"
            setOnClickListener { prefs.monitoredPackages = selected; toast("Saved ${selected.size} apps"); finish() }
        })
        setContentView(ScrollView(this).apply { addView(col) })
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
