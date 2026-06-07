package io.kumi.edge

import io.kumi.sdk.AgentOptions
import io.kumi.sdk.KumiAgent
import io.kumi.sdk.RegisterOptions
import io.kumi.sdk.ToolHandler
import io.kumi.sdk.ToolParameter

fun initKumi() {
    val agent = KumiAgent(
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
    agent.runInBackground()
}
