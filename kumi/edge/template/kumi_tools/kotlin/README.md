# Kumi Edge — Kotlin (JVM)

## Quick Start

1. Run `kumi --edge --lang kotlin` (or `kumi --edge`) from your project root.
2. Edit `kumi_tools/kotlin/src/main/kotlin/io/kumi/edge/KumiSetup.kt`.
3. From `kumi_tools/kotlin/`:

```bash
./gradlew run
```

(Use `gradle run` if you do not use the Gradle wrapper.)

## Dependencies

OkHttp WebSocket + Gson — declared in `build.gradle.kts`. The `io.kumi.sdk` package is copied into `src/main/kotlin/io/kumi/sdk/` by `kumi --edge`.

## Configure

Use `kumi_tools/.env`:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Kotlin App
```
