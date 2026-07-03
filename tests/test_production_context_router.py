from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_user


def _make_pm(tmp_path: Path) -> ProjectManager:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "Anime", "drama")
    return pm


def _client(monkeypatch, pm: ProjectManager) -> TestClient:
    from server.routers import production_context

    monkeypatch.setattr(production_context, "get_project_manager", lambda: pm)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(production_context.router, prefix="/api/v1")
    return TestClient(app)


def test_get_and_save_production_context(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path))

    initial = client.get("/api/v1/projects/demo/production-context")
    assert initial.status_code == 200
    assert initial.json()["context"]["step_context"]["manual_opt_in_only"] is True

    saved = client.put(
        "/api/v1/projects/demo/production-context",
        json={"project_bible": {"logline": "狐妖用红伞改变命运", "tone": "克制、悬疑"}},
    )
    assert saved.status_code == 200
    assert saved.json()["success"] is True
    assert saved.json()["context"]["project_bible"]["logline"] == "狐妖用红伞改变命运"


def test_append_revision_and_build_manual_snippet(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path))

    revision = client.post(
        "/api/v1/projects/demo/production-context/revisions",
        json={"failure_category": "角色漂移", "human_critique": "发色错了", "next_fix_strategy": "强调银发"},
    )
    assert revision.status_code == 200
    assert revision.json()["revision"]["human_critique"] == "发色错了"

    snippet = client.post("/api/v1/projects/demo/production-context/injection-snippet", json={"latest_revisions": 1})
    assert snippet.status_code == 200
    assert "Manual opt-in context injection" in snippet.json()["snippet"]
    assert "强调银发" in snippet.json()["snippet"]


def test_missing_project_returns_404(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path))

    response = client.get("/api/v1/projects/missing/production-context")

    assert response.status_code == 404


def test_production_context_routes_do_not_enqueue_or_confirm(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path))

    with (
        patch("lib.generation_queue.get_generation_queue", new=AsyncMock()) as queue,
        patch("server.services.script_review.ScriptReviewService.confirm") as confirm,
    ):
        response = client.put(
            "/api/v1/projects/demo/production-context",
            json={"project_bible": {"logline": "manual only"}},
        )

    assert response.status_code == 200
    queue.assert_not_called()
    confirm.assert_not_called()
