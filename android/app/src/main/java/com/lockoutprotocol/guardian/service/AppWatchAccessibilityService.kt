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

    /**
     * The closest thing Android has to a window title, which the focus classifier leans on: a
     * small vision model reads a supplied string far more reliably than a 12sp toolbar.
     *
     * There is no single API, so this takes the first of: the window's own title, the browser URL
     * bar, then the longest title-like text near the top of the tree. Returns "" rather than
     * guessing — a missing title costs accuracy, never a block.
     */
    fun topScreenTitle(): String = try {
        val top = windows
            ?.filter { it.type == android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION }
            ?.maxByOrNull { it.layer }
        val declared = top?.title?.toString()?.trim().orEmpty()
        if (declared.isNotEmpty()) {
            declared.take(300)
        } else {
            val root = top?.root
            (browserUrl(root) ?: headerText(root)).orEmpty().take(300)
        }
    } catch (e: Exception) {
        ""
    }

    /** The URL from a browser's address bar. Most browsers expose it as an editable node with a
     *  known view id. */
    private fun browserUrl(root: android.view.accessibility.AccessibilityNodeInfo?): String? {
        if (root == null) return null
        for (id in URL_BAR_IDS) {
            val nodes = runCatching { root.findAccessibilityNodeInfosByViewId(id) }
                .getOrNull().orEmpty()
            val text = nodes.firstNotNullOfOrNull { it.text?.toString()?.trim()?.ifEmpty { null } }
            if (text != null) return text
        }
        return null
    }

    /** Fallback: the most title-like text near the top of the tree. Bounded, because this runs
     *  on every check and a full traversal of a busy app's tree is not free. */
    private fun headerText(root: android.view.accessibility.AccessibilityNodeInfo?): String? {
        if (root == null) return null
        var best: String? = null
        fun walk(node: android.view.accessibility.AccessibilityNodeInfo?, depth: Int) {
            if (node == null || depth > HEADER_MAX_DEPTH) return
            val text = node.text?.toString()?.trim()
            // Short and non-empty; body copy is excluded by length.
            if (!text.isNullOrEmpty() && text.length in 3..80) {
                if ((best?.length ?: 0) < text.length) best = text
            }
            for (i in 0 until minOf(node.childCount, HEADER_MAX_CHILDREN)) {
                walk(runCatching { node.getChild(i) }.getOrNull(), depth + 1)
            }
        }
        walk(root, 0)
        return best
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

        /** Address-bar view ids used by the common Android browsers. */
        private val URL_BAR_IDS = listOf(
            "com.android.chrome:id/url_bar",
            "org.mozilla.firefox:id/mozac_browser_toolbar_url_view",
            "com.brave.browser:id/url_bar",
            "com.microsoft.emmx:id/url_bar",
            "com.opera.browser:id/url_field",
            "com.duckduckgo.mobile.android:id/omnibarTextInput",
        )

        // Bounds on the fallback title walk: on a mid-range phone a full traversal is measurable
        // battery.
        private const val HEADER_MAX_DEPTH = 4
        private const val HEADER_MAX_CHILDREN = 12
    }
}
