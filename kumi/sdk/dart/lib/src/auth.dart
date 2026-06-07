import 'dart:convert';

import 'package:http/http.dart' as http;

const _tokenPrefix = 'kumi_';
const _lanTokenPrefix = 'kumi-lan_';
const _legacyLanPrefixes = ['ml1_', 'kumi_lan_'];

List<int> _b64urlDecode(String data) {
  var padding = (4 - data.length % 4) % 4;
  final padded = data + '=' * padding;
  return base64Url.decode(padded);
}

bool isLanCode(String code) {
  if (code.startsWith(_lanTokenPrefix)) return true;
  for (final p in _legacyLanPrefixes) {
    if (code.startsWith(p)) return true;
  }
  return false;
}

bool isRelayToken(String code) =>
    code.startsWith(_tokenPrefix) && !isLanCode(code);

String parseLanCodeToServerUrl(String code) {
  String encoded;
  if (code.startsWith(_lanTokenPrefix)) {
    encoded = code.substring(_lanTokenPrefix.length);
  } else {
    encoded = '';
    for (final p in _legacyLanPrefixes) {
      if (code.startsWith(p)) {
        encoded = code.substring(p.length);
        break;
      }
    }
    if (encoded.isEmpty) {
      throw ArgumentError('invalid Kumi LAN code prefix');
    }
  }
  final raw = utf8.decode(_b64urlDecode(encoded));
  final data = jsonDecode(raw) as Map<String, dynamic>;
  String host;
  int port;
  if (data.containsKey('h')) {
    host = '${data['h']}';
    port = (data['p'] is num) ? (data['p'] as num).toInt() : 8000;
  } else if (data.containsKey('base_url')) {
    final uri = Uri.parse('${data['base_url']}');
    host = uri.host;
    if (host.isEmpty) throw ArgumentError('LAN code missing host');
    port = uri.port > 0 ? uri.port : 8000;
  } else {
    throw ArgumentError('LAN code missing host');
  }
  if (data.containsKey('x')) {
    final x = data['x'];
    if (x is num) {
      final exp = x.toInt();
      final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
      if (exp > 0 && exp < now) {
        throw ArgumentError('LAN code has expired');
      }
    }
  }
  return 'http://$host:$port';
}

class BootstrapResult {
  final String relayUrl;
  final String accessToken;

  BootstrapResult({required this.relayUrl, required this.accessToken});
}

Future<BootstrapResult> bootstrapProfileAsync(
  String joinCode,
  String scope,
  String deviceName,
) async {
  final cred = jsonDecode(
    utf8.decode(_b64urlDecode(joinCode.substring(_tokenPrefix.length))),
  ) as Map<String, dynamic>;
  final relayUrl = (cred['relay_url'] as String).replaceAll(RegExp(r'/+$'), '');
  final body = jsonEncode({
    'join_code': joinCode,
    'scope': scope,
    'device_name': deviceName.trim(),
  });
  final resp = await http.post(
    Uri.parse('$relayUrl/v1/bootstrap'),
    headers: {'Content-Type': 'application/json'},
    body: body,
  );
  if (resp.statusCode >= 400) {
    throw Exception('bootstrap failed: ${resp.body}');
  }
  final result = jsonDecode(resp.body) as Map<String, dynamic>;
  final at = result['access_token'] as String?;
  if (at == null || at.isEmpty) {
    throw Exception('bootstrap response missing access_token');
  }
  return BootstrapResult(relayUrl: relayUrl, accessToken: at);
}
