package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cosgn00cProgram.
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
        new BmsScreen.Field("APPLIDO", 3, 2, 10, BmsScreen.FieldType.DISPLAY, "Applid", false),
        new BmsScreen.Field("SYSIDO", 3, 24, 10, BmsScreen.FieldType.DISPLAY, "Sysid", false),
        new BmsScreen.Field("USERIDI", 10, 30, 20, BmsScreen.FieldType.INPUT, "Userid", false),
        new BmsScreen.Field("PASSWDI", 12, 30, 20, BmsScreen.FieldType.INPUT, "Passwd", true),
        new BmsScreen.Field("ERRMSGO", 20, 2, 76, BmsScreen.FieldType.MESSAGE, null, false)
    );
}
