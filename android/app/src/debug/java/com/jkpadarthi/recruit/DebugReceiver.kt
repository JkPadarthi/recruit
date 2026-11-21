package com.jkpadarthi.recruit

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * DEBUG BUILDS ONLY (compiled from src/debug, absent from release APKs).
 *
 * Two mechanisms need proving, and they are independent — FCM delivers a message,
 * AlarmManager fires at a time. This lets the second one be tested before any
 * Firebase project exists, and lets the first be separated from it afterwards.
 *
 *   # schedule a real deadline alarm (fires at T-90 / T-30)
 *   adb shell am broadcast -a com.jkpadarthi.recruit.DEBUG_SCHEDULE \
 *     --es tag dbg-1 \
 *     --es when_iso "2026-11-23T14:30:00+05:30" \
 *     --es event "HCL Tech Online Test" \
 *     --es body "Reporting venue: PRP 713"
 *
 *   # post a notification right now (tests channel + permission)
 *   adb shell am broadcast -a com.jkpadarthi.recruit.DEBUG_NOTIFY \
 *     --es title "✅ You're on the list" \
 *     --es body "HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713"
 *
 *   # what is scheduled, and can we be exact?
 *   adb shell am broadcast -a com.jkpadarthi.recruit.DEBUG_ALARMS
 */
class DebugReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        Notifications.ensureChannels(context)
        when (intent.action) {
            ACTION_SCHEDULE -> {
                val tag = intent.getStringExtra("tag") ?: "dbg"
                val whenIso = intent.getStringExtra("when_iso")
                val event = intent.getStringExtra("event") ?: "Debug deadline"
                val body = intent.getStringExtra("body") ?: "Scheduled from adb"
                val exact = AlarmScheduler.canScheduleExact(context)
                Log.i(TAG, "schedule tag=$tag when=$whenIso exactPermitted=$exact")
                AlarmScheduler.scheduleFor(context, tag, whenIso, event, body)
            }

            ACTION_NOTIFY -> {
                val title = intent.getStringExtra("title") ?: "Debug notification"
                val body = intent.getStringExtra("body") ?: "Posted from adb"
                Log.i(TAG, "notify canPost=${Notifications.canPost(context)}")
                Notifications.post(context, Notifications.CH_UPDATES, "dbg-notify", title, body, null)
            }

            ACTION_ALARMS -> {
                val list = Prefs.alarms(context)
                Log.i(TAG, "exactPermitted=${AlarmScheduler.canScheduleExact(context)} " +
                    "canPost=${Notifications.canPost(context)} pending=${list.size}")
                list.forEach { Log.i(TAG, "  ${it.optString("id")} at ${it.optLong("at")}") }
            }
        }
    }

    companion object {
        private const val TAG = "RecruitDebug"
        private const val ACTION_SCHEDULE = "com.jkpadarthi.recruit.DEBUG_SCHEDULE"
        private const val ACTION_NOTIFY = "com.jkpadarthi.recruit.DEBUG_NOTIFY"
        private const val ACTION_ALARMS = "com.jkpadarthi.recruit.DEBUG_ALARMS"
    }
}
