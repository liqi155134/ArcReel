from __future__ import annotations

from pathlib import Path

from lib.project_manager import ProjectManager


def _make_pm(tmp_path: Path) -> ProjectManager:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "Anime", "drama")
    return pm


def test_missing_context_returns_defaults_without_writing_file(tmp_path: Path) -> None:
    from lib.production_context import CONTEXT_FILENAME, ProductionContextService

    pm = _make_pm(tmp_path)
    service = ProductionContextService(pm)

    context = service.get_context("demo")

    assert context["schema_version"] == 1
    assert context["project_bible"]["logline"] == ""
    assert context["step_context"]["manual_opt_in_only"] is True
    assert context["revision_memory"] == []
    assert not (pm.get_project_path("demo") / CONTEXT_FILENAME).exists()


def test_save_context_merges_defaults_and_writes_sidecar(tmp_path: Path) -> None:
    from lib.production_context import CONTEXT_FILENAME, ProductionContextService

    pm = _make_pm(tmp_path)
    service = ProductionContextService(pm)

    context = service.save_context(
        "demo",
        {
            "project_bible": {
                "logline": "狐妖用红伞改变命运",
                "tone": "克制、悬疑",
                "negative_constraints": ["不要随机换发色"],
            }
        },
    )

    assert context["project_bible"]["logline"] == "狐妖用红伞改变命运"
    assert context["project_bible"]["tone"] == "克制、悬疑"
    assert context["project_bible"]["visual_style"] == ""
    assert context["project_bible"]["negative_constraints"] == ["不要随机换发色"]
    assert (pm.get_project_path("demo") / CONTEXT_FILENAME).exists()


def test_append_revision_records_human_critique_and_next_fix_strategy(tmp_path: Path) -> None:
    from lib.production_context import ProductionContextService

    service = ProductionContextService(_make_pm(tmp_path))

    revision = service.append_revision(
        "demo",
        {
            "step": "shot_prompt",
            "shot_id": "E01S01",
            "failure_category": "角色漂移",
            "human_critique": "应该保持银发和红伞",
            "next_fix_strategy": "下一版明确银发、红伞、近景",
            "before_after_versions": ["v1", "v2"],
        },
    )
    context = service.get_context("demo")

    assert revision["id"].startswith("rev_")
    assert revision["human_critique"] == "应该保持银发和红伞"
    assert revision["next_fix_strategy"] == "下一版明确银发、红伞、近景"
    assert context["revision_memory"][-1]["shot_id"] == "E01S01"


def test_manual_injection_snippet_is_copyable_and_opt_in(tmp_path: Path) -> None:
    from lib.production_context import ProductionContextService

    service = ProductionContextService(_make_pm(tmp_path))
    service.save_context(
        "demo",
        {
            "project_bible": {
                "logline": "狐妖用红伞改变命运",
                "character_anchors": ["狐妖：银发、红伞、克制"],
                "negative_constraints": ["不要随机换发色"],
            }
        },
    )
    service.append_revision("demo", {"failure_category": "角色漂移", "next_fix_strategy": "保持银发红伞"})

    snippet = service.build_manual_injection("demo", latest_revisions=1)

    assert "Manual opt-in context injection" in snippet
    assert "狐妖用红伞改变命运" in snippet
    assert "狐妖：银发、红伞、克制" in snippet
    assert "保持银发红伞" in snippet
    assert "auto-inject" not in snippet.lower()
