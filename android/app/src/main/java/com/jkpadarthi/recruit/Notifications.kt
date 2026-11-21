package com.jkpadarthi.recruit

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import android.util.Log

object Notifications {
    private const val TAG = "RecruitNotify"

    /** "You are on the list" — one card per mail, tagged so re-sends replace it. */
    const val CH_UPDATES = "recruit_updates"

    /** "Report to PRP 713 in 90 minutes" — fired by a local exact alarm, not by push. */
    const val CH_DEADLINES = "recruit_deadlines"

    fun ensureChannels(c: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = c.getSystemService(NotificationManager::class.java) ?: return

        nm.createNotificationChannel(
            NotificationChannel(CH_UPDATES, "Placement updates", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Shortlists, online tests and announcements"
                enableVibration(true)
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(CH_DEADLINES, "Deadline reminders", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Reporting time from your own row in the shortlist sheet"
                enableVibration(true)
            }
        )
    }

    fun canPost(c: Context): Boolean = NotificationManagerCompat.from(c).areNotificationsEnabled()

    fun post(c: Context, channel: String, tag: String?, title: String, body: String, url: String?) {
        if (!canPost(c)) {
            Log.i(TAG, "notifications disabled by user; dropping '$title'")
            return
        }
        val open = Intent(c, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            if (!url.isNullOrBlank()) putExtra("url", url)
        }
        val pi = PendingIntent.getActivity(
            c,
            (tag ?: title).hashCode(),
            open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val n = NotificationCompat.Builder(c, channel)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)   // heads-up on API < 26
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()

        runCatching { NotificationManagerCompat.from(c).notify(tag, 0, n) }
            .onFailure { Log.w(TAG, "post failed", it) }
    }
}
