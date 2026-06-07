using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace Kumi;

/// <summary>
/// Authentication helpers: LAN code / relay credential parsing and relay bootstrap.
/// </summary>
internal static class Auth
{
    private const string TokenPrefix = "kumi_";
    private const string LanTokenPrefix = "kumi-lan_";
    private static readonly string[] LegacyLanPrefixes = { "ml1_", "kumi_lan_" };

    private static byte[] Base64UrlDecode(string data)
    {
        var padded = data + new string('=', (4 - data.Length % 4) % 4);
        var base64 = padded.Replace('-', '+').Replace('_', '/');
        return Convert.FromBase64String(base64);
    }

    public static (string host, int port) DecodeLanCode(string token)
    {
        string? encoded = null;

        if (token.StartsWith(LanTokenPrefix))
        {
            encoded = token[LanTokenPrefix.Length..];
        }
        else
        {
            foreach (var prefix in LegacyLanPrefixes)
            {
                if (token.StartsWith(prefix))
                {
                    encoded = token[prefix.Length..];
                    break;
                }
            }
        }

        if (encoded is null)
            throw new ArgumentException("Invalid Kumi LAN code prefix.");

        var json = Encoding.UTF8.GetString(Base64UrlDecode(encoded));
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        string host;
        int port;

        if (root.TryGetProperty("h", out var hProp))
        {
            host = hProp.GetString()!;
            port = root.TryGetProperty("p", out var pProp) ? pProp.GetInt32() : 8000;
        }
        else if (root.TryGetProperty("base_url", out var buProp))
        {
            var uri = new Uri(buProp.GetString()!);
            host = uri.Host;
            port = uri.Port > 0 ? uri.Port : 8000;
        }
        else
        {
            throw new ArgumentException("LAN code missing host.");
        }

        if (root.TryGetProperty("x", out var xProp))
        {
            var expiry = xProp.GetInt64();
            if (expiry > 0 && expiry < DateTimeOffset.UtcNow.ToUnixTimeSeconds())
                throw new ArgumentException("LAN code has expired.");
        }

        return (host, port);
    }

    public static JsonElement DecodeCredential(string token)
    {
        if (!token.StartsWith(TokenPrefix))
            throw new ArgumentException("Invalid Kumi credential prefix.");

        var json = Encoding.UTF8.GetString(Base64UrlDecode(token[TokenPrefix.Length..]));
        return JsonDocument.Parse(json).RootElement;
    }

    public static bool IsLanCode(string code)
    {
        if (code.StartsWith(LanTokenPrefix)) return true;
        return LegacyLanPrefixes.Any(p => code.StartsWith(p));
    }

    public static bool IsRelayToken(string code) =>
        code.StartsWith(TokenPrefix) && !IsLanCode(code);

    public static string ParseLanCode(string code)
    {
        var (host, port) = DecodeLanCode(code);
        return $"http://{host}:{port}";
    }

    public static async Task<BootstrapResult> BootstrapProfile(
        string joinCode, string scope, string deviceName)
    {
        var cred = DecodeCredential(joinCode);
        var relayUrl = cred.GetProperty("relay_url").GetString()!.TrimEnd('/');

        var payload = new { join_code = joinCode, scope, device_name = deviceName?.Trim() ?? "" };

        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        var response = await client.PostAsJsonAsync($"{relayUrl}/v1/bootstrap", payload);

        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync();
            throw new IOException($"Bootstrap failed: {body}");
        }

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync());
        var root = doc.RootElement;

        if (!root.TryGetProperty("access_token", out var atProp) ||
            string.IsNullOrEmpty(atProp.GetString()))
        {
            throw new IOException("Bootstrap response missing access_token.");
        }

        return new BootstrapResult(relayUrl, atProp.GetString()!);
    }

    public sealed class BootstrapResult
    {
        public string RelayUrl { get; }
        public string AccessToken { get; }

        public BootstrapResult(string relayUrl, string accessToken)
        {
            RelayUrl = relayUrl;
            AccessToken = accessToken;
        }
    }
}
