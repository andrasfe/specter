package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for CoactupcProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout {

    public static final List<CicsScreen.Field> FIELDS = List.of(
        new CicsScreen.Field("TITLE01O", 0, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("TITLE02O", 1, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("PGMNAMEO", 2, 2, 12, CicsScreen.FieldType.DISPLAY, "Program", false),
        new CicsScreen.Field("TRNNAMEO", 2, 24, 12, CicsScreen.FieldType.DISPLAY, "Trans", false),
        new CicsScreen.Field("CURDATEO", 2, 50, 10, CicsScreen.FieldType.DISPLAY, "Date", false),
        new CicsScreen.Field("CURTIMEO", 2, 68, 10, CicsScreen.FieldType.DISPLAY, "Time", false),
        new CicsScreen.Field("ACCTSIDO", 4, 2, 35, CicsScreen.FieldType.DISPLAY, "Account ID", false),
        new CicsScreen.Field("ACSTTUSO", 4, 42, 35, CicsScreen.FieldType.DISPLAY, "Status", false),
        new CicsScreen.Field("ACRDLIMO", 5, 2, 35, CicsScreen.FieldType.DISPLAY, "Credit Limit", false),
        new CicsScreen.Field("ACURBALO", 5, 42, 35, CicsScreen.FieldType.DISPLAY, "Current Balance", false),
        new CicsScreen.Field("ACCTSIDI", 6, 30, 20, CicsScreen.FieldType.INPUT, "Account ID", false),
        new CicsScreen.Field("ACSTTUSI", 7, 30, 20, CicsScreen.FieldType.INPUT, "Status", false),
        new CicsScreen.Field("ACRDLIMI", 8, 30, 20, CicsScreen.FieldType.INPUT, "Credit Limit", false),
        new CicsScreen.Field("ACSHLIMI", 9, 30, 20, CicsScreen.FieldType.INPUT, "Cash Limit", false),
        new CicsScreen.Field("ACRCYCRI", 10, 30, 20, CicsScreen.FieldType.INPUT, "Cycle Credit", false),
        new CicsScreen.Field("ACRCYDBI", 11, 30, 20, CicsScreen.FieldType.INPUT, "Cycle Debit", false),
        new CicsScreen.Field("OPNYEARI", 12, 30, 20, CicsScreen.FieldType.INPUT, "Open Year", false),
        new CicsScreen.Field("OPNMONI", 13, 30, 20, CicsScreen.FieldType.INPUT, "Open Month", false),
        new CicsScreen.Field("OPNDAYI", 14, 30, 20, CicsScreen.FieldType.INPUT, "Open Day", false),
        new CicsScreen.Field("EXPYEARI", 15, 30, 20, CicsScreen.FieldType.INPUT, "Exp Year", false),
        new CicsScreen.Field("EXPMONI", 16, 30, 20, CicsScreen.FieldType.INPUT, "Exp Month", false),
        new CicsScreen.Field("EXPDAYI", 17, 30, 20, CicsScreen.FieldType.INPUT, "Exp Day", false),
        new CicsScreen.Field("RISYEARI", 18, 30, 20, CicsScreen.FieldType.INPUT, "Reissue Year", false),
        new CicsScreen.Field("RISMONI", 19, 30, 20, CicsScreen.FieldType.INPUT, "Reissue Month", false),
        new CicsScreen.Field("RISDAYI", 20, 30, 20, CicsScreen.FieldType.INPUT, "Reissue Day", false),
        new CicsScreen.Field("ERRMSGO", 21, 2, 76, CicsScreen.FieldType.MESSAGE, null, false),
        new CicsScreen.Field("INFOMSGO", 22, 2, 76, CicsScreen.FieldType.MESSAGE, null, false)
    );
}
