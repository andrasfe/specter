package com.specter.generated;

import java.io.IOException;
import java.util.List;

/**
 * Common interface for BMS screen renderers.
 *
 * <p>Implementations include {@link BmsScreen} (Lanterna interactive TUI)
 * and {@link HeadlessScreen} (plain-text stdin/stdout).
 */
public interface CicsScreen extends AutoCloseable {

    enum FieldType { CENTER, DISPLAY, INPUT, MESSAGE }

    record Field(String name, int row, int col, int width,
                 FieldType type, String label, boolean masked) {}

    /** Render output fields from program state. */
    void sendMap(ProgramState state) throws IOException;

    /** Block until an action key; returns the EIBAID value. */
    String waitForAction() throws IOException;

    /** Populate state with collected input values. */
    void receiveMap(ProgramState state);

    /** Display plain text (SEND TEXT). */
    void sendText(ProgramState state, String text) throws IOException;

    /** Show a transfer-control message. */
    void showXctl(String programName) throws IOException;

    @Override
    void close() throws IOException;
}
