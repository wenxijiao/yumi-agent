package io.yumi.sdk

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.Gson
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.IOException
import java.net.InetAddress
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class YumiAgent(opts: AgentOptions) {
    private val gson = Gson()
    private val tools = ConcurrentHashMap<String, RegisteredTool>()
    private val stopRequested = AtomicBoolean(false)
    private val executor: ExecutorService = Executors.newCachedThreadPool { r ->
        Thread(r, "yumi-kotlin").apply { isDaemon = true }
    }
    private var connectThread: Thread? = null

    private val connectionCode: String
    private val edgeName: String
    private val policyBaseDir: String

    init {
        val envFile = resolveEnvPath(opts.envPath)
        loadEnvFile(envFile)
        policyBaseDir = Path.of(envFile).parent?.toString() ?: "."
        var cc = opts.connectionCode.orEmpty()
        if (cc.isEmpty()) cc = yumiEnv("YUMI_CONNECTION_CODE")
        if (cc.isEmpty()) cc = yumiEnv("BRAIN_URL")
        connectionCode = cc
        var en = opts.edgeName.orEmpty()
        if (en.isEmpty()) en = yumiEnv("EDGE_NAME")
        if (en.isEmpty()) {
            en = try {
                InetAddress.getLocalHost().hostName
            } catch (_: Exception) {
                "yumi-edge"
            }
        }
        edgeName = en
    }

    fun register(opts: RegisterOptions) {
        val schema = buildToolSchema(opts)
        tools[opts.name] = RegisteredTool(schema, opts.handler, opts.requireConfirmation)
    }

    fun runInBackground() {
        if (tools.isEmpty()) {
            System.err.println("[Yumi] Warning: no tools registered.")
        }
        val t = Thread({ connectLoop() }, "yumi-connect").apply { isDaemon = true }
        connectThread = t
        t.start()
    }

    fun stop() {
        stopRequested.set(true)
        connectThread?.interrupt()
        executor.shutdownNow()
        try {
            executor.awaitTermination(5, TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
        }
    }

    private fun connectLoop() {
        val config = try {
            resolveConnection(connectionCode, edgeName)
        } catch (e: Exception) {
            System.err.println("[Yumi] Failed to resolve connection: ${e.message}")
            return
        }
        val wsUrl = if (config.mode == "relay") config.websocketUrl() else config.baseUrl
        var reconnectDelay = 3000L
        while (!stopRequested.get() && !Thread.currentThread().isInterrupted) {
            try {
                runSession(wsUrl, config.accessToken)
                reconnectDelay = 3000L
            } catch (e: Exception) {
                if (stopRequested.get()) break
                val waitMs = (reconnectDelay + (Math.random() * 500).toLong()).coerceAtLeast(1000L)
                System.err.println("[Yumi] Connection lost: ${e.message}. Reconnecting in ${waitMs}ms...")
                try {
                    Thread.sleep(waitMs)
                } catch (_: InterruptedException) {
                    break
                }
                reconnectDelay = (reconnectDelay * 2).coerceAtMost(30000L)
            }
        }
    }

    private fun runSession(wsUrl: String, accessToken: String) {
        val client = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build()
        val request = Request.Builder().url(wsUrl).build()
        val closeLatch = CountDownLatch(1)
        val error = AtomicReference<Throwable?>(null)

        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                val registerPayload = JsonObject()
                registerPayload.addProperty("type", "register")
                registerPayload.addProperty("edge_name", edgeName)
                val toolSchemas = com.google.gson.JsonArray()
                tools.values.forEach { toolSchemas.add(it.schema) }
                registerPayload.add("tools", toolSchemas)
                registerPayload.add("tool_confirmation_policy", loadConfirmationPolicyJson())
                if (accessToken.isNotEmpty()) {
                    registerPayload.addProperty("access_token", accessToken)
                }
                webSocket.send(gson.toJson(registerPayload))
                println("[Yumi] Connected as [$edgeName] with ${tools.size} tool(s).")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(webSocket, text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (stopRequested.get()) {
                    error.set(null)
                } else {
                    error.set(IOException("WebSocket closed: $code $reason"))
                }
                closeLatch.countDown()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                error.set(t)
                closeLatch.countDown()
            }
        }

        client.newWebSocket(request, listener)
        closeLatch.await()
        if (stopRequested.get()) return
        val err = error.get()
        if (err != null) throw err
    }

    private fun handleMessage(ws: WebSocket, text: String) {
        val msg = try {
            JsonParser.parseString(text).asJsonObject
        } catch (_: Exception) {
            return
        }
        val type = if (msg.has("type")) msg.get("type").asString else ""
        when (type) {
            "persist_tool_confirmation_policy" -> handlePersistPolicy(msg)
            "tool_call" -> executor.submit { handleToolCall(ws, msg) }
            else -> {}
        }
    }

    private fun handleToolCall(ws: WebSocket, msg: JsonObject) {
        val toolName = if (msg.has("name")) msg.get("name").asString else ""
        val callId = if (msg.has("call_id")) msg.get("call_id").asString else "unknown"
        val rawArgs = if (msg.has("arguments")) msg.getAsJsonObject("arguments") else JsonObject()
        val args = ToolArguments(rawArgs)
        val tool = tools[toolName]
        val result = if (tool == null) {
            "Error: Tool '$toolName' is not registered on this edge."
        } else {
            try {
                tool.handler.handle(args)
            } catch (e: Exception) {
                "Error executing tool '$toolName': ${e.message}"
            }
        }
        val reply = JsonObject()
        reply.addProperty("type", "tool_result")
        reply.addProperty("call_id", callId)
        reply.addProperty("result", result)
        reply.addProperty("cancelled", false)
        try {
            ws.send(gson.toJson(reply))
        } catch (_: Exception) {
        }
    }

    private fun handlePersistPolicy(msg: JsonObject) {
        saveConfirmationPolicy(msg)
    }

    private fun confirmationPolicyPath(): String {
        val o = yumiEnv("YUMI_TOOL_CONFIRMATION_PATH").trim()
        if (o.isNotEmpty()) return o
        return Path.of(policyBaseDir, ".yumi_tool_confirmation.json").toString()
    }

    private fun loadConfirmationPolicyJson(): JsonObject {
        val path = Path.of(confirmationPolicyPath())
        if (!Files.isRegularFile(path)) {
            return defaultPolicy()
        }
        return try {
            val raw = JsonParser.parseString(Files.readString(path)).asJsonObject
            JsonObject().apply {
                add("always_allow", raw.getAsJsonArray("always_allow") ?: com.google.gson.JsonArray())
                add("force_confirm", raw.getAsJsonArray("force_confirm") ?: com.google.gson.JsonArray())
            }
        } catch (_: Exception) {
            defaultPolicy()
        }
    }

    private fun defaultPolicy() = JsonObject().apply {
        add("always_allow", com.google.gson.JsonArray())
        add("force_confirm", com.google.gson.JsonArray())
    }

    private fun saveConfirmationPolicy(data: JsonObject) {
        val path = Path.of(confirmationPolicyPath())
        try {
            Files.createDirectories(path.parent)
            val payload = JsonObject()
            payload.add("always_allow", data.getAsJsonArray("always_allow") ?: com.google.gson.JsonArray())
            payload.add("force_confirm", data.getAsJsonArray("force_confirm") ?: com.google.gson.JsonArray())
            Files.writeString(path, gson.toJson(payload))
        } catch (_: Exception) {
        }
    }

    private fun resolveEnvPath(explicit: String?): String {
        if (!explicit.isNullOrEmpty()) return explicit
        val cwd = Path.of(System.getProperty("user.dir", "."))
        val a = cwd.resolve("yumi_tools").resolve(".env")
        val b = cwd.resolve(".env")
        return if (Files.isRegularFile(a)) a.toString() else b.toString()
    }

    private class RegisteredTool(
        val schema: JsonObject,
        val handler: ToolHandler,
        @Suppress("unused") val requireConfirmation: Boolean,
    )
}
