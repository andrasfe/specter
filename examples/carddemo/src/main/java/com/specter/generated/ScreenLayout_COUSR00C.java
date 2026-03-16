package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cousr00cProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout_COUSR00C {

    public static final List<CicsScreen.Field> FIELDS = List.of(
        new CicsScreen.Field("TITLE01O", 0, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("TITLE02O", 1, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("PGMNAMEO", 2, 2, 12, CicsScreen.FieldType.DISPLAY, "Program", false),
        new CicsScreen.Field("TRNNAMEO", 2, 24, 12, CicsScreen.FieldType.DISPLAY, "Trans", false),
        new CicsScreen.Field("CURDATEO", 2, 50, 10, CicsScreen.FieldType.DISPLAY, "Date", false),
        new CicsScreen.Field("CURTIMEO", 2, 68, 10, CicsScreen.FieldType.DISPLAY, "Time", false),
        new CicsScreen.Field("USRIDINO", 4, 2, 35, CicsScreen.FieldType.DISPLAY, "Usridin", false),
        new CicsScreen.Field("SEL0001I", 5, 30, 20, CicsScreen.FieldType.INPUT, "Sel0001", false),
        new CicsScreen.Field("USRID01I", 6, 30, 20, CicsScreen.FieldType.INPUT, "Usrid01", false),
        new CicsScreen.Field("SEL0002I", 7, 30, 20, CicsScreen.FieldType.INPUT, "Sel0002", false),
        new CicsScreen.Field("USRID02I", 8, 30, 20, CicsScreen.FieldType.INPUT, "Usrid02", false),
        new CicsScreen.Field("SEL0003I", 9, 30, 20, CicsScreen.FieldType.INPUT, "Sel0003", false),
        new CicsScreen.Field("USRID03I", 10, 30, 20, CicsScreen.FieldType.INPUT, "Usrid03", false),
        new CicsScreen.Field("SEL0004I", 11, 30, 20, CicsScreen.FieldType.INPUT, "Sel0004", false),
        new CicsScreen.Field("USRID04I", 12, 30, 20, CicsScreen.FieldType.INPUT, "Usrid04", false),
        new CicsScreen.Field("SEL0005I", 13, 30, 20, CicsScreen.FieldType.INPUT, "Sel0005", false),
        new CicsScreen.Field("USRID05I", 14, 30, 20, CicsScreen.FieldType.INPUT, "Usrid05", false),
        new CicsScreen.Field("SEL0006I", 15, 30, 20, CicsScreen.FieldType.INPUT, "Sel0006", false),
        new CicsScreen.Field("USRID06I", 16, 30, 20, CicsScreen.FieldType.INPUT, "Usrid06", false),
        new CicsScreen.Field("SEL0007I", 17, 30, 20, CicsScreen.FieldType.INPUT, "Sel0007", false),
        new CicsScreen.Field("USRID07I", 18, 30, 20, CicsScreen.FieldType.INPUT, "Usrid07", false),
        new CicsScreen.Field("SEL0008I", 19, 30, 20, CicsScreen.FieldType.INPUT, "Sel0008", false),
        new CicsScreen.Field("ERRMSGO", 21, 2, 76, CicsScreen.FieldType.MESSAGE, null, false)
    );
}
