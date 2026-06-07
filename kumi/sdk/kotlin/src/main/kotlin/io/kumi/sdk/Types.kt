package io.kumi.sdk

import com.google.gson.JsonObject

class ToolArguments(private val raw: JsonObject) {
    fun string(key: String): String =
        if (raw.has(key)) raw.get(key).asString else ""

    fun int(key: String, fallback: Int): Int =
        if (raw.has(key)) raw.get(key).asInt else fallback

    fun double(key: String, fallback: Double): Double =
        if (raw.has(key)) raw.get(key).asDouble else fallback

    fun bool(key: String, fallback: Boolean): Boolean =
        if (raw.has(key)) raw.get(key).asBoolean else fallback
}

data class ToolParameter(
    val name: String,
    val typeName: String,
    val description: String,
    /** `null` means required (default true). */
    val isRequired: Boolean? = null,
)

fun interface ToolHandler {
    fun handle(args: ToolArguments): String
}

data class RegisterOptions(
    val name: String,
    val description: String,
    val parameters: List<ToolParameter> = emptyList(),
    val timeout: Int? = null,
    val requireConfirmation: Boolean = false,
    val alwaysInclude: Boolean = false,
    val allowProactive: Boolean = false,
    val proactiveContext: Boolean = false,
    val proactiveContextArgs: JsonObject? = null,
    val proactiveContextDescription: String? = null,
    val handler: ToolHandler,
)

data class AgentOptions(
    val connectionCode: String? = null,
    val edgeName: String? = null,
    val envPath: String? = null,
)
