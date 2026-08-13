package com.lockoutprotocol.guardian.tamper

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.view.accessibility.AccessibilityNodeInfo
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.service.AppWatchAccessibilityService
import com.lockoutprotocol.guardian.ui.PledgeActivity

/**
 * The self-guard. While Guardian's accessibility access is still on, every window change flows
 * through here. Two escalating responses:
 *
 *  1. **System Settings opened** → show the pledge overlay (the user must renew their pledge before
 *     using Settings). Non-blocking: they can still use Settings after pledging.
 *  2. **A Guardian-disable screen reached** — Guardian's own accessibility toggle, its App-info /
 *     force-stop / uninstall page, or the uninstaller confirmation — → bounce out (BACK/HOME) and
 *     fire a tamper alert. This targets ONLY Guardian's own screens, so the rest of Settings stays
 *     usable and the user is never trapped out of their device.
 *
 * None of this can *prevent* a determined user on stock Android (accessibility is revocable by
 * design); it makes disabling Guardian slow, deliberate, and loud instead of a silent two taps.
 */
object SettingsGuard {

    private val SETTINGS_PKGS = setOf(
        "com.android.settings", "com.google.android.settings"
    )
    private val UNINSTALLER_PKGS = setOf(
        "com.android.packageinstaller", "com.google.android.packageinstaller",
        "com.miui.packageinstaller", "com.samsung.android.packageinstaller"
    )

    // Keyword sets used to recognise the dangerous screens from their visible text.
    private const val APP_LABEL = "guardian"
    private val DISABLE_WORDS = listOf(
        "force stop", "uninstall", "disable", "turn off", "remove", "deactivate", "clear data"
    )

    private const val PLEDGE_COOLDOWN_MS = 30_000L
    private const val BOUNCE_COOLDOWN_MS = 1_500L
    @Volatile private var lastPledgeAt = 0L
    @Volatile private var lastBounceAt = 0L

    fun onWindow(service: AppWatchAccessibilityService, pkg: String, className: String?) {
        val prefs = Prefs.get(service)
        val isSettings = pkg in SETTINGS_PKGS || pkg.endsWith(".settings")
        val isUninstaller = pkg in UNINSTALLER_PKGS

        if (!isSettings && !isUninstaller) return
        if (!prefs.guardSelf && !prefs.pledgeOnSettings) return

        val text = collectVisibleText(service)
        val mentionsGuardian = text.contains(APP_LABEL)
        val looksDangerous = mentionsGuardian && DISABLE_WORDS.any { text.contains(it) }

        // 2. Guardian's own disable/uninstall screen → hard bounce + alert.
        if (prefs.guardSelf && (looksDangerous || (isUninstaller && mentionsGuardian))) {
            val now = System.currentTimeMillis()
            if (now - lastBounceAt >= BOUNCE_COOLDOWN_MS) {
                lastBounceAt = now
                TamperAlert.raise(service,
                    "A screen to disable, force-stop or uninstall Guardian was opened in Settings.")
            }
            service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            service.goHome()
            return
        }

        // 1. Plain Settings entry → renew the pledge (throttled so it isn't a loop).
        if (prefs.pledgeOnSettings && isSettings) {
            val now = System.currentTimeMillis()
            if (now - lastPledgeAt >= PLEDGE_COOLDOWN_MS) {
                lastPledgeAt = now
                showPledge(service)
            }
        }
    }

    private fun showPledge(context: Context) {
        val i = Intent(context, PledgeActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        runCatching { context.startActivity(i) }
    }

    /** Walk the active window's node tree (bounded) collecting lower-cased text + descriptions. */
    private fun collectVisibleText(service: AppWatchAccessibilityService): String {
        val root = runCatching { service.rootInActiveWindow }.getOrNull() ?: return ""
        val sb = StringBuilder()
        walk(root, sb, depth = 0)
        return sb.toString().lowercase()
    }

    private fun walk(node: AccessibilityNodeInfo?, sb: StringBuilder, depth: Int) {
        node ?: return
        if (depth > 24 || sb.length > 4000) return
        node.text?.let { sb.append(it).append(' ') }
        node.contentDescription?.let { sb.append(it).append(' ') }
        for (i in 0 until node.childCount) {
            walk(node.getChild(i), sb, depth + 1)
        }
    }
}
