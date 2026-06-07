package io.kumi.sdk

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.Base64

private const val TOKEN_PREFIX = "kumi_"
private const val LAN_TOKEN_PREFIX = "kumi-lan_"
private val LEGACY_LAN_PREFIXES = arrayOf("ml1_", "kumi_lan_")

private fun b64urlDecode(data: String): ByteArray {
    val padding = (4 - data.length % 4) % 4
    val padded = data + "=".repeat(padding)
    return Base64.getUrlDecoder().decode(padded)
}

fun isLanCode(code: String): Boolean {
    if (code.startsWith(LAN_TOKEN_PREFIX)) return true
    return LEGACY_LAN_PREFIXES.any { code.startsWith(it) }
}

fun isRelayToken(code: String): Boolean = code.startsWith(TOKEN_PREFIX) && !isLanCode(code)

fun parseLanCodeToServerUrl(code: String): String {
    val encoded = when {
        code.startsWith(LAN_TOKEN_PREFIX) -> code.substring(LAN_TOKEN_PREFIX.length)
        else -> {
            var e: String? = null
            for (prefix in LEGACY_LAN_PREFIXES) {
                if (code.startsWith(prefix)) {
                    e = code.substring(prefix.length)
                    break
                }
            }
            e ?: throw IllegalArgumentException("invalid Kumi LAN code prefix")
        }
    }
    val json = String(b64urlDecode(encoded), StandardCharsets.UTF_8)
    val data = JsonParser.parseString(json).asJsonObject
    val host: String
    val port: Int
    if (data.has("h")) {
        host = data.get("h").asJsonPrimitive.asString
        port = if (data.has("p")) data.get("p").asInt else 8000
    } else if (data.has("base_url")) {
        val uri = java.net.URI.create(data.get("base_url").asString)
        host = uri.host ?: throw IllegalArgumentException("LAN code missing host")
        port = if (uri.port > 0) uri.port else 8000
    } else {
        throw IllegalArgumentException("LAN code missing host")
    }
    if (data.has("x")) {
        val exp = data.get("x").asLong
        if (exp > 0 && exp < Instant.now().epochSecond) {
            throw IllegalArgumentException("LAN code has expired")
        }
    }
    return "http://$host:$port"
}

data class BootstrapResult(val relayUrl: String, val accessToken: String)

fun bootstrapProfile(joinCode: String, scope: String, deviceName: String): BootstrapResult {
    val cred = JsonParser.parseString(
        String(b64urlDecode(joinCode.substring(TOKEN_PREFIX.length)), StandardCharsets.UTF_8)
    ).asJsonObject
    val relayUrl = cred.get("relay_url").asString.trimEnd('/')
    val gson = Gson()
    val payload = JsonObject().apply {
        addProperty("join_code", joinCode)
        addProperty("scope", scope)
        addProperty("device_name", deviceName.trim())
    }
    val client = OkHttpClient.Builder().callTimeout(java.time.Duration.ofSeconds(15)).build()
    val body = gson.toJson(payload).toRequestBody("application/json; charset=utf-8".toMediaType())
    val req = Request.Builder().url("$relayUrl/v1/bootstrap").post(body).build()
    client.newCall(req).execute().use { resp ->
        val text = resp.body?.string().orEmpty()
        check(resp.isSuccessful) { "bootstrap failed: $text" }
        val result = JsonParser.parseString(text).asJsonObject
        val at = result.get("access_token").asString
        return BootstrapResult(relayUrl, at)
    }
}
