/**
 * Yumi Edge — C++ tool registration
 *
 * Register your functions with agent.registerTool() and call initYumi()
 * from your main program entry point.
 *
 * Build: add the YumiSDK directory via CMake add_subdirectory(), then
 * link with target_link_libraries(your_app PRIVATE yumi_sdk).
 *
 * See README.md for full setup instructions.
 */

#include <yumi/yumi_agent.hpp>
#include <string>

// ── Connection (edit here, or set in .env) ──

static const char* YUMI_CONNECTION_CODE = "yumi-lan_...";  // from `yumi --server`
static const char* YUMI_EDGE_NAME = "My C++ App";

yumi::YumiAgent* initYumi() {
    auto* agent = new yumi::YumiAgent(YUMI_CONNECTION_CODE, YUMI_EDGE_NAME);

    // ── Register tools: name + description + parameters + handler ──

    // agent->registerTool({
    //     .name = "jump",
    //     .description = "Make the character jump",
    //     .parameters = {
    //         {"height", "number", "Jump height in meters"},
    //     },
    //     .handler = [](const yumi::ToolArguments& args) -> std::string {
    //         double h = args.number("height").value_or(1.0);
    //         return "Jumped " + std::to_string(h) + " meters";
    //     },
    // });

    // Dangerous tools: user confirms in the Yumi web UI or `yumi --chat` (not on device):
    // agent->registerTool({
    //     .name = "delete_all",
    //     .description = "Delete all data",
    //     .requireConfirmation = true,
    //     .handler = [](const yumi::ToolArguments&) -> std::string {
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
    //     .handler = [](const yumi::ToolArguments&) -> std::string {
    //         return "ok";
    //     },
    // });

    agent->runInBackground();
    return agent;
}

// Example main (remove or replace with your own):
// int main() {
//     auto* agent = initYumi();
//     // ... your main loop ...
//     // agent->stop();
//     // delete agent;
//     return 0;
// }
