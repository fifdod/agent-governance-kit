"""Run-scoped evidence writing, manifest construction, and tamper detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime_utils import (
    sha256_file,
    sha256_value,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)


class EvidenceError(ValueError):
    """Raised when evidence operations fail (missing artifact, hash mismatch)."""


class EvidenceBundle:
    """Run-scoped evidence directory with atomic writes and manifest."""

    def __init__(self, root: str | Path, *, must_be_empty: bool = True):
        self.root = Path(root)
        if must_be_empty:
            self.root.mkdir(parents=True, exist_ok=False)
        else:
            self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        """Get path for an evidence artifact (must be directly under root)."""
        candidate = self.root / name
        if candidate.parent != self.root:
            raise EvidenceError("evidence file must be directly under run root")
        return candidate

    def write_json(self, name: str, value: Any) -> Path:
        """Write a JSON evidence artifact atomically."""
        target = self.path(name)
        write_json_atomic(target, value)
        return target

    def write_text(self, name: str, text: str) -> Path:
        """Write a text evidence artifact atomically."""
        target = self.path(name)
        write_text_atomic(target, text)
        return target

    def write_jsonl_event(self, name: str, event: dict[str, Any]) -> Path:
        """Append a JSONL event to an evidence stream."""
        target = self.path(name)
        line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
        return target

    def read_jsonl_stream(self, name: str) -> list[dict[str, Any]]:
        """Read a JSONL evidence stream."""
        target = self.path(name)
        if not target.is_file():
            return []
        events: list[dict[str, Any]] = []
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def build_manifest(self) -> dict[str, Any]:
        """Build the evidence manifest with SHA-256 hashes for all artifacts."""
        files: list[dict[str, Any]] = []
        for path in sorted(self.root.iterdir(), key=lambda p: p.name.casefold()):
            if not path.is_file() or path.name == "evidence_manifest.json":
                continue
            files.append(
                {
                    "relative_path": path.name,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        manifest = {
            "created_at": utc_now(),
            "algorithm": "SHA256",
            "files": files,
        }
        self.write_json("evidence_manifest.json", manifest)
        return manifest

    def verify_manifest(self) -> dict[str, Any]:
        """Verify all artifacts match the manifest. Returns {valid, errors, file_count}."""
        manifest_path = self.path("evidence_manifest.json")
        if not manifest_path.is_file():
            return {"valid": False, "errors": ["evidence_manifest.json not found"], "file_count": 0}

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {"valid": False, "errors": [f"manifest parse error: {exc}"], "file_count": 0}

        errors: list[str] = []
        file_count = len(manifest.get("files", []))

        for item in manifest.get("files", []):
            try:
                path = self.path(item["relative_path"])
            except EvidenceError as exc:
                errors.append(f"invalid path {item.get('relative_path')}: {exc}")
                continue

            if not path.is_file():
                errors.append(f"missing artifact: {item['relative_path']}")
                continue

            actual_size = path.stat().st_size
            if actual_size != item["size"]:
                errors.append(
                    f"size mismatch for {item['relative_path']}: "
                    f"expected {item['size']}, got {actual_size}"
                )
                continue

            actual_hash = sha256_file(path)
            if actual_hash != item["sha256"]:
                errors.append(f"hash mismatch for {item['relative_path']}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "file_count": file_count,
        }

    def verify_artifact(self, name: str, expected_sha256: str) -> bool:
        """Verify a single artifact's hash against an expected value."""
        path = self.path(name)
        if not path.is_file():
            return False
        return sha256_file(path) == expected_sha256


def compute_artifact_hash(data: Any) -> str:
    """Compute a deterministic SHA-256 hash for any JSON-serializable value."""
    return sha256_value(data)
