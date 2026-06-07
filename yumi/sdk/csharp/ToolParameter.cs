namespace Yumi;

/// <summary>
/// Describes a single parameter in a tool's schema.
/// </summary>
public sealed class ToolParameter
{
    public string Name { get; }
    public string Type { get; }
    public string Description { get; }
    public bool Required { get; }

    public ToolParameter(string name, string type, string description, bool required = true)
    {
        Name = name;
        Type = type;
        Description = description;
        Required = required;
    }
}
