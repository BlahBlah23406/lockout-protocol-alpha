package com.lockoutprotocol.guardian.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Fires when a new app is installed and auto-enrolls it into Guardian's monitored set.
 *
 * Registered dynamically by [MonitorService] rather than in the manifest: since Android 8,
 * manifest receivers don't get the cross-app PACKAGE_ADDED broadcast, but a context-registered
 * receiver in the always-on foreground service does.
 */
class PackageInstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_PACKAGE_ADDED) return
        // EXTRA_REPLACING is true for app *updates*; we only enroll genuinely new installs.
        if (intent.getBooleanExtra(Intent.EXTRA_REPLACING, false)) return
        val pkg = intent.data?.schemeSpecificPart ?: return
        AutoMonitor.enroll(context, pkg)
    }
}
