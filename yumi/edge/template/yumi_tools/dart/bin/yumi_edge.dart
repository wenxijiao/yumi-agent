import 'dart:async';

import 'package:yumi_edge/yumi_setup.dart';

Future<void> main() async {
  initYumi();
  // ignore: avoid_print
  print('Yumi edge running. Press Ctrl+C to stop.');
  await Future<void>.delayed(const Duration(days: 365));
}
