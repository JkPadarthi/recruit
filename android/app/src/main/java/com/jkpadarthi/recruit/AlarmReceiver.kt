package com.jkpadarthi.recruit

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Fires at the exact deadline reminder minute, straight from the OS alarm queue. */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Notifications.ensureChannels(context)
        val title = intent.getStringExtra("title") ?: "Deadline reminder"
        val body = intent.getStringExtra("body").orEmpty()
        Notifications.post(
            context,
            Notifications.CH_DEADLINES,
            intent.getStringExtra("id"),
            title,
            body,
            "/dashboard#hits"
        )
        Prefs.prunePast(context)
    }
}
