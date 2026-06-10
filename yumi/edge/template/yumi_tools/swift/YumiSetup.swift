/// Yumi Edge — Swift tool registration
///
/// Add the local Swift package at ``YumiSDK/`` (contains ``Package.swift``)
/// via Xcode → File → Add Package Dependencies → Add Local…, then
/// ``import YumiSDK``. See ``README.md`` for same-target (no SPM) setup.
///
/// Call ``initYumi()`` early in your app lifecycle (e.g. from ``@main``).

import YumiSDK

// MARK: - Import your tool functions
// import MyApp

// MARK: - Connection (edit here — simplest on iPhone; no bundle file needed)

private let yumiConnectionCode = "yumi-lan_..."  // paste from `yumi --server`
private let yumiEdgeName = "My IOS Device"            // shown in the Yumi UI

func initYumi() -> YumiAgent {
    let agent = YumiAgent(
        connectionCode: yumiConnectionCode,
        edgeName: yumiEdgeName
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

    // Dangerous tools: user confirms in the Yumi web UI or `yumi --chat` (not on device):
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
