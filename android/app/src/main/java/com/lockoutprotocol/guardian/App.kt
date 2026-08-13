package com.lockoutprotocol.guardian

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.lockoutprotocol.guardian.data.EventLog
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.tamper.SafetyCovenant

class App : Application() {
    override fun onCreate() {
        super.onCreate()

        EventLog.init(this)

        val prefs = Prefs.get(this)

        // Remember once we've ever been armed, so the covenant can notice a later revert to TEST mode.
        if (!prefs.dryRun) prefs.everArmed = true

        // Self-binding safety check: alert the accountability contact if the safeguards were weakened.
        SafetyCovenant.check(this)

        // Monitoring is always on — there is no start/stop. It runs whenever accessibility is on.
        prefs.monitoringEnabled = true

        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        mgr.createNotificationChannel(
            NotificationChannel(
                CHANNEL_SERVICE, "Guardian monitoring",
                NotificationManager.IMPORTANCE_LOW
            ).apply { description = "Keeps Guardian running in the background." }
        )
    }

    companion object {
        const val CHANNEL_SERVICE = "guardian_service"
    }
}
