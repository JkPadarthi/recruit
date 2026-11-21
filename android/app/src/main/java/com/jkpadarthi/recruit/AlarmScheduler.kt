package com.jkpadarthi.recruit

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import org.json.JSONObject
import java.time.OffsetDateTime

/**
 * Local deadline reminders.
 *
 * THIS is the part a web app cannot do. A push needs the network and a living
 * delivery path; an AlarmManager alarm is already inside the OS, so it fires at
 * the exact minute even in Doze, with no radio and no network.
 *
 * setExactAndAllowWhileIdle() bypasses Doze entirely (rate-limited to about one
 * firing per 9 minutes per app — irrelevant for two reminders per deadline).
 */
object AlarmScheduler {
    private const val TAG = "RecruitAlarms"

    /** Two knocks: enough time to travel, not enough to nag. */
    private val LEADS = listOf(90, 30)

    fun canScheduleExact(c: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        val am = c.getSystemService(AlarmManager::class.java) ?: return false
        return am.canScheduleExactAlarms()
    }

    /**
     * @param whenIso ISO-8601 WITH offset, e.g. "2026-11-23T14:30:00+05:30".
     *                The server sends the student's own sheet row, formatted.
     */
    fun scheduleFor(c: Context, tag: String, whenIso: String?, title: String, body: String) {
        if (whenIso.isNullOrBlank()) return
        val whenMs = runCatching {
            OffsetDateTime.parse(whenIso).toInstant().toEpochMilli()
        }.getOrNull() ?: run {
            Log.w(TAG, "unparseable when_iso: $whenIso")
            return
        }
        if (whenMs <= System.currentTimeMillis()) return   // already underway

        val am = c.getSystemService(AlarmManager::class.java) ?: return
        val exact = canScheduleExact(c)

        for (lead in LEADS) {
            val at = whenMs - lead * 60_000L
            if (at <= System.currentTimeMillis()) continue

            val id = "$tag-$lead"
            val label = if (lead >= 60) "$title — in $lead min" else "$title — in $lead min, go now"
            val i = Intent(c, AlarmReceiver::class.java).apply {
                putExtra("id", id)
                putExtra("title", label)
                putExtra("body", body)
            }
            val pi = PendingIntent.getBroadcast(
                c, id.hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            if (exact) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            } else {
                // Degraded path if the user denied exact alarms: still Doze-safe,
                // but the OS may shift it by a few minutes.
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            }

            Prefs.addAlarm(c, JSONObject().apply {
                put("id", id)
                put("at", at)
                put("title", label)
                put("body", body)
            })
            Log.i(TAG, "scheduled $id for $at (exact=$exact)")
        }
    }

    /** Alarms do not survive a reboot; re-arm everything still in the future. */
    fun rescheduleAll(c: Context) {
        Prefs.prunePast(c)
        val am = c.getSystemService(AlarmManager::class.java) ?: return
        val exact = canScheduleExact(c)
        for (a in Prefs.alarms(c)) {
            val at = a.optLong("at", 0L)
            if (at <= System.currentTimeMillis()) continue
            val id = a.optString("id")
            val i = Intent(c, AlarmReceiver::class.java).apply {
                putExtra("id", id)
                putExtra("title", a.optString("title"))
                putExtra("body", a.optString("body"))
            }
            val pi = PendingIntent.getBroadcast(
                c, id.hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            Log.i(TAG, "re-armed $id for $at after boot")
        }
    }
}
