using System.Collections.Generic;

namespace Kumi;

/// <summary>
/// Builder-style configuration for registering a tool with <see cref="KumiAgent"/>.
/// </summary>
public sealed class RegisterOptions
{
    public string? Name { get; private set; }
    public string? Description { get; private set; }
    public List<ToolParameter> Parameters { get; private set; } = new();
    public int? Timeout { get; private set; }
    public bool RequireConfirmation { get; private set; }
    public bool AlwaysInclude { get; private set; }
    public bool AllowProactive { get; private set; }
    public bool ProactiveContext { get; private set; }
    public Dictionary<string, object>? ProactiveContextArgs { get; private set; }
    public string? ProactiveContextDescription { get; private set; }
    public ToolHandler? Handler { get; private set; }

    public RegisterOptions SetName(string name) { Name = name; return this; }
    public RegisterOptions SetDescription(string desc) { Description = desc; return this; }
    public RegisterOptions SetParameters(params ToolParameter[] pars) { Parameters = new List<ToolParameter>(pars); return this; }
    public RegisterOptions SetTimeout(int seconds) { Timeout = seconds; return this; }
    public RegisterOptions SetRequireConfirmation(bool v) { RequireConfirmation = v; return this; }
    public RegisterOptions SetAlwaysInclude(bool v) { AlwaysInclude = v; return this; }
    public RegisterOptions SetAllowProactive(bool v) { AllowProactive = v; return this; }
    public RegisterOptions SetProactiveContext(bool v) { ProactiveContext = v; return this; }
    public RegisterOptions SetProactiveContextArgs(Dictionary<string, object> args) { ProactiveContextArgs = args; return this; }
    public RegisterOptions SetProactiveContextDescription(string description) { ProactiveContextDescription = description; return this; }
    public RegisterOptions SetHandler(ToolHandler h) { Handler = h; return this; }
}
