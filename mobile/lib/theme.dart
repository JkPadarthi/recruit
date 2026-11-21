import 'package:material_ui/material_ui.dart';

/// The PWA's design system, ported 1:1.
///
/// Every value here was read out of `static/style.css` — deep green-black
/// surfaces, saffron accent, three radii, two typefaces. The app previously
/// invented a navy/indigo palette, which is why it felt like a different
/// product standing next to the PWA.
class R {
  R._();

  // surfaces (--bg / --surface / --surface-2 / --surface-3)
  static const bg = Color(0xFF0E1715);
  static const surface = Color(0xFF16211E);
  static const surface2 = Color(0xFF1E2B27);
  static const surface3 = Color(0xFF283833);

  // hairlines (--line / --line-strong = rgba(220,240,230,0.08 / 0.16))
  static const line = Color(0x14DCF0E6);
  static const lineStrong = Color(0x29DCF0E6);

  // ink (--ink / --ink-2 / --ink-3)
  static const ink = Color(0xFFECF1EA);
  static const ink2 = Color(0xFFA9B8B1);
  static const ink3 = Color(0xFF74847D);

  // accents
  static const saffron = Color(0xFFF4B33D);
  static const saffronInk = Color(0xFF1C1405);
  static const saffronSoft = Color(0x24F4B33D); // 0.14 alpha
  static const good = Color(0xFF5FCB8A);
  static const info = Color(0xFF5AB8E8);
  static const over = Color(0xFFFF7A5C);

  // radii (--r-s / --r-m / --r-l)
  static const rS = 10.0;
  static const rM = 16.0;
  static const rL = 26.0;

  // reading width (--page), tab bar height (--tabbar-h)
  static const page = 600.0;
  static const tabbar = 68.0;

  static const ui = 'InstrumentSans';
  static const num = 'Bricolage';

  // ---- type scale, matching the PWA's sizes -------------------------------
  static const brand = TextStyle(
      fontFamily: num,
      fontSize: 19,
      fontWeight: FontWeight.w700,
      color: ink,
      letterSpacing: -0.2);
  static const h1 = TextStyle(
      fontFamily: ui, fontSize: 17, fontWeight: FontWeight.w700, color: ink, height: 1.25);
  static const subject = TextStyle(
      fontFamily: ui, fontSize: 15, fontWeight: FontWeight.w600, color: ink, height: 1.3);
  static const body =
      TextStyle(fontFamily: ui, fontSize: 13.5, color: ink2, height: 1.45);
  static const small =
      TextStyle(fontFamily: ui, fontSize: 13, color: ink2, height: 1.35);
  static const meta = TextStyle(fontFamily: ui, fontSize: 12, color: ink3, height: 1.2);

  /// Codes, application numbers and venues — tabular numerals read better in
  /// Bricolage, exactly like the PWA's --font-num.
  static const code = TextStyle(
      fontFamily: num, fontSize: 13, fontWeight: FontWeight.w600, color: ink, letterSpacing: 0.2);
  static const venue = TextStyle(
      fontFamily: num, fontSize: 15, fontWeight: FontWeight.w700, color: ink, height: 1.2);

  static BoxDecoration card({bool soft = false}) => BoxDecoration(
        color: soft ? surface2 : surface,
        borderRadius: BorderRadius.circular(rM),
        border: Border.all(color: line),
      );

  /// The amber "your row" panel from the feed.
  static BoxDecoration amberPanel() => BoxDecoration(
        color: saffronSoft,
        borderRadius: BorderRadius.circular(rS),
        border: Border.all(color: const Color(0x4DF4B33D)),
      );

  static BoxDecoration pill({Color bg = surface2, Color? border}) => BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
        border: border == null ? null : Border.all(color: border),
      );

  /// Stable colour per company, derived from the name.
  static Color companyColor(String name) {
    if (name.isEmpty) return saffron;
    var h = 0;
    for (final c in name.codeUnits) {
      h = (h * 31 + c) & 0x7fffffff;
    }
    return HSLColor.fromAHSL(1, (h % 360).toDouble(), 0.42, 0.66).toColor();
  }
}

ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    fontFamily: R.ui,
    colorScheme: const ColorScheme.dark(
      primary: R.saffron,
      onPrimary: R.saffronInk,
      secondary: R.good,
      surface: R.surface,
      onSurface: R.ink,
      error: R.over,
    ),
    scaffoldBackgroundColor: R.bg,
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(fontFamily: R.ui, bodyColor: R.ink, displayColor: R.ink),
    appBarTheme: const AppBarTheme(
      backgroundColor: R.bg,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      scrolledUnderElevation: 0,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: const Color(0xFF111C19),
      indicatorColor: R.saffronSoft,
      height: R.tabbar,
      labelTextStyle: WidgetStateProperty.all(
        const TextStyle(fontFamily: R.ui, fontSize: 11.5, fontWeight: FontWeight.w600),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 23,
          color: states.contains(WidgetState.selected) ? R.saffron : R.ink3,
        ),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: R.saffron,
        foregroundColor: R.saffronInk,
        textStyle:
            const TextStyle(fontFamily: R.ui, fontWeight: FontWeight.w700, fontSize: 13.5),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 11),
      ),
    ),
    dividerTheme: const DividerThemeData(color: R.line, thickness: 1, space: 1),
  );
}
