package io.yumi;

/**
 * Functional interface for tool execution callbacks.
 */
@FunctionalInterface
public interface ToolHandler {
    String handle(ToolArguments args);
}
