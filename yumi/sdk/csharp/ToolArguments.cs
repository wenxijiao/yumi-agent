using System.Text.Json;

namespace Yumi;

/// <summary>
/// Type-safe accessor for tool call arguments backed by a <see cref="JsonElement"/>.
/// </summary>
public sealed class ToolArguments
{
    private readonly JsonElement _raw;

    public ToolArguments(JsonElement raw)
    {
        _raw = raw;
    }

    public JsonElement Raw => _raw;

    public string GetString(string key, string fallback = "")
    {
        if (_raw.TryGetProperty(key, out var el) && el.ValueKind == JsonValueKind.String)
            return el.GetString() ?? fallback;
        return fallback;
    }

    public int GetInt(string key, int fallback = 0)
    {
        if (_raw.TryGetProperty(key, out var el) && el.TryGetInt32(out var v))
            return v;
        return fallback;
    }

    public double GetDouble(string key, double fallback = 0.0)
    {
        if (_raw.TryGetProperty(key, out var el) && el.TryGetDouble(out var v))
            return v;
        return fallback;
    }

    public bool GetBool(string key, bool fallback = false)
    {
        if (_raw.TryGetProperty(key, out var el))
        {
            if (el.ValueKind == JsonValueKind.True) return true;
            if (el.ValueKind == JsonValueKind.False) return false;
        }
        return fallback;
    }
}
