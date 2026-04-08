from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, content: str) -> None:
    """Atomically write text content to a file.

    Uses temp-file + fsync + replace to avoid partial writes on interruption.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(target.parent),
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, target)


def atomic_write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Atomically write JSON content to a file."""
    atomic_write_text(path, json.dumps(data, indent=indent, default=str))


def append_line_with_fsync(path: str | Path, line: str) -> None:
    """Append one line and fsync so progress survives sudden process exit."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
