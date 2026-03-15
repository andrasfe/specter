"""Terminal UI templates for CICS BMS screen emulation.

Templates for rendering 3270-style screens using either the Lanterna library
(interactive TUI) or a headless plain-text mode (stdin/stdout).  Both modes
share a common ``CicsScreen`` interface and are driven by the same
``TerminalMain`` entrypoint with pseudo-conversational CICS flow.
"""

XCTL_SIGNAL_JAVA = """\
package {package_name};

/**
 * Thrown by {{@link TerminalStubExecutor}} when the program issues
 * EXEC CICS XCTL PROGRAM — signals a transfer of control to
 * another CICS program.  The {{@link MultiProgramRunner}} catches
 * this and routes to the target program.
 */
public class XctlSignal extends RuntimeException {{
    private static final long serialVersionUID = 1L;

    public final String targetProgram;

    public XctlSignal(String targetProgram) {{
        super("XCTL to " + targetProgram);
        this.targetProgram = targetProgram;
    }}
}}
"""

CICS_RETURN_SIGNAL_JAVA = """\
package {package_name};

/**
 * Thrown by {{@link TerminalStubExecutor}} when the program issues
 * EXEC CICS RETURN TRANSID — signals end of a pseudo-conversational
 * turn.  The {{@link TerminalMain}} loop catches this and waits for
 * the next user action before re-invoking the program.
 */
public class CicsReturnSignal extends RuntimeException {{
    public final boolean hasTransid;

    public CicsReturnSignal(boolean hasTransid) {{
        super("CICS RETURN");
        this.hasTransid = hasTransid;
    }}
}}
"""

TERMINAL_SCREEN_JAVA = """\
package {package_name};

import java.io.IOException;
import java.util.List;

/**
 * Common interface for BMS screen renderers.
 *
 * <p>Implementations include {{@link BmsScreen}} (Lanterna interactive TUI)
 * and {{@link HeadlessScreen}} (plain-text stdin/stdout).
 */
public interface CicsScreen extends AutoCloseable {{

    enum FieldType {{ CENTER, DISPLAY, INPUT, MESSAGE }}

    record Field(String name, int row, int col, int width,
                 FieldType type, String label, boolean masked) {{}}

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
}}
"""

HEADLESS_SCREEN_JAVA = """\
package {package_name};

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
 *   <li>{{@code FIELDNAME=value}} — set an input field</li>
 *   <li>{{@code ENTER}} — submit (DFHENTER)</li>
 *   <li>{{@code F3}}/{{@code PF3}} — PF3 key (DFHPF3)</li>
 *   <li>{{@code F5}}/{{@code PF5}} — PF5 key (DFHPF5)</li>
 *   <li>{{@code F12}}/{{@code PF12}} — PF12 key (DFHPF12)</li>
 *   <li>{{@code CLEAR}} — clear key (DFHCLEAR)</li>
 *   <li>Empty line — same as ENTER</li>
 * </ul>
 */
public class HeadlessScreen implements CicsScreen {{

    private final List<CicsScreen.Field> fields;
    private final Map<String, String> inputValues = new LinkedHashMap<>();
    private final BufferedReader reader;
    private final PrintStream out;

    public HeadlessScreen(List<CicsScreen.Field> fields) {{
        this(fields, System.in, System.out);
    }}

    public HeadlessScreen(List<CicsScreen.Field> fields,
                          InputStream in, PrintStream out) {{
        this.fields = fields;
        this.reader = new BufferedReader(new InputStreamReader(in));
        this.out = out;
    }}

    @Override
    public void sendMap(ProgramState state) throws IOException {{
        // Pre-populate input fields from corresponding -O output values
        for (CicsScreen.Field field : fields) {{
            if (field.type() == CicsScreen.FieldType.INPUT
                    && field.name().endsWith("I")) {{
                String outName = field.name().substring(
                        0, field.name().length() - 1) + "O";
                if (state.containsKey(outName)) {{
                    String v = String.valueOf(state.get(outName));
                    if (!"null".equals(v) && !v.isBlank()) {{
                        inputValues.put(field.name(), v);
                    }}
                }}
            }}
        }}

        // Render into 80x24 character buffer
        char[][] buf = new char[24][80];
        for (char[] row : buf) Arrays.fill(row, ' ');

        for (CicsScreen.Field field : fields) {{
            String val = state.containsKey(field.name())
                    ? String.valueOf(state.get(field.name())) : "";
            if ("null".equals(val)) val = "";

            switch (field.type()) {{
                case CENTER -> {{
                    int offset = Math.max(0, (80 - val.length()) / 2);
                    place(buf, field.row(), offset, val, 80 - offset);
                }}
                case DISPLAY -> {{
                    if (field.label() != null && !field.label().isEmpty()) {{
                        String lbl = field.label() + ":";
                        place(buf, field.row(), field.col(), lbl, 80 - field.col());
                        place(buf, field.row(),
                                field.col() + lbl.length() + 1, val,
                                80 - field.col() - lbl.length() - 1);
                    }} else {{
                        place(buf, field.row(), field.col(), val,
                                80 - field.col());
                    }}
                }}
                case INPUT -> {{
                    if (field.label() != null) {{
                        int lc = Math.max(0, field.col()
                                - field.label().length() - 2);
                        place(buf, field.row(), lc,
                                field.label() + ":", 80 - lc);
                    }}
                    String cur = inputValues.getOrDefault(field.name(), "");
                    String display = field.masked()
                            ? "*".repeat(cur.length()) : cur;
                    String padded = "[" + (display
                            + "_".repeat(field.width()))
                            .substring(0, field.width()) + "]";
                    place(buf, field.row(), field.col() - 1,
                            padded, 80 - field.col() + 1);
                }}
                case MESSAGE -> {{
                    if (!val.isBlank()) {{
                        place(buf, field.row(), field.col(), val,
                                80 - field.col());
                    }}
                }}
            }}
        }}

        // Output
        out.println("+" + "-".repeat(80) + "+");
        for (char[] row : buf) {{
            out.println("|" + new String(row) + "|");
        }}
        out.println("+" + "-".repeat(80) + "+");
        out.println("[Enter=Submit  F3=Exit  F12=Search]");
        out.flush();
    }}

    @Override
    public String waitForAction() throws IOException {{
        while (true) {{
            out.print("> ");
            out.flush();
            String line = reader.readLine();
            if (line == null) {{
                return "DFHPF3"; // EOF → exit
            }}
            line = line.trim();

            // Empty line = ENTER
            if (line.isEmpty()) {{
                return "DFHENTER";
            }}

            // Action keys
            String aid = mapAction(line);
            if (aid != null) {{
                return aid;
            }}

            // Field assignment: NAME=VALUE
            int eq = line.indexOf('=');
            if (eq > 0) {{
                String fname = line.substring(0, eq).trim().toUpperCase();
                String fval = line.substring(eq + 1).trim();
                inputValues.put(fname, fval);
                continue;
            }}

            out.println("? Unknown input: " + line);
            out.println("  Use FIELD=value, ENTER, F3, F12, or empty line");
        }}
    }}

    @Override
    public void receiveMap(ProgramState state) {{
        for (Map.Entry<String, String> entry : inputValues.entrySet()) {{
            state.put(entry.getKey(), entry.getValue());
        }}
        state.put("WS-RESP-CD", 0);
        state.put("WS-REAS-CD", 0);
    }}

    @Override
    public void sendText(ProgramState state, String text) throws IOException {{
        String msg = String.valueOf(state.getOrDefault("WS-MESSAGE", text));
        out.println("+" + "-".repeat(80) + "+");
        out.println("| " + msg);
        out.println("+" + "-".repeat(80) + "+");
        out.flush();
    }}

    @Override
    public void showXctl(String programName) throws IOException {{
        out.println("[XCTL -> " + programName + "]");
        out.flush();
    }}

    @Override
    public void close() {{
        // Nothing to close for headless mode
    }}

    // -- Helpers --------------------------------------------------------------

    private static void place(char[][] buf, int row, int col,
                              String text, int maxLen) {{
        if (row < 0 || row >= buf.length || col < 0 || col >= buf[0].length)
            return;
        int len = Math.min(text.length(), maxLen);
        for (int i = 0; i < len && col + i < buf[0].length; i++) {{
            buf[row][col + i] = text.charAt(i);
        }}
    }}

    private static String mapAction(String input) {{
        return switch (input.toUpperCase()) {{
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
        }};
    }}
}}
"""

BMS_SCREEN_JAVA = """\
package {package_name};

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
 * {{@link ProgramState}} and collecting input field values from the user.
 * Supports Enter, F3, and Tab key handling.
 */
public class BmsScreen implements CicsScreen {{

    private final Screen screen;
    private final TextGraphics graphics;
    private final List<CicsScreen.Field> fields;
    private final Map<String, String> inputValues = new LinkedHashMap<>();
    private int activeFieldIndex = 0;

    public BmsScreen(List<CicsScreen.Field> fields) throws IOException {{
        this.fields = fields;
        Terminal terminal = new DefaultTerminalFactory()
                .setInitialTerminalSize(new TerminalSize(80, 24))
                .createTerminal();
        this.screen = new TerminalScreen(terminal);
        this.screen.startScreen();
        this.screen.setCursorPosition(null);
        this.graphics = screen.newTextGraphics();
    }}

    @Override
    public void sendMap(ProgramState state) throws IOException {{
        // Pre-populate input fields from corresponding output values.
        for (CicsScreen.Field field : fields) {{
            if (field.type() == CicsScreen.FieldType.INPUT && field.name().endsWith("I")) {{
                String outName = field.name().substring(0, field.name().length() - 1) + "O";
                if (state.containsKey(outName)) {{
                    String v = String.valueOf(state.get(outName));
                    if (!"null".equals(v) && !v.isBlank()) {{
                        inputValues.put(field.name(), v);
                    }}
                }}
            }}
        }}

        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);

        // Fill background
        for (int r = 0; r < 24; r++) {{
            graphics.putString(0, r, " ".repeat(80));
        }}

        for (CicsScreen.Field field : fields) {{
            String val = state.containsKey(field.name())
                    ? String.valueOf(state.get(field.name()))
                    : "";
            if (val.equals("null")) val = "";

            switch (field.type()) {{
                case CENTER -> {{
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.enableModifiers(SGR.BOLD);
                    int offset = Math.max(0, (80 - val.length()) / 2);
                    graphics.putString(offset, field.row(), val);
                    graphics.disableModifiers(SGR.BOLD);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                }}
                case DISPLAY -> {{
                    if (field.label() != null && !field.label().isEmpty()) {{
                        graphics.setForegroundColor(TextColor.ANSI.WHITE);
                        graphics.enableModifiers(SGR.BOLD);
                        graphics.putString(field.col(), field.row(), field.label() + ":");
                        graphics.disableModifiers(SGR.BOLD);
                        graphics.setForegroundColor(TextColor.ANSI.GREEN);
                        graphics.putString(
                                field.col() + field.label().length() + 2,
                                field.row(), val);
                    }} else {{
                        graphics.putString(field.col(), field.row(), val);
                    }}
                }}
                case INPUT -> {{
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.enableModifiers(SGR.BOLD);
                    int labelCol = Math.max(0, field.col() - (field.label() != null
                            ? field.label().length() + 2 : 0));
                    if (field.label() != null) {{
                        graphics.putString(labelCol, field.row(),
                                field.label() + ":");
                    }}
                    graphics.disableModifiers(SGR.BOLD);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                    String cur = inputValues.getOrDefault(field.name(), "");
                    String display = field.masked()
                            ? "*".repeat(cur.length()) : cur;
                    String padded = (display + "_".repeat(field.width()))
                            .substring(0, field.width());
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.putString(field.col(), field.row(), padded);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                }}
                case MESSAGE -> {{
                    if (!val.isBlank()) {{
                        graphics.setForegroundColor(TextColor.ANSI.RED);
                        graphics.enableModifiers(SGR.BOLD);
                        graphics.putString(field.col(), field.row(), val);
                        graphics.disableModifiers(SGR.BOLD);
                        graphics.setForegroundColor(TextColor.ANSI.GREEN);
                    }}
                }}
            }}
        }}

        // Status bar
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.setBackgroundColor(TextColor.ANSI.BLUE);
        graphics.putString(0, 23, " ".repeat(80));
        graphics.putString(1, 23, "Enter=Submit   F3=Exit   Tab=Next Field");
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        graphics.setForegroundColor(TextColor.ANSI.GREEN);

        screen.refresh(Screen.RefreshType.COMPLETE);
    }}

    /**
     * Block until the user presses Enter or a PF key.
     * During the wait the user can type into input fields and Tab between them.
     *
     * @return the EIBAID value corresponding to the key pressed
     */
    @Override
    public String waitForAction() throws IOException {{
        List<CicsScreen.Field> inputFields = fields.stream()
                .filter(f -> f.type() == CicsScreen.FieldType.INPUT)
                .toList();

        if (inputFields.isEmpty()) {{
            // No input fields — just wait for a key
            while (true) {{
                KeyStroke key = screen.readInput();
                String aid = mapKeyToEibaid(key);
                if (aid != null) return aid;
            }}
        }}

        activeFieldIndex = 0;
        StringBuilder currentInput = new StringBuilder(
                inputValues.getOrDefault(
                        inputFields.get(activeFieldIndex).name(), ""));
        positionCursor(inputFields.get(activeFieldIndex), currentInput.length());
        screen.refresh(Screen.RefreshType.COMPLETE);

        while (true) {{
            KeyStroke key = screen.readInput();

            // Check for action keys
            String aid = mapKeyToEibaid(key);
            if (aid != null) {{
                // Save current field
                inputValues.put(inputFields.get(activeFieldIndex).name(),
                        currentInput.toString().trim());
                return aid;
            }}

            if (key.getKeyType() == KeyType.Tab
                    || key.getKeyType() == KeyType.ReverseTab) {{
                // Save current and move to next/prev field
                inputValues.put(inputFields.get(activeFieldIndex).name(),
                        currentInput.toString().trim());
                if (key.getKeyType() == KeyType.Tab) {{
                    activeFieldIndex =
                            (activeFieldIndex + 1) % inputFields.size();
                }} else {{
                    activeFieldIndex = (activeFieldIndex - 1
                            + inputFields.size()) % inputFields.size();
                }}
                currentInput = new StringBuilder(
                        inputValues.getOrDefault(
                                inputFields.get(activeFieldIndex).name(), ""));
                positionCursor(inputFields.get(activeFieldIndex),
                        currentInput.length());
                screen.refresh(Screen.RefreshType.COMPLETE);
                continue;
            }}

            if (key.getKeyType() == KeyType.Backspace) {{
                if (currentInput.length() > 0) {{
                    currentInput.deleteCharAt(currentInput.length() - 1);
                    redrawInputField(inputFields.get(activeFieldIndex),
                            currentInput.toString());
                    positionCursor(inputFields.get(activeFieldIndex),
                            currentInput.length());
                    screen.refresh(Screen.RefreshType.COMPLETE);
                }}
                continue;
            }}

            if (key.getKeyType() == KeyType.Character) {{
                CicsScreen.Field f = inputFields.get(activeFieldIndex);
                if (currentInput.length() < f.width()) {{
                    currentInput.append(key.getCharacter());
                    redrawInputField(f, currentInput.toString());
                    positionCursor(f, currentInput.length());
                    screen.refresh(Screen.RefreshType.COMPLETE);
                }}
            }}
        }}
    }}

    @Override
    public void receiveMap(ProgramState state) {{
        for (Map.Entry<String, String> entry : inputValues.entrySet()) {{
            state.put(entry.getKey(), entry.getValue());
        }}
        // Set RESP to 0 (normal)
        state.put("WS-RESP-CD", 0);
        state.put("WS-REAS-CD", 0);
    }}

    @Override
    public void sendText(ProgramState state, String text) throws IOException {{
        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        for (int r = 0; r < 24; r++) {{
            graphics.putString(0, r, " ".repeat(80));
        }}
        String msg = String.valueOf(state.getOrDefault("WS-MESSAGE", text));
        graphics.putString(2, 10, msg);
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.setBackgroundColor(TextColor.ANSI.BLUE);
        graphics.putString(0, 23, " ".repeat(80));
        graphics.putString(1, 23, "Press any key to exit...");
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        screen.refresh(Screen.RefreshType.COMPLETE);
        screen.readInput();
    }}

    @Override
    public void showXctl(String programName) throws IOException {{
        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.YELLOW);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);
        for (int r = 0; r < 24; r++) {{
            graphics.putString(0, r, " ".repeat(80));
        }}
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
    }}

    @Override
    public void close() throws IOException {{
        screen.stopScreen();
    }}

    // -- Private helpers ---------------------------------------------------

    private String mapKeyToEibaid(KeyStroke key) {{
        return switch (key.getKeyType()) {{
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
        }};
    }}

    private void positionCursor(CicsScreen.Field field, int offset) {{
        screen.setCursorPosition(
                new com.googlecode.lanterna.TerminalPosition(
                        field.col() + Math.min(offset, field.width() - 1),
                        field.row()));
    }}

    private void redrawInputField(CicsScreen.Field field, String value) {{
        String display = field.masked()
                ? "*".repeat(value.length()) : value;
        String padded = (display + "_".repeat(field.width()))
                .substring(0, field.width());
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.putString(field.col(), field.row(), padded);
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
    }}
}}
"""

TERMINAL_STUB_EXECUTOR_JAVA = """\
package {package_name};

import java.io.IOException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Stub executor that intercepts CICS screen operations and delegates
 * them to a {{@link CicsScreen}} for rendering (Lanterna or headless).
 *
 * <p>Non-screen operations (READ, WRITE, etc.) are forwarded to the
 * wrapped {{@link DefaultStubExecutor}} so that FIFO stub queues still
 * work for business logic.
 */
public class TerminalStubExecutor extends DefaultStubExecutor {{

    private static final Pattern SEND_MAP_PAT =
            Pattern.compile("SEND\\\\s+MAP", Pattern.CASE_INSENSITIVE);
    private static final Pattern RECEIVE_MAP_PAT =
            Pattern.compile("RECEIVE\\\\s+MAP", Pattern.CASE_INSENSITIVE);
    private static final Pattern SEND_TEXT_PAT =
            Pattern.compile("SEND\\\\s+TEXT", Pattern.CASE_INSENSITIVE);
    private static final Pattern XCTL_PAT =
            Pattern.compile("XCTL\\\\s+PROGRAM\\\\s*\\\\(?'?([^)']+)'?\\\\)?",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern RETURN_TRANSID_PAT =
            Pattern.compile("RETURN\\\\s+TRANSID", Pattern.CASE_INSENSITIVE);
    private static final Pattern RETURN_PAT =
            Pattern.compile("RETURN\\\\s+END", Pattern.CASE_INSENSITIVE);
    private static final Pattern ASSIGN_PAT =
            Pattern.compile(
                    "ASSIGN\\\\s+(\\\\w+)\\\\s*\\\\(([^)]+)\\\\)",
                    Pattern.CASE_INSENSITIVE);

    private final CicsScreen bmsScreen;

    public TerminalStubExecutor(CicsScreen bmsScreen) {{
        this.bmsScreen = bmsScreen;
    }}

    @Override
    public void dummyExec(ProgramState state, String type, String rawText) {{
        if (!"CICS".equalsIgnoreCase(type)) {{
            super.dummyExec(state, type, rawText);
            return;
        }}

        try {{
            if (SEND_MAP_PAT.matcher(rawText).find()) {{
                bmsScreen.sendMap(state);
                state.execs.add(java.util.Map.of("op", "SEND MAP"));
            }} else if (RECEIVE_MAP_PAT.matcher(rawText).find()) {{
                bmsScreen.receiveMap(state);
                state.execs.add(java.util.Map.of("op", "RECEIVE MAP"));
            }} else if (SEND_TEXT_PAT.matcher(rawText).find()) {{
                bmsScreen.sendText(state, rawText);
                state.execs.add(java.util.Map.of("op", "SEND TEXT"));
            }} else if (XCTL_PAT.matcher(rawText).find()) {{
                Matcher m = XCTL_PAT.matcher(rawText);
                m.find();
                String program = m.group(1).trim();
                // Resolve variable reference
                if (program.contains("-") || program.equals(program.toUpperCase())) {{
                    Object resolved = state.get(program);
                    if (resolved != null && !String.valueOf(resolved).isBlank()) {{
                        program = String.valueOf(resolved).trim();
                    }}
                }}
                state.execs.add(java.util.Map.of("op", "XCTL:" + program));
                throw new XctlSignal(program);
            }} else if (ASSIGN_PAT.matcher(rawText).find()) {{
                Matcher m = ASSIGN_PAT.matcher(rawText);
                while (m.find()) {{
                    String keyword = m.group(1).toUpperCase();
                    String target = m.group(2).trim();
                    // Strip OF qualification
                    int ofIdx = target.toUpperCase().indexOf(" OF ");
                    if (ofIdx > 0) target = target.substring(0, ofIdx).trim();
                    switch (keyword) {{
                        case "APPLID" -> state.put(target, "CICSA001");
                        case "SYSID" -> state.put(target, "CICS");
                        default -> state.put(target, keyword);
                    }}
                }}
                state.execs.add(java.util.Map.of("op", "ASSIGN"));
            }} else {{
                super.dummyExec(state, type, rawText);
            }}
        }} catch (IOException e) {{
            throw new RuntimeException("Screen I/O error", e);
        }}
    }}

    @Override
    public void cicsRead(ProgramState state, String dataset, String ridfld,
                         String intoRecord, String respVar, String resp2Var) {{
        state.put(respVar, 0);
        state.put(resp2Var, 0);

        // Populate mock record data based on the target record type.
        if ("CARD-XREF-RECORD".equals(intoRecord)) {{
            String acctId = String.valueOf(state.get(ridfld)).trim();
            state.put("XREF-CUST-ID", acctId);
            state.put("XREF-CARD-NUM", "4111111111111111");
        }} else if ("ACCOUNT-RECORD".equals(intoRecord)) {{
            String acctId = String.valueOf(state.get(ridfld)).trim();
            state.put("ACCT-ID", acctId);
            state.put("ACCT-ACTIVE-STATUS", "Y");
            state.put("ACCT-CURR-BAL", 1500.00);
            state.put("ACCT-CREDIT-LIMIT", 5000.00);
            state.put("ACCT-CASH-CREDIT-LIMIT", 1000.00);
            state.put("ACCT-CURR-CYC-CREDIT", 200.00);
            state.put("ACCT-CURR-CYC-DEBIT", 100.00);
            state.put("ACCT-OPEN-DATE", "2020-01-15");
            state.put("ACCT-EXPIRAION-DATE", "2027-12-31");
            state.put("ACCT-REISSUE-DATE", "2024-01-15");
            state.put("ACCT-GROUP-ID", "RETAIL");
        }} else if ("CUSTOMER-RECORD".equals(intoRecord)) {{
            Object custId = state.get("WS-CARD-RID-CUST-ID");
            state.put("CUST-ID", custId != null ? custId : "00001");
            state.put("CUST-FIRST-NAME", "John");
            state.put("CUST-MIDDLE-NAME", "M");
            state.put("CUST-LAST-NAME", "Smith");
            state.put("CUST-SSN", "123456789");
            state.put("CUST-DOB-YYYY-MM-DD", "1985-06-15");
            state.put("CUST-FICO-CREDIT-SCORE", 750);
            state.put("CUST-ADDR-LINE-1", "123 Main Street");
            state.put("CUST-ADDR-LINE-2", "Apt 4B");
            state.put("CUST-ADDR-LINE-3", "Springfield");
            state.put("CUST-ADDR-STATE-CD", "IL");
            state.put("CUST-ADDR-COUNTRY-CD", "US");
            state.put("CUST-ADDR-ZIP", "62701");
            state.put("CUST-PHONE-NUM-1", "(217)555-1234");
            state.put("CUST-PHONE-NUM-2", "(217)555-5678");
            state.put("CUST-GOVT-ISSUED-ID", "IL-DL-12345");
            state.put("CUST-EFT-ACCOUNT-ID", "9876543210");
            state.put("CUST-PRI-CARD-HOLDER-IND", "Y");
        }} else {{
            // Security or other file — mirror password for auth checks
            Object pwd = state.get("WS-USER-PWD");
            if (pwd != null) {{
                state.put("SEC-USR-PWD", pwd);
            }}
            state.putIfAbsent("SEC-USR-TYPE", "U");
        }}

        state.execs.add(java.util.Map.of("op",
                "READ DATASET(" + dataset + ") [simulated]"));
    }}

    @Override
    public void cicsReturn(ProgramState state, boolean hasTransid) {{
        state.execs.add(java.util.Map.of("op", "CICS RETURN"));
        throw new CicsReturnSignal(hasTransid);
    }}
}}
"""

TERMINAL_MAIN_JAVA = """\
package {package_name};

import java.io.IOException;
import java.util.List;

/**
 * Interactive terminal entrypoint for {{@link {program_class_name}}}.
 *
 * <p>Implements the CICS pseudo-conversational loop:
 * <ol>
 *   <li>Run program (first call: EIBCALEN=0)</li>
 *   <li>Program sends BMS screen, issues RETURN TRANSID</li>
 *   <li>Wait for user action (Enter, PF3, etc.)</li>
 *   <li>Set EIBAID, EIBCALEN>0, re-run program</li>
 *   <li>Repeat until program exits or user presses F3</li>
 * </ol>
 *
 * <p>Usage: {{@code java -cp app.jar {package_name}.TerminalMain}}
 */
public class TerminalMain {{

    public static void main(String[] args) throws IOException {{
        List<CicsScreen.Field> layout = ScreenLayout.FIELDS;
        boolean headless = args.length > 0 && "--headless".equals(args[0]);
        CicsScreen screen = headless
                ? new HeadlessScreen(layout)
                : new BmsScreen(layout);
        TerminalStubExecutor stubs = new TerminalStubExecutor(screen);

        ProgramState state = new ProgramState();
        state.put("EIBCALEN", 0);
{initial_state_lines}
        try {{
            boolean running = true;
            while (running) {{
                try {{
                    {program_class_name} program =
                            new {program_class_name}(stubs);
                    program.run(state);
                    running = false; // Normal completion
                }} catch (CicsReturnSignal ret) {{
                    if (!ret.hasTransid) {{
                        running = false;
                    }} else {{
                        // Pseudo-conversational: wait for user action
                        String eibaid = screen.waitForAction();
                        // Preserve state across turns, update CICS fields
                        state.put("EIBAID", eibaid);
                        state.put("EIBCALEN", 1);
                        // Map EIBAID to CCARD-AID flags (CSSTRPFY copybook)
                        state.put("CCARD-AID-ENTER", "DFHENTER".equals(eibaid));
                        state.put("CCARD-AID-PFK03", "DFHPF3".equals(eibaid));
                        state.put("CCARD-AID-PFK05", "DFHPF5".equals(eibaid));
                        state.put("CCARD-AID-PFK12", "DFHPF12".equals(eibaid));
                        state.abended = false;
                        state.trace.clear();
                        state.execs.clear();
                    }}
                }} catch (GobackSignal g) {{
                    running = false;
                }}
            }}
        }} finally {{
            screen.close();
        }}
    }}
}}
"""

SCREEN_LAYOUT_JAVA = """\
package {package_name};

import java.util.List;

/**
 * BMS screen layout for {program_class_name}.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {{@link BmsScreen}} rendering.
 */
public class {screen_layout_class_name} {{

    public static final List<CicsScreen.Field> FIELDS = List.of(
{field_entries}
    );
}}
"""

MULTI_PROGRAM_RUNNER_JAVA = """\
package {package_name};

import java.io.IOException;
import java.util.*;
import java.util.function.Function;

/**
 * Multi-program CICS XCTL router.
 *
 * <p>Manages a registry of {{@link CicsProgram}} factory functions and
 * handles XCTL transfers between them.  Each program runs in its own
 * pseudo-conversational loop until it either completes normally,
 * issues GOBACK, or transfers control via {{@link XctlSignal}}.
 *
 * <p>Program factories accept a {{@link StubExecutor}} so the runner
 * can wire a {{@link TerminalStubExecutor}} backed by the correct
 * screen for each program.
 *
 * <p>Usage:
 * <pre>{{@code
 *   new MultiProgramRunner(false).run();
 * }}</pre>
 */
public class MultiProgramRunner {{

    private final Map<String, Function<StubExecutor, CicsProgram>> registry = new LinkedHashMap<>();
    private final boolean headless;
    private String firstProgram;

    public MultiProgramRunner(boolean headless) {{
        this.headless = headless;
{program_registry_entries}
    }}

    public void run() throws IOException {{
        String currentProgram = firstProgram;
        ProgramState state = new ProgramState();
        state.put("EIBCALEN", 0);
        CicsScreen screen = null;

        while (currentProgram != null) {{
            Function<StubExecutor, CicsProgram> factory = registry.get(currentProgram);
            if (factory == null) {{
                System.err.println("Unknown program: " + currentProgram);
                break;
            }}

            // Probe the layout by creating a temporary instance
            CicsProgram probe = factory.apply(new DefaultStubExecutor());
            List<CicsScreen.Field> layout = probe.screenLayout();

            // Set up screen for this program's layout
            if (screen != null) {{
                try {{ screen.close(); }} catch (IOException ignored) {{}}
            }}
            if (!layout.isEmpty()) {{
                screen = headless ? new HeadlessScreen(layout) : new BmsScreen(layout);
            }} else {{
                screen = null;
            }}

            // Wire TerminalStubExecutor for this screen
            StubExecutor stubs = screen != null
                ? new TerminalStubExecutor(screen)
                : new DefaultStubExecutor();

            // Create actual program instance with terminal stubs
            CicsProgram prog = factory.apply(stubs);

            // Seed per-program CICS state (LIT-*, CCDA-*, WS-TRANID, etc.)
            prog.initState(state);
            state.abended = false;
            state.trace.clear();
            state.execs.clear();

            // Run pseudo-conversational loop for this program
            currentProgram = runProgram(factory, stubs, state, screen);
        }}
        if (screen != null) {{
            try {{ screen.close(); }} catch (IOException ignored) {{}}
        }}
    }}

    private String runProgram(Function<StubExecutor, CicsProgram> factory,
                              StubExecutor stubs,
                              ProgramState state, CicsScreen screen) {{
        while (true) {{
            try {{
                // Create fresh program instance per turn (like real CICS)
                CicsProgram prog = factory.apply(stubs);
                prog.run(state);
                return null; // Normal completion
            }} catch (CicsReturnSignal ret) {{
                if (!ret.hasTransid) return null;
                if (screen == null) return null;
                // Pseudo-conversational: wait for user action
                try {{
                    String eibaid = screen.waitForAction();
                    state.put("EIBAID", eibaid);
                    state.put("EIBCALEN", 1);
                    state.put("CCARD-AID-ENTER", "DFHENTER".equals(eibaid));
                    state.put("CCARD-AID-PFK03", "DFHPF3".equals(eibaid));
                    state.put("CCARD-AID-PFK05", "DFHPF5".equals(eibaid));
                    state.put("CCARD-AID-PFK07", "DFHPF7".equals(eibaid));
                    state.put("CCARD-AID-PFK08", "DFHPF8".equals(eibaid));
                    state.put("CCARD-AID-PFK12", "DFHPF12".equals(eibaid));
                    state.abended = false;
                    state.trace.clear();
                    state.execs.clear();
                }} catch (IOException e) {{
                    System.err.println("Screen I/O error: " + e.getMessage());
                    return null;
                }}
            }} catch (XctlSignal xctl) {{
                return xctl.targetProgram; // Transfer to target
            }} catch (GobackSignal g) {{
                return null;
            }}
        }}
    }}

    public static void main(String[] args) throws IOException {{
        boolean headless = args.length > 0 && "--headless".equals(args[0]);
        new MultiProgramRunner(headless).run();
    }}
}}
"""
