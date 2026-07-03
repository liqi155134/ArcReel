from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_MD = REPO / "agent_runtime_profile/.claude/agents/extract-chapter-events.md"
WORKFLOW_DOC = REPO / "docs/short_drama_standards/chapter-event-graph.md"


def test_extract_chapter_events_agent_is_asset_only_draft_workflow() -> None:
    md = AGENT_MD.read_text(encoding="utf-8")
    text = md.lower()

    assert "name: extract-chapter-events" in md
    assert "drafts/chapter-events.json" in md
    assert "manual review" in text or "人工审核" in md
    assert "draft artifact" in text or "草稿资产" in md
    assert "event_id" in md
    assert "causal_prev" in md
    assert "temporal_order" in md
    assert "cross_chapter_arcs" in md


def test_extract_chapter_events_agent_does_not_grant_runtime_tools_or_generation() -> None:
    md = AGENT_MD.read_text(encoding="utf-8").lower()

    forbidden = [
        "mcp__arcreel__",
        "confirm_script_review",
        "generate_video",
        "generate_episode_script",
        "enqueue",
        "provider credential",
        "provider secret",
        "claude -p",
    ]
    assert [term for term in forbidden if term in md] == []


def test_chapter_event_graph_doc_declares_schema_stage_deferred() -> None:
    doc = WORKFLOW_DOC.read_text(encoding="utf-8").lower()

    assert "asset-only" in doc
    assert "schema changes are deferred" in doc
    assert "manual review" in doc
    assert "drafts/chapter-events.json" in doc
