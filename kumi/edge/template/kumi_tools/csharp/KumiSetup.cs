using Kumi;

/// <summary>
/// Kumi edge setup — register your tools here.
/// Call <see cref="KumiSetup.InitKumi"/> from your application's entry point.
/// </summary>
public static class KumiSetup
{
    // ── Configuration ──
    // Set your connection code here (LAN: "kumi-lan_...", remote: "kumi_...").
    // Leave empty to read from KUMI_CONNECTION_CODE env var or kumi_tools/.env.
    private const string KumiConnectionCode = "";
    private const string KumiEdgeName = "My C# App";

    public static KumiAgent InitKumi()
    {
        var agent = new KumiAgent(KumiConnectionCode, KumiEdgeName);

        // Register your tools below.

        agent.Register(new RegisterOptions()
            .SetName("hello")
            .SetDescription("Say hello to someone")
            .SetParameters(
                new ToolParameter("name", "string", "Person to greet")
            )
            .SetHandler(args =>
            {
                var name = args.GetString("name", "World");
                return $"Hello, {name}!";
            })
        );

        // Example: tool with confirmation required
        // agent.Register(new RegisterOptions()
        //     .SetName("dangerous_action")
        //     .SetDescription("Do something irreversible")
        //     .SetRequireConfirmation(true)
        //     .SetHandler(args => "done")
        // );

        agent.RunInBackground();
        return agent;
    }
}
