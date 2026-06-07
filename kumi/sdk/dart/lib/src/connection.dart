import 'auth.dart';
import 'env.dart';

class ConnectionConfig {
  final String mode;
  final String baseUrl;
  final String accessToken;

  ConnectionConfig({
    required this.mode,
    required this.baseUrl,
    required this.accessToken,
  });

  String websocketUrl() {
    if (mode == 'relay') {
      return '${httpToWs(baseUrl)}/ws/edge';
    }
    return baseUrl;
  }
}

String httpToWs(String u) {
  final t = u.replaceAll(RegExp(r'/+$'), '');
  if (t.startsWith('https://')) return 'wss://${t.substring(8)}';
  if (t.startsWith('http://')) return 'ws://${t.substring(7)}';
  return t;
}

Future<ConnectionConfig> resolveConnectionAsync(String code, String edgeName) async {
  var relayUrl = kumiEnv('KUMI_RELAY_URL');
  var accessToken = kumiEnv('KUMI_ACCESS_TOKEN');
  if (relayUrl.isNotEmpty && accessToken.isNotEmpty) {
    return ConnectionConfig(
      mode: 'relay',
      baseUrl: relayUrl.replaceAll(RegExp(r'/+$'), ''),
      accessToken: accessToken,
    );
  }

  if (code.startsWith('ws://') || code.startsWith('wss://')) {
    return ConnectionConfig(mode: 'direct', baseUrl: code, accessToken: '');
  }

  if (isLanCode(code)) {
    final serverUrl = parseLanCodeToServerUrl(code);
    final wsUrl = '${httpToWs(serverUrl)}/ws/edge';
    return ConnectionConfig(mode: 'direct', baseUrl: wsUrl, accessToken: '');
  }

  if (isRelayToken(code)) {
    final profile = await bootstrapProfileAsync(code, 'edge', edgeName);
    setKumiEnv('KUMI_RELAY_URL', profile.relayUrl);
    setKumiEnv('KUMI_ACCESS_TOKEN', profile.accessToken);
    return ConnectionConfig(
      mode: 'relay',
      baseUrl: profile.relayUrl,
      accessToken: profile.accessToken,
    );
  }

  if (code.startsWith('http://') || code.startsWith('https://')) {
    final base = code.replaceAll(RegExp(r'/+$'), '');
    final wsUrl = '${httpToWs(base)}/ws/edge';
    return ConnectionConfig(mode: 'direct', baseUrl: wsUrl, accessToken: '');
  }

  return ConnectionConfig(
    mode: 'direct',
    baseUrl: 'ws://127.0.0.1:8000/ws/edge',
    accessToken: '',
  );
}
