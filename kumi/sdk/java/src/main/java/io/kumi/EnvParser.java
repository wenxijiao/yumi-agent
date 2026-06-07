package io.kumi;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Simple .env file parser. Sets values into System properties (not
 * System.getenv which is unmodifiable) unless the env var already exists.
 *
 * <p>Values are accessible via {@link EnvParser#getEnv(String)} which
 * checks both {@code System.getenv} and {@code System.getProperty}.</p>
 */
public final class EnvParser {
    private EnvParser() {}

    /**
     * Load a .env file. Existing environment variables and previously
     * loaded values are never overwritten.
     */
    public static void loadEnvFile(String filePath) {
        Path path = Path.of(filePath);
        if (!Files.isRegularFile(path)) return;

        try (BufferedReader reader = Files.newBufferedReader(path)) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                int eq = line.indexOf('=');
                if (eq < 0) continue;
                String key = line.substring(0, eq).trim();
                String value = line.substring(eq + 1).trim();
                if (value.length() >= 2) {
                    if ((value.startsWith("\"") && value.endsWith("\"")) ||
                        (value.startsWith("'") && value.endsWith("'"))) {
                        value = value.substring(1, value.length() - 1);
                    }
                }
                if (getEnv(key) == null || getEnv(key).isEmpty()) {
                    System.setProperty(key, value);
                }
            }
        } catch (IOException ignored) {
        }
    }

    /**
     * Read a configuration value: checks System.getenv first, then
     * System.getProperty (for values loaded from .env).
     */
    public static String getEnv(String key) {
        String v = System.getenv(key);
        if (v != null && !v.isEmpty()) return v;
        return System.getProperty(key);
    }

    public static String getEnv(String key, String fallback) {
        String v = getEnv(key);
        return (v != null && !v.isEmpty()) ? v : fallback;
    }
}
