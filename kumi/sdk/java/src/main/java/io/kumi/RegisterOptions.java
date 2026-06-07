package io.kumi;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * Builder-style configuration for registering a tool with KumiAgent.
 */
public class RegisterOptions {
    private String name;
    private String description;
    private List<ToolParameter> parameters = new ArrayList<>();
    private Integer timeout;
    private boolean requireConfirmation;
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
    public boolean isAlwaysInclude() { return alwaysInclude; }
    public boolean isAllowProactive() { return allowProactive; }
    public boolean isProactiveContext() { return proactiveContext; }
    public Map<String, Object> getProactiveContextArgs() { return proactiveContextArgs; }
    public String getProactiveContextDescription() { return proactiveContextDescription; }
    public ToolHandler getHandler() { return handler; }
}
