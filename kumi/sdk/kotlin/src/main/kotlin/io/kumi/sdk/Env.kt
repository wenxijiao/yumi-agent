package io.kumi.sdk

import java.nio.file.Files
import java.nio.file.Path

private val loaded = mutableMapOf<String, String>()

fun loadEnvFile(path: String) {
    val p = Path.of(path)
    if (!Files.isRegularFile(p)) return
    Files.readAllLines(p).forEach { line ->
        val t = line.trim()
        if (t.isEmpty() || t.startsWith("#")) return@forEach
        val idx = t.indexOf('=')
        if (idx < 0) return@forEach
        var key = t.substring(0, idx).trim()
        var value = t.substring(idx + 1).trim()
        if (value.length >= 2) {
            val q = value[0]
            if ((q == '"' || q == '\'') && value.endsWith(q)) {
                value = value.substring(1, value.length - 1)
            }
        }
        val existing = System.getenv(key)
        if (existing.isNullOrEmpty()) {
            loaded[key] = value
        }
    }
}

fun kumiEnv(key: String): String {
    val p = System.getenv(key)
    if (!p.isNullOrEmpty()) return p
    return loaded[key].orEmpty()
}

fun setKumiEnv(key: String, value: String) {
    loaded[key] = value
}
