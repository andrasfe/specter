package com.specter.generated;

import java.io.*;
import java.util.*;

/**
 * Headless BMS screen renderer using plain-text stdin/stdout.
 *
 * <p>Renders screens as formatted 80-column text and reads input as
 * simple commands.  Useful for automated testing and environments
 * without a real terminal.
 *
 * <h3>Input protocol</h3>
 * <ul>
 *   <li>{@code FIELDNAME=value} — set an input field</li>
 *   <li>{@code ENTER} — submit (DFHENTER)</li>
 *   <li>{@code F3}/{@code PF3} — PF3 key (DFHPF3)</li>
 *   <li>{@code F5}/{@code PF5} — PF5 key (DFHPF5)</li>
 *   <li>{@code F12}/{@code PF12} — PF12 key (DFHPF12)</li>
 *   <li>{@code CLEAR} — clear key (DFHCLEAR)</li>
 *   <li>Empty line — same as ENTER</li>
 * </ul>
 */
public class HeadlessScreen implements CicsScreen {

    private final List<CicsScreen.Field> fields;
    private final Map<String, String> inputValues = new LinkedHashMap<>();
    private final BufferedReader reader;
    private final PrintStream out;

    public HeadlessScreen(List<CicsScreen.Field> fields) {
        this(fields, System.in, System.out);
    }

    public HeadlessScreen(List<CicsScreen.Field> fields,
                          InputStream in, PrintStream out) {
        this.fields = fields;
        this.reader = new BufferedReader(new InputStreamReader(in));
        this.out = out;
    }

    @Override
    public void sendMap(ProgramState state) throws IOException {
        // Pre-populate input fields from corresponding -O output values
        for (CicsScreen.Field field : fields) {
            if (field.type() == CicsScreen.FieldType.INPUT
                    && field.name().endsWith("I")) {
                String outName = field.name().substring(
                        0, field.name().length() - 1) + "O";
                if (state.containsKey(outName)) {
                    String v = String.valueOf(state.get(outName));
                    if (!"null".equals(v) && !v.isBlank()) {
                        inputValues.put(field.name(), v);
                    }
                }
            }
        }

        // Render into 80x24 character buffer
        char[][] buf = new char[24][80];
        for (char[] row : buf) Arrays.fill(row, ' ');

        for (CicsScreen.Field field : fields) {
            String val = state.containsKey(field.name())
                    ? String.valueOf(state.get(field.name())) : "";
            if ("null".equals(val)) val = "";

            switch (field.type()) {
                case CENTER -> {
                    int offset = Math.max(0, (80 - val.length()) / 2);
                    place(buf, field.row(), offset, val, 80 - offset);
                }
                case DISPLAY -> {
                    if (field.label() != null && !field.label().isEmpty()) {
                        String lbl = field.label() + ":";
                        place(buf, field.row(), field.col(), lbl, 80 - field.col());
                        place(buf, field.row(),
                                field.col() + lbl.length() + 1, val,
                                80 - field.col() - lbl.length() - 1);
                    } else {
                        place(buf, field.row(), field.col(), val,
                                80 - field.col());
                    }
                }
                case INPUT -> {
                    if (field.label() != null) {
                        int lc = Math.max(0, field.col()
                                - field.label().length() - 2);
                        place(buf, field.row(), lc,
                                field.label() + ":", 80 - lc);
                    }
                    String cur = inputValues.getOrDefault(field.name(), "");
                    String display = field.masked()
                            ? "*".repeat(cur.length()) : cur;
                    String padded = "[" + (display
                            + "_".repeat(field.width()))
                            .substring(0, field.width()) + "]";
                    place(buf, field.row(), field.col() - 1,
                            padded, 80 - field.col() + 1);
                }
                case MESSAGE -> {
                    if (!val.isBlank()) {
                        place(buf, field.row(), field.col(), val,
                                80 - field.col());
                    }
                }
            }
        }

        // Output
        out.println("+" + "-".repeat(80) + "+");
        for (char[] row : buf) {
            out.println("|" + new String(row) + "|");
        }
        out.println("+" + "-".repeat(80) + "+");
        out.println("[Enter=Submit  F3=Exit  F12=Search]");
        out.flush();
    }

    @Override
    public String waitForAction() throws IOException {
        while (true) {
            out.print("> ");
            out.flush();
            String line = reader.readLine();
            if (line == null) {
                return "DFHPF3"; // EOF → exit
            }
            line = line.trim();

            // Empty line = ENTER
            if (line.isEmpty()) {
                return "DFHENTER";
            }

            // Action keys
            String aid = mapAction(line);
            if (aid != null) {
                return aid;
            }

            // Field assignment: NAME=VALUE
            int eq = line.indexOf('=');
            if (eq > 0) {
                String fname = line.substring(0, eq).trim().toUpperCase();
                String fval = line.substring(eq + 1).trim();
                inputValues.put(fname, fval);
                continue;
            }

            out.println("? Unknown input: " + line);
            out.println("  Use FIELD=value, ENTER, F3, F12, or empty line");
        }
    }

    @Override
    public void receiveMap(ProgramState state) {
        for (Map.Entry<String, String> entry : inputValues.entrySet()) {
            state.put(entry.getKey(), entry.getValue());
        }
        state.put("WS-RESP-CD", 0);
        state.put("WS-REAS-CD", 0);
    }

    @Override
    public void sendText(ProgramState state, String text) throws IOException {
        String msg = String.valueOf(state.getOrDefault("WS-MESSAGE", text));
        out.println("+" + "-".repeat(80) + "+");
        out.println("| " + msg);
        out.println("+" + "-".repeat(80) + "+");
        out.flush();
    }

    @Override
    public void showXctl(String programName) throws IOException {
        out.println("[XCTL -> " + programName + "]");
        out.flush();
    }

    @Override
    public void close() {
        // Nothing to close for headless mode
    }

    // -- Helpers --------------------------------------------------------------

    private static void place(char[][] buf, int row, int col,
                              String text, int maxLen) {
        if (row < 0 || row >= buf.length || col < 0 || col >= buf[0].length)
            return;
        int len = Math.min(text.length(), maxLen);
        for (int i = 0; i < len && col + i < buf[0].length; i++) {
            buf[row][col + i] = text.charAt(i);
        }
    }

    private static String mapAction(String input) {
        return switch (input.toUpperCase()) {
            case "ENTER" -> "DFHENTER";
            case "F1",  "PF1"  -> "DFHPF1";
            case "F2",  "PF2"  -> "DFHPF2";
            case "F3",  "PF3"  -> "DFHPF3";
            case "F4",  "PF4"  -> "DFHPF4";
            case "F5",  "PF5"  -> "DFHPF5";
            case "F6",  "PF6"  -> "DFHPF6";
            case "F7",  "PF7"  -> "DFHPF7";
            case "F8",  "PF8"  -> "DFHPF8";
            case "F9",  "PF9"  -> "DFHPF9";
            case "F10", "PF10" -> "DFHPF10";
            case "F11", "PF11" -> "DFHPF11";
            case "F12", "PF12" -> "DFHPF12";
            case "CLEAR"       -> "DFHCLEAR";
            default -> null;
        };
    }
}
