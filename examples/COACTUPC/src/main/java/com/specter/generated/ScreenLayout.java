package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for CoactupcProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout {

    public static final List<TerminalScreen.Field> FIELDS = List.of(
        new TerminalScreen.Field("TITLE01O", 0, 0, 80, TerminalScreen.FieldType.CENTER, null, false),
        new TerminalScreen.Field("TITLE02O", 1, 0, 80, TerminalScreen.FieldType.CENTER, null, false),
        new TerminalScreen.Field("PGMNAMEO", 2, 2, 12, TerminalScreen.FieldType.DISPLAY, "Program", false),
        new TerminalScreen.Field("TRNNAMEO", 2, 24, 12, TerminalScreen.FieldType.DISPLAY, "Trans", false),
        new TerminalScreen.Field("CURDATEO", 2, 50, 10, TerminalScreen.FieldType.DISPLAY, "Date", false),
        new TerminalScreen.Field("CURTIMEO", 2, 68, 10, TerminalScreen.FieldType.DISPLAY, "Time", false),
        new TerminalScreen.Field("AADDGRPO", 4, 2, 35, TerminalScreen.FieldType.DISPLAY, "Group", false),
        new TerminalScreen.Field("ACCTSIDC", 4, 42, 35, TerminalScreen.FieldType.DISPLAY, "Account ID", false),
        new TerminalScreen.Field("ACCTSIDO", 5, 2, 35, TerminalScreen.FieldType.DISPLAY, "Account ID", false),
        new TerminalScreen.Field("ACRCYCRO", 5, 42, 35, TerminalScreen.FieldType.DISPLAY, "Cycle Credit", false),
        new TerminalScreen.Field("AADDGRPI", 6, 30, 20, TerminalScreen.FieldType.INPUT, "Group", false),
        new TerminalScreen.Field("ACCTSIDI", 7, 30, 20, TerminalScreen.FieldType.INPUT, "Account ID", false),
        new TerminalScreen.Field("ACRCYCRI", 8, 30, 20, TerminalScreen.FieldType.INPUT, "Cycle Credit", false),
        new TerminalScreen.Field("ACRCYDBI", 9, 30, 20, TerminalScreen.FieldType.INPUT, "Cycle Debit", false),
        new TerminalScreen.Field("ACRDLIMI", 10, 30, 20, TerminalScreen.FieldType.INPUT, "Credit Limit", false),
        new TerminalScreen.Field("ACSADL1I", 11, 30, 20, TerminalScreen.FieldType.INPUT, "Address Line 1", false),
        new TerminalScreen.Field("ACSADL2I", 12, 30, 20, TerminalScreen.FieldType.INPUT, "Address Line 2", false),
        new TerminalScreen.Field("ACSCITYI", 13, 30, 20, TerminalScreen.FieldType.INPUT, "City", false),
        new TerminalScreen.Field("ACSCTRYI", 14, 30, 20, TerminalScreen.FieldType.INPUT, "Country", false),
        new TerminalScreen.Field("ACSEFTCI", 15, 30, 20, TerminalScreen.FieldType.INPUT, "EFT Account", false),
        new TerminalScreen.Field("ACSFNAMI", 16, 30, 20, TerminalScreen.FieldType.INPUT, "First Name", false),
        new TerminalScreen.Field("ACSGOVTI", 17, 30, 20, TerminalScreen.FieldType.INPUT, "Govt ID", false),
        new TerminalScreen.Field("ACSHLIMI", 18, 30, 20, TerminalScreen.FieldType.INPUT, "Cash Limit", false),
        new TerminalScreen.Field("ACSLNAMI", 19, 30, 20, TerminalScreen.FieldType.INPUT, "Last Name", false),
        new TerminalScreen.Field("ACSMNAMI", 20, 30, 20, TerminalScreen.FieldType.INPUT, "Middle Name", false),
        new TerminalScreen.Field("ERRMSGO", 21, 2, 76, TerminalScreen.FieldType.MESSAGE, null, false),
        new TerminalScreen.Field("INFOMSGO", 22, 2, 76, TerminalScreen.FieldType.MESSAGE, null, false)
    );
}
