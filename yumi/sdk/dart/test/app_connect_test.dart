import 'package:yumi_sdk/yumi_sdk.dart';
import 'package:test/test.dart';

void main() {
  group('YumiApp.buildPortalUrl', () {
    test('appends app_id, return_to, and state preserving existing params', () {
      final portal = Uri.parse('https://identity.example.com/?theme=dark');
      final url = YumiApp.buildPortalUrl(
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

  group('YumiAppTokens.fromCallback', () {
    test('parses access_token + extras + id_token', () {
      final callback = Uri.parse(
        'com.example.myapp://auth'
        '?access_token=yumi_AAA'
        '&id_token=eyAAA'
        '&state=xyz'
        '&custom_token=cTok',
      );
      final tokens = YumiAppTokens.fromCallback(callback);
      expect(tokens.accessToken, 'yumi_AAA');
      expect(tokens.idToken, 'eyAAA');
      expect(tokens.extra['custom_token'], 'cTok');
      // state is consumed by the SDK, not surfaced as extra
      expect(tokens.extra.containsKey('state'), isFalse);
    });

    test('throws when access_token missing', () {
      final callback = Uri.parse('com.example.myapp://auth?state=xyz');
      expect(
        () => YumiAppTokens.fromCallback(callback),
        throwsA(isA<YumiAppHandshakeException>()),
      );
    });

    test('accepts legacy "token" param as id_token fallback', () {
      final callback = Uri.parse(
        'com.example.myapp://auth?access_token=A&token=legacy_id_token',
      );
      final tokens = YumiAppTokens.fromCallback(callback);
      expect(tokens.accessToken, 'A');
      expect(tokens.idToken, 'legacy_id_token');
    });
  });

  group('YumiAppTokens.toJson / fromJson roundtrip', () {
    test('preserves all fields including extras', () {
      final original = YumiAppTokens(
        accessToken: 'a',
        idToken: 'b',
        extra: {'k': 'v'},
      );
      final roundtripped = YumiAppTokens.fromJson(original.toJson());
      expect(roundtripped.accessToken, 'a');
      expect(roundtripped.idToken, 'b');
      expect(roundtripped.extra['k'], 'v');
    });
  });

  group('YumiApp full handshake via fake adapter', () {
    test('reuses stored tokens when reuseStored=true', () async {
      final fake = _FakeAdapter()
        ..stored['myapp'] = const YumiAppTokens(accessToken: 'cached');
      final agent = await YumiApp.connect(
        fake,
        YumiAppConnectOptions(
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
      final agent = await YumiApp.connect(
        fake,
        YumiAppConnectOptions(
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
        () => YumiApp.connect(
          fake,
          YumiAppConnectOptions(
            appId: 'myapp',
            identityPortalUrl: Uri.parse('https://identity.example.com/'),
            returnTo: Uri.parse('http://localhost:1/cb'),
          ),
        ),
        throwsA(isA<YumiAppHandshakeException>()),
      );
    });
  });

  group('reconnect / disconnect', () {
    test('reconnect clears cache then runs fresh handshake', () async {
      final fake = _FakeAdapter()
        ..stored['myapp'] = const YumiAppTokens(accessToken: 'stale')
        ..plannedCallbackParams = {'access_token': 'new', 'state': '__will_be_set__'};
      await YumiApp.reconnect(
        fake,
        YumiAppConnectOptions(
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
        ..stored['myapp'] = const YumiAppTokens(accessToken: 'x');
      await YumiApp.disconnect(fake, 'myapp');
      expect(fake.stored.containsKey('myapp'), isFalse);
    });
  });
}

class _FakeAdapter implements YumiAppHandshakeAdapter {
  final Map<String, YumiAppTokens> stored = {};
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
  Future<void> storeTokens(String appId, YumiAppTokens tokens) async {
    stored[appId] = tokens;
  }

  @override
  Future<YumiAppTokens?> loadStoredTokens(String appId) async => stored[appId];

  @override
  Future<void> clearStoredTokens(String appId) async {
    stored.remove(appId);
  }
}
