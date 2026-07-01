package io.yumi.edge

import io.yumi.sdk.AgentOptions
import io.yumi.sdk.YumiAgent
import io.yumi.sdk.RegisterOptions
import io.yumi.sdk.ToolHandler
import io.yumi.sdk.ToolParameter

fun initYumi() {
    val agent = YumiAgent(
        AgentOptions(
            connectionCode = null,
            edgeName = "My Kotlin App",
            envPath = null,
        ),
    )
    agent.register(
        RegisterOptions(
            name = "hello",
            description = "Say hello to someone",
            parameters = listOf(
                ToolParameter(
                    name = "name",
                    typeName = "string",
                    description = "Person to greet",
                ),
            ),
            handler = ToolHandler { args -> "Hello, ${args.string("name")}!" },
        ),
    )
    // Example tool — replace with your own. Registered in "pinned" exposure mode
    // so it is always exposed to the agent.
    agent.register(
        RegisterOptions(
            name = "ping",
            description = "Ping the edge and echo a message back",
            parameters = listOf(
                ToolParameter(
                    name = "message",
                    typeName = "string",
                    description = "Text to echo back.",
                    isRequired = false,
                ),
            ),
            mode = "pinned",
            handler = ToolHandler { args -> "pong: ${args.string("message")}" },
        ),
    )
    agent.runInBackground()
}
