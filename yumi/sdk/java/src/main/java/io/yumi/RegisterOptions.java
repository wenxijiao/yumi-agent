package io.yumi;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * Builder-style configuration for registering a tool with YumiAgent.
 */
public class RegisterOptions {
    private String name;
    private String description;
    private List<ToolParameter> parameters = new ArrayList<>();
    private Integer timeout;
    private boolean requireConfirmation;
    /** Exposure mode — "dynamic" (default), "pinned", or "autorun". Input sugar mapped onto the flags below. */
    private String mode = "dynamic";
    /** Fixed arguments for an "autorun" tool. */
    private Map<String, Object> contextArgs;
    /** Label shown when an "autorun" result is injected. */
    private String contextLabel;
    private boolean alwaysInclude;
    private boolean allowProactive;
    private boolean proactiveContext;
    private Map<String, Object> proactiveContextArgs;
    private String proactiveContextDescription;
    private ToolHandler handler;

    public RegisterOptions name(String name) { this.name = name; return this; }
    public RegisterOptions description(String desc) { this.description = desc; return this; }
    public RegisterOptions parameters(ToolParameter... params) { this.parameters = Arrays.asList(params); return this; }
    public RegisterOptions parameters(List<ToolParameter> params) { this.parameters = params; return this; }
    public RegisterOptions timeout(int seconds) { this.timeout = seconds; return this; }
    public RegisterOptions requireConfirmation(boolean v) { this.requireConfirmation = v; return this; }
    public RegisterOptions mode(String v) { this.mode = v; return this; }
    public RegisterOptions contextArgs(Map<String, Object> v) { this.contextArgs = v; return this; }
    public RegisterOptions contextLabel(String v) { this.contextLabel = v; return this; }
    public RegisterOptions alwaysInclude(boolean v) { this.alwaysInclude = v; return this; }
    public RegisterOptions allowProactive(boolean v) { this.allowProactive = v; return this; }
    public RegisterOptions proactiveContext(boolean v) { this.proactiveContext = v; return this; }
    public RegisterOptions proactiveContextArgs(Map<String, Object> v) { this.proactiveContextArgs = v; return this; }
    public RegisterOptions proactiveContextDescription(String v) { this.proactiveContextDescription = v; return this; }
    public RegisterOptions handler(ToolHandler h) { this.handler = h; return this; }

    public String getName() { return name; }
    public String getDescription() { return description; }
    public List<ToolParameter> getParameters() { return parameters; }
    public Integer getTimeout() { return timeout; }
    public boolean isRequireConfirmation() { return requireConfirmation; }
    public String getMode() { return mode; }
    public Map<String, Object> getContextArgs() { return contextArgs; }
    public String getContextLabel() { return contextLabel; }
    public boolean isAlwaysInclude() { return alwaysInclude; }
    public boolean isAllowProactive() { return allowProactive; }
    public boolean isProactiveContext() { return proactiveContext; }
    public Map<String, Object> getProactiveContextArgs() { return proactiveContextArgs; }
    public String getProactiveContextDescription() { return proactiveContextDescription; }
    public ToolHandler getHandler() { return handler; }

    /**
     * Apply the {@code mode} sugar onto the low-level wire flags, returning a
     * copy with resolved fields. {@code mode} is never emitted on the wire.
     *
     * @throws IllegalArgumentException if mode is not "dynamic", "pinned", or "autorun".
     */
    RegisterOptions resolveMode() {
        String m = mode == null ? "dynamic" : mode;
        switch (m) {
            case "dynamic":
                return this;
            case "pinned": {
                RegisterOptions r = copy();
                r.alwaysInclude = true;
                return r;
            }
            case "autorun": {
                RegisterOptions r = copy();
                r.proactiveContext = true;
                if (contextArgs != null) r.proactiveContextArgs = contextArgs;
                if (contextLabel != null) r.proactiveContextDescription = contextLabel;
                return r;
            }
            default:
                throw new IllegalArgumentException(
                        "mode must be 'dynamic', 'pinned', or 'autorun'; got '" + m + "'");
        }
    }

    private RegisterOptions copy() {
        RegisterOptions r = new RegisterOptions();
        r.name = name;
        r.description = description;
        r.parameters = parameters;
        r.timeout = timeout;
        r.requireConfirmation = requireConfirmation;
        r.mode = mode;
        r.contextArgs = contextArgs;
        r.contextLabel = contextLabel;
        r.alwaysInclude = alwaysInclude;
        r.allowProactive = allowProactive;
        r.proactiveContext = proactiveContext;
        r.proactiveContextArgs = proactiveContextArgs;
        r.proactiveContextDescription = proactiveContextDescription;
        r.handler = handler;
        return r;
    }
}
