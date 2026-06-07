package io.yumi.sdk

data class ConnectionConfig(
    val mode: String,
    val baseUrl: String,
    val accessToken: String,
) {
    fun websocketUrl(): String =
        if (mode == "relay") "${httpToWs(baseUrl.trimEnd('/'))}/ws/edge" else baseUrl
}

fun httpToWs(url: String): String {
    val u = url.trimEnd('/')
    return when {
        u.startsWith("https://") -> "wss://" + u.substring("https://".length)
        u.startsWith("http://") -> "ws://" + u.substring("http://".length)
        else -> u
    }
}

fun resolveConnection(code: String, edgeName: String): ConnectionConfig {
    val relayUrl = yumiEnv("YUMI_RELAY_URL")
    val accessToken = yumiEnv("YUMI_ACCESS_TOKEN")
    if (relayUrl.isNotEmpty() && accessToken.isNotEmpty()) {
        return ConnectionConfig("relay", relayUrl.trimEnd('/'), accessToken)
    }

    if (code.startsWith("ws://") || code.startsWith("wss://")) {
        return ConnectionConfig("direct", code, "")
    }

    if (isLanCode(code)) {
        val serverUrl = parseLanCodeToServerUrl(code)
        val wsUrl = "${httpToWs(serverUrl)}/ws/edge"
        return ConnectionConfig("direct", wsUrl, "")
    }

    if (isRelayToken(code)) {
        val profile = bootstrapProfile(code, "edge", edgeName)
        setYumiEnv("YUMI_RELAY_URL", profile.relayUrl)
        setYumiEnv("YUMI_ACCESS_TOKEN", profile.accessToken)
        return ConnectionConfig("relay", profile.relayUrl, profile.accessToken)
    }

    if (code.startsWith("http://") || code.startsWith("https://")) {
        val base = code.trimEnd('/')
        val wsUrl = "${httpToWs(base)}/ws/edge"
        return ConnectionConfig("direct", wsUrl, "")
    }

    return ConnectionConfig("direct", "ws://127.0.0.1:8000/ws/edge", "")
}
