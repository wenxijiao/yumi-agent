package io.yumi;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/**
 * Type-safe accessor for tool call arguments backed by a Gson JsonObject.
 */
public class ToolArguments {
    private final JsonObject raw;

    public ToolArguments(JsonObject raw) {
        this.raw = raw != null ? raw : new JsonObject();
    }

    public JsonObject getRaw() { return raw; }

    public String getString(String key, String fallback) {
        JsonElement e = raw.get(key);
        if (e == null || !e.isJsonPrimitive()) return fallback;
        return e.getAsString();
    }

    public String getString(String key) {
        return getString(key, "");
    }

    public int getInt(String key, int fallback) {
        JsonElement e = raw.get(key);
        if (e == null || !e.isJsonPrimitive()) return fallback;
        try { return e.getAsInt(); } catch (Exception ex) { return fallback; }
    }

    public double getDouble(String key, double fallback) {
        JsonElement e = raw.get(key);
        if (e == null || !e.isJsonPrimitive()) return fallback;
        try { return e.getAsDouble(); } catch (Exception ex) { return fallback; }
    }

    public boolean getBoolean(String key, boolean fallback) {
        JsonElement e = raw.get(key);
        if (e == null || !e.isJsonPrimitive()) return fallback;
        try { return e.getAsBoolean(); } catch (Exception ex) { return fallback; }
    }
}
