package io.yumi;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

/**
 * Builds the JSON tool schema sent during WebSocket registration.
 */
public final class SchemaBuilder {
    private SchemaBuilder() {}

    public static JsonObject build(RegisterOptions opts) {
        JsonObject properties = new JsonObject();
        JsonArray required = new JsonArray();

        for (ToolParameter p : opts.getParameters()) {
            JsonObject prop = new JsonObject();
            prop.addProperty("type", p.getType());
            prop.addProperty("description", p.getDescription());
            properties.add(p.getName(), prop);
            if (p.isRequired()) {
                required.add(p.getName());
            }
        }

        JsonObject params = new JsonObject();
        params.addProperty("type", "object");
        params.add("properties", properties);
        params.add("required", required);

        JsonObject function = new JsonObject();
        function.addProperty("name", opts.getName());
        function.addProperty("description", opts.getDescription());
        function.add("parameters", params);

        JsonObject schema = new JsonObject();
        schema.addProperty("type", "function");
        schema.add("function", function);

        if (opts.getTimeout() != null) {
            schema.addProperty("timeout", opts.getTimeout());
        }
        if (opts.isRequireConfirmation()) {
            schema.addProperty("require_confirmation", true);
        }
        if (opts.isAlwaysInclude()) {
            schema.addProperty("always_include", true);
        }
        if (opts.isAllowProactive()) {
            schema.addProperty("allow_proactive", true);
        }
        if (opts.isProactiveContext()) {
            schema.addProperty("proactive_context", true);
        }
        if (opts.getProactiveContextArgs() != null) {
            schema.add("proactive_context_args", new Gson().toJsonTree(opts.getProactiveContextArgs()));
        }
        if (opts.getProactiveContextDescription() != null && !opts.getProactiveContextDescription().isBlank()) {
            schema.addProperty("proactive_context_description", opts.getProactiveContextDescription());
        }

        return schema;
    }
}
