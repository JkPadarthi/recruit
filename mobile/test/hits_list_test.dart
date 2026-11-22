import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:recruit/models.dart';
import 'package:recruit/screens/home.dart';

/// Pins the bug that shipped in 1.3.1: `HitCard` used `Row(crossAxisAlignment: stretch)`
/// inside a ListView, where the height is unbounded. Debug throws an assertion; a RELEASE
/// build strips it, gives the first card an infinite height, and pushes every other card
/// off-screen — the counter said "13 Your hits" and the phone showed exactly one.
///
/// The assertion is geometric on purpose: the test binding's viewport hides `Material`
/// from lazily built children, so ink widgets complain in the harness and never on device.
void main() {
  Hit hit(int id, String company, {String slot = ''}) => Hit.fromJson({
        'id': id,
        'ingested_id': id,
        'read': false,
        'first_seen_at': '2026-11-20T12:00:00+05:30',
        'subject': '$company Online Test on 23-11-2026',
        'kind': 'selection',
        'company': company,
        'slot': slot,
      });

  testWidgets('every card has a finite height, with or without a sheet row',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ListView(
          children: [
            HitCard(
              hit: hit(1, 'HCL Tech',
                  slot: 'Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)'),
              unread: true,
              onTap: () {},
            ),
            HitCard(hit: hit(2, 'Capgemini'), unread: false, onTap: () {}),
            HitCard(hit: hit(3, 'Accenture'), unread: false, onTap: () {}),
          ],
        ),
      ),
    ));
    tester.takeException(); // the harness's missing ink canvas, not a layout fault

    for (var i = 0; i < 3; i++) {
      final size = tester.getSize(find.byType(HitCard).at(i));
      expect(size.height.isFinite, isTrue, reason: 'card $i asked for infinite height');
      expect(size.height, lessThan(400), reason: 'card $i is swallowing the viewport');
      expect(size.height, greaterThan(40), reason: 'card $i collapsed');
    }
    expect(find.text('Accenture'), findsOneWidget,
        reason: 'the third card must be in the tree, not pushed off-screen');
  });
}
