/// One-call "connect this app to a Yumi deployment" helper.
///
/// Any third-party app that wants to expose tools to a Yumi deployment goes
/// through the same handshake:
///
/// ```
/// App  ──open(?app_id=X&return_to=Y&state=Z)──▶  Identity Portal
///                                                       │
///                                                       │ signs user in
///                                                       ▼
///                                              POST /auth/issue-app-token
///                                                       │
/// App  ◀────────────deep-link callback ?access_token=…&state=Z──────
///                                                       │
/// App  ──YumiAgent(connectionCode: access_token)──▶  Yumi
/// ```
///
/// The protocol is identity-provider-agnostic: this SDK only deals with the
/// URL handoff and the resulting access token. Authenticating the user
/// (Firebase, OAuth, magic link, whatever) is the portal's job.
///
/// Because the actual "open a browser" and "wait for a deep-link callback"
/// primitives differ between Flutter, pure Dart CLI, and embedded contexts,
/// the helper takes a [YumiAppHandshakeAdapter]. The SDK ships a desktop
/// adapter that uses a loopback HTTP server; Flutter apps supply their own
/// adapter that bridges `url_launcher` + a deep-link receiver.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'agent.dart';
import 'types.dart';

/// Tokens returned by an identity portal after a successful handshake.
class YumiAppTokens {
  /// The Yumi access token to pass as ``connectionCode`` to [YumiAgent].
  /// Required.
  final String accessToken;

  /// Optional identity-provider ID token (e.g. Firebase ID token) that the
  /// portal sometimes returns alongside the Yumi access token. The SDK
  /// passes it through unchanged; consumers store / use it as they like.
  final String? idToken;

  /// Free-form additional fields the portal returned. The SDK preserves
  /// everything unknown so app-level code can read deployment-specific
  /// metadata (e.g. ``custom_token`` for cross-project Firebase Auth).
  final Map<String, String> extra;

  const YumiAppTokens({
    required this.accessToken,
    this.idToken,
    this.extra = const {},
  });

  factory YumiAppTokens.fromCallback(Uri callback) {
    final params = callback.queryParameters;
    final access = (params['access_token'] ?? '').trim();
    if (access.isEmpty) {
      throw const YumiAppHandshakeException(
        'Portal callback did not include access_token.',
      );
    }
    final id = (params['id_token'] ?? params['token'] ?? '').trim();
    final extra = <String, String>{};
    params.forEach((k, v) {
      if (k == 'access_token' || k == 'id_token' || k == 'token' || k == 'state') {
        return;
      }
      extra[k] = v;
    });
    return YumiAppTokens(
      accessToken: access,
      idToken: id.isEmpty ? null : id,
      extra: extra,
    );
  }

  Map<String, dynamic> toJson() => {
        'access_token': accessToken,
        if (idToken != null) 'id_token': idToken,
        if (extra.isNotEmpty) 'extra': extra,
      };

  factory YumiAppTokens.fromJson(Map<String, dynamic> json) {
    final extraRaw = json['extra'];
    final extra = <String, String>{};
    if (extraRaw is Map) {
      extraRaw.forEach((k, v) {
        if (k is String && v != null) extra[k] = v.toString();
      });
    }
    return YumiAppTokens(
      accessToken: (json['access_token'] ?? '').toString(),
      idToken: (json['id_token'] as String?)?.trim().isEmpty ?? true
          ? null
          : (json['id_token'] as String).trim(),
      extra: extra,
    );
  }
}

class YumiAppHandshakeException implements Exception {
  final String message;
  const YumiAppHandshakeException(this.message);

  @override
  String toString() => 'YumiAppHandshakeException: $message';
}

/// Platform glue for opening the portal URL and receiving the callback.
abstract class YumiAppHandshakeAdapter {
  /// Open [portalUrl] in the user's browser and resolve with the callback
  /// URI once the portal redirects back. Implementations validate that the
  /// callback's ``state`` matches [expectedState] (the SDK also re-validates
  /// after this returns, defence-in-depth).
  Future<Uri> openAndAwaitCallback({
    required Uri portalUrl,
    required String expectedState,
  });

  /// Persist [tokens] for the given [appId]. Implementations use whatever
  /// secure storage is appropriate (keychain on iOS, encrypted shared prefs
  /// on Android, encrypted file on desktop).
  Future<void> storeTokens(String appId, YumiAppTokens tokens);

  /// Load previously stored tokens for [appId], or null if none.
  Future<YumiAppTokens?> loadStoredTokens(String appId);

  /// Forget any stored tokens for [appId] (called by [YumiApp.disconnect]).
  Future<void> clearStoredTokens(String appId);
}

/// Desktop / CLI handshake adapter.
///
/// Spins a one-shot HTTP server on a loopback port to receive the portal's
/// callback redirect (the portal's [apps/{appId}] entry must allow
/// ``http://localhost:*/cb`` for this to work) and writes tokens to a file
/// in [storageDir] (``~/.yumi/app_tokens/<appId>.json`` by default).
class LoopbackHandshakeAdapter implements YumiAppHandshakeAdapter {
  final Directory? storageDir;
  final void Function(Uri portalUrl)? onOpenUrl;
  final Duration callbackTimeout;

  LoopbackHandshakeAdapter({
    this.storageDir,
    this.onOpenUrl,
    this.callbackTimeout = const Duration(minutes: 5),
  });

  Directory get _resolvedStorageDir {
    if (storageDir != null) return storageDir!;
    final home = Platform.environment['HOME'] ??
        Platform.environment['USERPROFILE'] ??
        Directory.current.path;
    return Directory('$home/.yumi/app_tokens');
  }

  File _tokenFile(String appId) {
    final dir = _resolvedStorageDir;
    if (!dir.existsSync()) dir.createSync(recursive: true);
    final safeId = appId.replaceAll(RegExp(r'[^a-zA-Z0-9_.-]'), '_');
    return File('${dir.path}/$safeId.json');
  }

  @override
  Future<Uri> openAndAwaitCallback({
    required Uri portalUrl,
    required String expectedState,
  }) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    try {
      final callbackPath = portalUrl.queryParameters['return_to'] ?? '';
      final cbPath = Uri.tryParse(callbackPath)?.path ?? '/cb';
      final completer = Completer<Uri>();
      final timer = Timer(callbackTimeout, () {
        if (!completer.isCompleted) {
          completer.completeError(
            const YumiAppHandshakeException(
              'Portal handshake timed out (no callback received).',
            ),
          );
        }
      });
      server.listen((req) async {
        if (req.uri.path != cbPath) {
          req.response
            ..statusCode = 404
            ..close();
          return;
        }
        final ok = req.uri.queryParameters['state'] == expectedState;
        req.response.headers.contentType = ContentType.html;
        req.response.write(
          ok
              ? '<!doctype html><meta charset="utf-8"><h1>Connected.</h1>'
                '<p>You may close this window and return to the app.</p>'
              : '<!doctype html><meta charset="utf-8"><h1>State mismatch.</h1>'
                '<p>Please retry from the app.</p>',
        );
        await req.response.close();
        if (!completer.isCompleted) {
          if (ok) {
            completer.complete(req.uri);
          } else {
            completer.completeError(
              const YumiAppHandshakeException('Portal callback state mismatch.'),
            );
          }
        }
      });
      if (onOpenUrl != null) {
        onOpenUrl!(portalUrl);
      } else {
        // ignore: avoid_print
        print('[Yumi] Open this URL to finish connecting:\n${portalUrl.toString()}');
      }
      final result = await completer.future;
      timer.cancel();
      return result;
    } finally {
      await server.close(force: true);
    }
  }

  @override
  Future<void> storeTokens(String appId, YumiAppTokens tokens) async {
    final f = _tokenFile(appId);
    await f.writeAsString(jsonEncode(tokens.toJson()));
  }

  @override
  Future<YumiAppTokens?> loadStoredTokens(String appId) async {
    final f = _tokenFile(appId);
    if (!await f.exists()) return null;
    try {
      final decoded = jsonDecode(await f.readAsString());
      if (decoded is Map<String, dynamic>) {
        return YumiAppTokens.fromJson(decoded);
      }
    } catch (_) {}
    return null;
  }

  @override
  Future<void> clearStoredTokens(String appId) async {
    final f = _tokenFile(appId);
    if (await f.exists()) {
      try {
        await f.delete();
      } catch (_) {}
    }
  }
}

/// Bind options for [YumiApp.connect].
class YumiAppConnectOptions {
  /// Stable identifier of the app in the deployment's app registry. The same
  /// value the portal sees as ``?app_id=...`` and the framework later reads
  /// from the access token's metadata.
  final String appId;

  /// Identity-portal URL the deployment publishes (e.g.
  /// ``https://identity.example.com/``). The SDK appends ``app_id``,
  /// ``return_to``, and ``state`` query parameters.
  final Uri identityPortalUrl;

  /// Deep-link or loopback URL the portal redirects back to with tokens.
  /// On desktop/CLI use ``http://localhost:0/cb`` and let the loopback
  /// adapter pick a port (the portal must allow ``http://localhost:*/cb``).
  /// On Flutter use the app's custom scheme, e.g. ``com.example.myapp://auth``.
  final Uri returnTo;

  /// Optional name shown in the deployment's edge list, e.g.
  /// ``"Alice's iPhone"``. Defaults to the host name.
  final String? edgeName;

  /// If true and stored tokens already exist for [appId], skip the portal
  /// handshake and reuse them. Default true.
  final bool reuseStored;

  const YumiAppConnectOptions({
    required this.appId,
    required this.identityPortalUrl,
    required this.returnTo,
    this.edgeName,
    this.reuseStored = true,
  });
}

/// Top-level helper: portal handshake → token persistence → started [YumiAgent].
class YumiApp {
  /// Run the full connect flow.
  ///
  /// 1. If [opts.reuseStored] is true and stored tokens exist, skip the
  ///    portal handshake.
  /// 2. Otherwise: open the portal, wait for the callback, parse tokens,
  ///    persist them.
  /// 3. Construct a [YumiAgent] using the access token as ``connectionCode``
  ///    and start it in the background.
  ///
  /// Tool registration happens *after* this call returns the agent:
  ///
  /// ```dart
  /// final agent = await YumiApp.connect(
  ///   adapter,
  ///   YumiAppConnectOptions(
  ///     appId: 'myapp',
  ///     identityPortalUrl: Uri.parse('https://identity.example.com/'),
  ///     returnTo: Uri.parse('com.example.myapp://auth'),
  ///   ),
  /// );
  /// agent.register(RegisterOptions(name: 'ping', ..., handler: (_) async => 'pong'));
  /// agent.runInBackground();
  /// ```
  static Future<YumiAgent> connect(
    YumiAppHandshakeAdapter adapter,
    YumiAppConnectOptions opts,
  ) async {
    YumiAppTokens? tokens;
    if (opts.reuseStored) {
      tokens = await adapter.loadStoredTokens(opts.appId);
    }
    tokens ??= await _runHandshake(adapter, opts);

    final agent = YumiAgent(
      AgentOptions(
        connectionCode: tokens.accessToken,
        edgeName: opts.edgeName,
      ),
    );
    return agent;
  }

  /// Force a fresh handshake even if stored tokens exist. Useful after a
  /// 401 response from the deployment (token revoked / expired beyond
  /// refresh).
  static Future<YumiAgent> reconnect(
    YumiAppHandshakeAdapter adapter,
    YumiAppConnectOptions opts,
  ) async {
    await adapter.clearStoredTokens(opts.appId);
    return connect(
      adapter,
      YumiAppConnectOptions(
        appId: opts.appId,
        identityPortalUrl: opts.identityPortalUrl,
        returnTo: opts.returnTo,
        edgeName: opts.edgeName,
        reuseStored: false,
      ),
    );
  }

  /// Forget tokens for [appId]. The next [connect] will trigger a new
  /// portal handshake.
  static Future<void> disconnect(
    YumiAppHandshakeAdapter adapter,
    String appId,
  ) =>
      adapter.clearStoredTokens(appId);

  /// Generate a portal URL with the standard query parameters. Exposed for
  /// callers that need to drive the handshake themselves (e.g. tests, or
  /// platforms whose adapter inspects the URL before launching).
  static Uri buildPortalUrl({
    required Uri identityPortalUrl,
    required String appId,
    required Uri returnTo,
    required String state,
  }) {
    final params = <String, String>{
      ...identityPortalUrl.queryParameters,
      'app_id': appId,
      'return_to': returnTo.toString(),
      'state': state,
    };
    return identityPortalUrl.replace(queryParameters: params);
  }

  static Future<YumiAppTokens> _runHandshake(
    YumiAppHandshakeAdapter adapter,
    YumiAppConnectOptions opts,
  ) async {
    final state = _newState();
    final portalUrl = buildPortalUrl(
      identityPortalUrl: opts.identityPortalUrl,
      appId: opts.appId,
      returnTo: opts.returnTo,
      state: state,
    );
    final callback = await adapter.openAndAwaitCallback(
      portalUrl: portalUrl,
      expectedState: state,
    );
    if (callback.queryParameters['state'] != state) {
      throw const YumiAppHandshakeException(
        'Portal callback state did not match. Refusing tokens.',
      );
    }
    final tokens = YumiAppTokens.fromCallback(callback);
    await adapter.storeTokens(opts.appId, tokens);
    return tokens;
  }

  static String _newState() {
    final rng = Random.secure();
    final bytes = List<int>.generate(24, (_) => rng.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }
}
