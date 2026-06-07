// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "KumiSDK",
    platforms: [
        .macOS(.v12),
        .iOS(.v15),
        .tvOS(.v15),
        .watchOS(.v8),
    ],
    products: [
        .library(name: "KumiSDK", targets: ["KumiSDK"]),
    ],
    targets: [
        .target(name: "KumiSDK"),
    ]
)
