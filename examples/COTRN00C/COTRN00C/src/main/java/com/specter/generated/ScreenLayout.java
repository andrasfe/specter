package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cotrn00cProgram.
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
        new CicsScreen.Field("TRNIDINO", 4, 2, 35, CicsScreen.FieldType.DISPLAY, "Trnidin", false),
        new CicsScreen.Field("SEL0001I", 5, 30, 20, CicsScreen.FieldType.INPUT, "Sel0001", false),
        new CicsScreen.Field("TRNID01I", 6, 30, 20, CicsScreen.FieldType.INPUT, "Trnid01", false),
        new CicsScreen.Field("SEL0002I", 7, 30, 20, CicsScreen.FieldType.INPUT, "Sel0002", false),
        new CicsScreen.Field("TRNID02I", 8, 30, 20, CicsScreen.FieldType.INPUT, "Trnid02", false),
        new CicsScreen.Field("SEL0003I", 9, 30, 20, CicsScreen.FieldType.INPUT, "Sel0003", false),
        new CicsScreen.Field("TRNID03I", 10, 30, 20, CicsScreen.FieldType.INPUT, "Trnid03", false),
        new CicsScreen.Field("SEL0004I", 11, 30, 20, CicsScreen.FieldType.INPUT, "Sel0004", false),
        new CicsScreen.Field("TRNID04I", 12, 30, 20, CicsScreen.FieldType.INPUT, "Trnid04", false),
        new CicsScreen.Field("SEL0005I", 13, 30, 20, CicsScreen.FieldType.INPUT, "Sel0005", false),
        new CicsScreen.Field("TRNID05I", 14, 30, 20, CicsScreen.FieldType.INPUT, "Trnid05", false),
        new CicsScreen.Field("SEL0006I", 15, 30, 20, CicsScreen.FieldType.INPUT, "Sel0006", false),
        new CicsScreen.Field("TRNID06I", 16, 30, 20, CicsScreen.FieldType.INPUT, "Trnid06", false),
        new CicsScreen.Field("SEL0007I", 17, 30, 20, CicsScreen.FieldType.INPUT, "Sel0007", false),
        new CicsScreen.Field("TRNID07I", 18, 30, 20, CicsScreen.FieldType.INPUT, "Trnid07", false),
        new CicsScreen.Field("SEL0008I", 19, 30, 20, CicsScreen.FieldType.INPUT, "Sel0008", false),
        new CicsScreen.Field("ERRMSGO", 21, 2, 76, CicsScreen.FieldType.MESSAGE, null, false)
    );
}
