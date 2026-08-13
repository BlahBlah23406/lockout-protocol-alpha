package com.lockoutprotocol.guardian.tamper

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.os.UserManager
import android.util.Log
import com.lockoutprotocol.guardian.data.EventLog

/**
 * The strongest technical lockdown Guardian can reach: **device-owner** mode. A normal user-installed
 * app can always be force-stopped or uninstalled — Android reserves that for the user by design. But
 * if Guardian is provisioned as device owner (one-time, via ADB on a device with no other accounts:
 *
 *   adb shell dpm set-device-owner com.lockoutprotocol.guardian/.tamper.GuardianAdminReceiver
 *
 * ) then it can genuinely block uninstall and the routes normally used to defeat it. This helper
 * applies those policies whenever Guardian *is* device owner, and is a harmless no-op otherwise, so
 * it's safe to call on every boot / admin-enable.
 */
object DeviceOwnerPolicy {

    private const val TAG = "DeviceOwnerPolicy"

    /** Restrictions that close the usual "just disable it" routes. Applied only as device owner. */
    private val RESTRICTIONS = listOf(
        UserManager.DISALLOW_UNINSTALL_APPS,      // no uninstall of any app (incl. Guardian)
        UserManager.DISALLOW_APPS_CONTROL,        // no force-stop / clear-data / disable in Settings
        UserManager.DISALLOW_SAFE_BOOT,           // can't boot to safe mode to bypass us
        UserManager.DISALLOW_FACTORY_RESET,       // no wipe-to-escape
        UserManager.DISALLOW_ADD_USER,            // no fresh user profile to dodge monitoring
        UserManager.DISALLOW_DEBUGGING_FEATURES   // no ADB to undo any of the above
    )

    fun isDeviceOwner(context: Context): Boolean {
        val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        return dpm.isDeviceOwnerApp(context.packageName)
    }

    fun apply(context: Context) {
        val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        if (!dpm.isDeviceOwnerApp(context.packageName)) return
        val admin = ComponentName(context, GuardianAdminReceiver::class.java)

        runCatching { dpm.setUninstallBlocked(admin, context.packageName, true) }
            .onFailure { Log.w(TAG, "setUninstallBlocked: ${it.message}") }

        for (r in RESTRICTIONS) {
            runCatching { dpm.addUserRestriction(admin, r) }
                .onFailure { Log.w(TAG, "addUserRestriction $r: ${it.message}") }
        }

        // Whitelist Guardian as the only permitted accessibility service. This does not force it on,
        // but combined with DISALLOW_APPS_CONTROL it removes the easy Settings routes to strip it.
        runCatching {
            dpm.setPermittedAccessibilityServices(admin, listOf(context.packageName))
        }.onFailure { Log.w(TAG, "setPermittedAccessibilityServices: ${it.message}") }

        EventLog.add("🔒 device-owner lockdown applied (uninstall + reset + safe-boot blocked)")
    }
}
