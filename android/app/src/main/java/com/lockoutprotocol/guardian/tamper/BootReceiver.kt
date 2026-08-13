package com.lockoutprotocol.guardian.tamper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.service.MonitorService

/**
 * Restarts monitoring after a reboot or an app update. With screenshots via accessibility there
 * is no consent to re-grant, so we just start the service. (The accessibility service also
 * auto-starts monitoring in onServiceConnected, so this is a belt-and-braces backup.)
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val prefs = Prefs.get(context)
        // Re-assert the device-owner lockdown after a reboot / app update (no-op if not owner).
        DeviceOwnerPolicy.apply(context)
        if (prefs.monitoringEnabled) {
            MonitorService.start(context)
        }
    }
}
