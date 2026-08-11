"""Deterministic runtime primitives: hashing, atomic writes, timestamps."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize value as canonical JSON bytes (sorted keys, no whitespace)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    """SHA-256 hash of a value's canonical JSON representation."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    """SHA-256 hash of a file's contents."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 hash of a text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json_atomic(path: str | Path, value: Any) -> None:
    """Write JSON to a file atomically via temp file + os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def write_text_atomic(path: str | Path, text: str) -> None:
    """Write text to a file atomically via temp file + os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def normalize_repo_path(raw: str) -> str:
    """Normalize a repository-relative path for comparison.

    Rejects absolute paths, traversal attempts, and empty values.
    Returns forward-slash normalized lowercase path.
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("path must be a non-empty string")
    value = raw.replace("\\", "/")
    if value.startswith("/") or ":" in value:
        raise ValueError(f"path appears absolute: {raw!r}")
    parts = value.split("/")
    if ".." in parts:
        raise ValueError(f"path contains traversal: {raw!r}")
    return "/".join(part for part in parts if part not in ("", ".")).lower()
