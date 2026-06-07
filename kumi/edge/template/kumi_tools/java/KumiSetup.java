import io.kumi.KumiAgent;
import io.kumi.RegisterOptions;
import io.kumi.ToolParameter;

/**
 * Kumi edge setup — register your tools here.
 * Call {@link #initKumi()} from your application's main method.
 */
public class KumiSetup {

    // ── Configuration ──
    // Set your connection code here (LAN: "kumi-lan_...", remote: "kumi_...").
    // Leave empty to read from KUMI_CONNECTION_CODE env var or kumi_tools/.env.
    private static final String KUMI_CONNECTION_CODE = "";
    private static final String KUMI_EDGE_NAME = "My Java App";

    public static void initKumi() {
        var agent = new KumiAgent(KUMI_CONNECTION_CODE, KUMI_EDGE_NAME);

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
