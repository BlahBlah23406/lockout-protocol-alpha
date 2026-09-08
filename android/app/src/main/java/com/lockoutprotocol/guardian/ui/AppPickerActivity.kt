package com.lockoutprotocol.guardian.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.Prefs

/**
 * Pick which apps are watched. Two jobs, one screen.
 *
 * Launched plainly it edits the saved default watchlist, exactly as the inline picker in
 * [SettingsActivity] used to. Launched with [EXTRA_SELECTION] and `startActivityForResult` it
 * becomes a session-scoped picker: [FocusStartActivity] uses it to tick one extra app for today
 * without touching the defaults, and gets the new selection back rather than it being saved.
 *
 * Extracted from `SettingsActivity` so the two callers share one list, one search box and one set
 * of labels. A second copy would have drifted within a week.
 */
class AppPickerActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    /** True when we own the saved watchlist; false when we're editing a session's selection. */
    private var editingDefaults = true
    private val selected = mutableSetOf<String>()
    private var apps: List<Pair<String, String>> = emptyList()
    private var query = ""

    private lateinit var listHost: LinearLayout
    private lateinit var counter: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)

        val incoming = intent.getStringArrayListExtra(EXTRA_SELECTION)
        editingDefaults = incoming == null
        selected += incoming ?: prefs.monitoredPackages

        apps = loadApps()
        build()
    }

    /** Every user-launchable app, label first, excluding ourselves. */
    private fun loadApps(): List<Pair<String, String>> {
        val pm = packageManager
        val main = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(main, 0)
            .map { it.activityInfo.packageName to it.loadLabel(pm).toString() }
            .distinctBy { it.first }
            .filter { it.first != packageName }
            .sortedBy { it.second.lowercase() }
    }

    private fun build() {
        val title = intent.getStringExtra(EXTRA_TITLE) ?: "Apps to monitor"
        val note = intent.getStringExtra(EXTRA_NOTE) ?: if (editingDefaults) {
            "This is your default watchlist. Newly installed apps are added automatically when " +
                "content rules are on; in a focus session only what you pick is watched."
        } else {
            "Ticking an extra app watches it for this session only. Unticking one of your " +
                "defaults excuses it for this session only. Neither edits your saved watchlist."
        }

        counter = Lcars.body(this, "").apply { setTextColor(Lcars.BLUE); textSize = 12f }

        val search = EditText(this).apply {
            hint = "Search apps"
            addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    query = s?.toString()?.trim()?.lowercase().orEmpty()
                    renderList()
                }
                override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            })
        }

        listHost = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val root = Lcars.root(this).apply {
            addView(Lcars.header(this@AppPickerActivity, title, Lcars.BLUE))
            addView(Lcars.body(this@AppPickerActivity, note).apply {
                setTextColor(Lcars.LILAC); textSize = 11f
            })
            addView(counter)
            addView(search)
            addView(listHost)
            addView(Lcars.pill(this@AppPickerActivity,
                if (editingDefaults) "Save selection" else "Done", Lcars.ORANGE) { finishWith() })
            addView(Lcars.pill(this@AppPickerActivity, "Cancel", Lcars.LILAC) {
                setResult(Activity.RESULT_CANCELED)
                finish()
            })
        }
        setContentView(ScrollView(this).apply { addView(root) })
        renderList()
    }

    private fun renderList() {
        listHost.removeAllViews()
        val rows = if (query.isEmpty()) apps else apps.filter { (pkg, label) ->
            label.lowercase().contains(query) || pkg.lowercase().contains(query)
        }
        counter.text = "${selected.size} selected · ${rows.size} shown"

        if (rows.isEmpty()) {
            listHost.addView(Lcars.body(this, "— no matching apps —").apply {
                setTextColor(Lcars.READOUT)
            })
            return
        }
        rows.forEach { (pkg, label) ->
            listHost.addView(CheckBox(this).apply {
                text = "$label\n$pkg"
                textSize = 13f
                isChecked = pkg in selected
                setOnCheckedChangeListener { _, checked ->
                    if (checked) selected.add(pkg) else selected.remove(pkg)
                    counter.text = "${selected.size} selected · ${rows.size} shown"
                }
            })
        }
    }

    private fun finishWith() {
        if (editingDefaults) {
            prefs.monitoredPackages = selected.toSet()
        } else {
            setResult(Activity.RESULT_OK, Intent().apply {
                putStringArrayListExtra(EXTRA_SELECTION, ArrayList(selected))
            })
        }
        finish()
    }

    companion object {
        /** Present = session-scoped mode; the chosen set comes back in the result under this key. */
        const val EXTRA_SELECTION = "selection"
        const val EXTRA_TITLE = "title"
        const val EXTRA_NOTE = "note"

        /** Edit the saved default watchlist. */
        fun openForDefaults(ctx: Context) {
            ctx.startActivity(Intent(ctx, AppPickerActivity::class.java))
        }
    }
}
