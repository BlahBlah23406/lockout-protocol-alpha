package com.lockoutprotocol.guardian.service

import android.content.Context
import android.content.Intent
import android.util.Log
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs

/**
 * Keeps the monitored set in sync with what's installed: every newly installed, user-launchable
 * app is automatically added to monitoring. Removing an app from monitoring requires unlocking
 * Guardian (the whole app sits behind the passcode gate), so a freshly installed app can't be
 * used to dodge accountability.
 *
 * Two paths feed this:
 *  - [PackageInstallReceiver] (registered live by [MonitorService]) catches installs instantly.
 *  - [syncNewInstalls] runs whenever the service (re)starts, catching anything installed while we
 *    weren't listening (service killed, reboot, etc.).
 */
object AutoMonitor {

    private const val TAG = "AutoMonitor"

    /** User-launchable apps currently installed (excludes Guardian itself). */
    fun launchableApps(ctx: Context): Set<String> {
        val pm = ctx.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(intent, 0)
            .map { it.activityInfo.packageName }
            .filter { it != ctx.packageName }
            .toSet()
    }

    /** Enroll one newly-installed package (called from the live install receiver). */
    fun enroll(ctx: Context, pkg: String) {
        if (pkg == ctx.packageName) return
        // Only user-launchable apps (skip pure background/service packages you can't "use").
        if (ctx.packageManager.getLaunchIntentForPackage(pkg) == null) return
        val prefs = Prefs.get(ctx)
        prefs.knownPackages = prefs.knownPackages + pkg
        if (pkg in prefs.monitoredPackages) return
        prefs.monitoredPackages = prefs.monitoredPackages + pkg
        Log.i(TAG, "auto-enrolled new install: $pkg")
        EventLog.add("➕ new app auto-monitored: $pkg")
    }

    /**
     * Catch up on installs that happened while the live receiver wasn't registered. The first run
     * records a baseline WITHOUT enrolling everything already installed; only apps that appear
     * after the baseline are auto-monitored. Re-pointing [knownPackages] at the current set each
     * pass also drops uninstalled apps, so a later re-install is treated as new again.
     */
    fun syncNewInstalls(ctx: Context) {
        val prefs = Prefs.get(ctx)
        val current = launchableApps(ctx)
        if (!prefs.autoMonitorBaselineDone) {
            prefs.knownPackages = current
            prefs.autoMonitorBaselineDone = true
            Log.i(TAG, "auto-monitor baseline recorded (${current.size} apps)")
            return
        }
        val newcomers = current - prefs.knownPackages
        prefs.knownPackages = current
        if (newcomers.isEmpty()) return
        prefs.monitoredPackages = prefs.monitoredPackages + newcomers
        newcomers.forEach {
            Log.i(TAG, "auto-enrolled (catch-up) new install: $it")
            EventLog.add("➕ new app auto-monitored: $it")
        }
    }
}
