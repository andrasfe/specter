package com.specter.generated;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Insertion-ordered registry of {@link Paragraph} instances.
 *
 * <p>Maintains both a {@link LinkedHashMap} for O(1) name lookup and
 * an {@link ArrayList} for index-based range queries needed by
 * PERFORM THRU.
 */
public class ParagraphRegistry {

    private final Map<String, Paragraph> byName = new LinkedHashMap<>();
    private final List<Paragraph> ordered = new ArrayList<>();
    private final List<String> orderedNames = new ArrayList<>();

    /**
     * Register a paragraph.  Must be called in COBOL source order.
     */
    public void register(Paragraph p) {
        byName.put(p.name, p);
        ordered.add(p);
        orderedNames.add(p.name);
    }

    /**
     * Look up a paragraph by its COBOL name.
     *
     * @return the paragraph, or {@code null} if not found.
     */
    public Paragraph get(String name) {
        return byName.get(name);
    }

    /**
     * Return the sub-list of paragraphs from {@code from} to {@code thru}
     * inclusive, in registration (source) order.
     *
     * <p>If either name is not found the method returns an empty list
     * rather than throwing.
     */
    public List<Paragraph> getThruRange(String from, String thru) {
        int start = orderedNames.indexOf(from);
        int end = orderedNames.indexOf(thru);
        if (start < 0 || end < 0 || start > end) {
            return Collections.emptyList();
        }
        return ordered.subList(start, end + 1);
    }

    /**
     * Return an unmodifiable list of all paragraph names in registration
     * order.
     */
    public List<String> allNames() {
        return Collections.unmodifiableList(orderedNames);
    }
}
