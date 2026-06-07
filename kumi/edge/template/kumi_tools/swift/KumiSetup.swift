/// Kumi Edge — Swift tool registration
///
/// Add the local Swift package at ``KumiSDK/`` (contains ``Package.swift``)
/// via Xcode → File → Add Package Dependencies → Add Local…, then
/// ``import KumiSDK``. See ``README.md`` for same-target (no SPM) setup.
///
/// Call ``initKumi()`` early in your app lifecycle (e.g. from ``@main``).

import KumiSDK

// MARK: - Import your tool functions
// import MyApp

// MARK: - Connection (edit here — simplest on iPhone; no bundle file needed)

private let kumiConnectionCode = "kumi-lan_..."  // paste from `kumi --server`, or kumi_... for relay
private let kumiEdgeName = "My IOS Device"            // shown in the Kumi UI

func initKumi() -> KumiAgent {
    let agent = KumiAgent(
        connectionCode: kumiConnectionCode,
        edgeName: kumiEdgeName
    )

    // MARK: - Register tools: name + description + parameters + handler

    // agent.register(
    //     name: "jump",
    //     description: "Make the character jump",
    //     parameters: [
    //         .init("height", type: .number, description: "Jump height in meters"),
    //     ]
    // ) { args in
    //     let height = args.double("height") ?? 1.0
    //     return jump(height: height)
    // }

    // Dangerous tools: user confirms in the Kumi web UI or `kumi --chat` (not on device):
    // agent.register(
    //     name: "delete_all",
    //     description: "Delete all data",
    //     requireConfirmation: true
    // ) { _ in
    //     return deleteAll()
    // }

    agent.runInBackground()
    return agent
}
