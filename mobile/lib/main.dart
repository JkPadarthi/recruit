import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'notify.dart';
import 'push.dart';
import 'screens/home.dart';
import 'screens/login.dart';

/// The one place the backend lives.
const String kBaseUrl = 'https://recruit.98487840.xyz';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Notifier.instance.init();
  runApp(const RecruitApp());
}

class RecruitApp extends StatelessWidget {
  const RecruitApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Recruit',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6C8CFF),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF0F1115),
      ),
      home: const Root(),
    );
  }
}

enum _Phase { loading, login, ready }

/// Login vs dashboard, decided by asking the server who we are. The session
/// cookie is persisted, so this is usually a silent, instant check.
class Root extends StatefulWidget {
  const Root({super.key});

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  final _api = ApiClient(kBaseUrl);
  _Phase _phase = _Phase.loading;
  Map<String, dynamic>? _me;

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    await _api.loadSession();
    if (!_api.hasSession) {
      if (mounted) setState(() => _phase = _Phase.login);
      return;
    }
    try {
      final me = await _api.me();
      if (!mounted) return;
      setState(() {
        _me = me;
        _phase = _Phase.ready;
      });
      // Firebase, FCM token, and the alarm-arming listeners. No-op until a
      // Firebase project exists.
      await Push.instance.start(_api);
    } on ApiException catch (e) {
      if (e.isAuth) await _api.logout();
      if (mounted) setState(() => _phase = _Phase.login);
    } catch (_) {
      if (mounted) setState(() => _phase = _Phase.login);
    }
  }

  Future<void> _onLoggedIn(Map<String, dynamic> me) async {
    setState(() {
      _me = me;
      _phase = _Phase.ready;
    });
    // Now there is a session cookie, so the device token has an owner.
    await Push.instance.start(_api);
  }

  Future<void> _signOut() async {
    await _api.logout();
    if (mounted) {
      setState(() {
        _me = null;
        _phase = _Phase.login;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    switch (_phase) {
      case _Phase.loading:
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      case _Phase.login:
        return LoginScreen(api: _api, onLoggedIn: _onLoggedIn);
      case _Phase.ready:
        return HomeScreen(api: _api, me: _me ?? const {}, onSignOut: _signOut);
    }
  }
}
