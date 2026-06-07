#include <kumi/kumi_agent.h>
#include <kumi/kumi_agent.hpp>

#include <memory>
#include <string>
#include <vector>

extern "C" {

KumiAgentHandle kumi_agent_create(
    const char* connection_code,
    const char* edge_name,
    const char* env_path
) {
    auto* agent = new kumi::KumiAgent(
        connection_code ? connection_code : "",
        edge_name ? edge_name : "",
        env_path ? env_path : "",
        std::make_shared<kumi::DefaultTransport>()
    );
    return static_cast<KumiAgentHandle>(agent);
}

struct CHandlerContext {
    kumi_tool_handler_t handler;
    void* userData;
};

void kumi_agent_register(
    KumiAgentHandle handle,
    const char* name,
    const char* description,
    const KumiToolParam* params,
    int param_count,
    kumi_tool_handler_t handler,
    void* user_data
) {
    auto* agent = static_cast<kumi::KumiAgent*>(handle);

    std::vector<kumi::ToolParameter> parameters;
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
        .handler = [ctx](const kumi::ToolArguments& args) -> std::string {
            std::string argsJson = args.rawData().dump();
            const char* result = ctx->handler(argsJson.c_str(), ctx->userData);
            return result ? std::string(result) : "";
        },
    });
}

void kumi_agent_run_in_background(KumiAgentHandle handle) {
    auto* agent = static_cast<kumi::KumiAgent*>(handle);
    agent->runInBackground();
}

void kumi_agent_stop(KumiAgentHandle handle) {
    auto* agent = static_cast<kumi::KumiAgent*>(handle);
    agent->stop();
}

void kumi_agent_destroy(KumiAgentHandle handle) {
    auto* agent = static_cast<kumi::KumiAgent*>(handle);
    delete agent;
}

} // extern "C"
