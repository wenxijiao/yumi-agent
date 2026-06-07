# Kumi Edge — Dart

Targets **Dart VM** (CLI / server). For Flutter, use the same `kumi_sdk` package in your app.

## Quick Start

1. Edit `kumi_tools/dart/lib/kumi_setup.dart`.
2. From `kumi_tools/dart/`:

```bash
dart pub get
dart run
```

## Layout

- `kumi_sdk/` — copied Kumi SDK (`package:kumi_sdk`)
- `lib/kumi_setup.dart` — register tools and call `initKumi()` from your entrypoint

## Configure

`kumi_tools/.env`:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Dart App
```
