"""Tests for evidence system — manifest and tamper detection."""

import json

import pytest

from agent_governance.evidence import EvidenceBundle, EvidenceError, compute_artifact_hash
from agent_governance.runtime_utils import sha256_value


class TestEvidenceBundle:
    """Tests for evidence bundle creation and verification."""

    def test_write_and_verify_json(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("task_spec.json", {"key": "value"})
        manifest = bundle.build_manifest()
        result = bundle.verify_manifest()
        assert result["valid"]
        assert result["file_count"] == 1

    def test_write_text(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_text("summary.txt", "execution summary")
        manifest = bundle.build_manifest()
        assert len(manifest["files"]) == 1

    def test_verify_empty_bundle(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.build_manifest()
        result = bundle.verify_manifest()
        assert result["valid"]
        assert result["file_count"] == 0

    def test_missing_manifest(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        result = bundle.verify_manifest()
        assert not result["valid"]
        assert "not found" in result["errors"][0]

    def test_missing_artifact(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("a.json", {"x": 1})
        bundle.build_manifest()
        # Delete the artifact
        (tmp_path / "evidence" / "a.json").unlink()
        result = bundle.verify_manifest()
        assert not result["valid"]
        assert any("missing" in e for e in result["errors"])

    def test_hash_mismatch(self, tmp_path):
        """Evidence tamper detection — hash mismatch detected."""
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("data.json", {"original": True})
        bundle.build_manifest()
        # Tamper with the file
        bundle.write_json("data.json", {"tampered": True})
        result = bundle.verify_manifest()
        assert not result["valid"]
        assert any("hash mismatch" in e for e in result["errors"])

    def test_size_mismatch(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_text("data.txt", "short")
        manifest = bundle.build_manifest()
        # Overwrite with different content
        bundle.write_text("data.txt", "much longer content here")
        result = bundle.verify_manifest()
        assert not result["valid"]
        assert any("size mismatch" in e for e in result["errors"])

    def test_verify_single_artifact(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("report.json", {"status": "PASS"})
        # Hash the actual file content, not the canonical JSON value
        from agent_governance.runtime_utils import sha256_file
        actual_hash = sha256_file(tmp_path / "evidence" / "report.json")
        assert bundle.verify_artifact("report.json", actual_hash)
        assert not bundle.verify_artifact("report.json", "bad_hash")

    def test_jsonl_append_and_read(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_jsonl_event("events.jsonl", {"seq": 1, "event": "created"})
        bundle.write_jsonl_event("events.jsonl", {"seq": 2, "event": "accepted"})
        events = bundle.read_jsonl_stream("events.jsonl")
        assert len(events) == 2
        assert events[0]["seq"] == 1
        assert events[1]["seq"] == 2

    def test_jsonl_empty_stream(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        events = bundle.read_jsonl_stream("nonexistent.jsonl")
        assert events == []

    def test_manifest_has_required_fields(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("a.json", {"x": 1})
        manifest = bundle.build_manifest()
        assert "created_at" in manifest
        assert "algorithm" in manifest
        assert manifest["algorithm"] == "SHA256"
        assert "files" in manifest
        f = manifest["files"][0]
        assert "relative_path" in f
        assert "size" in f
        assert "sha256" in f

    def test_nested_path_rejected(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        with pytest.raises(EvidenceError, match="directly under"):
            bundle.path("../escape.json")

    def test_compute_artifact_hash(self):
        h1 = compute_artifact_hash({"a": 1, "b": 2})
        h2 = compute_artifact_hash({"b": 2, "a": 1})
        assert h1 == h2  # sorted keys = deterministic

    def test_must_be_empty_default(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        # Creating again with must_be_empty=True should fail
        with pytest.raises(FileExistsError):
            EvidenceBundle(tmp_path / "evidence", must_be_empty=True)

    def test_not_must_be_empty(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence_reuse", must_be_empty=False)
        bundle.write_json("first.json", {"x": 1})
        # Re-open same dir
        bundle2 = EvidenceBundle(tmp_path / "evidence_reuse", must_be_empty=False)
        bundle2.write_json("second.json", {"y": 2})
        assert (tmp_path / "evidence_reuse" / "first.json").is_file()
        assert (tmp_path / "evidence_reuse" / "second.json").is_file()

    def test_multiple_artifacts(self, tmp_path):
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("task_spec.json", {"id": "1"})
        bundle.write_json("policy.json", {"version": "1.0"})
        bundle.write_text("summary.txt", "done")
        bundle.build_manifest()
        result = bundle.verify_manifest()
        assert result["valid"]
        assert result["file_count"] == 3
