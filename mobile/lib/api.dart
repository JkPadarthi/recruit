import 'dart:convert';
import 'dart:io' show Platform;

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Talks to the Recruit API exactly like the web dashboard does.
///
/// Auth is the same session cookie the site uses (`recruit_session`). Flutter has
/// no cookie jar, so we keep it ourselves and persist it — which is what makes
/// "log in once and never again" work, and lets [registerFcmToken] authenticate
/// without a second password.
class ApiClient {
  ApiClient(this._base);

  final String _base;
  final http.Client _http = http.Client();
  String? _cookie;

  static const _cookieKey = 'session_cookie';

  bool get hasSession => _cookie != null;

  Future<void> loadSession() async {
    final sp = await SharedPreferences.getInstance();
    _cookie = sp.getString(_cookieKey);
  }

  Future<void> _saveCookie(String? setCookieHeader) async {
    if (setCookieHeader == null) return;
    // 'recruit_session=abc123; Path=/; HttpOnly; ...' -> 'recruit_session=abc123'
    final pair = setCookieHeader.split(';').first.trim();
    if (pair.isEmpty || !pair.contains('=')) return;
    _cookie = pair;
    final sp = await SharedPreferences.getInstance();
    await sp.setString(_cookieKey, pair);
  }

  /// Called when a request comes back 401 mid-session — the cookie is dead (password
  /// changed on another device, epoch bumped, server reset). The app must return to the
  /// login screen; the PWA does this with a redirect, and silently rendering an empty
  /// list instead is the worst possible outcome because it looks like "no shortlists".
  void Function()? onAuthLost;

  String get baseUrl => _base;

  Future<void> logout() async {
    // Best effort: tell the server to drop its cookie, then clear locally.
    try {
      await _post('/api/logout', const {});
    } catch (_) {}
    _cookie = null;
    final sp = await SharedPreferences.getInstance();
    await sp.remove(_cookieKey);
  }

  Map<String, String> _headers({bool json = false}) => {
        if (json) 'Content-Type': 'application/json',
        'Cookie': ?_cookie,   // omitted entirely when there is no session
        'Accept': 'application/json',
      };

  Future<dynamic> _get(String path) async {
    final r = await _http
        .get(Uri.parse('$_base$path'), headers: _headers())
        .timeout(const Duration(seconds: 20));
    return _decode(r, path);
  }

  Future<dynamic> _put(String path, Map<String, dynamic> body) async {
    final r = await _http
        .put(Uri.parse('$_base$path'),
            headers: _headers(json: true), body: jsonEncode(body))
        .timeout(const Duration(seconds: 20));
    return _decode(r, path);
  }

  Future<dynamic> _delete(String path) async {
    final r = await _http
        .delete(Uri.parse('$_base$path'), headers: _headers())
        .timeout(const Duration(seconds: 20));
    return _decode(r, path);
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final r = await _http
        .post(Uri.parse('$_base$path'),
            headers: _headers(json: true), body: jsonEncode(body))
        .timeout(const Duration(seconds: 20));
    return _decode(r, path);
  }

  dynamic _decode(http.Response r, String path) {
    if (r.statusCode >= 400) {
      // A 401 on login/register is "wrong password", not a dead session.
      if (r.statusCode == 401 &&
          !path.startsWith('/api/login') &&
          !path.startsWith('/api/register')) {
        onAuthLost?.call();
      }
      throw ApiException(r.statusCode, r.body);
    }
    if (r.body.isEmpty) return null;
    return jsonDecode(r.body);
  }

  // ---------------------------------------------------------------- endpoints
  Future<Map<String, dynamic>> login(String email, String password) async {
    final r = await _http.post(
      Uri.parse('$_base/api/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email.trim(), 'password': password}),
    ).timeout(const Duration(seconds: 20));
    if (r.statusCode == 401) throw const ApiException(401, 'Wrong email or password');
    if (r.statusCode >= 400) throw ApiException(r.statusCode, r.body);
    await _saveCookie(r.headers['set-cookie']);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Ask for a code (or another one). The server answers the same way whether or not
  /// the address exists, so the string it returns is safe to show verbatim.
  Future<String> verifyStart(String email) async {
    final r = await _post('/api/verify/start', {'email': email});
    return '${(r as Map?)?['message'] ?? 'If that address needs a code, it is on its way.'}';
  }

  /// Mark the address proven. The server also signs us in, so no second login follows.
  Future<Map<String, dynamic>> verifyConfirm(String email, String code) async =>
      (await _post('/api/verify/confirm', {'email': email, 'code': code}))
          as Map<String, dynamic>;

  bool get isVerifiedOnServer => false; // kept for readability of call sites

  Future<Map<String, dynamic>> me() async =>
      (await _get('/api/me')) as Map<String, dynamic>;

  Future<List<dynamic>> hits() async => (await hitsFeed()).hits;

  /// The list endpoint also returns an unread count; the app needs both.
  Future<({List<dynamic> hits, int unread})> hitsFeed() async {
    final j = await _get('/api/hits') as Map<String, dynamic>;
    return (
      hits: (j['hits'] as List<dynamic>?) ?? const [],
      unread: (j['unread'] as num?)?.toInt() ?? 0,
    );
  }

  /// Opening a hit clears its dot. Idempotent server-side.
  Future<void> markRead(int hitId) async {
    await _post('/api/hits/$hitId/read', const {});
  }

  Future<List<dynamic>> mails({int limit = 50}) async {
    final j = await _get('/api/mails?limit=$limit') as Map<String, dynamic>;
    return (j['mails'] as List<dynamic>?) ?? const [];
  }

  Future<Map<String, dynamic>> addId(String registerId) async =>
      (await _post('/api/me/ids', {'register_id': registerId}))
          as Map<String, dynamic>;

  /// Hands Play Services' token to the server. Same call the Kotlin shell made.
  /// Direct link to a hit's calendar file. Opened in the browser/Calendar app,
  /// which is the only reminder an iPhone can keep without a paid Apple account.
  String hitIcsUrl(int hitId) => '$_base/api/hits/$hitId/ics';

  Future<bool> registerFcmToken(String token) async {
    // The server picks a different payload shape per platform, so this must be
    // truthful: an iOS token registered as "android" gets a message FCM rejects.
    final platform = Platform.isIOS ? 'ios' : 'android';
    final r = await _post('/api/push/fcm', {'token': token, 'platform': platform});
    return r != null;
  }

  // ------------------------------------------------------------ account
  Future<Map<String, dynamic>> register({
    required String email,
    required String password,
    String name = '',
    String branch = '',
    String division = '',
  }) async {
    final r = await _http.post(
      Uri.parse('$_base/api/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email': email,
        'password': password,
        'name': name,
        'branch': branch,
        'division': division,
      }),
    ).timeout(const Duration(seconds: 20));
    if (r.statusCode >= 400) throw ApiException(r.statusCode, r.body);
    await _saveCookie(r.headers['set-cookie']);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateProfile({
    String? name,
    String? branch,
    String? division,
  }) async {
    final body = <String, dynamic>{
      'name': ?name,
      'branch': ?branch,
      'division': ?division,
    };
    return (await _put('/api/me/profile', body)) as Map<String, dynamic>;
  }

  /// Changing the login address. The password is required by the server: the email
  /// is also the reset channel, so a stolen session must not be able to move it.
  Future<Map<String, dynamic>> updateEmail(String email, String password) async =>
      (await _put('/api/me/email', {'email': email, 'password': password}))
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> deleteId(int rowId) async =>
      (await _delete('/api/me/ids/$rowId')) as Map<String, dynamic>;

  // ------------------------------------------------------------- admin
  Future<Map<String, dynamic>> adminStats() async =>
      (await _get('/api/admin/stats')) as Map<String, dynamic>;

  Future<Map<String, dynamic>> adminPoll() async =>
      ((await _post('/api/admin/poll', const {})) as Map<String, dynamic>?) ?? const {};

  Future<Map<String, dynamic>> adminTestPush(int userId) async =>
      ((await _post('/api/admin/test-push', {
        'user_id': userId,
        'title': 'Test from the app',
        'body': 'Sent by an admin from the Recruit client',
      })) as Map<String, dynamic>?) ??
      const {};

  /// People who pressed "forgot password" while mail was off — nobody answered them yet.
  Future<List<Map<String, dynamic>>> adminResetRequests() async {
    final j = await _get('/api/admin/password-requests') as Map<String, dynamic>;
    return ((j['requests'] as List<dynamic>?) ?? const [])
        .map((e) => e as Map<String, dynamic>)
        .toList();
  }

  /// Mints a single-use link the admin can forward by any channel at all.
  Future<Map<String, dynamic>> adminResetLink(int userId) async =>
      (await _post('/api/admin/users/$userId/reset-link', const {}))
          as Map<String, dynamic>;

  void close() => _http.close();
}

class ApiException implements Exception {
  const ApiException(this.status, this.body);
  final int status;
  final String body;

  /// FastAPI puts the human-readable reason in {"detail": ...}; the app shows that
  /// verbatim ("Wrong password.", "Another account already uses that address.").
  /// The server's machine-readable reason, when it sends one ("email_unverified").
  String get code {
    try {
      final j = jsonDecode(body);
      if (j is Map && j['code'] is String) return j['code'] as String;
    } catch (_) {}
    return '';
  }

  bool get needsVerification => status == 403 && code == 'email_unverified';

  String get detail {
    try {
      final j = jsonDecode(body);
      if (j is Map && j['detail'] is String) return j['detail'] as String;
    } catch (_) {}
    return body;
  }

  /// 401 means the session cookie is gone or stale — send the user to login.
  bool get isAuth => status == 401;

  @override
  String toString() => 'ApiException($status): $body';
}
