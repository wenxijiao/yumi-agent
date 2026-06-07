#include <yumi/yumi_agent.h>
#include <yumi/yumi_agent.hpp>

#include <memory>
#include <string>
#include <vector>

extern "C" {

YumiAgentHandle yumi_agent_create(
    const char* connection_code,
    const char* edge_name,
    const char* env_path
) {
    auto* agent = new yumi::YumiAgent(
        connection_code ? connection_code : "",
        edge_name ? edge_name : "",
        env_path ? env_path : "",
        std::make_shared<yumi::DefaultTransport>()
    );
    return static_cast<YumiAgentHandle>(agent);
}

struct CHandlerContext {
    yumi_tool_handler_t handler;
    void* userData;
};

void yumi_agent_register(
    YumiAgentHandle handle,
    const char* name,
    const char* description,
    const YumiToolParam* params,
    int param_count,
    yumi_tool_handler_t handler,
    void* user_data
) {
    auto* agent = static_cast<yumi::YumiAgent*>(handle);

    std::vector<yumi::ToolParameter> parameters;
    for (int i = 0; i < param_count; ++i) {
        parameters.push_back({
            params[i].name ? params[i].name : "",
            params[i].type ? params[i].type : "string",
            params[i].description ? params[i].description : "",
            params[i].required != 0
        });
    }

    // Capture handler + user_data in a shared context
    auto ctx = std::make_shared<CHandlerContext>();
    ctx->handler = handler;
    ctx->userData = user_data;

    agent->registerTool({
        .name = name ? name : "",
        .description = description ? description : "",
        .parameters = std::move(parameters),
        .handler = [ctx](const yumi::ToolArguments& args) -> std::string {
            std::string argsJson = args.rawData().dump();
            const char* result = ctx->handler(argsJson.c_str(), ctx->userData);
            return result ? std::string(result) : "";
        },
    });
}

void yumi_agent_run_in_background(YumiAgentHandle handle) {
    auto* agent = static_cast<yumi::YumiAgent*>(handle);
    agent->runInBackground();
}

void yumi_agent_stop(YumiAgentHandle handle) {
    auto* agent = static_cast<yumi::YumiAgent*>(handle);
    agent->stop();
}

void yumi_agent_destroy(YumiAgentHandle handle) {
    auto* agent = static_cast<yumi::YumiAgent*>(handle);
    delete agent;
}

} // extern "C"
