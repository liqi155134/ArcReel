from __future__ import annotations

from pathlib import Path

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


def _complete_asset_sheets(project: dict) -> None:
    project.setdefault("characters", {}).setdefault("阿离", {})["character_sheet"] = "characters/ali.png"
    project.setdefault("scenes", {}).setdefault("屋檐", {})["scene_sheet"] = "scenes/eaves.png"
    project.setdefault("props", {}).setdefault("信纸", {})["prop_sheet"] = "props/letter.png"


def _write_step1(pm: ProjectManager, content: dict) -> None:
    drafts = pm.get_project_path("demo") / "drafts" / "episode_1"
    drafts.mkdir(parents=True, exist_ok=True)
    atomic_write_json(drafts / "step1_normalized_script.json", content)


def _client(monkeypatch, tmp_path: Path) -> tuple[TestClient, ProjectManager]:
    pm = _make_project(tmp_path)
    monkeypatch.setattr(router_mod, "get_project_manager", lambda: pm)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(router_mod.router, prefix="/api/v1")
    return TestClient(app), pm


def test_get_state_defaults_local_workflow_reviews_to_false(tmp_path: Path) -> None:
    pm = _make_project(tmp_path)

    state = ScriptReviewService(pm).get_state("demo", 1)

    assert state["local_workflow_reviews"] == {
        "storyboard_reviewed": False,
        "storyboard_reviewed_at": None,
        "storyboard_decision": "pending",
        "storyboard_note": "",
        "storyboard_checklist": {
            "character_consistency": False,
            "scene_prop_consistency": False,
            "shot_count": False,
            "prompt_quality": False,
        },
        "video_reviewed": False,
        "video_reviewed_at": None,
        "video_decision": "pending",
        "video_note": "",
        "video_checklist": {
            "motion_continuity": False,
            "face_stability": False,
            "duration_rhythm": False,
            "first_last_frame": False,
        },
        "export_reviewed": False,
        "export_reviewed_at": None,
        "export_decision": "pending",
        "export_note": "",
        "export_checklist": {
            "subtitles_audio": False,
            "aspect_cover": False,
            "file_naming": False,
            "final_playback": False,
        },
    }


def test_set_workflow_review_persists_and_can_unset_storyboard_gate(tmp_path: Path) -> None:
    pm = _make_project(tmp_path)
    svc = ScriptReviewService(pm)

    reviewed = svc.set_workflow_review("demo", 1, "storyboard", True)

    assert reviewed["local_workflow_reviews"]["storyboard_reviewed"] is True
    assert isinstance(reviewed["local_workflow_reviews"]["storyboard_reviewed_at"], str)
    episode_meta = pm.load_project("demo")["episodes"][0]
    assert episode_meta["local_workflow_reviews"]["storyboard"]["reviewed"] is True

    unreviewed = svc.set_workflow_review("demo", 1, "storyboard", False)

    assert unreviewed["local_workflow_reviews"]["storyboard_reviewed"] is False
    assert unreviewed["local_workflow_reviews"]["storyboard_reviewed_at"] is None
    episode_meta = pm.load_project("demo")["episodes"][0]
    assert episode_meta["local_workflow_reviews"]["storyboard"]["reviewed"] is False


def test_set_workflow_review_persists_human_decision_and_note(tmp_path: Path) -> None:
    pm = _make_project(tmp_path)
    svc = ScriptReviewService(pm)

    state = svc.set_workflow_review(
        "demo",
        1,
        "storyboard",
        False,
        decision="needs_changes",
        note="第 3 镜角色脸不一致，先重出分镜图。",
    )

    reviews = state["local_workflow_reviews"]
    assert reviews["storyboard_reviewed"] is False
    assert reviews["storyboard_decision"] == "needs_changes"
    assert reviews["storyboard_note"] == "第 3 镜角色脸不一致，先重出分镜图。"

    episode_meta = pm.load_project("demo")["episodes"][0]
    record = episode_meta["local_workflow_reviews"]["storyboard"]
    assert record["reviewed"] is False
    assert record["decision"] == "needs_changes"
    assert record["note"] == "第 3 镜角色脸不一致，先重出分镜图。"


def test_set_workflow_review_persists_manual_checklist(tmp_path: Path) -> None:
    pm = _make_project(tmp_path)
    svc = ScriptReviewService(pm)

    state = svc.set_workflow_review(
        "demo",
        1,
        "video",
        False,
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
    assert reviews["video_checklist"] == {
        "motion_continuity": True,
        "face_stability": False,
        "duration_rhythm": True,
        "first_last_frame": False,
    }

    episode_meta = pm.load_project("demo")["episodes"][0]
    assert episode_meta["local_workflow_reviews"]["video"]["checklist"] == {
        "motion_continuity": True,
        "face_stability": False,
        "duration_rhythm": True,
        "first_last_frame": False,
    }


def test_router_updates_local_workflow_gate(tmp_path: Path, monkeypatch) -> None:
    client, pm = _client(monkeypatch, tmp_path)
    with client:
        base = "/api/v1/projects/demo/episodes/1/script-review/workflow-gates/storyboard"
        resp = client.put(
            base,
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
        assert body["local_workflow_reviews"]["storyboard_reviewed"] is False
        assert body["local_workflow_reviews"]["storyboard_decision"] == "needs_changes"
        assert body["local_workflow_reviews"]["storyboard_note"] == "先换首帧"
        assert body["local_workflow_reviews"]["storyboard_checklist"] == {
            "character_consistency": True,
            "scene_prop_consistency": True,
            "shot_count": False,
            "prompt_quality": True,
        }
        assert pm.load_project("demo")["episodes"][0]["local_workflow_reviews"]["storyboard"]["reviewed"] is False


def test_router_rejects_unknown_local_workflow_gate(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(monkeypatch, tmp_path)
    with client:
        resp = client.put("/api/v1/projects/demo/episodes/1/script-review/workflow-gates/provider", json={"reviewed": True})

        assert resp.status_code == 422
