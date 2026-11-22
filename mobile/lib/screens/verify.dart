import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../theme.dart';

/// Signup proves the address, not just the password.
///
/// Behind this screen the server answers every data route with 403
/// `email_unverified` — deliberately, because an unverified account used to be able to
/// claim a classmate's address and receive their shortlists.
class VerifyScreen extends StatefulWidget {
  const VerifyScreen({
    super.key,
    required this.api,
    required this.email,
    required this.onVerified,
    required this.onSignOut,
  });

  final ApiClient api;
  final String email;
  final Future<void> Function() onVerified;
  final Future<void> Function() onSignOut;

  @override
  State<VerifyScreen> createState() => _VerifyScreenState();
}

class _VerifyScreenState extends State<VerifyScreen> {
  final _code = TextEditingController();
  bool _busy = false;
  String? _note;
  bool _noteBad = false;
  int _resendIn = 0;
  Timer? _tick;

  @override
  void dispose() {
    _tick?.cancel();
    _code.dispose();
    super.dispose();
  }

  void _say(String text, {bool bad = false}) =>
      setState(() { _note = text; _noteBad = bad; });

  Future<void> _submit() async {
    final code = _code.text.trim();
    if (code.length != 6) return _say('Enter all six digits.', bad: true);
    setState(() => _busy = true);
    try {
      await widget.api.verifyConfirm(widget.email, code);
      await widget.onVerified();
    } on ApiException catch (e) {
      _say(e.detail, bad: true);
    } catch (e) {
      _say('Could not check that code: $e', bad: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _resend() async {
    if (_resendIn > 0) return;
    setState(() => _resendIn = 60);
    _tick?.cancel();
    _tick = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      setState(() => _resendIn = _resendIn - 1);
      if (_resendIn <= 0) t.cancel();
    });
    try {
      final msg = await widget.api.verifyStart(widget.email);
      _say(msg);
    } catch (e) {
      _say('Could not send a new code: $e', bad: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: R.bg,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(22, 28, 22, 28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Image.asset('assets/brand/logo.png', width: 64, height: 64),
                  const SizedBox(height: 20),
                  Text('Check your email', style: R.h1),
                  const SizedBox(height: 8),
                  Text(
                    'We sent a six-digit code to ${widget.email}. It expires in 30 minutes.',
                    style: R.body,
                  ),
                  const SizedBox(height: 20),
                  TextField(
                    controller: _code,
                    autofocus: true,
                    keyboardType: TextInputType.number,
                    textAlign: TextAlign.center,
                    maxLength: 6,
                    style: R.brand.copyWith(fontSize: 24, letterSpacing: 10, color: R.ink),
                    cursorColor: R.saffron,
                    decoration: InputDecoration(
                      counterText: '',
                      hintText: '000000',
                      hintStyle: R.brand.copyWith(
                          fontSize: 24, letterSpacing: 10, color: R.ink3.withValues(alpha: 0.4)),
                      filled: true,
                      fillColor: R.surface2,
                      contentPadding: const EdgeInsets.symmetric(vertical: 16),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(R.rS),
                          borderSide: BorderSide.none),
                    ),
                    onChanged: (v) {
                      final digits = v.replaceAll(RegExp(r'\D'), '');
                      if (digits != v) _code.text = digits;
                      if (digits.length == 6) _submit();
                    },
                  ),
                  const SizedBox(height: 14),
                  SizedBox(
                    height: 46,
                    child: FilledButton(
                      onPressed: _busy ? null : _submit,
                      style: FilledButton.styleFrom(
                        backgroundColor: R.saffron,
                        foregroundColor: R.saffronInk,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(R.rS)),
                      ),
                      child: _busy
                          ? const SizedBox(
                              height: 18, width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Verify and continue'),
                    ),
                  ),
                  if (_note != null) ...[
                    const SizedBox(height: 14),
                    Text(_note!,
                        textAlign: TextAlign.center,
                        style: R.small.copyWith(
                            color: _noteBad ? R.over : R.good)),
                  ],
                  const SizedBox(height: 18),
                  TextButton(
                    onPressed: _resendIn > 0 ? null : _resend,
                    child: Text(_resendIn > 0
                        ? 'Send a new code in ${_resendIn}s'
                        : 'Nothing arrived? Send a new code'),
                  ),
                  TextButton(
                    onPressed: widget.onSignOut,
                    style: TextButton.styleFrom(foregroundColor: R.ink3),
                    child: const Text('Use a different account', style: R.meta),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
