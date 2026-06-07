import 'dart:io';

final Map<String, String> _loadedEnv = {};

/// Loads `KEY=value` pairs from a `.env` file into a local map.
/// Does not override existing [Platform.environment] values (same as Go SDK).
void loadEnvFile(String path) {
  final f = File(path);
  if (!f.existsSync()) return;
  for (final line in f.readAsLinesSync()) {
    final t = line.trim();
    if (t.isEmpty || t.startsWith('#')) continue;
    final idx = t.indexOf('=');
    if (idx < 0) continue;
    var key = t.substring(0, idx).trim();
    var value = t.substring(idx + 1).trim();
    if (value.length >= 2) {
      final q = value[0];
      if ((q == '"' || q == "'") && value.endsWith(q)) {
        value = value.substring(1, value.length - 1);
      }
    }
    final existing = Platform.environment[key];
    if (existing == null || existing.isEmpty) {
      _loadedEnv[key] = value;
    }
  }
}

String yumiEnv(String key) {
  final p = Platform.environment[key];
  if (p != null && p.isNotEmpty) return p;
  return _loadedEnv[key] ?? '';
}

void setYumiEnv(String key, String value) {
  _loadedEnv[key] = value;
}
