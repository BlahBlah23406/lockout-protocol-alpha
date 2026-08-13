package com.lockoutprotocol.guardian.ui

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.service.ForegroundApp
import com.lockoutprotocol.guardian.tamper.DeviceOwnerPolicy
import com.lockoutprotocol.guardian.tamper.GuardianAdminReceiver

/** One-time permission setup. Lives off the home screen since it's only needed during install. */
class SetupActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.get(this)
        status = Lcars.panel(this, "")

        val P = Lcars.PALETTE
        var i = 0
        fun next() = P[i++ % P.size]

        val root = Lcars.root(this).apply {
            addView(Lcars.header(this@SetupActivity, "Setup · Permissions", Lcars.ORANGE))
            addView(Lcars.body(this@SetupActivity,
                "Grant these once so Guardian can watch apps and resist tampering."))
            addView(status)
            addView(Lcars.pill(this@SetupActivity, "1 · Grant accessibility", next()) { openAccessibility() })
            addView(Lcars.pill(this@SetupActivity, "2 · Display over apps", next()) { openOverlay() })
            addView(Lcars.pill(this@SetupActivity, "3 · Device admin (tamper)", next()) { enableAdmin() })
            addView(Lcars.pill(this@SetupActivity, "4 · Ignore battery saver", next()) { ignoreBattery() })
            addView(Lcars.spacer(this@SetupActivity, 16))
            addView(Lcars.body(this@SetupActivity,
                "FULL LOCKDOWN (optional, strongest): make Guardian un-uninstallable and block " +
                "force-stop / safe-boot / factory-reset. One-time, on a device with no other " +
                "Google account, run over USB:\n\n" +
                "adb shell dpm set-device-owner com.lockoutprotocol.guardian/.tamper.GuardianAdminReceiver\n\n" +
                "Guardian applies the lockdown automatically once it is device owner."))
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onResume() {
        super.onResume()
        fun ok(b: Boolean) = if (b) "● DONE" else "○ needed"
        val owner = DeviceOwnerPolicy.isDeviceOwner(this)
        status.text = buildString {
            appendLine("ACCESSIBILITY ${ok(ForegroundApp.accessibilityConnected)}")
            appendLine("OVERLAY       ${ok(Settings.canDrawOverlays(this@SetupActivity))}")
            appendLine("TAMPER GUARD  ${ok(isAdmin())}")
            append("DEVICE OWNER  ${if (owner) "● FULL LOCKDOWN" else "○ optional (ADB)"}")
        }
    }

    private fun openAccessibility() = startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))

    private fun openOverlay() = startActivity(
        Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
    )

    private fun enableAdmin() {
        val cn = ComponentName(this, GuardianAdminReceiver::class.java)
        startActivity(Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
            putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, cn)
            putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION,
                "Guardian uses device admin to resist tampering and alert your contact on removal.")
        })
    }

    private fun ignoreBattery() = startActivity(
        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
    )

    private fun isAdmin(): Boolean {
        val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        return dpm.isAdminActive(ComponentName(this, GuardianAdminReceiver::class.java))
    }
}
