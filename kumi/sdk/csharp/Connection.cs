namespace Kumi;

/// <summary>
/// Connection resolution: determines WebSocket URL and access token
/// from environment variables and connection code.
/// </summary>
internal static class Connection
{
    public sealed class ConnectionConfig
    {
        public string Mode { get; }
        public string BaseUrl { get; }
        public string? AccessToken { get; }

        public ConnectionConfig(string mode, string baseUrl, string? accessToken)
        {
            Mode = mode;
            BaseUrl = baseUrl;
            AccessToken = accessToken;
        }

        public string RelayEdgeWsUrl() =>
            HttpToWs(BaseUrl.TrimEnd('/')) + "/ws/edge";
    }

    public static string HttpToWs(string url)
    {
        if (url.StartsWith("https://")) return "wss://" + url["https://".Length..];
        if (url.StartsWith("http://")) return "ws://" + url["http://".Length..];
        return url;
    }

    public static async Task<ConnectionConfig> ResolveConnection(string? code, string edgeName)
    {
        var relayUrl = Environment.GetEnvironmentVariable("KUMI_RELAY_URL");
        var accessToken = Environment.GetEnvironmentVariable("KUMI_ACCESS_TOKEN");
        if (!string.IsNullOrEmpty(relayUrl) && !string.IsNullOrEmpty(accessToken))
            return new ConnectionConfig("relay", relayUrl.TrimEnd('/'), accessToken);

        code ??= "";

        if (code.StartsWith("ws://") || code.StartsWith("wss://"))
            return new ConnectionConfig("direct", code, null);

        if (Auth.IsLanCode(code))
        {
            var serverUrl = Auth.ParseLanCode(code);
            var wsUrl = HttpToWs(serverUrl.TrimEnd('/')) + "/ws/edge";
            return new ConnectionConfig("direct", wsUrl, null);
        }

        if (Auth.IsRelayToken(code))
        {
            var profile = await Auth.BootstrapProfile(code, "edge", edgeName);
            return new ConnectionConfig("relay", profile.RelayUrl, profile.AccessToken);
        }

        if (code.StartsWith("http://") || code.StartsWith("https://"))
        {
            var wsUrl = HttpToWs(code.TrimEnd('/')) + "/ws/edge";
            return new ConnectionConfig("direct", wsUrl, null);
        }

        return new ConnectionConfig("direct", "ws://127.0.0.1:8000/ws/edge", null);
    }
}
