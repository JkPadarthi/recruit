import 'dart:io' show Platform;

import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// What the app is allowed to do, as reported by Android itself.
///
/// One bridge, one source of truth: notifications, exact alarms and the OEM
/// battery whitelist are all answered by `MainActivity`, rather than half of it
/// coming out of a plugin's internals.
class Perms {
  Perms._();
  static const _ch = MethodChannel('recruit/system');
  static const _onboardedKey = 'onboarded_v1';

  static Future<bool> notificationsEnabled() async {
    if (!Platform.isAndroid) return true;
    return await _ch.invokeMethod<bool>('isNotificationsEnabled') ?? false;
  }

  /// Opens the system prompt; the answer arrives on resume, so re-read status.
  static Future<void> requestNotifications() async {
    if (!Platform.isAndroid) return;
    await _ch.invokeMethod('requestNotifications');
  }

  static Future<bool> exactAlarmsAllowed() async {
    if (!Platform.isAndroid) return true;
    return await _ch.invokeMethod<bool>('isExactAlarmAllowed') ?? false;
  }

  static Future<bool> openExactAlarmSettings() async {
    if (!Platform.isAndroid) return true;
    return await _ch.invokeMethod<bool>('openExactAlarmSettings') ?? false;
  }

  static Future<bool> batteryExempt() async {
    if (!Platform.isAndroid) return true;
    return await _ch.invokeMethod<bool>('isBatteryExempt') ?? false;
  }

  static Future<bool> requestBatteryExemption() async {
    if (!Platform.isAndroid) return true;
    return await _ch.invokeMethod<bool>('requestBatteryExemption') ?? false;
  }

  static Future<bool> isOnboarded() async {
    final sp = await SharedPreferences.getInstance();
    return sp.getBool(_onboardedKey) ?? false;
  }

  static Future<void> markOnboarded() async {
    final sp = await SharedPreferences.getInstance();
    await sp.setBool(_onboardedKey, true);
  }

  /// Used by Profile, so a user who revokes something can see it and fix it.
  static Future<({bool notifications, bool exact, bool battery})> snapshot() async {
    final results = await Future.wait([
      notificationsEnabled(),
      exactAlarmsAllowed(),
      batteryExempt(),
    ]);
    return (notifications: results[0], exact: results[1], battery: results[2]);
  }
}
