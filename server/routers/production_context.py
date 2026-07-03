"""Production Context / Project Bible API.

Endpoints expose manual sidecar state and a copyable snippet. They do not call
providers, start Claude, confirm workflow gates, or enqueue generation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from lib.app_data_dir import app_data_dir
from lib.production_context import ProductionContextService
from lib.project_manager import ProjectManager
from server.auth import CurrentUser

router = APIRouter()
pm = ProjectManager(app_data_dir())


def get_project_manager() -> ProjectManager:
    return pm


def get_production_context_service() -> ProductionContextService:
    return ProductionContextService(get_project_manager())


class ProductionContextPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_bible: dict[str, Any] | None = None
    step_context: dict[str, Any] | None = None
    revision_memory: list[Any] | None = None
    acceptance_checklist: list[Any] | None = None


class RevisionMemoryPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    step: str | None = None
    shot_id: str | None = None
    failure_category: str | None = None
    previous_prompt: str | None = None
    human_critique: str | None = None
    next_fix_strategy: str | None = None
    before_after_versions: list[Any] | None = None
    acceptance_checklist: list[Any] | None = None


class InjectionSnippetRequest(BaseModel):
    latest_revisions: int = Field(default=3, ge=0, le=20)


@router.get("/projects/{project_name}/production-context")
async def get_production_context(project_name: str, _user: CurrentUser) -> dict[str, Any]:
    try:
        context = await asyncio.to_thread(get_production_context_service().get_context, project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"context": context}


@router.put("/projects/{project_name}/production-context")
async def save_production_context(
    project_name: str,
    payload: ProductionContextPayload,
    _user: CurrentUser,
) -> dict[str, Any]:
    try:
        context = await asyncio.to_thread(
            get_production_context_service().save_context,
            project_name,
            payload.model_dump(exclude_none=True),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "context": context}


@router.post("/projects/{project_name}/production-context/revisions")
async def append_revision_memory(
    project_name: str,
    payload: RevisionMemoryPayload,
    _user: CurrentUser,
) -> dict[str, Any]:
    try:
        service = get_production_context_service()
        revision = await asyncio.to_thread(service.append_revision, project_name, payload.model_dump(exclude_none=True))
        context = await asyncio.to_thread(service.get_context, project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "revision": revision, "context": context}


@router.post("/projects/{project_name}/production-context/injection-snippet")
async def build_manual_injection_snippet(
    project_name: str,
    payload: InjectionSnippetRequest,
    _user: CurrentUser,
) -> dict[str, Any]:
    try:
        snippet = await asyncio.to_thread(
            get_production_context_service().build_manual_injection,
            project_name,
            latest_revisions=payload.latest_revisions,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"snippet": snippet}
