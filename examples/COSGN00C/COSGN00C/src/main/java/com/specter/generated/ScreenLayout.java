package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cosgn00cProgram.
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
        new CicsScreen.Field("APPLIDO", 3, 2, 10, CicsScreen.FieldType.DISPLAY, "Applid", false),
        new CicsScreen.Field("SYSIDO", 3, 24, 10, CicsScreen.FieldType.DISPLAY, "Sysid", false),
        new CicsScreen.Field("USERIDI", 5, 30, 20, CicsScreen.FieldType.INPUT, "User ID", false),
        new CicsScreen.Field("PASSWDI", 6, 30, 20, CicsScreen.FieldType.INPUT, "Password", true),
        new CicsScreen.Field("ERRMSGO", 21, 2, 76, CicsScreen.FieldType.MESSAGE, null, false)
    );
}
