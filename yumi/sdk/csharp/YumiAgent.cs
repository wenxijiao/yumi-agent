using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Yumi;

/// <summary>
/// Yumi edge agent for C#. Connects to the Yumi server over WebSocket,
/// registers tools, and dispatches incoming tool calls to handlers.
/// </summary>
/// <example>
/// <code>
/// var agent = new YumiAgent("yumi-lan_...", "My C# App");
/// agent.Register(new RegisterOptions()
///     .SetName("hello")
///     .SetDescription("Say hello")
///     .SetParameters(new ToolParameter("name", "string", "Person"))
///     .SetHandler(args => "Hello, " + args.GetString("name", "World") + "!"));
/// agent.RunInBackground();
/// </code>
/// </example>
public sealed class YumiAgent : IDisposable
{
    private const string LogPrefix = "[Yumi]";
    private const string ToolConfirmationFilename = ".yumi_tool_confirmation.json";

    private readonly string _connectionCode;
    private readonly string _edgeName;
    private readonly string _policyBaseDir;
    private readonly ConcurrentDictionary<string, RegisteredTool> _tools = new();
    private readonly CancellationTokenSource _cts = new();
    private Task? _connectTask;

    /// <summary>
    /// Create a new agent with an explicit connection code and edge name.
    /// </summary>
    public YumiAgent(string? connectionCode, string? edgeName, string? envPath = null)
    {
        string envFile;
        if (!string.IsNullOrEmpty(envPath))
        {
            envFile = envPath;
        }
        else
        {
            var cwd = Directory.GetCurrentDirectory();
            var yumiToolsEnv = Path.Combine(cwd, "yumi_tools", ".env");
            var rootEnv = Path.Combine(cwd, ".env");
            envFile = File.Exists(yumiToolsEnv) ? yumiToolsEnv : rootEnv;
        }

        EnvParser.LoadEnvFile(envFile);
        _policyBaseDir = Path.GetDirectoryName(Path.GetFullPath(envFile)) ?? cwd;

        var code = connectionCode;
        if (string.IsNullOrEmpty(code))
            code = EnvParser.GetEnv("YUMI_CONNECTION_CODE");
        if (string.IsNullOrEmpty(code))
            code = EnvParser.GetEnv("BRAIN_URL");
        _connectionCode = code ?? "";

        var name = edgeName;
        if (string.IsNullOrEmpty(name))
            name = EnvParser.GetEnv("EDGE_NAME");
        if (string.IsNullOrEmpty(name))
        {
            try { name = Environment.MachineName; }
            catch { name = "csharp-edge"; }
        }
        _edgeName = name;
    }

    private static string cwd => Directory.GetCurrentDirectory();

    /// <summary>Register a tool.</summary>
    public void Register(RegisterOptions opts)
    {
        // Map the `Mode` sugar onto the low-level wire flags before building
        // the schema. Throws ArgumentException for an invalid mode.
        opts.ApplyMode();
        var schema = SchemaBuilder.Build(opts);
        _tools[opts.Name!] = new RegisteredTool(schema, opts.Handler!, opts.RequireConfirmation);
    }

    /// <summary>Start the WebSocket connect loop on a background thread.</summary>
    public void RunInBackground()
    {
        if (_tools.IsEmpty)
            Console.Error.WriteLine($"{LogPrefix} Warning: no tools registered.");

        _connectTask = Task.Run(() => ConnectLoop(_cts.Token));
    }

    /// <summary>Stop the agent gracefully.</summary>
    public void Stop()
    {
        _cts.Cancel();
        try { _connectTask?.Wait(TimeSpan.FromSeconds(5)); } catch { /* ignored */ }
    }

    public void Dispose()
    {
        Stop();
        _cts.Dispose();
    }

    // ── connect loop ──

    private async Task ConnectLoop(CancellationToken ct)
    {
        Connection.ConnectionConfig config;
        try
        {
            config = await Connection.ResolveConnection(_connectionCode, _edgeName);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"{LogPrefix} Failed to resolve connection: {ex.Message}");
            return;
        }

        var wsUrl = config.Mode == "relay" ? config.RelayEdgeWsUrl() : config.BaseUrl;
        var reconnectDelay = TimeSpan.FromSeconds(3);
        var rng = new Random();

        while (!ct.IsCancellationRequested)
        {
            try
            {
                await RunSession(wsUrl, config.AccessToken, ct);
                reconnectDelay = TimeSpan.FromSeconds(3);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                if (ct.IsCancellationRequested) break;

                var jitter = TimeSpan.FromMilliseconds(rng.Next(-500, 501));
                var wait = reconnectDelay + jitter;
                if (wait < TimeSpan.FromSeconds(1)) wait = TimeSpan.FromSeconds(1);

                Console.Error.WriteLine(
                    $"{LogPrefix} Connection lost: {ex.Message}. Reconnecting in {wait.TotalSeconds:F1}s...");

                try { await Task.Delay(wait, ct); }
                catch (OperationCanceledException) { break; }

                reconnectDelay = TimeSpan.FromMilliseconds(
                    Math.Min(reconnectDelay.TotalMilliseconds * 2, 30_000));
            }
        }
    }

    private async Task RunSession(string wsUrl, string? accessToken, CancellationToken ct)
    {
        using var ws = new ClientWebSocket();
        var uri = new Uri(wsUrl);
        await ws.ConnectAsync(uri, ct);

        // Build and send register payload
        var toolSchemas = new JsonArray();
        foreach (var kv in _tools)
            toolSchemas.Add(JsonNode.Parse(kv.Value.Schema.ToJsonString())!);

        var registerPayload = new JsonObject
        {
            ["type"] = "register",
            ["edge_name"] = _edgeName,
            ["tools"] = toolSchemas,
            ["tool_confirmation_policy"] = JsonNode.Parse(
                JsonSerializer.Serialize(LoadConfirmationPolicy())),
        };

        if (!string.IsNullOrEmpty(accessToken))
            registerPayload["access_token"] = accessToken;

        var payloadBytes = Encoding.UTF8.GetBytes(registerPayload.ToJsonString());
        await ws.SendAsync(payloadBytes, WebSocketMessageType.Text, true, ct);
        Console.Error.WriteLine($"{LogPrefix} Connected as [{_edgeName}] with {_tools.Count} tool(s).");

        // Read loop
        var buffer = new byte[64 * 1024];
        var messageBuffer = new MemoryStream();

        while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
        {
            var result = await ws.ReceiveAsync(buffer, ct);

            if (result.MessageType == WebSocketMessageType.Close)
            {
                if (ct.IsCancellationRequested) return;
                throw new IOException($"WebSocket closed: {result.CloseStatus} {result.CloseStatusDescription}");
            }

            messageBuffer.Write(buffer, 0, result.Count);

            if (result.EndOfMessage)
            {
                var text = Encoding.UTF8.GetString(messageBuffer.ToArray());
                messageBuffer.SetLength(0);
                _ = Task.Run(() => HandleMessage(ws, text, ct), ct);
            }
        }
    }

    // ── message handling ──

    private async Task HandleMessage(ClientWebSocket ws, string text, CancellationToken ct)
    {
        JsonElement msg;
        try
        {
            msg = JsonDocument.Parse(text).RootElement;
        }
        catch
        {
            return;
        }

        var type = msg.TryGetProperty("type", out var tProp) ? tProp.GetString() ?? "" : "";

        switch (type)
        {
            case "persist_tool_confirmation_policy":
                HandlePersistPolicy(msg);
                break;
            case "tool_call":
                await HandleToolCall(ws, msg, ct);
                break;
        }
    }

    private async Task HandleToolCall(ClientWebSocket ws, JsonElement msg, CancellationToken ct)
    {
        var toolName = msg.TryGetProperty("name", out var nProp) ? nProp.GetString() ?? "" : "";
        var callId = msg.TryGetProperty("call_id", out var cProp) ? cProp.GetString() ?? "unknown" : "unknown";

        JsonElement rawArgs = default;
        if (msg.TryGetProperty("arguments", out var aProp))
            rawArgs = aProp;

        var args = new ToolArguments(rawArgs);
        string result;

        if (_tools.TryGetValue(toolName, out var tool))
        {
            try
            {
                result = tool.Handler(args);
            }
            catch (Exception ex)
            {
                result = $"Error executing tool '{toolName}': {ex.Message}";
            }
        }
        else
        {
            result = $"Error: Tool '{toolName}' is not registered on this edge.";
        }

        var reply = new JsonObject
        {
            ["type"] = "tool_result",
            ["call_id"] = callId,
            ["result"] = result ?? "",
            ["cancelled"] = false,
        };

        var replyBytes = Encoding.UTF8.GetBytes(reply.ToJsonString());
        try
        {
            await ws.SendAsync(replyBytes, WebSocketMessageType.Text, true, ct);
        }
        catch { /* ignored */ }
    }

    // ── confirmation policy ──

    private string ConfirmationPolicyPath()
    {
        var overridePath = EnvParser.GetEnv("YUMI_TOOL_CONFIRMATION_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath))
            return overridePath.Trim();
        return Path.Combine(_policyBaseDir, ToolConfirmationFilename);
    }

    private Dictionary<string, List<string>> LoadConfirmationPolicy()
    {
        var path = ConfirmationPolicyPath();
        if (!File.Exists(path))
            return DefaultPolicy();

        try
        {
            var content = File.ReadAllText(path);
            using var doc = JsonDocument.Parse(content);
            return new Dictionary<string, List<string>>
            {
                ["always_allow"] = GetStringArray(doc.RootElement, "always_allow"),
                ["force_confirm"] = GetStringArray(doc.RootElement, "force_confirm"),
            };
        }
        catch
        {
            return DefaultPolicy();
        }
    }

    private void SaveConfirmationPolicy(JsonElement data)
    {
        var path = ConfirmationPolicyPath();
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        var payload = new Dictionary<string, List<string>>
        {
            ["always_allow"] = GetStringArray(data, "always_allow"),
            ["force_confirm"] = GetStringArray(data, "force_confirm"),
        };

        try
        {
            File.WriteAllText(path, JsonSerializer.Serialize(payload,
                new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { /* ignored */ }
    }

    private void HandlePersistPolicy(JsonElement msg) => SaveConfirmationPolicy(msg);

    // ── helpers ──

    private static Dictionary<string, List<string>> DefaultPolicy() =>
        new()
        {
            ["always_allow"] = new List<string>(),
            ["force_confirm"] = new List<string>(),
        };

    private static List<string> GetStringArray(JsonElement obj, string key)
    {
        var result = new List<string>();
        if (!obj.TryGetProperty(key, out var el) || el.ValueKind != JsonValueKind.Array)
            return result;

        foreach (var item in el.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String)
            {
                var s = item.GetString();
                if (!string.IsNullOrEmpty(s))
                    result.Add(s);
            }
        }
        return result;
    }

    private sealed class RegisteredTool
    {
        public JsonObject Schema { get; }
        public ToolHandler Handler { get; }
        public bool RequireConfirmation { get; }

        public RegisteredTool(JsonObject schema, ToolHandler handler, bool requireConfirmation)
        {
            Schema = schema;
            Handler = handler;
            RequireConfirmation = requireConfirmation;
        }
    }
}
