#!/bin/bash
# Usage: ./find_undefined_sources.sh <mock.cbl> <source.cbl> <cpy_dir> NAME1 NAME2 NAME3 ...
#
# For each undefined variable name, shows:
# 1. Where it's used in the mock.cbl (first 3 occurrences)
# 2. Where it's defined in the original source or any copybook
# 3. What COPY statements are near its definition

MOCK="$1"; shift
SRC="$1"; shift
CPY="$1"; shift

echo "=== Undefined Variable Analysis ==="
echo "Mock: $MOCK"
echo "Source: $SRC"
echo "Copybooks: $CPY"
echo ""

for NAME in "$@"; do
    echo "━━━ $NAME ━━━"

    # Where is it used in mock.cbl?
    echo "  MOCK USAGE (first 3):"
    grep -n "$NAME" "$MOCK" 2>/dev/null | head -3 | sed 's/^/    /'

    # Is it in the original source?
    echo "  SOURCE DEFINITION:"
    grep -n "$NAME" "$SRC" 2>/dev/null | head -3 | sed 's/^/    /'

    # Is it in any copybook?
    echo "  COPYBOOK DEFINITION:"
    grep -rn "$NAME" "$CPY"/ 2>/dev/null | head -3 | sed 's/^/    /'

    # If found in a copybook, show the COPY statement for that copybook
    CPY_FILE=$(grep -rl "$NAME" "$CPY"/ 2>/dev/null | head -1)
    if [ -n "$CPY_FILE" ]; then
        CPY_NAME=$(basename "$CPY_FILE" | sed 's/\..*//')
        echo "  COPY STATEMENT IN SOURCE:"
        grep -n -i "COPY.*$CPY_NAME" "$SRC" 2>/dev/null | head -3 | sed 's/^/    /'
    fi

    echo ""
done
