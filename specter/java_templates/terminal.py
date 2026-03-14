"""Lanterna-based terminal UI templates for CICS BMS screen emulation.

Templates for rendering 3270-style screens using the Lanterna library,
handling pseudo-conversational CICS flow (SEND MAP / RECEIVE MAP / RETURN
TRANSID), and providing an interactive terminal entrypoint.
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
public class BmsScreen implements AutoCloseable {{

    public enum FieldType {{ CENTER, DISPLAY, INPUT, MESSAGE }}

    public record Field(String name, int row, int col, int width,
                        FieldType type, String label, boolean masked) {{}}

    private final Screen screen;
    private final TextGraphics graphics;
    private final List<Field> fields;
    private final Map<String, String> inputValues = new LinkedHashMap<>();
    private int activeFieldIndex = 0;

    public BmsScreen(List<Field> fields) throws IOException {{
        this.fields = fields;
        Terminal terminal = new DefaultTerminalFactory()
                .setInitialTerminalSize(new TerminalSize(80, 24))
                .createTerminal();
        this.screen = new TerminalScreen(terminal);
        this.screen.startScreen();
        this.screen.setCursorPosition(null);
        this.graphics = screen.newTextGraphics();
    }}

    /** Render output fields from program state onto the screen. */
    public void sendMap(ProgramState state) throws IOException {{
        screen.clear();
        graphics.setForegroundColor(TextColor.ANSI.GREEN);
        graphics.setBackgroundColor(TextColor.ANSI.BLACK);

        // Fill background
        for (int r = 0; r < 24; r++) {{
            graphics.putString(0, r, " ".repeat(80));
        }}

        for (Field field : fields) {{
            String val = state.containsKey(field.name)
                    ? String.valueOf(state.get(field.name))
                    : "";
            if (val.equals("null")) val = "";

            switch (field.type) {{
                case CENTER -> {{
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.enableModifiers(SGR.BOLD);
                    int offset = Math.max(0, (80 - val.length()) / 2);
                    graphics.putString(offset, field.row, val);
                    graphics.disableModifiers(SGR.BOLD);
                    graphics.setForegroundColor(TextColor.ANSI.GREEN);
                }}
                case DISPLAY -> {{
                    if (field.label != null && !field.label.isEmpty()) {{
                        graphics.setForegroundColor(TextColor.ANSI.WHITE);
                        graphics.enableModifiers(SGR.BOLD);
                        graphics.putString(field.col, field.row, field.label + ":");
                        graphics.disableModifiers(SGR.BOLD);
                        graphics.setForegroundColor(TextColor.ANSI.GREEN);
                        graphics.putString(
                                field.col + field.label.length() + 2,
                                field.row, val);
                    }} else {{
                        graphics.putString(field.col, field.row, val);
                    }}
                }}
                case INPUT -> {{
                    graphics.setForegroundColor(TextColor.ANSI.WHITE);
                    graphics.enableModifiers(SGR.BOLD);
                    int labelCol = Math.max(0, field.col - (field.label != null
                            ? field.label.length() + 2 : 0));
                    if (field.label != null) {{
                        graphics.putString(labelCol, field.row,
                                field.label + ":");
                    }}
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
                }}
                case MESSAGE -> {{
                    if (!val.isBlank()) {{
                        graphics.setForegroundColor(TextColor.ANSI.RED);
                        graphics.enableModifiers(SGR.BOLD);
                        graphics.putString(field.col, field.row, val);
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
    public String waitForAction() throws IOException {{
        List<Field> inputFields = fields.stream()
                .filter(f -> f.type == FieldType.INPUT)
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
                        inputFields.get(activeFieldIndex).name, ""));
        positionCursor(inputFields.get(activeFieldIndex), currentInput.length());
        screen.refresh(Screen.RefreshType.COMPLETE);

        while (true) {{
            KeyStroke key = screen.readInput();

            // Check for action keys
            String aid = mapKeyToEibaid(key);
            if (aid != null) {{
                // Save current field
                inputValues.put(inputFields.get(activeFieldIndex).name,
                        currentInput.toString().trim());
                return aid;
            }}

            if (key.getKeyType() == KeyType.Tab
                    || key.getKeyType() == KeyType.ReverseTab) {{
                // Save current and move to next/prev field
                inputValues.put(inputFields.get(activeFieldIndex).name,
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
                                inputFields.get(activeFieldIndex).name, ""));
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
                Field f = inputFields.get(activeFieldIndex);
                if (currentInput.length() < f.width) {{
                    currentInput.append(key.getCharacter());
                    redrawInputField(f, currentInput.toString());
                    positionCursor(f, currentInput.length());
                    screen.refresh(Screen.RefreshType.COMPLETE);
                }}
            }}
        }}
    }}

    /** Populate state with collected input values. */
    public void receiveMap(ProgramState state) {{
        for (Map.Entry<String, String> entry : inputValues.entrySet()) {{
            state.put(entry.getKey(), entry.getValue());
        }}
        // Set RESP to 0 (normal)
        state.put("WS-RESP-CD", 0);
        state.put("WS-REAS-CD", 0);
    }}

    /** Display plain text (SEND TEXT). */
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

    /** Show a transfer-control message. */
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

    private void positionCursor(Field field, int offset) {{
        screen.setCursorPosition(
                new com.googlecode.lanterna.TerminalPosition(
                        field.col + Math.min(offset, field.width - 1),
                        field.row));
    }}

    private void redrawInputField(Field field, String value) {{
        String display = field.masked
                ? "*".repeat(value.length()) : value;
        String padded = (display + "_".repeat(field.width))
                .substring(0, field.width);
        graphics.setForegroundColor(TextColor.ANSI.WHITE);
        graphics.putString(field.col, field.row, padded);
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
 * them to a {{@link BmsScreen}} for Lanterna terminal rendering.
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

    private final BmsScreen bmsScreen;

    public TerminalStubExecutor(BmsScreen bmsScreen) {{
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
                bmsScreen.showXctl(program);
                state.execs.add(java.util.Map.of("op", "XCTL:" + program));
                throw new GobackSignal();
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
        // In interactive terminal mode there is no real file.
        // Simulate a successful read: echo the entered password back so
        // credential checks pass, and set RESP=0.
        state.put(respVar, 0);
        state.put(resp2Var, 0);
        // Mirror user-entered password into the security record field
        // so the password comparison succeeds.
        Object pwd = state.get("WS-USER-PWD");
        if (pwd != null) {{
            state.put("SEC-USR-PWD", pwd);
        }}
        // Default user type to regular (not admin)
        state.putIfAbsent("SEC-USR-TYPE", "U");
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
        List<BmsScreen.Field> layout = ScreenLayout.FIELDS;
        BmsScreen bmsScreen = new BmsScreen(layout);
        TerminalStubExecutor stubs = new TerminalStubExecutor(bmsScreen);

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
                        String eibaid = bmsScreen.waitForAction();
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
            bmsScreen.close();
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
public class ScreenLayout {{

    public static final List<BmsScreen.Field> FIELDS = List.of(
{field_entries}
    );
}}
"""
