package com.lockoutprotocol.guardian.service

import android.accessibilityservice.AccessibilityService
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.hardware.HardwareBuffer
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.tamper.SettingsGuard
import com.lockoutprotocol.guardian.tamper.TamperAlert
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * Two jobs:
 *  1. Keep ForegroundApp.current up to date with whatever package is on screen.
 *  2. Provide on-demand screenshots via AccessibilityService.takeScreenshot() (API 30+).
 *
 * Using takeScreenshot() instead of MediaProjection means NO screen-recording indicator,
 * NO cast notification, NO consent dialog, and NO re-grant after reboot — we just grab a
 * single frame when a monitored app is open.
 */
class AppWatchAccessibilityService : AccessibilityService() {

    private val handler = Handler(Looper.getMainLooper())

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            val pkg = event.packageName?.toString() ?: return
            // Always record the real foreground app — including home / our own UI — so the monitor
            // loop skips capturing when no monitored app is actually on screen.
            ForegroundApp.update(pkg)
            // Drive override expiry on real (non-Guardian) foreground changes. We ignore our own
            // overlay so granting an override doesn't immediately count as "left & returned".
            if (pkg != packageName) Overrides.onForeground(pkg)
            // A violation screen is up and something else just took the foreground (Home swipe,
            // recents, another app) — put it straight back. Only the buttons on it release the gate.
            if (pkg != packageName && BlockGate.isArmed()) BlockGate.enforce()
            // Self-guard: intercept the Settings/uninstaller screens used to disable Guardian.
            if (pkg != packageName) {
                SettingsGuard.onWindow(this, pkg, event.className?.toString())
            }
        }
    }

    override fun onInterrupt() {}

    override fun onServiceConnected() {
        super.onServiceConnected()
        ForegroundApp.accessibilityConnected = true
        instance = this
        // Accessibility is bound automatically on boot/enable, so this is the most reliable
        // place to (re)start monitoring — no projection consent needed anymore.
        val prefs = Prefs.get(this)
        // Record that access is currently granted so a later silent revoke can be detected + alerted.
        prefs.accessibilityGranted = true
        if (prefs.monitoringEnabled && !MonitorService.isRunning) {
            MonitorService.start(this)
        }
    }

    /**
     * Grab a single screenshot of the default display. Returns a software ARGB_8888 bitmap
     * (readable by FrameQuality / encodable for upload), or null on failure.
     */
    suspend fun captureScreenshot(): Bitmap? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        return suspendCancellableCoroutine { cont ->
            try {
                takeScreenshot(
                    Display.DEFAULT_DISPLAY,
                    mainExecutor,
                    object : TakeScreenshotCallback {
                        override fun onSuccess(result: ScreenshotResult) {
                            val bmp = try {
                                val hb: HardwareBuffer = result.hardwareBuffer
                                val hw = Bitmap.wrapHardwareBuffer(hb, result.colorSpace)
                                // Copy into a software bitmap so pixels are readable, then downscale.
                                val sw = hw?.copy(Bitmap.Config.ARGB_8888, false)
                                hb.close()
                                hw?.recycle()
                                sw?.let { downscale(it) }
                            } catch (e: Exception) {
                                Log.w(TAG, "screenshot convert failed: ${e.message}")
                                null
                            }
                            if (cont.isActive) cont.resume(bmp)
                        }

                        override fun onFailure(errorCode: Int) {
                            Log.w(TAG, "takeScreenshot failed: code=$errorCode")
                            if (cont.isActive) cont.resume(null)
                        }
                    }
                )
            } catch (e: Exception) {
                Log.e(TAG, "takeScreenshot threw: ${e.message}")
                if (cont.isActive) cont.resume(null)
            }
        }
    }

    private fun downscale(src: Bitmap): Bitmap {
        if (src.width <= MAX_WIDTH) return src
        val scale = MAX_WIDTH.toFloat() / src.width
        val out = Bitmap.createScaledBitmap(src, MAX_WIDTH, (src.height * scale).toInt(), true)
        if (out != src) src.recycle()
        return out
    }

    /**
     * The package of the top-most *application* window right now. Unlike the last
     * TYPE_WINDOW_STATE_CHANGED event (which gets clobbered by the keyboard, status bar, toasts,
     * etc.), this looks at the actual window stack and returns the foreground app the user is in.
     */
    fun topAppPackage(): String? = try {
        windows
            ?.filter { it.type == android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION }
            ?.maxByOrNull { it.layer }
            ?.root?.packageName?.toString()
    } catch (e: Exception) {
        null
    }

    /** Used by the block logic to force the offending app off-screen. */
    fun goHome() = performGlobalAction(GLOBAL_ACTION_HOME)

    fun closeApp(pkg: String) = forceClose(pkg)

    /** Kill the app's background process (works only for apps that aren't holding a foreground service). */
    fun killApp(pkg: String) {
        try {
            val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            am.killBackgroundProcesses(pkg)
            Log.d(TAG, "killBackgroundProcesses $pkg")
        } catch (e: Exception) {
            Log.w(TAG, "killBackgroundProcesses failed: ${e.message}")
        }
    }

    /**
     * Close the app's current instance so it reopens fresh: relaunch it with CLEAR_TASK (which
     * finishes all its activities and starts a brand-new task), kill the process, then go home.
     * No root, no Settings navigation, no fragile gestures — just standard task management.
     */
    fun forceClose(pkg: String) {
        try {
            val launch = packageManager.getLaunchIntentForPackage(pkg)
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                startActivity(launch)
                Log.d(TAG, "cleared task for $pkg")
            }
        } catch (e: Exception) {
            Log.w(TAG, "clear task failed: ${e.message}")
        }
        killApp(pkg)
        handler.postDelayed({ goHome() }, 400)
    }

    override fun onUnbind(intent: Intent?): Boolean {
        ForegroundApp.accessibilityConnected = false
        instance = null
        // This is our one chance to react to the user turning accessibility OFF — the exact way
        // monitoring was defeated before. Fire a tamper alert to the accountability contact while
        // we still run in-process. (The heartbeat is a backup in case we're killed outright.)
        val prefs = Prefs.get(this)
        if (prefs.monitoringEnabled && prefs.accessibilityGranted) {
            prefs.accessibilityGranted = false
            TamperAlert.raise(this,
                "Guardian's accessibility access was turned off — screen monitoring is now disabled.",
                force = true)
        }
        return super.onUnbind(intent)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    companion object {
        private const val TAG = "AppWatchA11y"
        private const val MAX_WIDTH = 720
        @Volatile var instance: AppWatchAccessibilityService? = null
    }
}
