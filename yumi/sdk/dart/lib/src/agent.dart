import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'connection.dart';
import 'env.dart';
import 'schema.dart';
import 'types.dart';

const _logPrefix = '[Yumi]';
const _toolConfirmationFile = '.yumi_tool_confirmation.json';

class YumiAgent {
  final List<RegisterOptions> _registrations = [];
  bool _stopped = false;
  late final String _connectionCode;
  late final String _edgeName;
  late final String _policyBaseDir;

  YumiAgent(AgentOptions opts) {
    final envPath = _resolveEnvPath(opts.envPath);
    loadEnvFile(envPath);
    _policyBaseDir = File(envPath).parent.path;

    // Allow callers to provide (relayUrl, accessToken) directly — typical
    // mobile-app flow where the access token came from an identity bridge
    // and the SDK shouldn't try to bootstrap. We feed them through the
    // same in-process env map that resolveConnectionAsync already reads.
    final directRelay = (opts.relayUrl ?? '').trim();
    final directToken = (opts.accessToken ?? '').trim();
    if (directRelay.isNotEmpty && directToken.isNotEmpty) {
      setYumiEnv('YUMI_RELAY_URL', directRelay);
      setYumiEnv('YUMI_ACCESS_TOKEN', directToken);
    }

    var cc = opts.connectionCode ?? '';
    if (cc.isEmpty) cc = yumiEnv('YUMI_CONNECTION_CODE');
    if (cc.isEmpty) cc = yumiEnv('BRAIN_URL');
    _connectionCode = cc;

    var en = opts.edgeName ?? '';
    if (en.isEmpty) en = yumiEnv('EDGE_NAME');
    if (en.isEmpty) {
      en = Platform.environment['HOSTNAME'] ??
          Platform.environment['COMPUTERNAME'] ??
          'yumi-edge';
    }
    _edgeName = en;
  }

  void register(RegisterOptions opts) {
    _registrations.add(opts);
  }

  /// Starts the WebSocket loop (async). Does not block.
  void runInBackground() {
    unawaited(_connectLoop());
  }

  void stop() {
    _stopped = true;
  }

  Future<void> _connectLoop() async {
    var delay = const Duration(seconds: 3);
    while (!_stopped) {
      try {
        await _runSession();
        if (_stopped) break;
        delay = const Duration(seconds: 3);
      } catch (e) {
        if (_stopped) break;
        // ignore: avoid_print
        print('$_logPrefix Connection lost: $e. Reconnecting in ${delay.inSeconds}s...');
        await Future<void>.delayed(delay + Duration(milliseconds: DateTime.now().millisecond % 500));
        delay = Duration(seconds: (delay.inSeconds * 2).clamp(3, 30));
      }
    }
  }

  Future<void> _runSession() async {
    final cfg = await resolveConnectionAsync(_connectionCode, _edgeName);
    final wsUrl = cfg.websocketUrl();
    final token = cfg.accessToken;

    final tools = _registrations.map(buildToolSchema).toList();
    final registerPayload = <String, dynamic>{
      'type': 'register',
      'edge_name': _edgeName,
      'tools': tools,
      'tool_confirmation_policy': _loadConfirmationPolicy(),
    };
    if (token.isNotEmpty) {
      registerPayload['access_token'] = token;
    }

    final channel = WebSocketChannel.connect(Uri.parse(wsUrl));
    channel.sink.add(jsonEncode(registerPayload));

    // ignore: avoid_print
    print('$_logPrefix Connected as [$_edgeName] with ${tools.length} tool(s).');

    final done = Completer<void>();
    late final StreamSubscription<dynamic> sub;
    sub = channel.stream.listen(
      (dynamic message) {
        final text = message is String ? message : utf8.decode(message as List<int>);
        unawaited(_handleMessage(channel, text));
      },
      onError: (Object e, StackTrace st) {
        if (!done.isCompleted) done.completeError(e, st);
      },
      onDone: () {
        if (!done.isCompleted) done.complete();
      },
      cancelOnError: false,
    );

    await done.future;
    await sub.cancel();
  }

  Future<void> _handleMessage(WebSocketChannel channel, String text) async {
    Map<String, dynamic> v;
    try {
      v = jsonDecode(text) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    final msgType = v['type'] as String? ?? '';
    if (msgType == 'persist_tool_confirmation_policy') {
      _persistPolicy(v);
      return;
    }
    if (msgType == 'register_warning') {
      final dropped = (v['skipped_tools'] as List?) ?? const [];
      print('$_logPrefix Server did not mount ${dropped.length} tool(s).');
      return;
    }
    if (msgType == 'register_rejected') {
      // Refused (edge_name in use). Stop — don't reconnect to be rejected again.
      final reason = v['reason'] as String? ?? 'edge_name already in use';
      print('$_logPrefix Edge registration rejected by server: $reason');
      _stopped = true;
      await channel.sink.close();
      return;
    }
    if (msgType != 'tool_call') return;

    final name = v['name'] as String? ?? '';
    final callId = v['call_id'] as String? ?? 'unknown';
    final rawArgs = (v['arguments'] as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
    final args = ToolArguments(rawArgs);

    String result;
    RegisterOptions? reg;
    for (final r in _registrations) {
      if (r.name == name) {
        reg = r;
        break;
      }
    }
    if (reg == null) {
      result = "Error: Tool '$name' is not registered on this edge.";
    } else {
      try {
        result = await reg.handler(args);
      } catch (e) {
        result = 'Error executing tool: $e';
      }
    }

    final reply = jsonEncode({
      'type': 'tool_result',
      'call_id': callId,
      'result': result,
      'cancelled': false,
    });
    channel.sink.add(reply);
  }

  void _persistPolicy(Map<String, dynamic> msg) {
    final aa = (msg['always_allow'] as List?)?.map((e) => '$e').toList() ?? <String>[];
    final fc = (msg['force_confirm'] as List?)?.map((e) => '$e').toList() ?? <String>[];
    _saveConfirmationPolicy(aa, fc);
  }

  String _confirmationPath() {
    final o = yumiEnv('YUMI_TOOL_CONFIRMATION_PATH');
    if (o.isNotEmpty) return o;
    return '$_policyBaseDir/$_toolConfirmationFile';
  }

  Map<String, dynamic> _loadConfirmationPolicy() {
    final p = _confirmationPath();
    final f = File(p);
    if (!f.existsSync()) {
      return {'always_allow': <String>[], 'force_confirm': <String>[]};
    }
    try {
      final m = jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;
      return {
        'always_allow': m['always_allow'] ?? [],
        'force_confirm': m['force_confirm'] ?? [],
      };
    } catch (_) {
      return {'always_allow': <String>[], 'force_confirm': <String>[]};
    }
  }

  void _saveConfirmationPolicy(List<String> alwaysAllow, List<String> forceConfirm) {
    final path = _confirmationPath();
    final dir = File(path).parent;
    if (!dir.existsSync()) dir.createSync(recursive: true);
    File(path).writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert({
        'always_allow': alwaysAllow,
        'force_confirm': forceConfirm,
      }),
    );
  }
}

String _resolveEnvPath(String? explicit) {
  if (explicit != null && explicit.isNotEmpty) return explicit;
  // Walk up from cwd so the edge finds yumi_tools/.env regardless of which
  // subdir it is launched from (e.g. cwd = <workspace>/yumi_tools/dart).
  var dir = Directory.current.absolute;
  while (true) {
    final a = File('${dir.path}/yumi_tools/.env');
    if (a.existsSync()) return a.path;
    final b = File('${dir.path}/.env');
    if (b.existsSync()) return b.path;
    final parent = dir.parent;
    if (parent.path == dir.path) break; // reached filesystem root
    dir = parent;
  }
  return '${Directory.current.path}/.env';
}
