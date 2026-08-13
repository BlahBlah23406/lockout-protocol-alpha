package com.lockoutprotocol.guardian.ui

import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.widget.ScrollView
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.EventLog

/**
 * The pledge gate. Raised over the system Settings app (by [com.lockoutprotocol.guardian.tamper.SettingsGuard])
 * so that every visit to Settings first passes through a deliberate commitment not to use Settings
 * to undermine Guardian. It's friction, not a lock — "I promise" simply returns to Settings;
 * "I cannot" sends the user Home. Either way the intention is made conscious and logged.
 *
 * The wording is deliberately plain. If a stronger personal or religious vow means more to you,
 * edit the text below — the point is that the words carry weight for the person reading them.
 */
class PledgeActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = Lcars.root(this).apply {
            gravity = Gravity.CENTER
            addView(Lcars.header(this@PledgeActivity, "Pledge · Settings", Lcars.GOLD))
            addView(Lcars.spacer(this@PledgeActivity, 24))
            addView(Lcars.titleBig(this@PledgeActivity, "Pause.", Lcars.ORANGE))
            addView(Lcars.spacer(this@PledgeActivity, 24))
            addView(Lcars.body(this@PledgeActivity,
                "Tap “I promise” only if you genuinely commit not to use Settings to " +
                "undermine Guardian — or ANY other blocking, filtering, or accountability system " +
                "you have put in place (content blockers, DNS or network filters, Digital " +
                "Wellbeing / Screen Time limits, router or browser restrictions, other " +
                "accountability apps) — or their ability to execute their functions.").apply {
                gravity = Gravity.CENTER; textSize = 18f
            })
            addView(Lcars.spacer(this@PledgeActivity, 32))
            addView(Lcars.pill(this@PledgeActivity, "I promise", Lcars.GOLD) {
                EventLog.add("🤲 pledge taken — entered Settings")
                finish()
            })
            addView(Lcars.pill(this@PledgeActivity, "I cannot — take me back", Lcars.BLUE) {
                EventLog.add("🛡️ pledge declined — left Settings")
                goHome()
                finish()
            })
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    /** Do not let Back silently dismiss the pledge into Settings — Back means "take me home". */
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        goHome()
        finish()
    }

    private fun goHome() {
        val home = Intent(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        runCatching { startActivity(home) }
    }
}
