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
        new BmsScreen.Field("TRNIDINO", 4, 2, 40, BmsScreen.FieldType.DISPLAY, "Trnidin", false),
        new BmsScreen.Field("PAGENUMI", 10, 30, 20, BmsScreen.FieldType.INPUT, "Pagenum", false),
        new BmsScreen.Field("SEL0001I", 12, 30, 20, BmsScreen.FieldType.INPUT, "Sel0001", false),
        new BmsScreen.Field("SEL0002I", 14, 30, 20, BmsScreen.FieldType.INPUT, "Sel0002", false),
        new BmsScreen.Field("SEL0003I", 16, 30, 20, BmsScreen.FieldType.INPUT, "Sel0003", false),
        new BmsScreen.Field("SEL0004I", 18, 30, 20, BmsScreen.FieldType.INPUT, "Sel0004", false),
        new BmsScreen.Field("SEL0005I", 20, 30, 20, BmsScreen.FieldType.INPUT, "Sel0005", false),
        new BmsScreen.Field("SEL0006I", 22, 30, 20, BmsScreen.FieldType.INPUT, "Sel0006", false),
        new BmsScreen.Field("SEL0007I", 24, 30, 20, BmsScreen.FieldType.INPUT, "Sel0007", false),
        new BmsScreen.Field("SEL0008I", 26, 30, 20, BmsScreen.FieldType.INPUT, "Sel0008", false),
        new BmsScreen.Field("SEL0009I", 28, 30, 20, BmsScreen.FieldType.INPUT, "Sel0009", false),
        new BmsScreen.Field("SEL0010I", 30, 30, 20, BmsScreen.FieldType.INPUT, "Sel0010", false),
        new BmsScreen.Field("TAMT001I", 32, 30, 20, BmsScreen.FieldType.INPUT, "Tamt001", false),
        new BmsScreen.Field("TAMT002I", 34, 30, 20, BmsScreen.FieldType.INPUT, "Tamt002", false),
        new BmsScreen.Field("TAMT003I", 36, 30, 20, BmsScreen.FieldType.INPUT, "Tamt003", false),
        new BmsScreen.Field("TAMT004I", 38, 30, 20, BmsScreen.FieldType.INPUT, "Tamt004", false),
        new BmsScreen.Field("TAMT005I", 40, 30, 20, BmsScreen.FieldType.INPUT, "Tamt005", false),
        new BmsScreen.Field("TAMT006I", 42, 30, 20, BmsScreen.FieldType.INPUT, "Tamt006", false),
        new BmsScreen.Field("TAMT007I", 44, 30, 20, BmsScreen.FieldType.INPUT, "Tamt007", false),
        new BmsScreen.Field("TAMT008I", 46, 30, 20, BmsScreen.FieldType.INPUT, "Tamt008", false),
        new BmsScreen.Field("TAMT009I", 48, 30, 20, BmsScreen.FieldType.INPUT, "Tamt009", false),
        new BmsScreen.Field("TAMT010I", 50, 30, 20, BmsScreen.FieldType.INPUT, "Tamt010", false),
        new BmsScreen.Field("TDATE01I", 52, 30, 20, BmsScreen.FieldType.INPUT, "Tdate01", false),
        new BmsScreen.Field("TDATE02I", 54, 30, 20, BmsScreen.FieldType.INPUT, "Tdate02", false),
        new BmsScreen.Field("TDATE03I", 56, 30, 20, BmsScreen.FieldType.INPUT, "Tdate03", false),
        new BmsScreen.Field("TDATE04I", 58, 30, 20, BmsScreen.FieldType.INPUT, "Tdate04", false),
        new BmsScreen.Field("TDATE05I", 60, 30, 20, BmsScreen.FieldType.INPUT, "Tdate05", false),
        new BmsScreen.Field("TDATE06I", 62, 30, 20, BmsScreen.FieldType.INPUT, "Tdate06", false),
        new BmsScreen.Field("TDATE07I", 64, 30, 20, BmsScreen.FieldType.INPUT, "Tdate07", false),
        new BmsScreen.Field("TDATE08I", 66, 30, 20, BmsScreen.FieldType.INPUT, "Tdate08", false),
        new BmsScreen.Field("TDATE09I", 68, 30, 20, BmsScreen.FieldType.INPUT, "Tdate09", false),
        new BmsScreen.Field("TDATE10I", 70, 30, 20, BmsScreen.FieldType.INPUT, "Tdate10", false),
        new BmsScreen.Field("TDESC01I", 72, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc01", false),
        new BmsScreen.Field("TDESC02I", 74, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc02", false),
        new BmsScreen.Field("TDESC03I", 76, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc03", false),
        new BmsScreen.Field("TDESC04I", 78, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc04", false),
        new BmsScreen.Field("TDESC05I", 80, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc05", false),
        new BmsScreen.Field("TDESC06I", 82, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc06", false),
        new BmsScreen.Field("TDESC07I", 84, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc07", false),
        new BmsScreen.Field("TDESC08I", 86, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc08", false),
        new BmsScreen.Field("TDESC09I", 88, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc09", false),
        new BmsScreen.Field("TDESC10I", 90, 30, 20, BmsScreen.FieldType.INPUT, "Tdesc10", false),
        new BmsScreen.Field("TRNID01I", 92, 30, 20, BmsScreen.FieldType.INPUT, "Trnid01", false),
        new BmsScreen.Field("TRNID02I", 94, 30, 20, BmsScreen.FieldType.INPUT, "Trnid02", false),
        new BmsScreen.Field("TRNID03I", 96, 30, 20, BmsScreen.FieldType.INPUT, "Trnid03", false),
        new BmsScreen.Field("TRNID04I", 98, 30, 20, BmsScreen.FieldType.INPUT, "Trnid04", false),
        new BmsScreen.Field("TRNID05I", 100, 30, 20, BmsScreen.FieldType.INPUT, "Trnid05", false),
        new BmsScreen.Field("TRNID06I", 102, 30, 20, BmsScreen.FieldType.INPUT, "Trnid06", false),
        new BmsScreen.Field("TRNID07I", 104, 30, 20, BmsScreen.FieldType.INPUT, "Trnid07", false),
        new BmsScreen.Field("TRNID08I", 106, 30, 20, BmsScreen.FieldType.INPUT, "Trnid08", false),
        new BmsScreen.Field("TRNID09I", 108, 30, 20, BmsScreen.FieldType.INPUT, "Trnid09", false),
        new BmsScreen.Field("TRNID10I", 110, 30, 20, BmsScreen.FieldType.INPUT, "Trnid10", false),
        new BmsScreen.Field("TRNIDINI", 112, 30, 20, BmsScreen.FieldType.INPUT, "Trnidin", false),
        new BmsScreen.Field("ERRMSGO", 20, 2, 76, BmsScreen.FieldType.MESSAGE, null, false)
    );
}
