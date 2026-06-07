package io.yumi;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Yumi edge agent for Java. Connects to the Yumi server over WebSocket,
 * registers tools, and dispatches incoming tool calls to handlers.
 *
 * <p>Usage:</p>
 * <pre>{@code
 * var agent = new YumiAgent("yumi-lan_...", "My Java App");
 * agent.register(new RegisterOptions()
 *     .name("hello")
 *     .description("Say hello")
 *     .parameters(new ToolParameter("name", "string", "Person"))
 *     .handler(args -> "Hello, " + args.getString("name", "World") + "!"));
 * agent.runInBackground();
 * }</pre>
 */
public class YumiAgent {
    private static final Logger LOG = Logger.getLogger(YumiAgent.class.getName());
    private static final String LOG_PREFIX = "[Yumi]";
    private static final String TOOL_CONFIRMATION_FILENAME = ".yumi_tool_confirmation.json";
    private static final Gson GSON = new Gson();

    private final String connectionCode;
    private final String edgeName;
    private final String policyBaseDir;
    private final Map<String, RegisteredTool> tools = new ConcurrentHashMap<>();
    private final AtomicBoolean stopRequested = new AtomicBoolean(false);
    private final ExecutorService executor = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "yumi-agent");
        t.setDaemon(true);
        return t;
    });

    private volatile Thread connectThread;

    /**
     * Create a new agent with an explicit connection code and edge name.
     */
    public YumiAgent(String connectionCode, String edgeName) {
        this(connectionCode, edgeName, null);
    }

    /**
     * Create a new agent with optional .env file path.
     */
    public YumiAgent(String connectionCode, String edgeName, String envPath) {
        String envFile;
        if (envPath != null && !envPath.isEmpty()) {
            envFile = envPath;
        } else {
            String cwd = System.getProperty("user.dir");
            String yumiToolsEnv = Path.of(cwd, "yumi_tools", ".env").toString();
            String rootEnv = Path.of(cwd, ".env").toString();
            envFile = Files.isRegularFile(Path.of(yumiToolsEnv)) ? yumiToolsEnv : rootEnv;
        }

        EnvParser.loadEnvFile(envFile);
        this.policyBaseDir = Path.of(envFile).toAbsolutePath().getParent().toString();

        String code = connectionCode;
        if (code == null || code.isEmpty()) {
            code = EnvParser.getEnv("YUMI_CONNECTION_CODE");
        }
        if (code == null || code.isEmpty()) {
            code = EnvParser.getEnv("BRAIN_URL");
        }
        this.connectionCode = code != null ? code : "";

        String name = edgeName;
        if (name == null || name.isEmpty()) {
            name = EnvParser.getEnv("EDGE_NAME");
        }
        if (name == null || name.isEmpty()) {
            try { name = InetAddress.getLocalHost().getHostName(); } catch (Exception e) { name = "java-edge"; }
        }
        this.edgeName = name;
    }

    /**
     * Register a tool.
     */
    public void register(RegisterOptions opts) {
        JsonObject schema = SchemaBuilder.build(opts);
        tools.put(opts.getName(), new RegisteredTool(schema, opts.getHandler(), opts.isRequireConfirmation()));
    }

    /**
     * Start the WebSocket connect loop on a background daemon thread.
     */
    public void runInBackground() {
        if (tools.isEmpty()) {
            LOG.warning(LOG_PREFIX + " Warning: no tools registered.");
        }
        stopRequested.set(false);
        connectThread = new Thread(this::connectLoop, "yumi-connect");
        connectThread.setDaemon(true);
        connectThread.start();
    }

    /**
     * Stop the agent gracefully.
     */
    public void stop() {
        stopRequested.set(true);
        if (connectThread != null) {
            connectThread.interrupt();
        }
        executor.shutdownNow();
        try { executor.awaitTermination(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) {}
    }

    // ── connect loop ──

    private void connectLoop() {
        Connection.ConnectionConfig config;
        try {
            config = Connection.resolveConnection(connectionCode, edgeName);
        } catch (Exception e) {
            LOG.log(Level.SEVERE, LOG_PREFIX + " Failed to resolve connection", e);
            return;
        }

        String wsUrl = "relay".equals(config.mode) ? config.relayEdgeWsUrl() : config.baseUrl;
        long reconnectDelay = 3000;

        while (!stopRequested.get() && !Thread.currentThread().isInterrupted()) {
            try {
                runSession(wsUrl, config.accessToken);
                reconnectDelay = 3000;
            } catch (Exception e) {
                if (stopRequested.get() || Thread.currentThread().isInterrupted()) break;
                long jitterMs = ThreadLocalRandom.current().nextLong(-500, 501);
                long waitMs = Math.max(1000L, reconnectDelay + jitterMs);
                LOG.info(LOG_PREFIX + " Connection lost: " + e.getMessage()
                        + ". Reconnecting in " + (waitMs / 1000.0) + "s...");
                try { Thread.sleep(waitMs); } catch (InterruptedException ie) { break; }
                reconnectDelay = Math.min(reconnectDelay * 2, 30000);
            }
        }
    }

    private void runSession(String wsUrl, String accessToken) throws Exception {
        CountDownLatch closeLatch = new CountDownLatch(1);
        CompletableFuture<Throwable> errorFuture = new CompletableFuture<>();

        HttpClient client = HttpClient.newHttpClient();
        WebSocket ws = client.newWebSocketBuilder()
                .buildAsync(URI.create(wsUrl), new WebSocket.Listener() {
                    private final StringBuilder buffer = new StringBuilder();

                    @Override
                    public CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
                        buffer.append(data);
                        if (last) {
                            String text = buffer.toString();
                            buffer.setLength(0);
                            handleMessage(webSocket, text);
                        }
                        webSocket.request(1);
                        return null;
                    }

                    @Override
                    public CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
                        if (stopRequested.get()) {
                            errorFuture.complete(null);
                        } else {
                            errorFuture.complete(new IOException("WebSocket closed: " + statusCode + " " + reason));
                        }
                        closeLatch.countDown();
                        return null;
                    }

                    @Override
                    public void onError(WebSocket webSocket, Throwable error) {
                        errorFuture.complete(error);
                        closeLatch.countDown();
                    }
                })
                .join();

        // Send register payload
        JsonObject registerPayload = new JsonObject();
        registerPayload.addProperty("type", "register");
        registerPayload.addProperty("edge_name", edgeName);

        JsonArray toolSchemas = new JsonArray();
        for (RegisteredTool tool : tools.values()) {
            toolSchemas.add(tool.schema);
        }
        registerPayload.add("tools", toolSchemas);
        registerPayload.add("tool_confirmation_policy", loadConfirmationPolicyJson());

        if (accessToken != null && !accessToken.isEmpty()) {
            registerPayload.addProperty("access_token", accessToken);
        }

        ws.sendText(GSON.toJson(registerPayload), true).join();
        LOG.info(LOG_PREFIX + " Connected as [" + edgeName + "] with " + tools.size() + " tool(s).");

        // Wait for close or error
        closeLatch.await();

        Throwable err = errorFuture.getNow(null);
        if (err != null) {
            throw new IOException(err.getMessage(), err);
        }
    }

    // ── message handling ──

    private void handleMessage(WebSocket ws, String text) {
        JsonObject msg;
        try {
            msg = JsonParser.parseString(text).getAsJsonObject();
        } catch (Exception e) {
            return;
        }

        String type = msg.has("type") ? msg.get("type").getAsString() : "";

        switch (type) {
            case "persist_tool_confirmation_policy":
                handlePersistPolicy(msg);
                break;
            case "tool_call":
                executor.submit(() -> handleToolCall(ws, msg));
                break;
            case "cancel":
                break;
            default:
                break;
        }
    }

    private void handleToolCall(WebSocket ws, JsonObject msg) {
        String toolName = msg.has("name") ? msg.get("name").getAsString() : "";
        String callId = msg.has("call_id") ? msg.get("call_id").getAsString() : "unknown";
        JsonObject rawArgs = msg.has("arguments") ? msg.getAsJsonObject("arguments") : new JsonObject();

        ToolArguments args = new ToolArguments(rawArgs);
        boolean cancelled = false;
        String result;

        RegisteredTool tool = tools.get(toolName);
        if (tool == null) {
            result = "Error: Tool '" + toolName + "' is not registered on this edge.";
        } else {
            try {
                result = tool.handler.handle(args);
            } catch (Exception e) {
                result = "Error executing tool '" + toolName + "': " + e.getMessage();
            }
        }

        JsonObject reply = new JsonObject();
        reply.addProperty("type", "tool_result");
        reply.addProperty("call_id", callId);
        reply.addProperty("result", result != null ? result : "");
        reply.addProperty("cancelled", cancelled);

        try {
            ws.sendText(GSON.toJson(reply), true);
        } catch (Exception ignored) {}
    }

    // ── confirmation policy ──

    private String confirmationPolicyPath() {
        String override = EnvParser.getEnv("YUMI_TOOL_CONFIRMATION_PATH");
        if (override != null && !override.trim().isEmpty()) {
            return override.trim();
        }
        return Path.of(policyBaseDir, TOOL_CONFIRMATION_FILENAME).toString();
    }

    private JsonObject loadConfirmationPolicyJson() {
        Path path = Path.of(confirmationPolicyPath());
        if (!Files.isRegularFile(path)) {
            return defaultPolicy();
        }
        try {
            String content = Files.readString(path);
            JsonObject raw = JsonParser.parseString(content).getAsJsonObject();
            JsonObject result = new JsonObject();
            result.add("always_allow", getStringArray(raw, "always_allow"));
            result.add("force_confirm", getStringArray(raw, "force_confirm"));
            return result;
        } catch (Exception e) {
            return defaultPolicy();
        }
    }

    private void saveConfirmationPolicy(JsonObject data) {
        Path path = Path.of(confirmationPolicyPath());
        try {
            Files.createDirectories(path.getParent());
            JsonObject payload = new JsonObject();
            payload.add("always_allow", getStringArray(data, "always_allow"));
            payload.add("force_confirm", getStringArray(data, "force_confirm"));
            Files.writeString(path, GSON.toJson(payload));
        } catch (IOException ignored) {}
    }

    private void handlePersistPolicy(JsonObject msg) {
        saveConfirmationPolicy(msg);
    }

    // ── helpers ──

    private static JsonObject defaultPolicy() {
        JsonObject o = new JsonObject();
        o.add("always_allow", new JsonArray());
        o.add("force_confirm", new JsonArray());
        return o;
    }

    private static JsonArray getStringArray(JsonObject obj, String key) {
        JsonArray result = new JsonArray();
        if (obj == null || !obj.has(key)) return result;
        JsonElement e = obj.get(key);
        if (!e.isJsonArray()) return result;
        for (JsonElement item : e.getAsJsonArray()) {
            if (item.isJsonPrimitive()) {
                String s = item.getAsString();
                if (!s.isEmpty()) result.add(s);
            }
        }
        return result;
    }

    private static class RegisteredTool {
        final JsonObject schema;
        final ToolHandler handler;
        final boolean requireConfirmation;

        RegisteredTool(JsonObject schema, ToolHandler handler, boolean requireConfirmation) {
            this.schema = schema;
            this.handler = handler;
            this.requireConfirmation = requireConfirmation;
        }
    }
}
