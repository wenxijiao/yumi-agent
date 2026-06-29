# Yumi Edge — Kotlin (JVM)

## Quick Start

1. Run `yumi --edge` (or `yumi --edge --lang kotlin`) from your project root.
2. Edit `yumi_tools/kotlin/src/main/kotlin/io/yumi/edge/YumiSetup.kt`.
3. From `yumi_tools/kotlin/`:

```bash
./gradlew run
```

(Use `gradle run` if you do not use the Gradle wrapper.)

## Dependencies

OkHttp WebSocket + Gson — declared in `build.gradle.kts`. The `io.yumi.sdk` package is copied into `src/main/kotlin/io/yumi/sdk/` by `yumi --edge`.

## Configure

Use `yumi_tools/.env`:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My Kotlin App
```
