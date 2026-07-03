"""HTTP routes for explicit Claude draft-only bridge artifacts."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lib.app_data_dir import app_data_dir
from lib.project_manager import ProjectManager
from server.auth import CurrentUser
from server.services.claude_draft_bridge import ClaudeDraftBridgeService, ClaudeRunner, LocalClaudeRunner

logger = logging.getLogger(__name__)

router = APIRouter()
pm = ProjectManager(app_data_dir())
_runner: ClaudeRunner = LocalClaudeRunner()


class ClaudeDraftRequest(BaseModel):
    intent: str
    episode: int | None = None
    instruction: str = ""
    timeout_seconds: int = Field(default=120, ge=1, le=300)


def get_project_manager() -> ProjectManager:
    return pm


def get_claude_runner() -> ClaudeRunner:
    return _runner


@router.post("/projects/{project_name}/claude-drafts")
async def create_claude_draft(project_name: str, req: ClaudeDraftRequest, _user: CurrentUser):
    """Run one explicit draft-only Claude request and persist its artifact."""
    try:
        service = ClaudeDraftBridgeService(get_project_manager(), get_claude_runner())
        return await service.create_draft(
            project_name,
            intent=req.intent,
            episode=req.episode,
            instruction=req.instruction,
            timeout_seconds=req.timeout_seconds,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/projects/{project_name}/claude-drafts")
async def list_claude_drafts(project_name: str, _user: CurrentUser, episode: int | None = None):
    """List persisted Claude draft artifacts without starting any run."""
    try:
        service = ClaudeDraftBridgeService(get_project_manager(), get_claude_runner())
        return service.list_drafts(project_name, episode=episode)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")


@router.get("/projects/{project_name}/claude-drafts/{artifact_id:path}")
async def read_claude_draft(project_name: str, artifact_id: str, _user: CurrentUser):
    """Read a single persisted Claude draft artifact."""
    try:
        service = ClaudeDraftBridgeService(get_project_manager(), get_claude_runner())
        return service.read_draft(project_name, artifact_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
