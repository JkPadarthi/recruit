package com.jkpadarthi.recruit

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * A reboot wipes AlarmManager. Without this, a phone restarted overnight would
 * silently lose tomorrow's reporting-time reminder — the one that matters most.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        Notifications.ensureChannels(context)
        AlarmScheduler.rescheduleAll(context)
    }
}
