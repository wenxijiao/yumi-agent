import io.yumi.YumiAgent;
import io.yumi.RegisterOptions;
import io.yumi.ToolParameter;

/**
 * Yumi edge setup — register your tools here.
 * Call {@link #initYumi()} from your application's main method.
 */
public class YumiSetup {

    // ── Configuration ──
    // Set your connection code here (LAN: "yumi-lan_...", remote: "yumi_...").
    // Leave empty to read from YUMI_CONNECTION_CODE env var or yumi_tools/.env.
    private static final String YUMI_CONNECTION_CODE = "";
    private static final String YUMI_EDGE_NAME = "My Java App";

    public static void initYumi() {
        var agent = new YumiAgent(YUMI_CONNECTION_CODE, YUMI_EDGE_NAME);

        // Register your tools below.

        // Example tool — replace this with your own tools.
        agent.register(new RegisterOptions()
            .name("ping")
            .description("Ping the edge and echo a message back")
            .mode("pinned")
            .parameters(
                new ToolParameter("message", "string", "Text to echo back")
            )
            .handler(args -> {
                String message = args.getString("message", "hello");
                return "pong: " + message;
            })
        );

        // Example: tool with confirmation required
        // agent.register(new RegisterOptions()
        //     .name("dangerous_action")
        //     .description("Do something irreversible")
        //     .requireConfirmation(true)
        //     .handler(args -> "done")
        // );

        agent.runInBackground();
    }
}
