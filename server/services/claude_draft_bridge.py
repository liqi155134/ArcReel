"""Backend service for explicit, draft-only local Claude bridge runs."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TypedDict

from lib.claude_draft_artifacts import list_draft_artifacts, read_draft_artifact, write_draft_artifact
from lib.claude_draft_bridge import (
    build_claude_command,
    build_context_packet,
    build_prompt,
    build_scrubbed_env,
    context_hash,
    parse_claude_output,
    redact_text,
    validate_intent,
)
from lib.project_manager import ProjectManager
from server.services.script_review import ScriptReviewError, ScriptReviewService


class ClaudeRunResult(TypedDict):
    returncode: int
    stdout: str
    stderr: str


class ClaudeRunner(Protocol):
    async def run(
        self,
        *,
        command: list[str],
        prompt: str,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> ClaudeRunResult: ...


class LocalClaudeRunner:
    """Small subprocess wrapper; tests inject a fake runner and never call this."""

    async def run(
        self,
        *,
        command: list[str],
        prompt: str,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> ClaudeRunResult:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")), timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"returncode": 124, "stdout": "", "stderr": "Claude draft run timed out"}
        return {
            "returncode": proc.returncode if proc.returncode is not None else 1,
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        }


class ClaudeDraftBridgeService:
    def __init__(self, pm: ProjectManager, runner: ClaudeRunner | None = None):
        self.pm = pm
        self.runner = runner or LocalClaudeRunner()

    async def create_draft(
        self,
        project_name: str,
        *,
        intent: str,
        episode: int | None = None,
        instruction: str = "",
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        draft_intent = validate_intent(intent)
        timeout = _normalize_timeout(timeout_seconds)
        project = self.pm.load_project(project_name)
        project_path = self.pm.get_project_path(project_name)
        review_context = _load_review_context(self.pm, project_name, episode)
        packet = build_context_packet(
            project=project,
            episode=episode,
            step1_content=review_context.get("step1_content"),
            qa=review_context.get("qa"),
            workflow=review_context.get("workflow"),
            instruction=instruction,
        )
        command = build_claude_command()
        env = build_scrubbed_env(os.environ)
        prompt = build_prompt(draft_intent, packet)
        run_result = await self.runner.run(
            command=command,
            prompt=prompt,
            cwd=project_path,
            env=env,
            timeout_seconds=timeout,
        )
        payload = _build_artifact_payload(
            project_name=project_name,
            episode=episode,
            intent=draft_intent,
            packet=packet,
            run_result=run_result,
        )
        artifact = write_draft_artifact(project_path, payload)
        return read_draft_artifact(project_path, artifact.artifact_id)

    def list_drafts(self, project_name: str, episode: int | None = None) -> list[dict[str, Any]]:
        project_path = self.pm.get_project_path(project_name)
        return list_draft_artifacts(project_path, episode=episode)

    def read_draft(self, project_name: str, artifact_id: str) -> dict[str, Any]:
        project_path = self.pm.get_project_path(project_name)
        return read_draft_artifact(project_path, artifact_id)


def _normalize_timeout(timeout_seconds: int) -> int:
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    return min(timeout_seconds, 300)


def _load_review_context(pm: ProjectManager, project_name: str, episode: int | None) -> dict[str, Any]:
    if episode is None:
        return {"step1_content": {}, "qa": {}, "workflow": {}}
    try:
        state = ScriptReviewService(pm).get_state(project_name, episode)
    except ScriptReviewError as exc:
        return {
            "step1_content": {},
            "qa": {"script_review_error": exc.code},
            "workflow": {},
        }
    qa_keys = ("qa_gate_status", "qa_summary", "qa_findings", "blocking_findings", "warnings")
    workflow_keys = ("local_workflow_reviews", "local_workflow_artifacts")
    return {
        "step1_content": state.get("content") or {},
        "qa": _select_keys(state, qa_keys),
        "workflow": _select_keys(state, workflow_keys),
    }


def _select_keys(source: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _input_summary(packet: Mapping[str, Any]) -> dict[str, Any]:
    qa = packet.get("qa")
    summary: dict[str, Any] = {}
    if isinstance(qa, Mapping):
        if "qa_gate_status" in qa:
            summary["qa_gate_status"] = qa["qa_gate_status"]
        qa_summary = qa.get("qa_summary")
        if isinstance(qa_summary, Mapping) and "top_codes" in qa_summary:
            summary["top_codes"] = qa_summary["top_codes"]
    return summary


def _build_artifact_payload(
    *,
    project_name: str,
    episode: int | None,
    intent: str,
    packet: Mapping[str, Any],
    run_result: Mapping[str, object],
) -> dict[str, Any]:
    returncode = run_result.get("returncode")
    stdout_value = run_result.get("stdout")
    stderr_value = run_result.get("stderr")
    stdout = stdout_value if isinstance(stdout_value, str) else ""
    stderr = stderr_value if isinstance(stderr_value, str) else ""
    # Parse first, then decide success: the CLI can exit 0 while reporting an error
    # envelope (`is_error=true`), which must still be recorded as a failed run.
    parsed = parse_claude_output(stdout) if returncode == 0 else None
    envelope_error = bool(parsed and parsed.get("is_error"))
    succeeded = returncode == 0 and not envelope_error
    output = {k: v for k, v in parsed.items() if k != "is_error"} if (succeeded and parsed) else {}
    payload: dict[str, Any] = {
        "schema_version": 1,
        "intent": intent,
        "project_name": project_name,
        "episode": episode,
        "status": "succeeded" if succeeded else "failed",
        "context_hash": context_hash(packet),
        "policy": {
            "permission_mode": "plan",
            "tools": [],
            "draft_only": True,
            "env_scrubbed": True,
        },
        "input_summary": _input_summary(packet),
        "output": output,
    }
    if not succeeded:
        if envelope_error and parsed:
            fallback = parsed.get("summary") or parsed.get("raw_text") or "Claude draft run reported an error result"
            payload["error"] = redact_text(stderr or fallback)
        else:
            payload["error"] = redact_text(stderr or f"Claude draft run failed with return code {returncode}")
    return payload
