package com.specter.generated;

import java.util.List;

/**
 * BMS screen layout for Cousr02cProgram.
 *
 * <p>Generated from COBOL AST field analysis. Defines the position and
 * type of each screen field for {@link BmsScreen} rendering.
 */
public class ScreenLayout_COUSR02C {

    public static final List<CicsScreen.Field> FIELDS = List.of(
        new CicsScreen.Field("TITLE01O", 0, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("TITLE02O", 1, 0, 80, CicsScreen.FieldType.CENTER, null, false),
        new CicsScreen.Field("PGMNAMEO", 2, 2, 12, CicsScreen.FieldType.DISPLAY, "Program", false),
        new CicsScreen.Field("TRNNAMEO", 2, 24, 12, CicsScreen.FieldType.DISPLAY, "Trans", false),
        new CicsScreen.Field("CURDATEO", 2, 50, 10, CicsScreen.FieldType.DISPLAY, "Date", false),
        new CicsScreen.Field("CURTIMEO", 2, 68, 10, CicsScreen.FieldType.DISPLAY, "Time", false),
        new CicsScreen.Field("USRIDINI", 4, 30, 20, CicsScreen.FieldType.INPUT, "Usridin", false),
        new CicsScreen.Field("FNAMEI", 5, 30, 20, CicsScreen.FieldType.INPUT, "Fname", false),
        new CicsScreen.Field("LNAMEI", 6, 30, 20, CicsScreen.FieldType.INPUT, "Lname", false),
        new CicsScreen.Field("USRTYPEI", 7, 30, 20, CicsScreen.FieldType.INPUT, "Usrtype", false),
        new CicsScreen.Field("PASSWDI", 8, 30, 20, CicsScreen.FieldType.INPUT, "Password", true),
        new CicsScreen.Field("ERRMSGC", 21, 2, 76, CicsScreen.FieldType.MESSAGE, null, false),
        new CicsScreen.Field("ERRMSGO", 22, 2, 76, CicsScreen.FieldType.MESSAGE, null, false)
    );
}
