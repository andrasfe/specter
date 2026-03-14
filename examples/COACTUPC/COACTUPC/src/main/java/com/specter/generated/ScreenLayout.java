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
        new BmsScreen.Field("TITLE01O", 0, 0, 80, BmsScreen.FieldType.CENTER, null, false),
        new BmsScreen.Field("TITLE02O", 1, 0, 80, BmsScreen.FieldType.CENTER, null, false),
        new BmsScreen.Field("PGMNAMEO", 2, 2, 12, BmsScreen.FieldType.DISPLAY, "Pgmname", false),
        new BmsScreen.Field("TRNNAMEO", 2, 24, 12, BmsScreen.FieldType.DISPLAY, "Trnname", false),
        new BmsScreen.Field("CURDATEO", 2, 50, 10, BmsScreen.FieldType.DISPLAY, "Curdate", false),
        new BmsScreen.Field("CURTIMEO", 2, 68, 10, BmsScreen.FieldType.DISPLAY, "Curtime", false),
        new BmsScreen.Field("AADDGRPO", 4, 2, 35, BmsScreen.FieldType.DISPLAY, "Aaddgrp", false),
        new BmsScreen.Field("ACCTSIDC", 4, 42, 35, BmsScreen.FieldType.DISPLAY, "Acctsidc", false),
        new BmsScreen.Field("ACCTSIDO", 5, 2, 35, BmsScreen.FieldType.DISPLAY, "Acctsid", false),
        new BmsScreen.Field("ACRCYCRO", 5, 42, 35, BmsScreen.FieldType.DISPLAY, "Acrcycr", false),
        new BmsScreen.Field("AADDGRPI", 6, 30, 20, BmsScreen.FieldType.INPUT, "Aaddgrp", false),
        new BmsScreen.Field("ACCTSIDI", 7, 30, 20, BmsScreen.FieldType.INPUT, "Acctsid", false),
        new BmsScreen.Field("ACRCYCRI", 8, 30, 20, BmsScreen.FieldType.INPUT, "Acrcycr", false),
        new BmsScreen.Field("ACRCYDBI", 9, 30, 20, BmsScreen.FieldType.INPUT, "Acrcydb", false),
        new BmsScreen.Field("ACRDLIMI", 10, 30, 20, BmsScreen.FieldType.INPUT, "Acrdlim", false),
        new BmsScreen.Field("ACSADL1I", 11, 30, 20, BmsScreen.FieldType.INPUT, "Acsadl1", false),
        new BmsScreen.Field("ACSADL2I", 12, 30, 20, BmsScreen.FieldType.INPUT, "Acsadl2", false),
        new BmsScreen.Field("ACSCITYI", 13, 30, 20, BmsScreen.FieldType.INPUT, "Acscity", false),
        new BmsScreen.Field("ACSCTRYI", 14, 30, 20, BmsScreen.FieldType.INPUT, "Acsctry", false),
        new BmsScreen.Field("ACSEFTCI", 15, 30, 20, BmsScreen.FieldType.INPUT, "Acseftc", false),
        new BmsScreen.Field("ACSFNAMI", 16, 30, 20, BmsScreen.FieldType.INPUT, "Acsfnam", false),
        new BmsScreen.Field("ACSGOVTI", 17, 30, 20, BmsScreen.FieldType.INPUT, "Acsgovt", false),
        new BmsScreen.Field("ACSHLIMI", 18, 30, 20, BmsScreen.FieldType.INPUT, "Acshlim", false),
        new BmsScreen.Field("ACSLNAMI", 19, 30, 20, BmsScreen.FieldType.INPUT, "Acslnam", false),
        new BmsScreen.Field("ACSMNAMI", 20, 30, 20, BmsScreen.FieldType.INPUT, "Acsmnam", false),
        new BmsScreen.Field("ERRMSGO", 21, 2, 76, BmsScreen.FieldType.MESSAGE, null, false),
        new BmsScreen.Field("INFOMSGO", 22, 2, 76, BmsScreen.FieldType.MESSAGE, null, false)
    );
}
