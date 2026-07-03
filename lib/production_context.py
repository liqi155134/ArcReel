"""Project-level Production Context / Project Bible sidecar helpers.

The sidecar is manual-first: it stores a compact Project Bible and revision
memory next to ``project.json`` and can build a copyable snippet. Nothing in this
module auto-injects context into generation prompts or calls external services.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lib.json_io import atomic_write_json, load_json_or_none
from lib.project_manager import ProjectManager

CONTEXT_FILENAME = "production_context.json"
SCHEMA_VERSION = 1

DEFAULT_PROJECT_BIBLE: dict[str, Any] = {
    "logline": "",
    "audience": "",
    "tone": "",
    "visual_style": "",
    "world_rules": "",
    "character_anchors": [],
    "scene_anchors": [],
    "prop_anchors": [],
    "negative_constraints": [],
}

DEFAULT_STEP_CONTEXT: dict[str, Any] = {
    "manual_opt_in_only": True,
    "include_project_bible": True,
    "include_previous_step": True,
    "include_revision_memory": True,
    "include_acceptance_checklist": True,
}

DEFAULT_ACCEPTANCE_CHECKLIST: list[dict[str, Any]] = [
    {"id": "continuity", "label": "角色 / 场景 / 道具连续性已检查", "checked": False},
    {"id": "single_action", "label": "单镜头动作清晰且不过载", "checked": False},
    {"id": "references_ready", "label": "参考图 / 首帧 / 素材齐备", "checked": False},
    {"id": "manual_gate", "label": "人工审核通过后再进入生成 / 导出", "checked": False},
]

_REVISION_DEFAULTS: dict[str, Any] = {
    "step": "",
    "shot_id": "",
    "failure_category": "",
    "previous_prompt": "",
    "human_critique": "",
    "next_fix_strategy": "",
    "before_after_versions": [],
    "acceptance_checklist": [],
}


class ProductionContextService:
    """Read/write a project-local Production Bible and revision memory sidecar."""

    def __init__(self, project_manager: ProjectManager):
        self.pm = project_manager

    def get_context(self, project_name: str) -> dict[str, Any]:
        """Return merged defaults without creating the sidecar file."""
        stored = load_json_or_none(self._context_path(project_name))
        return _merge_context(stored if isinstance(stored, dict) else {})

    def save_context(self, project_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Merge and persist a partial or full production context payload."""
        current = self.get_context(project_name)
        context = _merge_context(_deep_merge(current, dict(payload)))
        atomic_write_json(self._context_path(project_name), context)
        return context

    def append_revision(self, project_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Append one human-reviewed retry memory record and persist it."""
        context = self.get_context(project_name)
        revision = _normalize_revision(payload)
        context["revision_memory"].append(revision)
        atomic_write_json(self._context_path(project_name), _merge_context(context))
        return revision

    def build_manual_injection(self, project_name: str, *, latest_revisions: int = 3) -> str:
        """Build a copyable manual opt-in snippet for a future prompt."""
        context = self.get_context(project_name)
        bible = context["project_bible"]
        latest_count = max(0, latest_revisions)
        revisions = context["revision_memory"][-latest_count:] if latest_count else []
        checklist = context["acceptance_checklist"]

        lines = [
            "# Manual opt-in context injection",
            "Attach this snippet only when a human explicitly wants shared project context in the next draft.",
            "",
            "## Project Bible",
        ]
        for key, label in (
            ("logline", "Logline"),
            ("audience", "Audience"),
            ("tone", "Tone"),
            ("visual_style", "Visual style"),
            ("world_rules", "World rules"),
        ):
            value = _stringify(bible.get(key))
            if value:
                lines.append(f"- {label}: {value}")

        for key, label in (
            ("character_anchors", "Character anchors"),
            ("scene_anchors", "Scene anchors"),
            ("prop_anchors", "Prop anchors"),
            ("negative_constraints", "Negative constraints"),
        ):
            items = [_stringify(item) for item in _as_list(bible.get(key))]
            items = [item for item in items if item]
            if items:
                lines.append(f"- {label}: {'; '.join(items)}")

        lines.extend(["", "## Latest Revision Memory"])
        if revisions:
            for revision in revisions:
                failure_category = _stringify(revision.get("failure_category")) or "uncategorized"
                lines.append(f"- Failure category: {failure_category}")
                for key, label in (
                    ("previous_prompt", "Previous prompt"),
                    ("human_critique", "Human critique"),
                    ("next_fix_strategy", "Next fix strategy"),
                ):
                    value = _stringify(revision.get(key))
                    if value:
                        lines.append(f"  - {label}: {value}")
        else:
            lines.append("- No revision memory yet.")

        lines.extend(["", "## Acceptance Checklist"])
        for item in checklist:
            if isinstance(item, Mapping):
                marker = "x" if item.get("checked") is True else " "
                label = _stringify(item.get("label") or item.get("id"))
            else:
                marker = " "
                label = _stringify(item)
            if label:
                lines.append(f"- [{marker}] {label}")
        return "\n".join(lines).strip() + "\n"

    def _context_path(self, project_name: str) -> Path:
        return self.pm.get_project_path(project_name) / CONTEXT_FILENAME


def _default_context() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_bible": copy.deepcopy(DEFAULT_PROJECT_BIBLE),
        "step_context": copy.deepcopy(DEFAULT_STEP_CONTEXT),
        "revision_memory": [],
        "acceptance_checklist": copy.deepcopy(DEFAULT_ACCEPTANCE_CHECKLIST),
    }


def _merge_context(stored: Mapping[str, Any]) -> dict[str, Any]:
    context = _deep_merge(_default_context(), dict(stored))
    context["schema_version"] = SCHEMA_VERSION
    if not isinstance(context.get("project_bible"), dict):
        context["project_bible"] = copy.deepcopy(DEFAULT_PROJECT_BIBLE)
    else:
        context["project_bible"] = _deep_merge(DEFAULT_PROJECT_BIBLE, context["project_bible"])
    if not isinstance(context.get("step_context"), dict):
        context["step_context"] = copy.deepcopy(DEFAULT_STEP_CONTEXT)
    else:
        context["step_context"] = _deep_merge(DEFAULT_STEP_CONTEXT, context["step_context"])
    if not isinstance(context.get("revision_memory"), list):
        context["revision_memory"] = []
    if not isinstance(context.get("acceptance_checklist"), list):
        context["acceptance_checklist"] = copy.deepcopy(DEFAULT_ACCEPTANCE_CHECKLIST)
    return context


def _normalize_revision(payload: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(payload)
    revision = copy.deepcopy(_REVISION_DEFAULTS)
    revision.update(source)
    revision["id"] = _stringify(source.get("id")) or f"rev_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    revision["created_at"] = _stringify(source.get("created_at")) or datetime.now(UTC).isoformat(timespec="seconds")
    for key in ("step", "shot_id", "failure_category", "previous_prompt", "human_critique", "next_fix_strategy"):
        revision[key] = _stringify(revision.get(key))
    revision["before_after_versions"] = _as_list(revision.get("before_after_versions"))
    revision["acceptance_checklist"] = _as_list(revision.get("acceptance_checklist"))
    return revision


def _deep_merge(base: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(dict(base))
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
