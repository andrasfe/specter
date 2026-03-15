package com.specter.generated;

import java.util.List;

/**
 * Common interface for CICS programs participating in XCTL routing.
 *
 * <p>Each generated program class implements this interface so that
 * {@link MultiProgramRunner} can invoke any program polymorphically
 * and route XCTL transfers between them.
 */
public interface CicsProgram {

    /**
     * Execute the program with the given state.
     *
     * @param state the shared program state carried across XCTL transfers
     * @return the state after execution
     */
    ProgramState run(ProgramState state);

    /**
     * Return the COBOL PROGRAM-ID (e.g. {@code "COSGN00C"}).
     */
    String programId();

    /**
     * Return the BMS screen layout for this program, or an empty list
     * if the program has no terminal screen.
     */
    List<CicsScreen.Field> screenLayout();

    /**
     * Seed per-program literal constants (LIT-*, CCDA-*) into the state.
     *
     * <p>Called by {@link MultiProgramRunner} before each program
     * execution to ensure COBOL literals like LIT-MENUPGM, LIT-THISMAP,
     * etc. are correctly set for the target program.
     *
     * @param state the program state to seed
     */
    void initState(ProgramState state);
}
