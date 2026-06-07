/**
 * Kumi Edge — C++ tool registration
 *
 * Register your functions with agent.registerTool() and call initKumi()
 * from your main program entry point.
 *
 * Build: add the KumiSDK directory via CMake add_subdirectory(), then
 * link with target_link_libraries(your_app PRIVATE kumi_sdk).
 *
 * See README.md for full setup instructions.
 */

#include <kumi/kumi_agent.hpp>
#include <string>

// ── Connection (edit here, or set in .env) ──

static const char* KUMI_CONNECTION_CODE = "kumi-lan_...";  // from `kumi --server`, or kumi_... for relay
static const char* KUMI_EDGE_NAME = "My C++ App";

kumi::KumiAgent* initKumi() {
    auto* agent = new kumi::KumiAgent(KUMI_CONNECTION_CODE, KUMI_EDGE_NAME);

    // ── Register tools: name + description + parameters + handler ──

    // agent->registerTool({
    //     .name = "jump",
    //     .description = "Make the character jump",
    //     .parameters = {
    //         {"height", "number", "Jump height in meters"},
    //     },
    //     .handler = [](const kumi::ToolArguments& args) -> std::string {
    //         double h = args.number("height").value_or(1.0);
    //         return "Jumped " + std::to_string(h) + " meters";
    //     },
    // });

    // Dangerous tools: user confirms in the Kumi web UI or `kumi --chat` (not on device):
    // agent->registerTool({
    //     .name = "delete_all",
    //     .description = "Delete all data",
    //     .requireConfirmation = true,
    //     .handler = [](const kumi::ToolArguments&) -> std::string {
    //         return "Deleted everything";
    //     },
    // });
    //
    // Read-only tools can opt in to proactive messaging context:
    // agent->registerTool({
    //     .name = "get_status",
    //     .description = "Read current app status",
    //     .allowProactive = true,
    //     .proactiveContext = true,
    //     .handler = [](const kumi::ToolArguments&) -> std::string {
    //         return "ok";
    //     },
    // });

    agent->runInBackground();
    return agent;
}

// Example main (remove or replace with your own):
// int main() {
//     auto* agent = initKumi();
//     // ... your main loop ...
//     // agent->stop();
//     // delete agent;
//     return 0;
// }
