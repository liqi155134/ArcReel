"""Project-local draft artifact ledger for the Claude draft-only bridge."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.claude_draft_bridge import redact_text
from lib.json_io import atomic_write_json, load_json

_LEDGER_ROOT = Path("drafts") / "claude_bridge"
_SAFE_SLUG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True)
class DraftArtifactRef:
    artifact_id: str
    path: Path


def _episode_dir_name(episode: int | None) -> str:
    return str(episode) if episode is not None else "global"


def _ledger_base(project_path: Path) -> Path:
    return project_path / _LEDGER_ROOT


def _artifact_dir(project_path: Path, episode: int | None) -> Path:
    return _ledger_base(project_path) / _episode_dir_name(episode)


def _slugify(value: object) -> str:
    slug = _SAFE_SLUG_RE.sub("-", str(value or "draft")).strip("-.")
    return slug or "draft"


def _sanitize_payload(payload: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    sanitized = dict(payload)
    sanitized.setdefault("schema_version", 1)
    sanitized.setdefault("created_at", datetime.now(UTC).isoformat())
    sanitized["artifact_id"] = artifact_id
    error = sanitized.get("error")
    if isinstance(error, str):
        sanitized["error"] = redact_text(error)
    return sanitized


def _resolve_artifact_path(project_path: Path, artifact_id: str) -> Path:
    candidate_id = Path(artifact_id)
    if candidate_id.is_absolute() or candidate_id.suffix != ".json" or any(part in {"", ".", ".."} for part in candidate_id.parts):
        raise ValueError("invalid artifact id")
    base = _ledger_base(project_path).resolve()
    candidate = (base / candidate_id).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("invalid artifact id")
    return candidate


def write_draft_artifact(project_path: Path, payload: dict[str, Any]) -> DraftArtifactRef:
    """Atomically write one bridge artifact below the project's ledger directory."""
    episode = payload.get("episode") if isinstance(payload.get("episode"), int) else None
    artifact_dir = _artifact_dir(project_path, episode)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{timestamp}-{_slugify(payload.get('intent'))}-{uuid.uuid4().hex[:8]}.json"
    path = artifact_dir / filename
    artifact_id = str(path.relative_to(_ledger_base(project_path)))
    atomic_write_json(path, _sanitize_payload(payload, artifact_id))
    return DraftArtifactRef(artifact_id=artifact_id, path=path)


def read_draft_artifact(project_path: Path, artifact_id: str) -> dict[str, Any]:
    """Read one artifact, rejecting path traversal IDs."""
    path = _resolve_artifact_path(project_path, artifact_id)
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("invalid artifact")
    return data


def list_draft_artifacts(project_path: Path, episode: int | None = None) -> list[dict[str, Any]]:
    """List draft artifacts for one project, optionally scoped to an episode."""
    base = _ledger_base(project_path)
    if not base.exists():
        return []
    paths = sorted((_artifact_dir(project_path, episode)).glob("*.json")) if episode is not None else sorted(base.glob("*/*.json"))
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = load_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("artifact_id", str(path.relative_to(base)))
        artifacts.append(data)
    return artifacts
