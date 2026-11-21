package com.jkpadarthi.recruit

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationManagerCompat
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * The one permission flutter_local_notifications cannot reach: the OEM battery
 * whitelist. Android exposes it only as a Settings intent, so we bridge it.
 *
 * Exposed as `recruit/system`:
 *   isBatteryExempt()         -> bool
 *   requestBatteryExemption() -> system dialog for this package
 *   isExactAlarmAllowed()     -> bool (SCHEDULE_EXACT_ALARM, Android 12+)
 *   openExactAlarmSettings()  -> the "Alarms & reminders" screen for this package
 */
class MainActivity : FlutterActivity() {

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "recruit/system")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    // All permission state lives here, so the Dart side has one
                    // source of truth instead of half a plugin's internals.
                    "isNotificationsEnabled" ->
                        result.success(NotificationManagerCompat.from(this).areNotificationsEnabled())

                    "requestNotifications" -> {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                            PackageManager.PERMISSION_GRANTED
                        ) {
                            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 4101)
                        }
                        result.success(true)
                    }

                    "isBatteryExempt" -> result.success(isBatteryExempt())

                    "requestBatteryExemption" -> startSafely(
                        // Play policy allows the package-scoped request where
                        // completing a task at a specific time is core function.
                        Intent(
                            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:$packageName"),
                        ),
                        result,
                    )

                    "isExactAlarmAllowed" -> result.success(isExactAlarmAllowed())

                    "openExactAlarmSettings" -> startSafely(
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                            Intent(
                                Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                                Uri.parse("package:$packageName"),
                            )
                        } else {
                            Intent(Settings.ACTION_SETTINGS)
                        },
                        result,
                    )

                    else -> result.notImplemented()
                }
            }
    }

    private fun isBatteryExempt(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager ?: return false
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    private fun isExactAlarmAllowed(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        val am = getSystemService(Context.ALARM_SERVICE) as? android.app.AlarmManager ?: return false
        return am.canScheduleExactAlarms()
    }

    private fun startSafely(intent: Intent, result: MethodChannel.Result) {
        try {
            startActivity(intent)
            result.success(true)
        } catch (_: Exception) {
            // Some OEMs hide these screens; failing gracefully beats crashing.
            result.success(false)
        }
    }
}
