import 'package:kumi_sdk/kumi_sdk.dart';
import 'package:test/test.dart';

void main() {
  group('KumiApp.buildPortalUrl', () {
    test('appends app_id, return_to, and state preserving existing params', () {
      final portal = Uri.parse('https://identity.example.com/?theme=dark');
      final url = KumiApp.buildPortalUrl(
        identityPortalUrl: portal,
        appId: 'myapp',
        returnTo: Uri.parse('com.example.myapp://auth'),
        state: 'st_123',
      );
      expect(url.queryParameters['app_id'], 'myapp');
      expect(url.queryParameters['return_to'], 'com.example.myapp://auth');
      expect(url.queryParameters['state'], 'st_123');
      expect(url.queryParameters['theme'], 'dark');
      expect(url.host, 'identity.example.com');
    });
  });

  group('KumiAppTokens.fromCallback', () {
    test('parses access_token + extras + id_token', () {
      final callback = Uri.parse(
        'com.example.myapp://auth'
        '?access_token=kumi_AAA'
        '&id_token=eyAAA'
        '&state=xyz'
        '&custom_token=cTok',
      );
      final tokens = KumiAppTokens.fromCallback(callback);
      expect(tokens.accessToken, 'kumi_AAA');
      expect(tokens.idToken, 'eyAAA');
      expect(tokens.extra['custom_token'], 'cTok');
      // state is consumed by the SDK, not surfaced as extra
      expect(tokens.extra.containsKey('state'), isFalse);
    });

    test('throws when access_token missing', () {
      final callback = Uri.parse('com.example.myapp://auth?state=xyz');
      expect(
        () => KumiAppTokens.fromCallback(callback),
        throwsA(isA<KumiAppHandshakeException>()),
      );
    });

    test('accepts legacy "token" param as id_token fallback', () {
      final callback = Uri.parse(
        'com.example.myapp://auth?access_token=A&token=legacy_id_token',
      );
      final tokens = KumiAppTokens.fromCallback(callback);
      expect(tokens.accessToken, 'A');
      expect(tokens.idToken, 'legacy_id_token');
    });
  });

  group('KumiAppTokens.toJson / fromJson roundtrip', () {
    test('preserves all fields including extras', () {
      final original = KumiAppTokens(
        accessToken: 'a',
        idToken: 'b',
        extra: {'k': 'v'},
      );
      final roundtripped = KumiAppTokens.fromJson(original.toJson());
      expect(roundtripped.accessToken, 'a');
      expect(roundtripped.idToken, 'b');
      expect(roundtripped.extra['k'], 'v');
    });
  });

  group('KumiApp full handshake via fake adapter', () {
    test('reuses stored tokens when reuseStored=true', () async {
      final fake = _FakeAdapter()
        ..stored['myapp'] = const KumiAppTokens(accessToken: 'cached');
      final agent = await KumiApp.connect(
        fake,
        KumiAppConnectOptions(
          appId: 'myapp',
          identityPortalUrl: Uri.parse('https://identity.example.com/'),
          returnTo: Uri.parse('http://localhost:1/cb'),
        ),
      );
      expect(fake.handshakeCount, 0);
      // The agent should be constructed; we can't easily start it without a
      // real server, but constructing it implies the cached token flowed
      // through.
      expect(agent, isNotNull);
    });

    test('runs handshake when no stored tokens', () async {
      final fake = _FakeAdapter()
        ..plannedCallbackParams = {'access_token': 'fresh', 'state': '__will_be_set__'};
      final agent = await KumiApp.connect(
        fake,
        KumiAppConnectOptions(
          appId: 'myapp',
          identityPortalUrl: Uri.parse('https://identity.example.com/'),
          returnTo: Uri.parse('http://localhost:1/cb'),
        ),
      );
      expect(fake.handshakeCount, 1);
      expect(fake.stored['myapp']?.accessToken, 'fresh');
      expect(agent, isNotNull);
    });

    test('rejects callback with bad state', () async {
      final fake = _FakeAdapter()
        // Adapter returns a callback with a tampered state — the SDK must
        // reject it even though the adapter already passed it through.
        ..plannedCallbackParams = {'access_token': 'fresh', 'state': 'EVIL'}
        ..overrideStateInCallback = true;
      expect(
        () => KumiApp.connect(
          fake,
          KumiAppConnectOptions(
            appId: 'myapp',
            identityPortalUrl: Uri.parse('https://identity.example.com/'),
            returnTo: Uri.parse('http://localhost:1/cb'),
          ),
        ),
        throwsA(isA<KumiAppHandshakeException>()),
      );
    });
  });

  group('reconnect / disconnect', () {
    test('reconnect clears cache then runs fresh handshake', () async {
      final fake = _FakeAdapter()
        ..stored['myapp'] = const KumiAppTokens(accessToken: 'stale')
        ..plannedCallbackParams = {'access_token': 'new', 'state': '__will_be_set__'};
      await KumiApp.reconnect(
        fake,
        KumiAppConnectOptions(
          appId: 'myapp',
          identityPortalUrl: Uri.parse('https://identity.example.com/'),
          returnTo: Uri.parse('http://localhost:1/cb'),
        ),
      );
      expect(fake.handshakeCount, 1);
      expect(fake.stored['myapp']?.accessToken, 'new');
    });

    test('disconnect forgets tokens', () async {
      final fake = _FakeAdapter()
        ..stored['myapp'] = const KumiAppTokens(accessToken: 'x');
      await KumiApp.disconnect(fake, 'myapp');
      expect(fake.stored.containsKey('myapp'), isFalse);
    });
  });
}

class _FakeAdapter implements KumiAppHandshakeAdapter {
  final Map<String, KumiAppTokens> stored = {};
  Map<String, String> plannedCallbackParams = const {};
  bool overrideStateInCallback = false;
  int handshakeCount = 0;

  @override
  Future<Uri> openAndAwaitCallback({
    required Uri portalUrl,
    required String expectedState,
  }) async {
    handshakeCount++;
    final params = {...plannedCallbackParams};
    // Echo the SDK-supplied state back unless the test asked us to tamper.
    if (!overrideStateInCallback) params['state'] = expectedState;
    final qs = params.entries.map((e) => '${e.key}=${Uri.encodeComponent(e.value)}').join('&');
    return Uri.parse('${portalUrl.queryParameters['return_to']}?$qs');
  }

  @override
  Future<void> storeTokens(String appId, KumiAppTokens tokens) async {
    stored[appId] = tokens;
  }

  @override
  Future<KumiAppTokens?> loadStoredTokens(String appId) async => stored[appId];

  @override
  Future<void> clearStoredTokens(String appId) async {
    stored.remove(appId);
  }
}
