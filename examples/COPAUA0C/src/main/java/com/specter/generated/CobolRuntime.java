package com.specter.generated;

/**
 * Static utility methods that mirror the Python runtime helpers
 * ({@code _to_num}, {@code _is_numeric}, etc.).
 *
 * <p>All methods are null-safe and never throw.
 */
public final class CobolRuntime {

    /** Call-depth limit shared by all paragraphs. */
    public static final int CALL_DEPTH_LIMIT = 200;

    private CobolRuntime() {
        // utility class
    }

    // -----------------------------------------------------------------------
    // Numeric conversion
    // -----------------------------------------------------------------------

    /**
     * Coerce an arbitrary value to {@code double}.
     *
     * <ul>
     *   <li>{@link Number} &rarr; {@code doubleValue()}</li>
     *   <li>{@link String} &rarr; trimmed, then parsed; 0.0 on failure</li>
     *   <li>{@code null} or anything else &rarr; 0.0</li>
     * </ul>
     */
    public static double toNum(Object v) {
        if (v instanceof Number) {
            return ((Number) v).doubleValue();
        }
        if (v instanceof String) {
            String s = ((String) v).trim();
            if (s.isEmpty()) {
                return 0.0;
            }
            try {
                return Double.parseDouble(s);
            } catch (NumberFormatException e) {
                return 0.0;
            }
        }
        return 0.0;
    }

    /**
     * Check whether a value is numeric (parseable as a number).
     */
    public static boolean isNumeric(Object v) {
        if (v == null) {
            return false;
        }
        if (v instanceof Number) {
            return true;
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) {
            return false;
        }
        try {
            Double.parseDouble(s);
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /**
     * Convert a value to {@link String}; {@code null} becomes {@code ""}.
     */
    public static String toStr(Object v) {
        if (v == null) {
            return "";
        }
        return String.valueOf(v);
    }

    // -----------------------------------------------------------------------
    // COBOL comparison
    // -----------------------------------------------------------------------

    /**
     * COBOL-style comparison.
     *
     * <p>If both operands are numeric (or parseable as numbers), compare
     * numerically.  Otherwise compare as trimmed strings (case-sensitive,
     * matching COBOL EBCDIC collation for ASCII-range data).
     *
     * @return negative, zero, or positive (like {@link Comparable#compareTo}).
     */
    /**
     * COBOL truthiness: non-null, non-empty-string, non-zero, and Boolean.TRUE.
     */
    public static boolean isTruthy(Object v) {
        if (v == null) return false;
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof Number) return ((Number) v).doubleValue() != 0;
        String s = v.toString().trim();
        return !s.isEmpty();
    }

    public static int cobolCompare(Object a, Object b) {
        boolean aNum = isNumeric(a);
        boolean bNum = isNumeric(b);
        if (aNum && bNum) {
            double da = toNum(a);
            double db = toNum(b);
            return Double.compare(da, db);
        }
        String sa = toStr(a).trim();
        String sb = toStr(b).trim();
        return sa.compareTo(sb);
    }
}
