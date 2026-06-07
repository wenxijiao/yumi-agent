using System.Text.Json;
using System.Text.Json.Nodes;

namespace Kumi;

/// <summary>
/// Builds the JSON tool schema sent during WebSocket registration.
/// </summary>
internal static class SchemaBuilder
{
    public static JsonObject Build(RegisterOptions opts)
    {
        var properties = new JsonObject();
        var required = new JsonArray();

        foreach (var p in opts.Parameters)
        {
            var prop = new JsonObject
            {
                ["type"] = p.Type,
                ["description"] = p.Description,
            };
            properties[p.Name] = prop;
            if (p.Required)
                required.Add(p.Name);
        }

        var parameters = new JsonObject
        {
            ["type"] = "object",
            ["properties"] = properties,
            ["required"] = required,
        };

        var function_ = new JsonObject
        {
            ["name"] = opts.Name,
            ["description"] = opts.Description,
            ["parameters"] = parameters,
        };

        var schema = new JsonObject
        {
            ["type"] = "function",
            ["function"] = function_,
        };

        if (opts.Timeout.HasValue)
            schema["timeout"] = opts.Timeout.Value;

        if (opts.RequireConfirmation)
            schema["require_confirmation"] = true;

        if (opts.AlwaysInclude)
            schema["always_include"] = true;

        if (opts.AllowProactive)
            schema["allow_proactive"] = true;

        if (opts.ProactiveContext)
            schema["proactive_context"] = true;

        if (opts.ProactiveContextArgs != null)
            schema["proactive_context_args"] = JsonSerializer.SerializeToNode(opts.ProactiveContextArgs);

        if (!string.IsNullOrWhiteSpace(opts.ProactiveContextDescription))
            schema["proactive_context_description"] = opts.ProactiveContextDescription;

        return schema;
    }
}
