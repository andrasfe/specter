#!/usr/bin/env bash
# Teacher-side helper for the Specter supervisor channel.
#
# Usage:
#   scripts/teach.sh <run_dir>
#
# Tails <run_dir>/escalations.jsonl, pretty-prints each event, and prints
# the exact JSON template a teacher should append to resolutions.jsonl to
# reply. Intended to be invoked from a Claude Code session with Monitor
# watching the stdout stream — each event is one line per notification.
#
# The teacher replies by appending a JSON line to <run_dir>/resolutions.jsonl:
#   {"id": "<escalation-id>", "verdict": "patch", "fix": {"1423": "..."},
#    "notes": "why this fix is safe"}
# Valid verdicts: patch | skip | abort | restart | retry_with
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <run_dir>" >&2
  exit 2
fi

RUN_DIR="$1"
ESC="$RUN_DIR/escalations.jsonl"
RES="$RUN_DIR/resolutions.jsonl"
STATUS="$RUN_DIR/status.jsonl"

mkdir -p "$RUN_DIR"
: > "$RES" 2>/dev/null || true  # ensure resolutions file exists, don't clobber if not empty
[[ -f "$RES" ]] || touch "$RES"
[[ -f "$ESC" ]] || touch "$ESC"
[[ -f "$STATUS" ]] || touch "$STATUS"

echo "teach.sh watching:"
echo "  escalations: $ESC"
echo "  resolutions: $RES (reply here)"
echo "  status:      $STATUS (heartbeats)"
echo

# -F survives log rotation/truncate; -n 0 starts at current end of file.
exec tail -F -n 0 "$ESC"
