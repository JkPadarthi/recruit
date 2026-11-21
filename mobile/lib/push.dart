import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api.dart';
import 'notify.dart';

/// FCM wiring — the half of the design that needs a Firebase project.
///
/// Deliberately degrades: if Firebase is not configured (no google-services.json,
/// so no default app), [start] logs and returns. Local deadline alarms keep
/// working, which is why the app is useful before this is set up.
///
/// Two delivery paths, by design:
///  * Foreground: `onMessage` arrives, we post the notification ourselves (FCM
///    does not display while the app is in the foreground).
///  * Background / killed: Play Services renders the `notification` block from
///    the server, and `onBackgroundMessage` still runs for the `data` payload so
///    the T-90/T-30 alarms can be armed.
class Push {
  Push._();
  static final Push instance = Push._();

  bool get configured => Firebase.apps.isNotEmpty;
  bool _started = false;

  Future<void> start(ApiClient api) async {
    // start() is called at boot AND after login; listeners must not stack.
    if (_started) {
      await registerAfterLogin(api);
      return;
    }
    _started = true;
    try {
      await Firebase.initializeApp();
    } catch (e) {
      debugPrint('Push: Firebase not configured ($e) — local alarms only');
      return;
    }

    FirebaseMessaging.onBackgroundMessage(_onBackground);

    // Ask once; on iOS this is the system prompt. Android 13+ is handled by the
    // local-notifications plugin in the Profile tab.
    await FirebaseMessaging.instance.requestPermission();

    // A token can exist before the user logs in; the server rejects anonymous
    // registrations with 401, so we retry from the login path too.
    await _register(api);
    // v17 deprecates onTokenRefresh/onRegistered in favour of register()/onRegistered,
    // but onRegistered yields the Firebase Installation ID (FID), while the server
    // posts to FCM HTTP v1 `message.token`, which needs the registration token.
    // Keep the deprecated accessors until the server can address FIDs.
    // ignore: deprecated_member_use
    FirebaseMessaging.instance.onTokenRefresh.listen((_) => _register(api));

    FirebaseMessaging.onMessage.listen((msg) async {
      // Foreground: nothing is displayed automatically for data + notification.
      await Notifier.instance.handlePushData(Map<String, dynamic>.from(msg.data));
    });
  }

  Future<void> _register(ApiClient api) async {
    try {
      // Deprecated in v17 (see the note in start()), but this is the token the
      // server addresses — not the installation ID that onRegistered reports.
      // ignore: deprecated_member_use
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null || token.isEmpty) return;
      if (!api.hasSession) {
        debugPrint('Push: token ready, waiting for a session before registering');
        return;
      }
      final ok = await api.registerFcmToken(token);
      debugPrint('Push: token registered=$ok');
    } catch (e) {
      debugPrint('Push: token registration failed: $e');
    }
  }

  /// Called again after login so the first token has an account to attach to.
  Future<void> registerAfterLogin(ApiClient api) => _register(api);
}

/// Runs in its own isolate when the app is backgrounded or killed.
/// Must be a top-level function and annotated, or the tree-shaker removes it.
@pragma('vm:entry-point')
Future<void> _onBackground(RemoteMessage msg) async {
  final data = Map<String, dynamic>.from(msg.data);
  await Notifier.instance.handlePushData(data, displayNotification: false);
}
