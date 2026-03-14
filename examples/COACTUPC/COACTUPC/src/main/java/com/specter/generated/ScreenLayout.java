package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for CoactupcProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout {

    public static final List<BmsScreen.Field> FIELDS = List.of(
        // Row 0-1: Titles
        new BmsScreen.Field("TITLE01O", 0, 0, 80, BmsScreen.FieldType.CENTER, null, false),
        new BmsScreen.Field("TITLE02O", 1, 0, 80, BmsScreen.FieldType.CENTER, null, false),
        // Row 2: Program info
        new BmsScreen.Field("PGMNAMEO", 2, 2, 12, BmsScreen.FieldType.DISPLAY, "Program", false),
        new BmsScreen.Field("TRNNAMEO", 2, 24, 12, BmsScreen.FieldType.DISPLAY, "Trans", false),
        new BmsScreen.Field("CURDATEO", 2, 50, 10, BmsScreen.FieldType.DISPLAY, "Date", false),
        new BmsScreen.Field("CURTIMEO", 2, 68, 10, BmsScreen.FieldType.DISPLAY, "Time", false),
        // Row 4: Account search
        new BmsScreen.Field("ACCTSIDI", 4, 18, 20, BmsScreen.FieldType.INPUT, "Account ID", false),
        new BmsScreen.Field("AADDGRPI", 4, 55, 20, BmsScreen.FieldType.INPUT, "Group", false),
        // Row 6-7: Customer name
        new BmsScreen.Field("ACSFNAMI", 6, 18, 20, BmsScreen.FieldType.INPUT, "First Name", false),
        new BmsScreen.Field("ACSLNAMI", 6, 55, 20, BmsScreen.FieldType.INPUT, "Last Name", false),
        new BmsScreen.Field("ACSMNAMI", 7, 18, 20, BmsScreen.FieldType.INPUT, "Middle Name", false),
        // Row 9-11: Address
        new BmsScreen.Field("ACSADL1I", 9, 18, 40, BmsScreen.FieldType.INPUT, "Address Line 1", false),
        new BmsScreen.Field("ACSADL2I", 10, 18, 40, BmsScreen.FieldType.INPUT, "Address Line 2", false),
        new BmsScreen.Field("ACSCITYI", 11, 18, 20, BmsScreen.FieldType.INPUT, "City", false),
        new BmsScreen.Field("ACSCTRYI", 11, 55, 20, BmsScreen.FieldType.INPUT, "Country", false),
        // Row 13-14: Financial
        new BmsScreen.Field("ACRDLIMI", 13, 18, 18, BmsScreen.FieldType.INPUT, "Credit Limit", false),
        new BmsScreen.Field("ACSHLIMI", 13, 55, 18, BmsScreen.FieldType.INPUT, "Cash Limit", false),
        new BmsScreen.Field("ACRCYCRI", 14, 18, 18, BmsScreen.FieldType.INPUT, "Cycle Credit", false),
        new BmsScreen.Field("ACRCYDBI", 14, 55, 18, BmsScreen.FieldType.INPUT, "Cycle Debit", false),
        // Row 16: Other
        new BmsScreen.Field("ACSEFTCI", 16, 18, 20, BmsScreen.FieldType.INPUT, "EFT Account", false),
        new BmsScreen.Field("ACSGOVTI", 16, 55, 20, BmsScreen.FieldType.INPUT, "Govt ID", false),
        // Row 21-22: Messages
        new BmsScreen.Field("ERRMSGO", 21, 2, 76, BmsScreen.FieldType.MESSAGE, null, false),
        new BmsScreen.Field("INFOMSGO", 22, 2, 76, BmsScreen.FieldType.MESSAGE, null, false)
    );
}
