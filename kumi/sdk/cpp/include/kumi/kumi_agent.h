/**
 * Kumi Edge SDK — C ABI
 *
 * Thin C wrapper around KumiAgent for use from C, Lua, or any language
 * that can call C functions via FFI.
 *
 * Usage:
 *   KumiAgentHandle agent = kumi_agent_create("kumi-lan_...", "My Device", NULL);
 *   kumi_agent_register(agent, "ping", "Return pong", NULL, 0, my_handler, NULL);
 *   kumi_agent_run_in_background(agent);
 *   // ... your main loop ...
 *   kumi_agent_stop(agent);
 *   kumi_agent_destroy(agent);
 */

#ifndef KUMI_AGENT_C_H
#define KUMI_AGENT_C_H

#ifdef __cplusplus
extern "C" {
#endif

typedef void* KumiAgentHandle;

/**
 * Tool handler callback.
 * @param args_json  JSON string containing the tool arguments.
 * @param user_data  Opaque pointer passed during registration.
 * @return Result string. The SDK copies this immediately; caller owns the memory.
 */
typedef const char* (*kumi_tool_handler_t)(const char* args_json, void* user_data);

/**
 * Tool parameter descriptor for C API registration.
 */
typedef struct {
    const char* name;
    const char* type;        /* "string", "integer", "number", "boolean", "array", "object" */
    const char* description;
    int required;            /* 1 = required, 0 = optional */
} KumiToolParam;

/**
 * Create a new KumiAgent.
 * @param connection_code  LAN code, relay token, WebSocket URL, or NULL for env/default.
 * @param edge_name        Display name in the Kumi UI, or NULL for hostname.
 * @param env_path         Explicit .env file path, or NULL for auto-detection.
 */
KumiAgentHandle kumi_agent_create(
    const char* connection_code,
    const char* edge_name,
    const char* env_path
);

/**
 * Register a tool.
 * @param agent            Handle from kumi_agent_create.
 * @param name             Tool name (must be unique).
 * @param description      AI-facing description.
 * @param params           Array of parameter descriptors (may be NULL if param_count == 0).
 * @param param_count      Number of parameters.
 * @param handler          Callback invoked when the AI calls this tool.
 * @param user_data        Passed to handler unchanged.
 */
void kumi_agent_register(
    KumiAgentHandle agent,
    const char* name,
    const char* description,
    const KumiToolParam* params,
    int param_count,
    kumi_tool_handler_t handler,
    void* user_data
);

/**
 * Start the WebSocket client in a background thread.
 */
void kumi_agent_run_in_background(KumiAgentHandle agent);

/**
 * Gracefully shut down the background client.
 */
void kumi_agent_stop(KumiAgentHandle agent);

/**
 * Destroy the agent and free all resources.
 */
void kumi_agent_destroy(KumiAgentHandle agent);

#ifdef __cplusplus
}
#endif

#endif /* KUMI_AGENT_C_H */
