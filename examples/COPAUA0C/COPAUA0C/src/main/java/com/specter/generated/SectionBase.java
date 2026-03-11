package com.specter.generated;

/**
 * Abstract base class for generated section classes.
 *
 * <p>Each section groups multiple COBOL paragraphs by numeric prefix.
 * Paragraphs are registered as anonymous {@link Paragraph} instances
 * that delegate to section methods.
 */
public abstract class SectionBase {

    protected final ParagraphRegistry registry;
    protected final StubExecutor stubs;

    protected SectionBase(ParagraphRegistry registry, StubExecutor stubs) {
        this.registry = registry;
        this.stubs = stubs;
    }

    /**
     * Register a paragraph backed by a method reference.
     */
    protected void paragraph(String name, java.util.function.Consumer<ProgramState> body) {
        registry.register(new Paragraph(name, registry, stubs) {
            @Override protected void doExecute(ProgramState state) {
                body.accept(state);
            }
        });
    }

    // -----------------------------------------------------------------------
    // Helpers available to generated code (same signatures as Paragraph)
    // -----------------------------------------------------------------------

    protected void perform(ProgramState state, String paraName) {
        Paragraph p = registry.get(paraName);
        if (p != null) {
            p.execute(state);
        }
    }

    protected void performThru(ProgramState state, String from, String thru) {
        for (Paragraph p : registry.getThruRange(from, thru)) {
            p.execute(state);
        }
    }

    protected void performTimes(ProgramState state, String paraName, int n) {
        Paragraph p = registry.get(paraName);
        if (p != null) {
            for (int i = 0; i < n; i++) {
                p.execute(state);
            }
        }
    }

    protected void display(ProgramState state, String... parts) {
        state.addDisplay(String.join("", parts));
    }

    protected void goback() {
        throw new GobackSignal();
    }
}
