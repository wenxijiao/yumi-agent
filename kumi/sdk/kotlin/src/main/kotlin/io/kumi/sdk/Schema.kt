package io.kumi.sdk

import com.google.gson.JsonArray
import com.google.gson.JsonObject

fun buildToolSchema(opts: RegisterOptions): JsonObject {
    val properties = JsonObject()
    val required = JsonArray()
    for (p in opts.parameters) {
        val prop = JsonObject()
        prop.addProperty("type", p.typeName)
        prop.addProperty("description", p.description)
        properties.add(p.name, prop)
        val isRequired = p.isRequired ?: true
        if (isRequired) required.add(p.name)
    }
    val parameters = JsonObject()
    parameters.addProperty("type", "object")
    parameters.add("properties", properties)
    parameters.add("required", required)
    val fn = JsonObject()
    fn.addProperty("name", opts.name)
    fn.addProperty("description", opts.description)
    fn.add("parameters", parameters)
    val schema = JsonObject()
    schema.addProperty("type", "function")
    schema.add("function", fn)
    if (opts.timeout != null) {
        schema.addProperty("timeout", opts.timeout)
    }
    if (opts.requireConfirmation) {
        schema.addProperty("require_confirmation", true)
    }
    if (opts.alwaysInclude) {
        schema.addProperty("always_include", true)
    }
    if (opts.allowProactive) {
        schema.addProperty("allow_proactive", true)
    }
    if (opts.proactiveContext) {
        schema.addProperty("proactive_context", true)
    }
    if (opts.proactiveContextArgs != null) {
        schema.add("proactive_context_args", opts.proactiveContextArgs)
    }
    if (!opts.proactiveContextDescription.isNullOrBlank()) {
        schema.addProperty("proactive_context_description", opts.proactiveContextDescription)
    }
    return schema
}
