package com.jkpadarthi.recruit

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/**
 * Receives messages from Google Play Services — a system component, not a browser.
 * High-priority messages arrive even in Doze and can start this process if Android
 * had killed it, which is the entire reason this app exists.
 *
 * Messages are DATA-ONLY (no `notification` block) so this service is the single
 * place that builds a notification: no duplicates, and we can also schedule the
 * local deadline alarms from the same payload.
 */
class RecruitMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        Log.i(TAG, "new FCM token")
        Prefs.setFcmToken(this, token)
        ApiClient.registerToken(applicationContext, token)
    }

    override fun onMessageReceived(msg: RemoteMessage) {
        Notifications.ensureChannels(this)
        val d = msg.data
        val title = d["title"]?.takeIf { it.isNotBlank() } ?: "Recruit"
        val body = d["body"].orEmpty()
        val tag = d["tag"] ?: "recruit"

        Log.i(TAG, "push received tag=$tag when=${d["when_iso"]}")
        Notifications.post(this, Notifications.CH_UPDATES, tag, title, body, d["url"])

        // The mail told us WHEN. Turn that into a local alarm that cannot be
        // delayed by the network, Doze, or an OEM battery manager.
        AlarmScheduler.scheduleFor(
            this,
            tag,
            d["when_iso"],
            d["event"] ?: title,
            body
        )
    }

    companion object {
        private const val TAG = "RecruitFCM"
    }
}
