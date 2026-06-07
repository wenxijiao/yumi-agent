using Yumi;

/// <summary>
/// Yumi edge setup — register your tools here.
/// Call <see cref="YumiSetup.InitYumi"/> from your application's entry point.
/// </summary>
public static class YumiSetup
{
    // ── Configuration ──
    // Set your connection code here (LAN: "yumi-lan_...", remote: "yumi_...").
    // Leave empty to read from YUMI_CONNECTION_CODE env var or yumi_tools/.env.
    private const string YumiConnectionCode = "";
    private const string YumiEdgeName = "My C# App";

    public static YumiAgent InitYumi()
    {
        var agent = new YumiAgent(YumiConnectionCode, YumiEdgeName);

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
