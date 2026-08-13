package com.lockoutprotocol.guardian.ui

import android.os.Bundle
import android.widget.ScrollView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.Prefs

/** Change (or set) the passcode from inside the app. Requires the current one if set. */
class ChangePinActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs.get(this)
        val hasPin = prefs.pinSet

        val current = Lcars.input(this, "Current passcode", numeric = true, password = true)
        val next = Lcars.input(this, "New passcode (min 4 digits)", numeric = true, password = true)
        val confirm = Lcars.input(this, "Confirm new passcode", numeric = true, password = true)

        val save = Lcars.pill(this, "Update passcode", Lcars.GOLD) {
            if (hasPin && !prefs.checkPin(current.text.toString())) { toast("Current passcode is wrong"); return@pill }
            val pin = next.text.toString()
            if (pin.length < 4) { toast("New passcode must be at least 4 digits"); return@pill }
            if (pin != confirm.text.toString()) { toast("New passcodes don't match"); return@pill }
            prefs.setPin(pin)
            toast("Passcode updated")
            finish()
        }

        val root = Lcars.root(this).apply {
            addView(Lcars.header(this@ChangePinActivity, "Security · Passcode"))
            addView(Lcars.body(this@ChangePinActivity,
                if (hasPin) "Enter your current passcode, then choose a new one."
                else "No passcode is set yet. Choose one below."))
            if (hasPin) addView(current)
            addView(next)
            addView(confirm)
            addView(Lcars.spacer(this@ChangePinActivity, 12))
            addView(save)
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
