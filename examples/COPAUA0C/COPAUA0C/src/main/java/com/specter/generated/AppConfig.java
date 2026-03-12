package com.specter.generated;

/**
 * Environment-variable-based configuration for database and JMS connections.
 *
 * <p>Reads {@code SPECTER_DB_URL}, {@code SPECTER_DB_USER},
 * {@code SPECTER_DB_PASSWORD}, and {@code SPECTER_JMS_URL} from the
 * environment with sensible localhost defaults.
 */
public final class AppConfig {

    private AppConfig() {
    }

    public static String getDbUrl() {
        return env("SPECTER_DB_URL", "jdbc:postgresql://localhost:5432/specter");
    }

    public static String getDbUser() {
        return env("SPECTER_DB_USER", "specter");
    }

    public static String getDbPassword() {
        return env("SPECTER_DB_PASSWORD", "specter");
    }

    /** Returns the JMS broker URL, or {@code null} if not configured. */
    public static String getJmsBrokerUrl() {
        return env("SPECTER_JMS_URL", null);
    }

    public static String getJmsUser() {
        return env("SPECTER_JMS_USER", "admin");
    }

    public static String getJmsPassword() {
        return env("SPECTER_JMS_PASSWORD", "admin");
    }

    private static String env(String key, String defaultValue) {
        String v = System.getenv(key);
        return (v != null && !v.isBlank()) ? v : defaultValue;
    }
}
