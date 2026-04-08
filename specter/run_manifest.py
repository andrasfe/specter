from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .persistence_utils import atomic_write_json

MANIFEST_FILE = ".specter_run_manifest.json"


def sha256_file(path: str | Path) -> str:
    p = Path(path)
    digest = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(work_dir: str | Path) -> dict:
    manifest_path = Path(work_dir) / MANIFEST_FILE
    if not manifest_path.exists():
        return {}
    try:
        import json

        return json.loads(manifest_path.read_text())
    except Exception:
        return {}


def save_manifest(work_dir: str | Path, manifest: dict) -> None:
    manifest_path = Path(work_dir) / MANIFEST_FILE
    atomic_write_json(manifest_path, manifest, indent=2)


def ensure_manifest(work_dir: str | Path, source_path: str | Path, copybook_dirs: list[Path]) -> dict:
    """Create or update a manifest with stable input hashes."""
    now = datetime.now(timezone.utc).isoformat()
    source = Path(source_path)
    copy_hashes = {}
    for d in copybook_dirs:
        if d.exists() and d.is_dir():
            copy_hashes[str(d)] = "dir"
    manifest = load_manifest(work_dir)
    if not manifest:
        manifest = {
            "version": 1,
            "created_at": now,
            "source": {
                "path": str(source),
                "sha256": sha256_file(source),
                "copybook_dirs": copy_hashes,
            },
            "state": {},
        }
    else:
        manifest.setdefault("source", {})
        manifest["source"]["path"] = str(source)
        manifest["source"]["sha256"] = sha256_file(source)
        manifest["source"]["copybook_dirs"] = copy_hashes
    manifest["updated_at"] = now
    save_manifest(work_dir, manifest)
    return manifest


def record_phase_checkpoint(
    work_dir: str | Path,
    phase_name: str,
    phase_number: int,
    mock_path: Path,
) -> None:
    """Persist latest successful phase in run manifest."""
    manifest = load_manifest(work_dir)
    if not manifest:
        return
    now = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("state", {})
    manifest["state"]["last_completed_phase"] = phase_name
    manifest["state"]["last_completed_phase_number"] = phase_number
    manifest["state"]["mock_cbl_name"] = mock_path.name
    manifest["state"]["mock_cbl_sha256"] = sha256_file(mock_path)
    manifest["state"]["timestamp"] = now
    manifest["updated_at"] = now
    save_manifest(work_dir, manifest)
