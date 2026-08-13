package com.lockoutprotocol.guardian.ui

import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.ScrollView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.Prefs

/**
 * Launcher entry point + passcode gate. Nothing in Guardian is reachable without passing this.
 * First run creates the passcode; afterwards it verifies.
 */
class LockActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        render()
    }

    private fun render() {
        val settingUp = !prefs.pinSet

        val title = Lcars.titleBig(this, if (settingUp) "Create Passcode" else "Authorize")
        val subtitle = Lcars.body(this, "GUARDIAN · ACCESS CONTROL").apply {
            gravity = Gravity.CENTER; setTextColor(Lcars.BLUE); letterSpacing = 0.2f
        }
        val input = Lcars.input(this, "Passcode (min 4 digits)", numeric = true, password = true)
        val confirm = Lcars.input(this, "Confirm passcode", numeric = true, password = true).apply {
            visibility = if (settingUp) View.VISIBLE else View.GONE
        }
        val button = Lcars.pill(this, if (settingUp) "Set passcode" else "Unlock", Lcars.GOLD) {
            val pin = input.text.toString()
            if (settingUp) {
                if (pin.length < 4) { toast("Passcode must be at least 4 digits"); return@pill }
                if (pin != confirm.text.toString()) { toast("Passcodes do not match"); return@pill }
                prefs.setPin(pin); proceed()
            } else {
                if (prefs.checkPin(pin)) proceed() else toast("Incorrect passcode")
            }
        }

        val root = Lcars.root(this).apply {
            gravity = Gravity.CENTER
            addView(Lcars.header(this@LockActivity, "Security"))
            addView(Lcars.spacer(this@LockActivity, 40))
            addView(title); addView(subtitle)
            addView(Lcars.spacer(this@LockActivity, 32))
            addView(input); addView(confirm); addView(button)
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun proceed() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
