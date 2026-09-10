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
 * The home-screen widget: start a session, or see the one running.
 *
 * The Android counterpart of the macOS menu-bar item and the Windows tray panel. It shows whether
 * anything is being watched, because that is the one fact worth having on a home screen for an app
 * that holds an AccessibilityService.
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

        // The whole widget is the button, and always lands somewhere useful: the start screen
        // shows the running session when there is one.
        val intent = Intent(ctx, FocusStartActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            // Starting a locked session from a stray home-screen tap would be a trap, so the
            // start screen always confirms rather than starting silently.
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

        /** Repaint every placed widget. Safe from any thread; a no-op with no widget placed. */
        fun refresh(ctx: Context) {
            runCatching {
                ctx.sendBroadcast(Intent(ctx, FocusWidget::class.java).setAction(ACTION_REFRESH))
            }
        }
    }
}
