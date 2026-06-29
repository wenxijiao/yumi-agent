# Yumi Edge — Java

Use this when your app is written in Java and you want to expose functions to Yumi through JDK 11+ native WebSocket.

## Quick Start

1. Add the bundled SDK to your project
2. Edit `yumi_tools/java/YumiSetup.java`
3. **Quick test:** run `YumiEdgeMain` from your IDE, or configure `exec:java` with main class `YumiEdgeMain`. Delete `YumiEdgeMain.java` when you call `initYumi()` from your own `main`.
4. Otherwise call `YumiSetup.initYumi()` from your app entry point and keep your JVM process alive as usual

## Files In This Folder

```text
yumi_tools/java/
├── README.md
├── YumiSetup.java         # edit this
├── YumiEdgeMain.java      # optional standalone entry; delete when embedding
└── yumi_sdk/              # bundled Maven project
    ├── pom.xml
    └── src/main/java/io/yumi/
```

## Add The SDK To Your Project

Choose one of these approaches:

### Maven multi-module

Add `yumi_tools/java/yumi_sdk` as a module in your existing build.

### Install locally

```bash
cd yumi_tools/java/yumi_sdk
mvn install
```

Then depend on it from your app:

```xml
<dependency>
    <groupId>io.yumi</groupId>
    <artifactId>yumi-sdk</artifactId>
    <version>0.0.1</version>
</dependency>
```

### Copy sources

Copy `src/main/java/io/yumi/` into your project if that better fits your setup.

## Configure Connection

Edit the constants in `YumiSetup.java`, or use `yumi_tools/.env`:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
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
        YumiSetup.initYumi();
        Thread.currentThread().join();
    }
}
```

## Notes

- Requires JDK 11+
- Uses native `java.net.http.WebSocket`
- The only external dependency is Gson
