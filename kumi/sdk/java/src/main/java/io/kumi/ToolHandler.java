package io.kumi;

/**
 * Functional interface for tool execution callbacks.
 */
@FunctionalInterface
public interface ToolHandler {
    String handle(ToolArguments args);
}
