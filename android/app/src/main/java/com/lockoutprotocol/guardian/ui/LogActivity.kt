package com.lockoutprotocol.guardian.ui

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.EventLog

/**
 * Live, timestamped activity log: every screenshot + AI verdict (with timings). Auto-refreshes
 * while open so you can watch it work.
 */
class LogActivity : AppCompatActivity() {

    private lateinit var text: TextView
    private lateinit var scroller: ScrollView
    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 1500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        text = TextView(this).apply {
            textSize = 12f
            setTextIsSelectable(true)
            typeface = android.graphics.Typeface.MONOSPACE
            setPadding(24, 24, 24, 24)
        }
        scroller = ScrollView(this).apply { addView(text) }

        val clear = Button(this).apply {
            text = "Clear log"
            setOnClickListener { EventLog.clear(); render() }
        }
        val header = TextView(this).apply {
            text = "Activity log (newest at bottom)"
            textSize = 18f; gravity = Gravity.CENTER; setPadding(0, 24, 0, 8)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(header)
            addView(scroller, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
            addView(clear)
        }
        setContentView(root)
    }

    private fun render() {
        val entries = EventLog.snapshot()
        text.text = if (entries.isEmpty()) "No activity yet." else entries.joinToString("\n")
        scroller.post { scroller.fullScroll(ScrollView.FOCUS_DOWN) }
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(refresh)
    }
}
