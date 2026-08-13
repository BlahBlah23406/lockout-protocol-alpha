package com.lockoutprotocol.guardian.tamper

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.text.TextUtils
import com.lockoutprotocol.guardian.service.AppWatchAccessibilityService

/**
 * Reads the system's list of enabled accessibility services to tell — from any process, including
 * the WorkManager heartbeat — whether Guardian's accessibility access is currently on. This is more
 * reliable than the in-memory [com.lockoutprotocol.guardian.service.ForegroundApp] flag, which is lost if
 * the process was restarted.
 */
object AccessibilityUtil {

    fun isGuardianEnabled(context: Context): Boolean {
        val expected = ComponentName(context, AppWatchAccessibilityService::class.java)
        val enabled = Settings.Secure.getString(
            context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        val splitter = TextUtils.SimpleStringSplitter(':')
        splitter.setString(enabled)
        for (entry in splitter) {
            val cn = ComponentName.unflattenFromString(entry) ?: continue
            if (cn == expected) return true
        }
        return false
    }
}
