# Kumi Edge — Swift

Use this when you want to expose Swift or Apple-platform app functions to Kumi.

The generated `KumiSDK/` folder is a complete Swift package.

## Quick Start

1. Add `kumi_tools/swift/KumiSDK` as a local Swift package in Xcode
2. Edit `kumi_tools/swift/KumiSetup.swift`
3. Set the connection code directly in that file
4. Call `initKumi()` early in your app lifecycle (e.g. from `@main` or `App.init`)

Swift has no `if __name__ == "__main__"`. For a **command-line** smoke test, add a tiny executable target in `Package.swift` whose `main` only calls `initKumi()` and then sleeps on the run loop; for **iOS/macOS apps**, calling `initKumi()` from your app delegate or SwiftUI `App` is the usual pattern.

## Files In This Folder

```text
kumi_tools/swift/
├── README.md
├── KumiSetup.swift        # edit this
├── bundle-env.example      # optional bundle-based config example
└── KumiSDK/               # full Swift package
    ├── Package.swift
    └── Sources/KumiSDK/
```

## Add The SDK

### Option A: local Swift package (recommended)

1. In Xcode, choose **File → Add Package Dependencies… → Add Local…**
2. Select `kumi_tools/swift/KumiSDK`
3. Add the `KumiSDK` library product to your app target
4. Keep `KumiSetup.swift` in your app target

### Option B: same target, no SwiftPM

Add both `KumiSetup.swift` and every file under `KumiSDK/Sources/KumiSDK/` to the same app target.

## Configure Connection

The simplest and most reliable path is to edit the constants in `KumiSetup.swift` directly.

That works the same way on:

- iPhone
- iPad
- Simulator
- macOS

Optional scheme variables, bundle files, and `.env` walking are still supported, but literals in code are the recommended default.

If you prefer a bundle file, see `bundle-env.example`.

## Register Tools

Inside `initKumi()`, call `agent.register(...)`:

```swift
agent.register(
    name: "jump",
    description: "Make the character jump",
    parameters: [
        .init("height", type: .number, description: "Jump height in meters")
    ]
) { args in
    let height = args.double("height") ?? 1.0
    return jump(height: height)
}
```

Use `requireConfirmation: true` for dangerous tools.

## Start It From Your App

Call `initKumi()` from your `@main`, `AppDelegate`, or another early startup location.

## Notes

- Bundle-based config writes tool-confirmation policy into `Application Support / Kumi/` when the bundle is read-only
- Direct code configuration is usually the least surprising setup for Apple apps
