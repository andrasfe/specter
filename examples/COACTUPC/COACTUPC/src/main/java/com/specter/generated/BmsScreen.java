package com.specter.generated;

import com.googlecode.lanterna.SGR;
import com.googlecode.lanterna.TerminalSize;
import com.googlecode.lanterna.TextColor;
import com.googlecode.lanterna.graphics.TextGraphics;
import com.googlecode.lanterna.input.KeyStroke;
import com.googlecode.lanterna.input.KeyType;
import com.googlecode.lanterna.screen.Screen;
import com.googlecode.lanterna.screen.TerminalScreen;
import com.googlecode.lanterna.terminal.DefaultTerminalFactory;
import com.googlecode.lanterna.terminal.Terminal;

import java.io.IOException;
import java.util.*;

/**
 * Lanterna-based BMS screen renderer.
 *
 * <p>Emulates a 3270 terminal by rendering output fields from
 * {@link ProgramState} and collecting input field values from the user.
 * Supports Enter, F3, and Tab key handling.
 */
public class BmsScreen implements AutoCloseable {

    public enum FieldType { CENTER, DISPLAY, INPUT, MESSAGE }

    public record Field(String name, int row, int col, int width,
                        FieldType type, String label, boolean masked) {}

    private final Screen screen;
    private final TextGraphics graphics;
    private final List<Field> fields;
    private final Map<String, String> inputValues = new LinkedHashMap<>();
    private int activeFieldIndex = 0;

    public BmsScreen(List<Field> fields) throws IOException {
        this.fields = fields;
        Terminal terminal = new DefaultTerminalFactory()
                .setInitialTerminalSize(new TerminalSize(80, 24))
                .createTerminal();
        this.screen = new TerminalScreen(terminal);
        this.screen.startScreen();
        this.screen.setCursorPosition(null);
        this.graphics = screen.newTextGraphics();
    }

    /** Render output fields from program state onto the screen. */
    public void sendMap(ProgramState state) throws IOException {
        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);

        // Fill background
        for (int r = 0; r < 24; r++) {
            graphics.putString(0, r, " ".repeat(80));
        }

        for (Field field : fields) {
            String val = state.containsKey(field.name)
                    ? String.valueOf(state.get(field.name))
                    : "";
            if (val.equals("null")) val = "";

            switch (field.type) {
                case CENTER -> {
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.enableModifiers(SGR.BOLD);
                    int offset = Math.max(0, (80 - val.length()) / 2);
                    graphics.putString(offset, field.row, val);
                    graphics.disableModifiers(SGR.BOLD);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                }
                case DISPLAY -> {
                    if (field.label != null && !field.label.isEmpty()) {
                        graphics.setForegroundColor(TextColor.ANSI.WHITE);
                        graphics.enableModifiers(SGR.BOLD);
                        graphics.putString(field.col, field.row, field.label + ":");
                        graphics.disableModifiers(SGR.BOLD);
                        graphics.setForegroundColor(TextColor.ANSI.GREEN);
                        graphics.putString(
                                field.col + field.label.length() + 2,
                                field.row, val);
                    } else {
                        graphics.putString(field.col, field.row, val);
                    }
                }
                case INPUT -> {
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.enableModifiers(SGR.BOLD);
                    int labelCol = Math.max(0, field.col - (field.label != null
                            ? field.label.length() + 2 : 0));
                    if (field.label != null) {
                        graphics.putString(labelCol, field.row,
                                field.label + ":");
                    }
                    graphics.disableModifiers(SGR.BOLD);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                    String cur = inputValues.getOrDefault(field.name, "");
                    String display = field.masked
                            ? "*".repeat(cur.length()) : cur;
                    String padded = (display + "_".repeat(field.width))
                            .substring(0, field.width);
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.putString(field.col, field.row, padded);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                }
                case MESSAGE -> {
                    if (!val.isBlank()) {
                        graphics.setForegroundColor(TextColor.ANSI.RED);
                        graphics.enableModifiers(SGR.BOLD);
                        graphics.putString(field.col, field.row, val);
                        graphics.disableModifiers(SGR.BOLD);
                        graphics.setForegroundColor(TextColor.ANSI.GREEN);
                    }
                }
            }
        }

        // Status bar
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.setBackgroundColor(TextColor.ANSI.BLUE);
        graphics.putString(0, 23, " ".repeat(80));
        graphics.putString(1, 23, "Enter=Submit   F3=Exit   Tab=Next Field");
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        graphics.setForegroundColor(TextColor.ANSI.GREEN);

        screen.refresh(Screen.RefreshType.COMPLETE);
    }

    /**
     * Block until the user presses Enter or a PF key.
     * During the wait the user can type into input fields and Tab between them.
     *
     * @return the EIBAID value corresponding to the key pressed
     */
    public String waitForAction() throws IOException {
        List<Field> inputFields = fields.stream()
                .filter(f -> f.type == FieldType.INPUT)
                .toList();

        if (inputFields.isEmpty()) {
            // No input fields — just wait for a key
            while (true) {
                KeyStroke key = screen.readInput();
                String aid = mapKeyToEibaid(key);
                if (aid != null) return aid;
            }
        }

        activeFieldIndex = 0;
        StringBuilder currentInput = new StringBuilder(
                inputValues.getOrDefault(
                        inputFields.get(activeFieldIndex).name, ""));
        positionCursor(inputFields.get(activeFieldIndex), currentInput.length());
        screen.refresh(Screen.RefreshType.COMPLETE);

        while (true) {
            KeyStroke key = screen.readInput();

            // Check for action keys
            String aid = mapKeyToEibaid(key);
            if (aid != null) {
                // Save current field
                inputValues.put(inputFields.get(activeFieldIndex).name,
                        currentInput.toString().trim());
                return aid;
            }

            if (key.getKeyType() == KeyType.Tab
                    || key.getKeyType() == KeyType.ReverseTab) {
                // Save current and move to next/prev field
                inputValues.put(inputFields.get(activeFieldIndex).name,
                        currentInput.toString().trim());
                if (key.getKeyType() == KeyType.Tab) {
                    activeFieldIndex =
                            (activeFieldIndex + 1) % inputFields.size();
                } else {
                    activeFieldIndex = (activeFieldIndex - 1
                            + inputFields.size()) % inputFields.size();
                }
                currentInput = new StringBuilder(
                        inputValues.getOrDefault(
                                inputFields.get(activeFieldIndex).name, ""));
                positionCursor(inputFields.get(activeFieldIndex),
                        currentInput.length());
                screen.refresh(Screen.RefreshType.COMPLETE);
                continue;
            }

            if (key.getKeyType() == KeyType.Backspace) {
                if (currentInput.length() > 0) {
                    currentInput.deleteCharAt(currentInput.length() - 1);
                    redrawInputField(inputFields.get(activeFieldIndex),
                            currentInput.toString());
                    positionCursor(inputFields.get(activeFieldIndex),
                            currentInput.length());
                    screen.refresh(Screen.RefreshType.COMPLETE);
                }
                continue;
            }

            if (key.getKeyType() == KeyType.Character) {
                Field f = inputFields.get(activeFieldIndex);
                if (currentInput.length() < f.width) {
                    currentInput.append(key.getCharacter());
                    redrawInputField(f, currentInput.toString());
                    positionCursor(f, currentInput.length());
                    screen.refresh(Screen.RefreshType.COMPLETE);
                }
            }
        }
    }

    /** Populate state with collected input values. */
    public void receiveMap(ProgramState state) {
        for (Map.Entry<String, String> entry : inputValues.entrySet()) {
            state.put(entry.getKey(), entry.getValue());
        }
        // Set RESP to 0 (normal)
        state.put("WS-RESP-CD", 0);
        state.put("WS-REAS-CD", 0);
    }

    /** Display plain text (SEND TEXT). */
    public void sendText(ProgramState state, String text) throws IOException {
        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        for (int r = 0; r < 24; r++) {
            graphics.putString(0, r, " ".repeat(80));
        }
        String msg = String.valueOf(state.getOrDefault("WS-MESSAGE", text));
        graphics.putString(2, 10, msg);
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.setBackgroundColor(TextColor.ANSI.BLUE);
        graphics.putString(0, 23, " ".repeat(80));
        graphics.putString(1, 23, "Press any key to exit...");
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        screen.refresh(Screen.RefreshType.COMPLETE);
        screen.readInput();
    }

    /** Show a transfer-control message. */
    public void showXctl(String programName) throws IOException {
        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.YELLOW);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        for (int r = 0; r < 24; r++) {
            graphics.putString(0, r, " ".repeat(80));
        }
        graphics.putString(2, 10, "Transferring to program: " + programName);
        graphics.putString(2, 12, "(In a full CICS environment this would "
                + "load " + programName + ")");
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.setBackgroundColor(TextColor.ANSI.BLUE);
        graphics.putString(0, 23, " ".repeat(80));
        graphics.putString(1, 23, "Press any key to exit...");
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        screen.refresh(Screen.RefreshType.COMPLETE);
        screen.readInput();
    }

    @Override
    public void close() throws IOException {
        screen.stopScreen();
    }

    // -- Private helpers ---------------------------------------------------

    private String mapKeyToEibaid(KeyStroke key) {
        return switch (key.getKeyType()) {
            case Enter -> "DFHENTER";
            case F3 -> "DFHPF3";
            case F1 -> "DFHPF1";
            case F2 -> "DFHPF2";
            case F4 -> "DFHPF4";
            case F5 -> "DFHPF5";
            case F6 -> "DFHPF6";
            case F7 -> "DFHPF7";
            case F8 -> "DFHPF8";
            case F9 -> "DFHPF9";
            case F10 -> "DFHPF10";
            case F11 -> "DFHPF11";
            case F12 -> "DFHPF12";
            case Escape -> "DFHCLEAR";
            default -> null;
        };
    }

    private void positionCursor(Field field, int offset) {
        screen.setCursorPosition(
                new com.googlecode.lanterna.TerminalPosition(
                        field.col + Math.min(offset, field.width - 1),
                        field.row));
    }

    private void redrawInputField(Field field, String value) {
        String display = field.masked
                ? "*".repeat(value.length()) : value;
        String padded = (display + "_".repeat(field.width))
                .substring(0, field.width);
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.putString(field.col, field.row, padded);
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
    }
}
