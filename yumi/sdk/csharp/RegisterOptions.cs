using System.Collections.Generic;

namespace Yumi;

/// <summary>
/// Builder-style configuration for registering a tool with <see cref="YumiAgent"/>.
/// </summary>
public sealed class RegisterOptions
{
    public string? Name { get; private set; }
    public string? Description { get; private set; }
    public List<ToolParameter> Parameters { get; private set; } = new();
    public int? Timeout { get; private set; }
    public bool RequireConfirmation { get; private set; }

    /// <summary>
    /// Exposure mode — "dynamic" (default), "pinned", or "autorun". Mapped onto
    /// the low-level flags below before the wire schema is built: "pinned" =>
    /// <see cref="AlwaysInclude"/>; "autorun" => <see cref="ProactiveContext"/>
    /// (plus <see cref="ContextArgs"/> / <see cref="ContextLabel"/>).
    /// </summary>
    public string Mode { get; private set; } = "dynamic";

    /// <summary>Fixed arguments for an "autorun" tool. Maps to <see cref="ProactiveContextArgs"/>.</summary>
    public Dictionary<string, object>? ContextArgs { get; private set; }

    /// <summary>Label shown when an "autorun" result is injected. Maps to <see cref="ProactiveContextDescription"/>.</summary>
    public string? ContextLabel { get; private set; }

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
    public RegisterOptions SetMode(string mode) { Mode = mode; return this; }
    public RegisterOptions SetContextArgs(Dictionary<string, object> args) { ContextArgs = args; return this; }
    public RegisterOptions SetContextLabel(string label) { ContextLabel = label; return this; }
    public RegisterOptions SetAlwaysInclude(bool v) { AlwaysInclude = v; return this; }
    public RegisterOptions SetAllowProactive(bool v) { AllowProactive = v; return this; }
    public RegisterOptions SetProactiveContext(bool v) { ProactiveContext = v; return this; }
    public RegisterOptions SetProactiveContextArgs(Dictionary<string, object> args) { ProactiveContextArgs = args; return this; }
    public RegisterOptions SetProactiveContextDescription(string description) { ProactiveContextDescription = description; return this; }
    public RegisterOptions SetHandler(ToolHandler h) { Handler = h; return this; }

    /// <summary>
    /// Map the <see cref="Mode"/> sugar onto the low-level wire flags. Called by
    /// <see cref="YumiAgent.Register"/> before the schema is built. Throws
    /// <see cref="System.ArgumentException"/> for an invalid mode.
    /// </summary>
    internal void ApplyMode()
    {
        switch (Mode)
        {
            case "pinned":
                AlwaysInclude = true;
                break;
            case "autorun":
                ProactiveContext = true;
                if (ContextArgs != null)
                    ProactiveContextArgs = ContextArgs;
                if (ContextLabel != null)
                    ProactiveContextDescription = ContextLabel;
                break;
            case "dynamic":
                break;
            default:
                throw new System.ArgumentException(
                    $"mode must be 'dynamic', 'pinned', or 'autorun'; got '{Mode}'", nameof(Mode));
        }
    }
}
