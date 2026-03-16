package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cotrn02cProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout_COTRN02C {

    public static final List<CicsScreen.Field> FIELDS = List.of(
        new CicsScreen.Field("TITLE01O", 0, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("TITLE02O", 1, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("PGMNAMEO", 2, 2, 12, CicsScreen.FieldType.DISPLAY, "Program", false),
        new CicsScreen.Field("TRNNAMEO", 2, 24, 12, CicsScreen.FieldType.DISPLAY, "Trans", false),
        new CicsScreen.Field("CURDATEO", 2, 50, 10, CicsScreen.FieldType.DISPLAY, "Date", false),
        new CicsScreen.Field("CURTIMEO", 2, 68, 10, CicsScreen.FieldType.DISPLAY, "Time", false),
        new CicsScreen.Field("CARDNINI", 4, 30, 20, CicsScreen.FieldType.INPUT, "Cardnin", false),
        new CicsScreen.Field("CONFIRMI", 5, 30, 20, CicsScreen.FieldType.INPUT, "Confirm", false),
        new CicsScreen.Field("ACTIDINI", 6, 30, 20, CicsScreen.FieldType.INPUT, "Actidin", false),
        new CicsScreen.Field("TTYPCDI", 7, 30, 20, CicsScreen.FieldType.INPUT, "Ttypcd", false),
        new CicsScreen.Field("TCATCDI", 8, 30, 20, CicsScreen.FieldType.INPUT, "Tcatcd", false),
        new CicsScreen.Field("TRNSRCI", 9, 30, 20, CicsScreen.FieldType.INPUT, "Trnsrc", false),
        new CicsScreen.Field("TRNAMTI", 10, 30, 20, CicsScreen.FieldType.INPUT, "Trnamt", false),
        new CicsScreen.Field("TDESCI", 11, 30, 20, CicsScreen.FieldType.INPUT, "Tdesc", false),
        new CicsScreen.Field("TORIGDTI", 12, 30, 20, CicsScreen.FieldType.INPUT, "Torigdt", false),
        new CicsScreen.Field("TPROCDTI", 13, 30, 20, CicsScreen.FieldType.INPUT, "Tprocdt", false),
        new CicsScreen.Field("MIDI", 14, 30, 20, CicsScreen.FieldType.INPUT, "Mid", false),
        new CicsScreen.Field("MNAMEI", 15, 30, 20, CicsScreen.FieldType.INPUT, "Mname", false),
        new CicsScreen.Field("MCITYI", 16, 30, 20, CicsScreen.FieldType.INPUT, "Mcity", false),
        new CicsScreen.Field("MZIPI", 17, 30, 20, CicsScreen.FieldType.INPUT, "Mzip", false),
        new CicsScreen.Field("ERRMSGC", 21, 2, 76, CicsScreen.FieldType.MESSAGE, null, false),
        new CicsScreen.Field("ERRMSGO", 22, 2, 76, CicsScreen.FieldType.MESSAGE, null, false)
    );
}
