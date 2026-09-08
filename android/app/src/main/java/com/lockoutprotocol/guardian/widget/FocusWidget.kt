package com.lockoutprotocol.guardian.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.lockoutprotocol.guardian.R
import com.lockoutprotocol.guardian.data.Prefs
import com.lockoutprotocol.guardian.data.lastTask
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.SessionStore
import com.lockoutprotocol.guardian.ui.FocusStartActivity

/**
 * The home-screen widget: start a focus session without opening the app, and see at a glance
 * whether one is running.
 *
 * This is the Android counterpart of the macOS menu-bar item and the Windows tray panel, and it
 * exists for the same reason: a focus tool that takes four taps to arm gets used on the days you
 * least need it and skipped on the days you do. Two states, one tap each —
 *
 *   idle    "What are you working on?" + a one-tap repeat of your last task
 *   running the task, the countdown, and how many checks have run
 *
 * It deliberately shows whether anything is being watched. The app holds an AccessibilityService
 * that can read the screen, so a widget that looked identical whether or not monitoring was live
 * would be hiding the one fact the user most needs on their home screen.
 */
class FocusWidget : AppWidgetProvider() {

    override fun onUpdate(ctx: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { render(ctx, manager, it) }
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        // Our own refresh broadcast, sent whenever a session starts, ends, or ticks.
        if (intent.action == ACTION_REFRESH) {
            val manager = AppWidgetManager.getInstance(ctx)
            manager.getAppWidgetIds(ComponentName(ctx, FocusWidget::class.java))
                .forEach { render(ctx, manager, it) }
        }
    }

    private fun render(ctx: Context, manager: AppWidgetManager, id: Int) {
        val session = SessionStore.current(ctx)
        val views = RemoteViews(ctx.packageName, R.layout.widget_focus)

        if (session == null) {
            val last = Prefs.get(ctx).lastTask
            views.setTextViewText(R.id.widget_state, "NO SESSION")
            views.setTextColor(R.id.widget_state, LILAC)
            views.setTextViewText(R.id.widget_task,
                if (last.isEmpty()) "What are you working on?" else last)
            views.setTextViewText(R.id.widget_detail, "Nothing is being watched")
            views.setTextViewText(R.id.widget_action,
                if (last.isEmpty()) "START A SESSION" else "START THAT AGAIN")
            views.setInt(R.id.widget_bar, "setBackgroundColor", LILAC)
        } else {
            val locked = session.accountability == Accountability.LOCKED
            views.setTextViewText(R.id.widget_state, if (locked) "LOCKED" else "IN FOCUS")
            views.setTextColor(R.id.widget_state, if (locked) RED else READOUT)
            views.setTextViewText(R.id.widget_task, session.task)
            views.setTextViewText(R.id.widget_detail,
                "${session.remainingText} · ${session.checks} checks, " +
                    "${session.offTaskCount} off-task")
            views.setTextViewText(R.id.widget_action, "OPEN")
            views.setInt(R.id.widget_bar, "setBackgroundColor", if (locked) RED else READOUT)
        }

        // The whole widget is the button. Tapping it always lands on the start screen, which shows
        // the running session when there is one — so there is no state in which a tap does nothing.
        val intent = Intent(ctx, FocusStartActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            // A widget tap on an idle widget with a remembered task means "same again", which the
            // start screen turns into a one-tap confirm rather than a silent start. Starting a
            // locked session from a home-screen tap with no confirmation would be a trap.
            putExtra(FocusStartActivity.EXTRA_FROM_WIDGET, true)
        }
        views.setOnClickPendingIntent(R.id.widget_root, PendingIntent.getActivity(
            ctx, 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))

        manager.updateAppWidget(id, views)
    }

    companion object {
        private const val ACTION_REFRESH = "com.lockoutprotocol.guardian.WIDGET_REFRESH"

        // Same LCARS palette as the app, inlined because RemoteViews can't read the theme.
        private const val LILAC = 0xFFCC88CC.toInt()
        private const val RED = 0xFFE0533D.toInt()
        private const val READOUT = 0xFF9AE6C9.toInt()

        /**
         * Ask every placed widget to repaint. Called when a session starts or ends and after each
         * check, so the countdown on the home screen is not a lie.
         *
         * Cheap and safe to call from any thread; a device with no widget placed does nothing.
         */
        fun refresh(ctx: Context) {
            runCatching {
                ctx.sendBroadcast(Intent(ctx, FocusWidget::class.java).setAction(ACTION_REFRESH))
            }
        }
    }
}
