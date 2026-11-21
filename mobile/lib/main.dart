import 'package:material_ui/material_ui.dart';

import 'api.dart';
import 'notify.dart';
import 'onboarding.dart';
import 'perms.dart';
import 'push.dart';
import 'theme.dart';
import 'screens/home.dart';
import 'screens/login.dart';

/// The one place the backend lives.
/// Where the API lives. Overridable at build time:
///   flutter build apk --dart-define=BASE_URL=https://staging.example
/// A hardcoded host means a domain change forces a new APK on every phone.
const String kBaseUrl = String.fromEnvironment(
  'BASE_URL',
  defaultValue: 'https://recruit.jaswanth.me',
);

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
      theme: buildTheme(),
      home: const Root(),
    );
  }
}

enum _Phase { loading, login, onboarding, ready }

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
      final onboarded = await Perms.isOnboarded();
      if (!mounted) return;
      setState(() {
        _me = me;
        _phase = onboarded ? _Phase.ready : _Phase.onboarding;
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
    final onboarded = await Perms.isOnboarded();
    if (!mounted) return;
    setState(() {
      _me = me;
      _phase = onboarded ? _Phase.ready : _Phase.onboarding;
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
      case _Phase.onboarding:
        return OnboardingScreen(
          onDone: () async {
            if (mounted) setState(() => _phase = _Phase.ready);
          },
        );
      case _Phase.ready:
        return HomeScreen(api: _api, me: _me ?? const {}, onSignOut: _signOut);
    }
  }
}
