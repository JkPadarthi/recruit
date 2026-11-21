package com.jkpadarthi.recruit

import android.content.Context
import android.util.Log
import android.webkit.CookieManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Tells the server "this phone is reachable at this FCM token".
 *
 * Identity comes from the web session cookie the WebView already holds, so the
 * app never handles a password and there is no second login to keep in sync.
 */
object ApiClient {
    private const val TAG = "RecruitApi"

    fun registerToken(context: Context, token: String) {
        if (token.isBlank()) return
        if (Prefs.registeredToken(context) == token) return

        val base = BuildConfig.BASE_URL
        val cookie = CookieManager.getInstance().getCookie(base)
        if (cookie.isNullOrBlank()) {
            Log.i(TAG, "no session cookie yet — will retry after the user logs in")
            return
        }

        Thread {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL("$base/api/push/fcm").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    doOutput = true
                    connectTimeout = 10_000
                    readTimeout = 10_000
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Cookie", cookie)
                }
                val body = JSONObject()
                    .put("token", token)
                    .put("platform", "android")
                    .toString()
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }

                val code = conn.responseCode
                Log.i(TAG, "token registration -> HTTP $code")
                if (code in 200..299) Prefs.setRegisteredToken(context, token)
            } catch (t: Throwable) {
                Log.w(TAG, "token registration failed", t)
            } finally {
                conn?.disconnect()
            }
        }.start()
    }
}
