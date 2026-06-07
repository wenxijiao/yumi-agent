# Kumi Edge — Java

Use this when your app is written in Java and you want to expose functions to Kumi through JDK 11+ native WebSocket.

## Quick Start

1. Add the bundled SDK to your project
2. Edit `kumi_tools/java/KumiSetup.java`
3. **Quick test:** run `KumiEdgeMain` from your IDE, or configure `exec:java` with main class `KumiEdgeMain`. Delete `KumiEdgeMain.java` when you call `initKumi()` from your own `main`.
4. Otherwise call `KumiSetup.initKumi()` from your app entry point and keep your JVM process alive as usual

## Files In This Folder

```text
kumi_tools/java/
├── README.md
├── KumiSetup.java         # edit this
├── KumiEdgeMain.java      # optional standalone entry; delete when embedding
└── kumi_sdk/              # bundled Maven project
    ├── pom.xml
    └── src/main/java/io/kumi/
```

## Add The SDK To Your Project

Choose one of these approaches:

### Maven multi-module

Add `kumi_tools/java/kumi_sdk` as a module in your existing build.

### Install locally

```bash
cd kumi_tools/java/kumi_sdk
mvn install
```

Then depend on it from your app:

```xml
<dependency>
    <groupId>io.kumi</groupId>
    <artifactId>kumi-sdk</artifactId>
    <version>0.1.0</version>
</dependency>
```

### Copy sources

Copy `src/main/java/io/kumi/` into your project if that better fits your setup.

## Configure Connection

Edit the constants in `KumiSetup.java`, or use `kumi_tools/.env`:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Java App
```

## Register Tools

```java
agent.register(new RegisterOptions()
    .name("set_light")
    .description("Control room lights")
    .parameters(
        new ToolParameter("room", "string", "Room name"),
        new ToolParameter("on", "boolean", "Turn on or off")
    )
    .handler(args -> {
        String room = args.getString("room", "living_room");
        boolean on = args.getBoolean("on", false);
        return "Light in " + room + ": " + on;
    })
);
```

Use `.requireConfirmation(true)` for dangerous tools.

## Start It From Your App

```java
public class Main {
    public static void main(String[] args) throws Exception {
        KumiSetup.initKumi();
        Thread.currentThread().join();
    }
}
```

## Notes

- Requires JDK 11+
- Uses native `java.net.http.WebSocket`
- The only external dependency is Gson
