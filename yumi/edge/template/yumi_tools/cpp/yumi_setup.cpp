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
#include <utility>

// ── Connection (edit here, or set in .env) ──

static const char* YUMI_CONNECTION_CODE = "yumi-lan_...";  // from `yumi --server`
static const char* YUMI_EDGE_NAME = "My C++ App";

yumi::YumiAgent* initYumi() {
    auto* agent = new yumi::YumiAgent(YUMI_CONNECTION_CODE, YUMI_EDGE_NAME);

    // ── Register tools: name + description + parameters + handler ──

    // yumi::RegisterOptions jump;
    // jump.name = "jump";
    // jump.description = "Make the character jump";
    // jump.parameters = {
    //     {"height", "number", "Jump height in meters"},
    // };
    // jump.handler = [](const yumi::ToolArguments& args) -> std::string {
    //     double h = args.number("height").value_or(1.0);
    //     return "Jumped " + std::to_string(h) + " meters";
    // };
    // agent->registerTool(std::move(jump));

    // Dangerous tools: user confirms in the Yumi web UI or `yumi --chat` (not on device):
    // yumi::RegisterOptions deleteAll;
    // deleteAll.name = "delete_all";
    // deleteAll.description = "Delete all data";
    // deleteAll.requireConfirmation = true;
    // deleteAll.handler = [](const yumi::ToolArguments&) -> std::string {
    //     return "Deleted everything";
    // };
    // agent->registerTool(std::move(deleteAll));
    //
    // Read-only tools can opt in to proactive messaging context:
    // yumi::RegisterOptions status;
    // status.name = "get_status";
    // status.description = "Read current app status";
    // status.allowProactive = true;
    // status.proactiveContext = true;
    // status.handler = [](const yumi::ToolArguments&) -> std::string {
    //     return "ok";
    // };
    // agent->registerTool(std::move(status));

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
