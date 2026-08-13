package com.lockoutprotocol.guardian.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.push.Pusher
import kotlin.concurrent.thread

/**
 * Friendly, no-jargon setup for push alerts. The user installs the free ntfy app and subscribes
 * to their private code — no account, no password.
 */
class NotifyActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs.get(this)
        val topic = prefs.ntfyTopic

        val steps = Lcars.body(this,
            "No email, no passwords. Just 3 steps:\n\n" +
                "1.  Install the free app \"ntfy\" (button below).\n" +
                "2.  Open ntfy, tap +, and enter EXACTLY this code.\n" +
                "3.  Come back and tap \"Send test alert\".")
        val code = Lcars.panel(this, topic, Lcars.GOLD).apply {
            gravity = Gravity.CENTER; textSize = 20f
        }

        val copy = Lcars.pill(this, "Copy code", Lcars.BLUE) {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("ntfy topic", topic))
            toast("Copied")
        }
        val install = Lcars.pill(this, "Install the ntfy app", Lcars.ORANGE) {
            openUrl("https://play.google.com/store/apps/details?id=io.heckel.ntfy")
        }
        val web = Lcars.pill(this, "View alerts in a browser", Lcars.LILAC) {
            openUrl("${prefs.ntfyServer}/$topic")
        }
        val test = Lcars.pill(this, "Send test alert", Lcars.GOLD) {
            thread {
                val r = Pusher.send(prefs, "Guardian test alert",
                    "If you can see this, your alerts are set up correctly!")
                runOnUiThread {
                    toast(if (r.isSuccess) "Sent — check your notifications" else "Failed: ${r.exceptionOrNull()?.message}")
                }
            }
        }

        val col = Lcars.root(this).apply {
            addView(Lcars.header(this@NotifyActivity, "Alerts · Comms", Lcars.GOLD))
            addView(steps); addView(code); addView(copy)
            addView(install); addView(web); addView(test)
        }
        setContentView(ScrollView(this).apply { addView(col) })
    }

    private fun openUrl(url: String) =
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
