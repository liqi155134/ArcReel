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


def parse_claude_output(stdout: str) -> dict[str, Any]:
    """Parse Claude JSON output, falling back to raw draft notes."""
    clean = redact_text(stdout.strip())
    if not clean:
        return {"summary": "", "findings": [], "proposed_patch": None, "raw_text": ""}
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return {"summary": clean, "findings": [], "proposed_patch": None, "raw_text": clean}

    if not isinstance(parsed, dict):
        return {"summary": clean, "findings": [], "proposed_patch": None, "raw_text": clean}

    summary_value = parsed.get("summary", "")
    findings_value = parsed.get("findings", [])
    proposed_patch = parsed.get("proposed_patch")
    return {
        "summary": summary_value if isinstance(summary_value, str) else json.dumps(summary_value, ensure_ascii=False),
        "findings": findings_value if isinstance(findings_value, list) else [],
        "proposed_patch": proposed_patch,
        "raw_text": "",
    }
