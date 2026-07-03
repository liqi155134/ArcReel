from __future__ import annotations

from pathlib import Path

import pytest


def test_missing_draft_directory_lists_empty(tmp_path: Path) -> None:
    from lib.claude_draft_artifacts import list_draft_artifacts

    assert list_draft_artifacts(tmp_path / "demo", episode=1) == []


def test_write_read_and_list_artifact_roundtrip(tmp_path: Path) -> None:
    from lib.claude_draft_artifacts import list_draft_artifacts, read_draft_artifact, write_draft_artifact

    project_path = tmp_path / "demo"
    artifact = write_draft_artifact(
        project_path,
        {
            "schema_version": 1,
            "intent": "script_review_notes",
            "project_name": "demo",
            "episode": 1,
            "status": "succeeded",
            "output": {"summary": "ok"},
        },
    )

    assert artifact.path.is_relative_to(project_path)
    loaded = read_draft_artifact(project_path, artifact.artifact_id)
    assert loaded["intent"] == "script_review_notes"
    assert loaded["output"]["summary"] == "ok"
    listed = list_draft_artifacts(project_path, episode=1)
    assert [item["artifact_id"] for item in listed] == [artifact.artifact_id]


def test_artifact_id_cannot_escape_project_root(tmp_path: Path) -> None:
    from lib.claude_draft_artifacts import read_draft_artifact

    with pytest.raises(ValueError, match="invalid artifact id"):
        read_draft_artifact(tmp_path / "demo", "../outside.json")


def test_failed_artifact_sanitizes_errors(tmp_path: Path) -> None:
    from lib.claude_draft_artifacts import read_draft_artifact, write_draft_artifact

    artifact = write_draft_artifact(
        tmp_path / "demo",
        {
            "schema_version": 1,
            "intent": "script_review_notes",
            "project_name": "demo",
            "episode": None,
            "status": "failed",
            "error": "ANTHROPIC_API_KEY=secret-token failed",
            "output": {},
        },
    )
    loaded = read_draft_artifact(tmp_path / "demo", artifact.artifact_id)

    assert "secret-token" not in loaded["error"]
    assert "[redacted]" in loaded["error"]
