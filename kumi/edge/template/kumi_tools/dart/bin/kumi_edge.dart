import 'dart:async';

import 'package:kumi_edge/kumi_setup.dart';

Future<void> main() async {
  initKumi();
  // ignore: avoid_print
  print('Kumi edge running. Press Ctrl+C to stop.');
  await Future<void>.delayed(const Duration(days: 365));
}
