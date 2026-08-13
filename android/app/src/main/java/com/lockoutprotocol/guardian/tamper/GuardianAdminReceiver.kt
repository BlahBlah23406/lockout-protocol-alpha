package com.lockoutprotocol.guardian.tamper

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent

/**
 * Becoming a device admin forces the user to deactivate admin before they can uninstall.
 * onDisableRequested fires the moment they try — our chance to fire the tamper alert. When Guardian
 * is provisioned as device owner this same receiver also carries the [DeviceOwnerPolicy] lockdown.
 */
class GuardianAdminReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        // If we're device owner, (re)apply the full lockdown; harmless no-op as a plain admin.
        DeviceOwnerPolicy.apply(context)
    }

    override fun onDisableRequested(context: Context, intent: Intent): CharSequence {
        TamperAlert.raise(context,
            "Someone is attempting to remove Guardian's device-admin rights — usually the first " +
            "step before uninstalling the app.", force = true)
        return "Removing Guardian disables your accountability monitoring and notifies your contact."
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        TamperAlert.raise(context, "Guardian's device-admin protection was removed.", force = true)
    }
}
