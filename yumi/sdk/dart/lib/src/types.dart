import 'dart:async';

typedef YumiToolHandler = FutureOr<String> Function(ToolArguments args);

class ToolArguments {
  final Map<String, dynamic> raw;

  ToolArguments(this.raw);

  String string(String key) {
    final v = raw[key];
    if (v == null) return '';
    if (v is String) return v;
    return v.toString();
  }

  int intValue(String key, int fallback) {
    final v = raw[key];
    if (v is int) return v;
    if (v is double) return v.toInt();
    return fallback;
  }

  double doubleValue(String key, double fallback) {
    final v = raw[key];
    if (v is double) return v;
    if (v is int) return v.toDouble();
    return fallback;
  }

  bool boolValue(String key, bool fallback) {
    final v = raw[key];
    if (v is bool) return v;
    return fallback;
  }
}

class ToolParameter {
  final String name;
  final String typeName;
  final String description;
  final bool? required_;

  ToolParameter({
    required this.name,
    required this.typeName,
    required this.description,
    this.required_,
  });
}

class RegisterOptions {
  final String name;
  final String description;
  final List<ToolParameter> parameters;
  final int? timeout;
  final bool requireConfirmation;
  final bool alwaysInclude;
  final bool allowProactive;
  final bool proactiveContext;
  final Map<String, dynamic>? proactiveContextArgs;
  final String? proactiveContextDescription;
  final YumiToolHandler handler;

  RegisterOptions({
    required this.name,
    required this.description,
    this.parameters = const [],
    this.timeout,
    this.requireConfirmation = false,
    this.alwaysInclude = false,
    this.allowProactive = false,
    this.proactiveContext = false,
    this.proactiveContextArgs,
    this.proactiveContextDescription,
    required this.handler,
  });
}

class AgentOptions {
  final String? connectionCode;
  final String? edgeName;
  final String? envPath;

  /// Direct (relay-url, access-token) override. Skips the
  /// ``/v1/bootstrap`` handshake the SDK would otherwise perform on a
  /// ``yumi_…`` connection code, and connects straight to
  /// ``<relayUrl>/ws/edge`` using ``accessToken`` for register-time auth.
  ///
  /// Set both when a trusted wrapper already holds the credentials needed by
  /// its deployment.
  /// The token itself doesn't have to encode a real ``relay_url`` (it
  /// often carries the placeholder ``https://yumi.local``) — that
  /// field is then just a deployment sentinel, not a routing hint.
  final String? relayUrl;
  final String? accessToken;

  AgentOptions({
    this.connectionCode,
    this.edgeName,
    this.envPath,
    this.relayUrl,
    this.accessToken,
  });
}
