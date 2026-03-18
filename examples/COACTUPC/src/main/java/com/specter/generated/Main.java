package com.specter.generated;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

/**
 * Docker / standalone entrypoint for {@link CoactupcProgram}.
 *
 * <p>Creates a {@link HikariDataSource} from {@link AppConfig},
 * optionally creates a JMS {@code ConnectionFactory}, wires a
 * {@link JdbcStubExecutor}, runs the program, and prints results.
 */
public class Main {

    public static void main(String[] args) {
        // Database connection pool
        HikariConfig hikari = new HikariConfig();
        hikari.setJdbcUrl(AppConfig.getDbUrl());
        hikari.setUsername(AppConfig.getDbUser());
        hikari.setPassword(AppConfig.getDbPassword());
        hikari.setMaximumPoolSize(5);
        HikariDataSource dataSource = new HikariDataSource(hikari);

        // JMS factory (nullable)
        Object jmsFactory = null;
        String jmsUrl = AppConfig.getJmsBrokerUrl();
        if (jmsUrl != null) {
            try {
                Class<?> factoryClass = Class.forName(
                    "org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory");
                jmsFactory = factoryClass
                    .getConstructor(String.class, String.class, String.class)
                    .newInstance(jmsUrl, AppConfig.getJmsUser(), AppConfig.getJmsPassword());
            } catch (Exception e) {
                System.err.println("JMS unavailable: " + e.getMessage());
            }
        }

        // Wire and run
        try (JdbcStubExecutor stubs = new JdbcStubExecutor(dataSource, jmsFactory)) {
            CoactupcProgram program = new CoactupcProgram(stubs);
            ProgramState result = program.run();

            // Print results
            System.out.println("=== Execution complete ===");
            System.out.println("Abended: " + result.abended);
            System.out.println("Paragraphs executed: " + result.trace.size());
            System.out.println("Trace: " + result.trace);
            if (!result.displays.isEmpty()) {
                System.out.println("Displays:");
                for (String d : result.displays) {
                    System.out.println("  " + d);
                }
            }
            if (!result.execs.isEmpty()) {
                System.out.println("EXEC operations: " + result.execs.size());
            }
            if (!result.calls.isEmpty()) {
                System.out.println("CALL operations: " + result.calls.size());
            }
        } catch (Exception e) {
            System.err.println("Execution error: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }

        dataSource.close();
    }
}
