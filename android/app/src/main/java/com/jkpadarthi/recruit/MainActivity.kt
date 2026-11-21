package com.jkpadarthi.recruit

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ProgressBar
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging

/**
 * A thin shell around the existing PWA. The web app does the work; this class adds
 * the three things a browser cannot: a system-delivered push channel, exact local
 * alarms, and the permissions that let both survive the OS.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var bar: ProgressBar

    private val askNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            Log.i(TAG, "POST_NOTIFICATIONS granted=$granted")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        web = findViewById(R.id.web)
        bar = findViewById(R.id.bar)

        Notifications.ensureChannels(this)
        setUpWebView()
        addDebugTools()

        if (savedInstanceState == null) {
            web.loadUrl(BuildConfig.BASE_URL + pathFrom(intent))
        }
        askNotificationPermission()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val path = pathFrom(intent)
        if (path.isNotEmpty()) web.loadUrl(BuildConfig.BASE_URL + path)
    }

    /** Notification taps carry "/dashboard#hits"; a plain launch carries nothing. */
    private fun pathFrom(intent: Intent?): String {
        val raw = intent?.getStringExtra("url") ?: return ""
        return if (raw.startsWith("http")) "" else raw
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setUpWebView() {
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true          // the PWA keeps its session in localStorage
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            userAgentString = "$userAgentString RecruitApp/1"
        }

        // Share cookies both ways: the WebView logs in, ApiClient reuses the session.
        android.webkit.CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(web, true)
        }

        web.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                bar.visibility = ProgressBar.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                bar.visibility = ProgressBar.GONE
                // Now that a session cookie probably exists, hand the server our token.
                registerWithServer()
                maybeAskForExactAlarms()
                maybeAskForBattery()
            }
        }
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    /**
     * Android 14+ denies SCHEDULE_EXACT_ALARM by default. Without it the reminders
     * still fire, but the OS may delay them — which is exactly what we are here to
     * avoid, so we ask, once, with an explanation.
     */
    private fun maybeAskForExactAlarms() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        if (AlarmScheduler.canScheduleExact(this)) return
        if (Prefs.alarms(this).isEmpty()) return      // nothing scheduled yet: don't nag
        AlertDialog.Builder(this)
            .setTitle("Allow exact reminders?")
            .setMessage(
                "Recruit schedules reminders from your own sheet row (\"report to PRP 713 " +
                    "at 2.30 pm\"). Android can fire those at the exact minute only if you " +
                    "allow \"Alarms & reminders\" for this app."
            )
            .setPositiveButton("Open settings") { _, _ ->
                runCatching {
                    startActivity(
                        Intent(
                            Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                            Uri.parse("package:$packageName")
                        )
                    )
                }
            }
            .setNegativeButton("Not now", null)
            .show()
    }

    /** The OEM battery manager is what freezes other apps; ask to be exempted, once. */
    private fun maybeAskForBattery() {
        if (Prefs.askedBattery(this)) return
        Prefs.setAskedBattery(this)
        AlertDialog.Builder(this)
            .setTitle("Stop the phone from sleeping Recruit")
            .setMessage(
                "Some phones freeze background apps to save battery, which delays " +
                    "notifications. If yours does, set Recruit to \"No restrictions\" " +
                    "(Xiaomi: Autostart + Battery saver). Reminders work either way."
            )
            .setPositiveButton("Open settings") { _, _ ->
                runCatching {
                    startActivity(
                        Intent(
                            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:$packageName")
                        )
                    )
                }
            }
            .setNegativeButton("Skip", null)
            .show()
    }

    /**
     * DEBUG BUILDS ONLY. Two mechanisms need proving and they are independent:
     * the push (needs Firebase) and the local alarm (needs nothing). This overlay
     * lets the alarm be tested with one tap — no cable, no adb, no Firebase.
     */
    private fun addDebugTools() {
        if (!BuildConfig.DEBUG) return
        val root = findViewById<android.widget.FrameLayout>(R.id.root) ?: return
        val panel = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            gravity = android.view.Gravity.END or android.view.Gravity.BOTTOM
            setPadding(0, 0, 24, 48)
        }
        fun button(label: String, action: () -> Unit) {
            panel.addView(android.widget.Button(this).apply {
                text = label
                textSize = 12f
                setOnClickListener { action() }
            })
        }
        button("⏱ Test alarm +1 min") {
            // 91 minutes out, so the T-90 reminder lands in about a minute.
            // NB: `when` is a Kotlin keyword — never name a variable after it.
            val whenIso = java.time.OffsetDateTime.now(java.time.ZoneId.of("Asia/Kolkata"))
                .plusMinutes(91).withSecond(0).withNano(0).toString()
            AlarmScheduler.scheduleFor(this, "dbg-${System.currentTimeMillis()}",
                whenIso, "DEBUG deadline", "Scheduled by the test button")
            android.widget.Toast.makeText(this,
                "Armed for ${whenIso.take(16)} (T-90 fires in ~1 min). Lock the phone.",
                android.widget.Toast.LENGTH_LONG).show()
            Log.i(TAG, "debug alarm armed when=$whenIso exact=${AlarmScheduler.canScheduleExact(this)}")
        }
        button("🔔 Test notification") {
            Notifications.post(this, Notifications.CH_UPDATES, "dbg-notify",
                "✅ Test notification", "If you can see this, the channel works.", null)
        }
        button("ℹ️ Alarm status") {
            val pending = Prefs.alarms(this).size
            val msg = "exact allowed: ${AlarmScheduler.canScheduleExact(this)}\n" +
                "notifications: ${Notifications.canPost(this)}\n" +
                "pending alarms: $pending"
            android.app.AlertDialog.Builder(this).setTitle("Status").setMessage(msg)
                .setPositiveButton("OK", null).show()
        }
        root.addView(panel)
    }

    private fun registerWithServer() {
        if (FirebaseApp.getApps(this).isEmpty()) {
            Log.w(TAG, "Firebase not configured yet — see android/README.md")
            return
        }
        FirebaseMessaging.getInstance().token
            .addOnSuccessListener { token ->
                Prefs.setFcmToken(this, token)
                ApiClient.registerToken(applicationContext, token)
            }
            .addOnFailureListener { Log.w(TAG, "could not obtain FCM token", it) }
    }

    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    companion object {
        private const val TAG = "RecruitApp"
    }
}
