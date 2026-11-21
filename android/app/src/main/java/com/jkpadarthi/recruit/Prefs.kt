package com.jkpadarthi.recruit

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Tiny persistent state store. Everything survives process death and reboot,
 * which is the point: the deadline alarms live here so BootReceiver can re-arm them.
 */
object Prefs {
    private const val NAME = "recruit"
    private fun sp(c: Context) = c.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /** The token FCM handed us. */
    fun setFcmToken(c: Context, token: String) = sp(c).edit().putString("fcm_token", token).apply()
    fun fcmToken(c: Context): String? = sp(c).getString("fcm_token", null)

    /** The token the SERVER acknowledged. Only used to avoid pointless re-posts. */
    fun setRegisteredToken(c: Context, token: String?) =
        sp(c).edit().putString("registered_token", token).apply()
    fun registeredToken(c: Context): String? = sp(c).getString("registered_token", null)

    fun alarms(c: Context): MutableList<JSONObject> {
        val raw = sp(c).getString("alarms", "[]") ?: "[]"
        val out = mutableListOf<JSONObject>()
        runCatching {
            val a = JSONArray(raw)
            for (i in 0 until a.length()) out.add(a.getJSONObject(i))
        }
        return out
    }

    fun saveAlarms(c: Context, list: List<JSONObject>) {
        val a = JSONArray()
        list.forEach { a.put(it) }
        sp(c).edit().putString("alarms", a.toString()).apply()
    }

    fun addAlarm(c: Context, obj: JSONObject) {
        val list = alarms(c)
        list.removeAll { it.optString("id") == obj.optString("id") }
        list.add(obj)
        saveAlarms(c, list)
    }

    /** Drop anything already in the past so the store cannot grow forever. */
    fun prunePast(c: Context) {
        val now = System.currentTimeMillis()
        saveAlarms(c, alarms(c).filter { it.optLong("at", 0L) > now })
    }

    fun setAskedBattery(c: Context) = sp(c).edit().putBoolean("asked_battery", true).apply()
    fun askedBattery(c: Context): Boolean = sp(c).getBoolean("asked_battery", false)
}
