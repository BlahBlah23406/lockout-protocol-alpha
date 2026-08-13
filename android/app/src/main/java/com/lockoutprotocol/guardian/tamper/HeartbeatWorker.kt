package com.lockoutprotocol.guardian.tamper

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.service.MonitorService
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * Two jobs, every ~15 min (WorkManager minimum):
 *  1. Watchdog — if monitoring is supposed to be on but the service died, restart it.
 *  2. Heartbeat — POST "I'm alive" to the optional server. If the phone is uninstalled,
 *     force-stopped for a long time, or offline, the server stops hearing from us and
 *     emails you. This is the ONLY reliable way to detect a full uninstall.
 */
class HeartbeatWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val prefs = Prefs.get(applicationContext)
        if (!prefs.monitoringEnabled) return Result.success()

        // Backup tamper detector: if accessibility was granted but is now off (e.g. the service was
        // killed before onUnbind could fire), report it and clear the flag so we alert only once.
        val a11yOn = AccessibilityUtil.isGuardianEnabled(applicationContext)
        if (prefs.accessibilityGranted && !a11yOn) {
            prefs.accessibilityGranted = false
            TamperAlert.raise(applicationContext,
                "Guardian's accessibility access is off — screen monitoring is disabled.", force = true)
        } else if (a11yOn && !prefs.accessibilityGranted) {
            prefs.accessibilityGranted = true
        }

        // Watchdog: if monitoring should be on but the service died (force-stopped, killed for
        // memory), just restart it. No consent needed since we screenshot via accessibility.
        if (!MonitorService.isRunning) {
            MonitorService.start(applicationContext)
        }

        // Heartbeat ping.
        val url = prefs.heartbeatUrl
        if (url.isNotBlank()) {
            runCatching {
                val payload = JSONObject().apply {
                    put("device", android.os.Build.MODEL)
                    put("ts", System.currentTimeMillis())
                    put("service_running", MonitorService.isRunning)
                    put("accessibility_on", a11yOn)
                }
                val req = Request.Builder().url(url)
                    .post(payload.toString().toRequestBody("application/json".toMediaType()))
                    .build()
                OkHttpClient().newCall(req).execute().close()
            }
        }
        return Result.success()
    }

    companion object {
        private const val NAME = "guardian_heartbeat"

        fun schedule(ctx: Context) {
            val work = PeriodicWorkRequestBuilder<HeartbeatWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(ctx)
                .enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.UPDATE, work)
        }

        fun cancel(ctx: Context) {
            WorkManager.getInstance(ctx).cancelUniqueWork(NAME)
        }
    }
}
