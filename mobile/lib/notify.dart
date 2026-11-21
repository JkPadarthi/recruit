import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// Local notifications + exact deadline alarms, Android and iOS.
///
/// This is the capability a browser cannot provide: `zonedSchedule` with
/// [AndroidScheduleMode.exactAllowWhileIdle] maps to
/// `AlarmManager.setExactAndAllowWhileIdle` on Android (fires in Doze, survives
/// reboot via the plugin's boot receiver) and to `UNCalendarNotificationTrigger`
/// on iOS. A push tells you that you are on a list; this tells you to walk into
/// PRP 713 — with no network involved.
class Notifier {
  Notifier._();
  static final Notifier instance = Notifier._();

  final _plugin = FlutterLocalNotificationsPlugin();

  static const updatesChannel = 'recruit_updates';
  static const deadlinesChannel = 'recruit_deadlines';

  /// VIT reporting times are IST. Hard-coding it is deliberate: the sheet says
  /// "2.30 pm" in Vellore time, and a traveller's phone clock must not move a
  /// deadline. No timezone plugin needed.
  static const _zone = 'Asia/Kolkata';

  bool _ready = false;

  Future<void> init() async {
    if (_ready) return;
    tzdata.initializeTimeZones();
    tz.setLocalLocation(tz.getLocation(_zone));

    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        ),
      ),
    );

    if (Platform.isAndroid) {
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      await android?.createNotificationChannel(const AndroidNotificationChannel(
        updatesChannel,
        'Placement updates',
        description: 'Shortlists, online tests and announcements',
        importance: Importance.high,
      ));
      await android?.createNotificationChannel(const AndroidNotificationChannel(
        deadlinesChannel,
        'Deadline reminders',
        description: 'Reporting time from your own row in the shortlist sheet',
        importance: Importance.high,
      ));
    }
    _ready = true;
  }

  /// Asks for everything the alarms need. Returns a human-readable summary so the
  /// UI can tell the user what is still off instead of failing silently.
  Future<String> requestPermissions() async {
    await init();
    final notes = StringBuffer();
    if (Platform.isAndroid) {
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      final n = await android?.requestNotificationsPermission();
      notes.writeln('notifications: ${n == true ? "allowed" : "denied"}');
      final exact = await android?.requestExactAlarmsPermission();
      notes.writeln('exact alarms: ${exact == true ? "allowed" : "denied"}');
    } else if (Platform.isIOS) {
      final ios = _plugin.resolvePlatformSpecificImplementation<
          IOSFlutterLocalNotificationsPlugin>();
      final ok = await ios?.requestPermissions(alert: true, badge: true, sound: true);
      notes.writeln('notifications: ${ok == true ? "allowed" : "denied"}');
    }
    return notes.toString().trim();
  }

  NotificationDetails _details(String channel, {bool alarm = false}) =>
      NotificationDetails(
        android: AndroidNotificationDetails(
          channel,
          channel == deadlinesChannel ? 'Deadline reminders' : 'Placement updates',
          importance: Importance.high,
          priority: Priority.high,
          category: alarm ? AndroidNotificationCategory.alarm : null,
          playSound: true,
        ),
        iOS: const DarwinNotificationDetails(
          presentAlert: true,
          presentBadge: true,
          presentSound: true,
          interruptionLevel: InterruptionLevel.timeSensitive,
        ),
      );

  /// One notification now — used by the debug button and by push handling.
  Future<void> show({
    required String tag,
    required String title,
    required String body,
  }) async {
    await init();
    await _plugin.show(
      id: tag.hashCode & 0x7fffffff,
      title: title,
      body: body,
      notificationDetails: _details(updatesChannel),
      payload: '/dashboard#hits',
    );
  }

  /// Schedules T-90 and T-30 reminders for a deadline. Silent no-op for past times.
  Future<int> scheduleDeadline({
    required String tag,
    required DateTime when,
    required String event,
    required String body,
  }) async {
    await init();
    var scheduled = 0;
    for (final lead in const [90, 30]) {
      final at = when.subtract(Duration(minutes: lead));
      if (!at.isAfter(DateTime.now())) continue;
      final label = lead >= 60 ? '$event — in $lead min' : '$event — in $lead min, go now';
      await _plugin.zonedSchedule(
        id: (tag.hashCode ^ lead) & 0x7fffffff,
        scheduledDate: tz.TZDateTime.from(at, tz.local),
        notificationDetails: _details(deadlinesChannel, alarm: true),
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
        title: label,
        body: body,
        payload: '/dashboard#hits',
      );
      scheduled++;
      debugPrint('RecruitAlarms: armed "$label" for $at (lead=$lead)');
    }
    return scheduled;
  }

  /// Handles the server's data payload — the same contract the Kotlin shell used.
  Future<void> handlePushData(
    Map<String, dynamic> data, {
    bool displayNotification = true,
  }) async {
    final title = (data['title'] as String?)?.trim();
    final body = (data['body'] as String?) ?? '';
    final tag = (data['tag'] as String?) ?? 'recruit';
    // In the background isolate Play Services has already rendered the
    // notification block; showing another would double-buzz the user.
    if (displayNotification && title != null && title.isNotEmpty) {
      await show(tag: tag, title: title, body: body);
    }
    final whenIso = (data['when_iso'] as String?)?.trim();
    if (whenIso != null && whenIso.isNotEmpty) {
      final at = DateTime.tryParse(whenIso);
      if (at != null) {
        await scheduleDeadline(
          tag: tag,
          when: at,
          event: (data['event'] as String?) ?? title ?? 'Deadline',
          body: body,
        );
      }
    }
  }

  /// What is actually armed — for the debug screen.
  Future<List<PendingNotificationRequest>> pending() async {
    await init();
    return _plugin.pendingNotificationRequests();
  }

  Future<void> cancelAll() async {
    await init();
    await _plugin.cancelAll();
  }
}
