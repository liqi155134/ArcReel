"""Draft-only Claude Code bridge helpers.

This module is deliberately provider-free: it builds a bounded context packet,
constructs a restrictive local Claude CLI command, scrubs inherited environment
variables, and parses draft text into a ledger-friendly shape. It does not run
Claude and does not expose ArcReel MCP/generation tools.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Literal, cast

DraftIntent = Literal["script_review_notes", "step1_rewrite_proposal", "production_context_suggestion"]
SUPPORTED_INTENTS: tuple[DraftIntent, ...] = (
    "script_review_notes",
    "step1_rewrite_proposal",
    "production_context_suggestion",
)

DRAFT_ONLY_SYSTEM_PROMPT = (
    "You are a local Claude Code draft assistant for ArcReel. "
    "Return review notes or proposal artifacts only. "
    "Do not approve gates, mutate project truth, start media work, or run tools."
)

_SAFE_ENV_KEYS = frozenset(
    {
        "HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SHELL",
        "USER",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        # Proxy vars must survive scrubbing: the container routes all outbound
        # traffic through a local no-auth relay, so the child `claude` process
        # cannot reach the Anthropic API without them. These carry no provider
        # secret (auth is injected by the relay, not by these values).
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)
_SENSITIVE_ENV_KEY_PARTS = (
    "API_KEY",
    "AUTH_TOKEN",
    "TOKEN",
    "SECRET",
    "COOKIE",
    "PASSWORD",
    "DATABASE_URL",
    "DB_URL",
    "BASE_URL",
    "ACCESS_KEY",
)
_SENSITIVE_ENV_PREFIXES = (
    "ANTHROPIC",
    "OPENAI",
    "GOOGLE",
    "GEMINI",
    "ARK",
    "VOLCENGINE",
    "DREAMINA",
    "JIMENG",
    "MINIMAX",
    "GROK",
    "XAI",
)
_SENSITIVE_FIELD_PARTS = (
    "api_key",
    "auth_token",
    "token",
    "secret",
    "cookie",
    "password",
    "credential",
    "base_url",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z0-9_]*(?:api[_-]?key|auth[_-]?token|token|secret|cookie|password|access[_-]?key)[a-z0-9_]*\s*=\s*)[^\s,;]+"
)
_MAX_CONTEXT_STRING = 4000


def validate_intent(intent: str) -> DraftIntent:
    """Return a supported draft intent or raise for unsafe/unsupported work."""
    if intent in SUPPORTED_INTENTS:
        return cast(DraftIntent, intent)
    raise ValueError(f"unsupported draft intent: {intent}")


def build_claude_command(claude_bin: str = "claude") -> list[str]:
    """Build the local Claude Code command without granting tools or bypass flags."""
    return [
        claude_bin,
        "-p",
        "--permission-mode",
        "plan",
        "--output-format",
        "json",
        "--system-prompt",
        DRAFT_ONLY_SYSTEM_PROMPT,
    ]


def build_scrubbed_env(source_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a small env for the Claude subprocess, dropping provider/server secrets."""
    if source_env is None:
        return {}

    scrubbed: dict[str, str] = {}
    for key, value in source_env.items():
        upper = key.upper()
        if key not in _SAFE_ENV_KEYS:
            continue
        if upper.startswith(_SENSITIVE_ENV_PREFIXES) or any(part in upper for part in _SENSITIVE_ENV_KEY_PARTS):
            continue
        scrubbed[key] = value
    return scrubbed


def redact_text(text: str) -> str:
    """Redact secret-looking assignments before persisting errors or raw output."""
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}[redacted]", text)


def _is_sensitive_field(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_FIELD_PARTS)


def _sanitize_value(value: Any, *, max_string: int = _MAX_CONTEXT_STRING) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if _is_sensitive_field(key):
                continue
            sanitized[str(key)] = _sanitize_value(child, max_string=max_string)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, max_string=max_string) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, max_string=max_string) for item in value]
    if isinstance(value, str):
        clean = redact_text(value)
        if len(clean) > max_string:
            omitted = len(clean) - max_string
            clean = f"{clean[:max_string]} <truncated {omitted} chars>"
        return clean
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def build_context_packet(
    *,
    project: Mapping[str, Any],
    episode: int | None = None,
    step1_content: Mapping[str, Any] | None = None,
    qa: Mapping[str, Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
    instruction: str = "",
) -> dict[str, Any]:
    """Build a sanitized, bounded prompt context packet for draft-only review."""
    return {
        "schema_version": 1,
        "draft_only": True,
        "project": _sanitize_value(project),
        "episode": episode,
        "step1_content": _sanitize_value(step1_content or {}),
        "qa": _sanitize_value(qa or {}),
        "workflow": _sanitize_value(workflow or {}),
        "instruction": _sanitize_value(instruction),
    }


def context_hash(packet: Mapping[str, Any]) -> str:
    """Return a stable hash for audit without storing unsanitized context."""
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def build_prompt(intent: DraftIntent, packet: Mapping[str, Any]) -> str:
    """Build stdin text for Claude from the already-sanitized context packet."""
    payload = {
        "task": intent,
        "draft_only": True,
        "response_contract": {
            "summary": "short human-readable draft summary",
            "findings": "optional list of issues or suggestions",
            "proposed_patch": "optional draft patch/proposal; never applied automatically",
        },
        "context": packet,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _draft_fields(
    *,
    summary: str = "",
    findings: list[Any] | None = None,
    proposed_patch: Any = None,
    raw_text: str = "",
    is_error: bool = False,
) -> dict[str, Any]:
    return {
        "summary": summary,
        "findings": findings if isinstance(findings, list) else [],
        "proposed_patch": proposed_patch,
        "raw_text": raw_text,
        "is_error": is_error,
    }


def _fields_from_payload(payload: Mapping[str, Any], *, is_error: bool) -> dict[str, Any]:
    summary_value = payload.get("summary", "")
    findings_value = payload.get("findings", [])
    proposed_patch = payload.get("proposed_patch")
    return _draft_fields(
        summary=summary_value if isinstance(summary_value, str) else json.dumps(summary_value, ensure_ascii=False),
        findings=findings_value if isinstance(findings_value, list) else [],
        proposed_patch=proposed_patch,
        raw_text="",
        is_error=is_error,
    )


def parse_claude_output(stdout: str) -> dict[str, Any]:
    """Parse `claude -p --output-format json` output into ledger-friendly fields.

    The CLI wraps model output in a result envelope
    ``{"type":"result","is_error":...,"result":"<model text>", ...}``; the model's
    actual content lives under ``.result`` (itself a JSON string when the system
    prompt asks for structured output). This unwraps the envelope, then parses the
    inner payload for ``summary``/``findings``/``proposed_patch``. It stays
    backward compatible with the pre-envelope shape where stdout *is* the inner
    JSON object, and falls back to raw draft notes when nothing parses.

    The returned ``is_error`` flag mirrors an error envelope so callers can treat
    the run as failed even when the process exit code was 0.
    """
    clean = redact_text(stdout.strip())
    if not clean:
        return _draft_fields()
    try:
        envelope = json.loads(clean)
    except json.JSONDecodeError:
        return _draft_fields(summary=clean, raw_text=clean)

    is_error = False
    inner: Any = envelope
    if isinstance(envelope, dict) and "result" in envelope:
        # Real CLI envelope: unwrap the model content from `.result`.
        is_error = envelope.get("is_error") is True
        inner = envelope.get("result")

    if isinstance(inner, str):
        inner_clean = inner.strip()
        if not inner_clean:
            return _draft_fields(is_error=is_error)
        try:
            inner = json.loads(inner_clean)
        except json.JSONDecodeError:
            return _draft_fields(summary=inner_clean, raw_text=inner_clean, is_error=is_error)

    if isinstance(inner, dict):
        return _fields_from_payload(inner, is_error=is_error)

    # Inner is a bare list/number/None: surface it as raw draft notes.
    text = "" if inner is None else inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
    return _draft_fields(summary=text, raw_text=text, is_error=is_error)
