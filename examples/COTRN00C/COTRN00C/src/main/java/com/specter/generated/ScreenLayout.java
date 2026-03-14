package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cotrn00cProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout {

    public static final List<BmsScreen.Field> FIELDS = List.of(
        new BmsScreen.Field("TITLE01O", 0, 0, 80, BmsScreen.FieldType.CENTER, null, false),
        new BmsScreen.Field("TITLE02O", 1, 0, 80, BmsScreen.FieldType.CENTER, null, false),
        new BmsScreen.Field("PGMNAMEO", 2, 2, 12, BmsScreen.FieldType.DISPLAY, "Pgmname", false),
        new BmsScreen.Field("TRNNAMEO", 2, 24, 12, BmsScreen.FieldType.DISPLAY, "Trnname", false),
        new BmsScreen.Field("CURDATEO", 2, 50, 10, BmsScreen.FieldType.DISPLAY, "Curdate", false),
        new BmsScreen.Field("CURTIMEO", 2, 68, 10, BmsScreen.FieldType.DISPLAY, "Curtime", false),
        new BmsScreen.Field("TRNIDINO", 4, 2, 35, BmsScreen.FieldType.DISPLAY, "Trnidin", false),
        new BmsScreen.Field("PAGENUMI", 5, 30, 20, BmsScreen.FieldType.INPUT, "Pagenum", false),
        new BmsScreen.Field("SEL0001I", 6, 30, 20, BmsScreen.FieldType.INPUT, "Sel0001", false),
        new BmsScreen.Field("SEL0002I", 7, 30, 20, BmsScreen.FieldType.INPUT, "Sel0002", false),
        new BmsScreen.Field("SEL0003I", 8, 30, 20, BmsScreen.FieldType.INPUT, "Sel0003", false),
        new BmsScreen.Field("SEL0004I", 9, 30, 20, BmsScreen.FieldType.INPUT, "Sel0004", false),
        new BmsScreen.Field("SEL0005I", 10, 30, 20, BmsScreen.FieldType.INPUT, "Sel0005", false),
        new BmsScreen.Field("SEL0006I", 11, 30, 20, BmsScreen.FieldType.INPUT, "Sel0006", false),
        new BmsScreen.Field("SEL0007I", 12, 30, 20, BmsScreen.FieldType.INPUT, "Sel0007", false),
        new BmsScreen.Field("SEL0008I", 13, 30, 20, BmsScreen.FieldType.INPUT, "Sel0008", false),
        new BmsScreen.Field("SEL0009I", 14, 30, 20, BmsScreen.FieldType.INPUT, "Sel0009", false),
        new BmsScreen.Field("SEL0010I", 15, 30, 20, BmsScreen.FieldType.INPUT, "Sel0010", false),
        new BmsScreen.Field("TAMT001I", 16, 30, 20, BmsScreen.FieldType.INPUT, "Tamt001", false),
        new BmsScreen.Field("TAMT002I", 17, 30, 20, BmsScreen.FieldType.INPUT, "Tamt002", false),
        new BmsScreen.Field("TAMT003I", 18, 30, 20, BmsScreen.FieldType.INPUT, "Tamt003", false),
        new BmsScreen.Field("TAMT004I", 19, 30, 20, BmsScreen.FieldType.INPUT, "Tamt004", false),
        new BmsScreen.Field("ERRMSGO", 21, 2, 76, BmsScreen.FieldType.MESSAGE, null, false)
    );
}
