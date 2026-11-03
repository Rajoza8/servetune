"""Canonical, exclusively created evidence files and offline integrity checks."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def seal(directory):
    root = Path(directory)
    files = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*")) if p.is_file()}
    write_json(root / "manifest.json", {"schema_version": 1, "files": files})


def verify(directory):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text())
    expected = manifest["files"]
    found = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p != root / "manifest.json"}
    if found != set(expected):
        raise ValueError("Evidence files were added or removed")
    for name, checksum in expected.items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or file_hash(path) != checksum:
            raise ValueError(f"Evidence hash mismatch: {name}")
    return json.loads((root / "preflight.json").read_text())
