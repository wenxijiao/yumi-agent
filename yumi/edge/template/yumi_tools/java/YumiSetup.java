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

        agent.register(new RegisterOptions()
            .name("hello")
            .description("Say hello to someone")
            .parameters(
                new ToolParameter("name", "string", "Person to greet")
            )
            .handler(args -> {
                String name = args.getString("name", "World");
                return "Hello, " + name + "!";
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
