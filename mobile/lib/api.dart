import 'dart:convert';

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

  Future<void> logout() async {
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
    return _decode(r);
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final r = await _http
        .post(Uri.parse('$_base$path'),
            headers: _headers(json: true), body: jsonEncode(body))
        .timeout(const Duration(seconds: 20));
    return _decode(r);
  }

  dynamic _decode(http.Response r) {
    if (r.statusCode >= 400) {
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
  Future<bool> registerFcmToken(String token) async {
    final r = await _post('/api/push/fcm', {'token': token, 'platform': 'android'});
    return r != null;
  }

  void close() => _http.close();
}

class ApiException implements Exception {
  const ApiException(this.status, this.body);
  final int status;
  final String body;

  /// 401 means the session cookie is gone or stale — send the user to login.
  bool get isAuth => status == 401;

  @override
  String toString() => 'ApiException($status): $body';
}
