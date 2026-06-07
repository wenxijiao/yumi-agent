namespace Kumi;

/// <summary>
/// Simple .env file parser. Loaded values are stored in a static dictionary
/// and are accessible via <see cref="GetEnv"/>. Existing environment variables
/// are never overwritten.
/// </summary>
internal static class EnvParser
{
    private static readonly Dictionary<string, string> _loaded = new();

    public static void LoadEnvFile(string filePath)
    {
        if (!File.Exists(filePath)) return;

        foreach (var rawLine in File.ReadAllLines(filePath))
        {
            var line = rawLine.Trim();
            if (string.IsNullOrEmpty(line) || line.StartsWith('#'))
                continue;

            var eq = line.IndexOf('=');
            if (eq < 0) continue;

            var key = line[..eq].Trim();
            var value = line[(eq + 1)..].Trim();

            if (value.Length >= 2)
            {
                if ((value.StartsWith('"') && value.EndsWith('"')) ||
                    (value.StartsWith('\'') && value.EndsWith('\'')))
                {
                    value = value[1..^1];
                }
            }

            var existing = GetEnv(key);
            if (string.IsNullOrEmpty(existing))
                _loaded[key] = value;
        }
    }

    public static string? GetEnv(string key)
    {
        var env = Environment.GetEnvironmentVariable(key);
        if (!string.IsNullOrEmpty(env)) return env;
        return _loaded.TryGetValue(key, out var v) ? v : null;
    }

    public static string GetEnv(string key, string fallback)
    {
        var v = GetEnv(key);
        return !string.IsNullOrEmpty(v) ? v : fallback;
    }
}
