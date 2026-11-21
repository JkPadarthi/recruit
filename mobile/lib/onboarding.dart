import 'package:material_ui/material_ui.dart';

import 'perms.dart';
import 'theme.dart';

/// First-run storyboard: explain, then ask. Every permission gets a reason in
/// plain language before the system dialog appears, and the two the app does NOT
/// want are said out loud — students are right to be suspicious of a free app.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key, required this.onDone});

  final Future<void> Function() onDone;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> with WidgetsBindingObserver {
  final _pages = PageController();
  int _page = 0;
  bool _notif = false;
  bool _exact = false;
  bool _battery = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pages.dispose();
    super.dispose();
  }

  /// Permission answers arrive outside the app (system sheet, Settings screen),
  /// so status is re-read whenever we come back to the foreground.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    final s = await Perms.snapshot();
    if (!mounted) return;
    setState(() {
      _notif = s.notifications;
      _exact = s.exact;
      _battery = s.battery;
    });
  }

  Future<void> _finish() async {
    await Perms.markOnboarded();
    await widget.onDone();
  }

  void _next() {
    if (_page >= 3) {
      _finish();
      return;
    }
    _pages.nextPage(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: R.bg,
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: R.page),
            child: Column(
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: _finish,
                    style: TextButton.styleFrom(foregroundColor: R.ink3),
                    child: const Text('Skip', style: R.meta),
                  ),
                ),
                Expanded(
                  child: PageView(
                    controller: _pages,
                    onPageChanged: (i) => setState(() => _page = i),
                    children: [
                      _welcome(),
                      _notificationsPage(),
                      _exactAlarmPage(),
                      _batteryPage(),
                    ],
                  ),
                ),
                _dots(),
                const SizedBox(height: 14),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 18),
                  child: SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _next,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Text(_page >= 3 ? 'Done' : 'Next'),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // --------------------------------------------------------------- page shell
  Widget _shell({
    required IconData icon,
    required String title,
    required String body,
    required Widget action,
    String? fineprint,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 66,
            height: 66,
            decoration: BoxDecoration(
              color: R.saffronSoft,
              shape: BoxShape.circle,
              border: Border.all(color: const Color(0x4DF4B33D)),
            ),
            child: Icon(icon, size: 30, color: R.saffron),
          ),
          const SizedBox(height: 20),
          Text(title, textAlign: TextAlign.center, style: R.brand.copyWith(fontSize: 22)),
          const SizedBox(height: 10),
          Text(body, textAlign: TextAlign.center, style: R.body),
          const SizedBox(height: 22),
          action,
          if (fineprint != null) ...[
            const SizedBox(height: 12),
            Text(fineprint, textAlign: TextAlign.center, style: R.meta),
          ],
        ],
      ),
    );
  }

  Widget _statusPill(bool ok, String yes, String no) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 4),
        decoration: R.pill(
          bg: ok ? R.saffronSoft : R.surface2,
          border: ok ? const Color(0x4DF4B33D) : R.line,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(ok ? Icons.check_circle_rounded : Icons.circle_outlined,
                size: 13, color: ok ? R.saffron : R.ink3),
            const SizedBox(width: 5),
            Text(ok ? yes : no, style: R.meta.copyWith(color: ok ? R.saffron : R.ink3)),
          ],
        ),
      );

  // ------------------------------------------------------------------- pages
  Widget _welcome() => _shell(
        icon: Icons.mark_email_read_outlined,
        title: 'CDC mail, without\nopening CDC mail',
        body: 'Recruit reads the placement mailbox for you. When your code appears in '
            'a shortlist, you get one line: what it is, when it is, and which room.',
        action: Column(
          children: [
            Container(
              padding: const EdgeInsets.all(13),
              decoration: R.card(),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('What we will ask for', style: R.meta.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  _askLine('Notifications', 'so the shortlist can reach you'),
                  _askLine('Alarms & reminders', 'so "report at 2:30" fires at 2:30'),
                  _askLine('Battery exemption', 'optional, so Android stops freezing us'),
                  const SizedBox(height: 10),
                  Text('We never ask for camera, contacts, location, or your files.',
                      style: R.meta.copyWith(color: R.saffron)),
                ],
              ),
            ),
          ],
        ),
      );

  Widget _askLine(String title, String why) => Padding(
        padding: const EdgeInsets.only(bottom: 5),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('· ', style: R.meta),
            Expanded(
              child: RichText(
                text: TextSpan(children: [
                  TextSpan(
                      text: '$title ',
                      style: R.small.copyWith(color: R.ink, fontWeight: FontWeight.w600)),
                  TextSpan(text: why, style: R.meta),
                ]),
              ),
            ),
          ],
        ),
      );

  Widget _notificationsPage() => _shell(
        icon: Icons.notifications_active_outlined,
        title: 'Shortlists, delivered',
        body: 'When a list contains your code, a notification arrives in seconds — '
            'even with the app closed. Android needs your permission for that.',
        action: Column(
          children: [
            _statusPill(_notif, 'Notifications on', 'Not allowed yet'),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _notif
                  ? _next
                  : () async {
                      await Perms.requestNotifications();
                      await _refresh();
                    },
              child: Text(_notif ? 'Continue' : 'Allow notifications'),
            ),
          ],
        ),
        fineprint: 'No sounds? Check that the Recruit channel is not muted in settings.',
      );

  Widget _exactAlarmPage() => _shell(
        icon: Icons.alarm_outlined,
        title: 'The 2.30 pm problem',
        body: 'Your mail says "report to PRP 713 at 2.30 pm". Recruit sets an alarm at '
            '1.00 pm and 2.00 pm. Android calls this "Alarms & reminders", and on '
            'Android 14 it is off by default.',
        action: Column(
          children: [
            _statusPill(_exact, 'Exact alarms allowed', 'Using approximate alarms'),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _exact
                  ? _next
                  : () async {
                      await Perms.openExactAlarmSettings();
                      await _refresh();
                    },
              child: Text(_exact ? 'Continue' : 'Open setting'),
            ),
            if (!_exact)
              TextButton(
                onPressed: _next,
                style: TextButton.styleFrom(foregroundColor: R.ink3),
                child: const Text('Later', style: R.meta),
              ),
          ],
        ),
        fineprint: 'Without it the reminder still fires, but Android may shift it by a few minutes.',
      );

  Widget _batteryPage() => _shell(
        icon: Icons.battery_saver_outlined,
        title: 'Stop the phone\nfrom sleeping Recruit',
        body: 'Some phones (Xiaomi, Realme, OPPO, vivo) freeze background apps to save '
            'battery, which delays notifications by hours. Adding Recruit to the '
            'no-restrictions list fixes it.',
        action: Column(
          children: [
            _statusPill(_battery, 'Already unrestricted', 'Still optimised'),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _battery
                  ? _finish
                  : () async {
                      await Perms.requestBatteryExemption();
                      await _refresh();
                    },
              child: Text(_battery ? 'Finish' : 'Allow'),
            ),
            if (!_battery)
              TextButton(
                onPressed: _finish,
                style: TextButton.styleFrom(foregroundColor: R.ink3),
                child: const Text('Skip — it may still work', style: R.meta),
              ),
          ],
        ),
        fineprint: 'Optional. Reminders work without it; only delivery of new mail can lag.',
      );

  Widget _dots() => Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          for (var i = 0; i < 4; i++)
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              margin: const EdgeInsets.symmetric(horizontal: 3),
              width: i == _page ? 18 : 6,
              height: 6,
              decoration: BoxDecoration(
                color: i == _page ? R.saffron : R.surface3,
                borderRadius: BorderRadius.circular(99),
              ),
            ),
        ],
      );
}
