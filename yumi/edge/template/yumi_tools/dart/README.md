# Yumi Edge — Dart

Targets **Dart VM** (CLI / server). For Flutter, use the same `yumi_sdk` package in your app.

## Quick Start

1. Edit `yumi_tools/dart/lib/yumi_setup.dart`.
2. From `yumi_tools/dart/`:

```bash
dart pub get
dart run
```

## Layout

- `yumi_sdk/` — copied Yumi SDK (`package:yumi_sdk`)
- `lib/yumi_setup.dart` — register tools and call `initYumi()` from your entrypoint

## Configure

`yumi_tools/.env`:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My Dart App
```
