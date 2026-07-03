from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.json_io import atomic_write_json
from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_user


class FakeClaudeRunner:
    def __init__(self, stdout: str = '{"summary":"review ok"}', stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[dict] = []

    async def run(self, *, command: list[str], prompt: str, cwd: Path, env: dict[str, str], timeout_seconds: int):
        self.calls.append({"command": command, "prompt": prompt, "cwd": cwd, "env": env, "timeout_seconds": timeout_seconds})
        return {"returncode": 0, "stdout": self.stdout, "stderr": self.stderr}


def _make_pm(tmp_path: Path) -> ProjectManager:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "Anime", "drama")
    pm.add_character("demo", "阿离", "少女")
    pm.add_episode("demo", 1, "第一集", "scripts/episode_1.json")
    drafts = pm.get_project_path("demo") / "drafts" / "episode_1"
    drafts.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        drafts / "step1_normalized_script.json",
        {
            "title": "第一集",
            "scenes": [
                {
                    "scene_id": "E1S01",
                    "duration_seconds": 8,
                    "segment_break": False,
                    "characters_in_scene": ["阿离"],
                    "scenes": [],
                    "props": [],
                    "scene_description": "阿离抬头。",
                    "utterances": [],
                    "source_text": "阿离抬头。",
                }
            ],
        },
    )
    return pm


def _client(monkeypatch, pm: ProjectManager, runner: FakeClaudeRunner) -> TestClient:
    router_mod = importlib.import_module("server.routers.claude_draft_bridge")
    monkeypatch.setattr(router_mod, "get_project_manager", lambda: pm)
    monkeypatch.setattr(router_mod, "get_claude_runner", lambda: runner)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(router_mod.router, prefix="/api/v1")
    return TestClient(app)


def test_create_draft_with_mocked_subprocess_writes_artifact(tmp_path: Path, monkeypatch) -> None:
    pm = _make_pm(tmp_path)
    runner = FakeClaudeRunner()
    client = _client(monkeypatch, pm, runner)

    response = client.post(
        "/api/v1/projects/demo/claude-drafts",
        json={"intent": "script_review_notes", "episode": 1, "instruction": "请审阅", "timeout_seconds": 30},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["intent"] == "script_review_notes"
    assert payload["output"]["summary"] == "review ok"
    assert runner.calls, "subprocess runner should be mocked and called once"
    call = runner.calls[0]
    assert "claude" in call["command"][0]
    assert "--permission-mode" in call["command"]
    assert "ANTHROPIC_API_KEY" not in call["env"]
    assert payload["artifact_id"]

    listed = client.get("/api/v1/projects/demo/claude-drafts?episode=1")
    assert listed.status_code == 200
    assert listed.json()[0]["artifact_id"] == payload["artifact_id"]

    loaded = client.get(f"/api/v1/projects/demo/claude-drafts/{payload['artifact_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["artifact_id"] == payload["artifact_id"]


def test_create_draft_refuses_unsupported_intent(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path), FakeClaudeRunner())

    response = client.post("/api/v1/projects/demo/claude-drafts", json={"intent": "generate_video", "episode": 1})

    assert response.status_code == 422


def test_create_draft_refuses_missing_project(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path), FakeClaudeRunner())

    response = client.post("/api/v1/projects/missing/claude-drafts", json={"intent": "script_review_notes"})

    assert response.status_code == 404


def test_bridge_routes_never_enqueue_generation_or_confirm_review(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, _make_pm(tmp_path), FakeClaudeRunner())

    with (
        patch("lib.generation_queue.get_generation_queue", new=AsyncMock()) as queue,
        patch("server.services.script_review.ScriptReviewService.confirm") as confirm,
    ):
        response = client.post("/api/v1/projects/demo/claude-drafts", json={"intent": "script_review_notes", "episode": 1})

    assert response.status_code == 200
    queue.assert_not_called()
    confirm.assert_not_called()
