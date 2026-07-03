from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.json_io import atomic_write_json
from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_user
from server.routers import script_review as router_mod
from server.services.script_review import ScriptReviewService


def _drama_step1() -> dict:
    return {
        "title": "第一集",
        "scenes": [
            {
                "scene_id": "E1S01",
                "duration_seconds": 8,
                "segment_break": False,
                "characters_in_scene": ["阿离"],
                "scenes": ["屋檐"],
                "props": ["信纸"],
                "scene_description": "突然，阿离在屋檐下拆开信纸，脸色骤变！",
                "utterances": [{"kind": "dialogue", "speaker": "阿离", "text": "真相？"}],
                "source_text": "突然，阿离拆开信纸，发现真相？",
            }
        ],
    }


def _complete_asset_sheets(project: dict) -> None:
    project.setdefault("characters", {}).setdefault("阿离", {})["character_sheet"] = "characters/ali.png"
    project.setdefault("scenes", {}).setdefault("屋檐", {})["scene_sheet"] = "scenes/eaves.png"
    project.setdefault("props", {}).setdefault("信纸", {})["prop_sheet"] = "props/letter.png"


def _write_step1(pm: ProjectManager, content: dict) -> None:
    drafts = pm.get_project_path("demo") / "drafts" / "episode_1"
    drafts.mkdir(parents=True, exist_ok=True)
    atomic_write_json(drafts / "step1_normalized_script.json", content)


def _make_project(tmp_path: Path) -> ProjectManager:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "Anime", "drama")
    pm.add_character("demo", "阿离", "少女")
    pm.add_project_scene("demo", "屋檐", "雨夜屋檐")
    pm.add_prop("demo", "信纸", "关键证据")
    pm.add_episode("demo", 1, "第一集", "scripts/episode_1.json")
    pm.update_project("demo", _complete_asset_sheets)
    _write_step1(pm, _drama_step1())
    return pm


def _client(monkeypatch, tmp_path: Path) -> tuple[TestClient, ProjectManager]:
    pm = _make_project(tmp_path)
    monkeypatch.setattr(router_mod, "get_project_manager", lambda: pm)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(router_mod.router, prefix="/api/v1")
    return TestClient(app), pm


def test_get_state_defaults_manual_workflow_reviews_and_artifact_ledger(tmp_path: Path) -> None:
    state = ScriptReviewService(_make_project(tmp_path)).get_state("demo", 1)

    assert state["local_workflow_reviews"]["storyboard_decision"] == "pending"
    assert state["local_workflow_reviews"]["video_decision"] == "pending"
    assert state["local_workflow_reviews"]["export_decision"] == "pending"
    assert state["local_workflow_reviews"]["storyboard_checklist"] == {
        "character_consistency": False,
        "scene_prop_consistency": False,
        "shot_count": False,
        "prompt_quality": False,
    }
    assert state["local_workflow_artifacts"] == {
        "seedance_prompt": "",
        "storyboard": {"path": "", "url": "", "note": "", "updated_at": None},
        "video": {"path": "", "url": "", "note": "", "updated_at": None},
        "export": {"path": "", "url": "", "note": "", "updated_at": None},
    }


def test_set_workflow_review_persists_human_decision_note_and_checklist(tmp_path: Path) -> None:
    pm = _make_project(tmp_path)
    state = ScriptReviewService(pm).set_workflow_review(
        "demo",
        1,
        "video",
        reviewed=False,
        decision="needs_changes",
        note="第 2 段脸部漂移，重生视频。",
        checklist={
            "motion_continuity": True,
            "face_stability": False,
            "duration_rhythm": True,
            "first_last_frame": False,
        },
    )

    reviews = state["local_workflow_reviews"]
    assert reviews["video_reviewed"] is False
    assert reviews["video_reviewed_at"] is None
    assert reviews["video_decision"] == "needs_changes"
    assert reviews["video_note"] == "第 2 段脸部漂移，重生视频。"
    assert reviews["video_checklist"] == {
        "motion_continuity": True,
        "face_stability": False,
        "duration_rhythm": True,
        "first_last_frame": False,
    }
    stored = pm.load_project("demo")["episodes"][0]["local_workflow_reviews"]["video"]
    assert stored["decision"] == "needs_changes"
    assert stored["checklist"]["face_stability"] is False


def test_set_workflow_artifacts_persists_references_only(tmp_path: Path) -> None:
    pm = _make_project(tmp_path)
    state = ScriptReviewService(pm).set_workflow_artifacts(
        "demo",
        1,
        seedance_prompt=" E1S01: 阿离雨夜屋檐下近景，电影感。 ",
        artifacts={
            "storyboard": {"path": "storyboards/e1s01.png", "url": "file:///shots/e1s01.png", "note": "人工确认分镜。"},
            "video": {"path": "videos/e1s01.mp4", "url": "file:///videos/e1s01.mp4", "note": "Seedance 手工导出。"},
            "export": {"path": "exports/e1-final.mp4", "url": "", "note": "剪映成片。"},
        },
    )

    artifacts = state["local_workflow_artifacts"]
    assert artifacts["seedance_prompt"] == "E1S01: 阿离雨夜屋檐下近景，电影感。"
    assert artifacts["storyboard"]["path"] == "storyboards/e1s01.png"
    assert artifacts["storyboard"]["url"] == "file:///shots/e1s01.png"
    assert artifacts["video"]["path"] == "videos/e1s01.mp4"
    assert artifacts["export"]["path"] == "exports/e1-final.mp4"
    assert isinstance(artifacts["storyboard"]["updated_at"], str)
    stored = pm.load_project("demo")["episodes"][0]["local_workflow_artifacts"]
    assert stored["seedance_prompt"] == "E1S01: 阿离雨夜屋檐下近景，电影感。"
    assert "task_id" not in stored["storyboard"]


def test_router_updates_workflow_gate_without_enqueueing_generation(tmp_path: Path, monkeypatch) -> None:
    client, pm = _client(monkeypatch, tmp_path)
    with patch("lib.generation_queue.get_generation_queue", new=AsyncMock()) as queue:
        with client:
            resp = client.put(
                "/api/v1/projects/demo/episodes/1/script-review/workflow-gates/storyboard",
                json={
                    "reviewed": False,
                    "decision": "needs_changes",
                    "note": "先换首帧",
                    "checklist": {
                        "character_consistency": True,
                        "scene_prop_consistency": True,
                        "shot_count": False,
                        "prompt_quality": True,
                    },
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["local_workflow_reviews"]["storyboard_decision"] == "needs_changes"
    assert pm.load_project("demo")["episodes"][0]["local_workflow_reviews"]["storyboard"]["reviewed"] is False
    queue.assert_not_called()


def test_router_updates_artifact_ledger_without_enqueueing_generation(tmp_path: Path, monkeypatch) -> None:
    client, pm = _client(monkeypatch, tmp_path)
    with patch("lib.generation_queue.get_generation_queue", new=AsyncMock()) as queue:
        with client:
            resp = client.put(
                "/api/v1/projects/demo/episodes/1/script-review/workflow-artifacts",
                json={
                    "seedance_prompt": "E1S01: 雨夜屋檐下的近景。",
                    "artifacts": {
                        "storyboard": {
                            "path": "storyboards/e1s01.png",
                            "url": "file:///shots/e1s01.png",
                            "note": "人工确认分镜。",
                        }
                    },
                },
            )

    assert resp.status_code == 200
    assert resp.json()["local_workflow_artifacts"]["storyboard"]["path"] == "storyboards/e1s01.png"
    assert pm.load_project("demo")["episodes"][0]["local_workflow_artifacts"]["storyboard"]["note"] == "人工确认分镜。"
    queue.assert_not_called()


def test_router_rejects_unknown_workflow_gate_and_unknown_checklist_item(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(monkeypatch, tmp_path)
    with client:
        unknown_gate = client.put(
            "/api/v1/projects/demo/episodes/1/script-review/workflow-gates/provider",
            json={"reviewed": True},
        )
        bad_checklist = client.put(
            "/api/v1/projects/demo/episodes/1/script-review/workflow-gates/storyboard",
            json={"reviewed": True, "checklist": {"provider_ready": True}},
        )
        bad_decision = client.put(
            "/api/v1/projects/demo/episodes/1/script-review/workflow-gates/storyboard",
            json={"reviewed": True, "decision": "auto_approved"},
        )

    assert unknown_gate.status_code == 422
    assert bad_checklist.status_code == 422
    assert bad_decision.status_code == 422


def test_router_rejects_unknown_artifact_gate(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(monkeypatch, tmp_path)
    with client:
        resp = client.put(
            "/api/v1/projects/demo/episodes/1/script-review/workflow-artifacts",
            json={"artifacts": {"provider": {"path": "x"}}},
        )

    assert resp.status_code == 422
