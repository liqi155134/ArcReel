from __future__ import annotations

import json
import os

import pytest

SENSITIVE_ENV = {
    "ANTHROPIC_API_KEY": "secret-anthropic",
    "ANTHROPIC_BASE_URL": "https://gateway.example",
    "OPENAI_API_KEY": "secret-openai",
    "ARK_API_KEY": "secret-ark",
    "VOLCENGINE_ACCESS_KEY": "secret-volc",
    "DREAMINA_TOKEN": "secret-dreamina",
    "JIMENG_COOKIE": "secret-jimeng",
    "DATABASE_URL": "sqlite:///secret.db",
}


def test_command_policy_is_draft_only_and_contains_no_tool_grants() -> None:
    from lib.claude_draft_bridge import build_claude_command

    command = build_claude_command()
    joined = " ".join(command)

    assert command[:2] == ["claude", "-p"]
    assert "--permission-mode" in command
    assert "plan" in command
    assert "--output-format" in command
    assert "json" in command
    assert "--system-prompt" in command
    assert "bypassPermissions" not in joined
    assert "dangerously-skip" not in joined
    assert "--bare" not in command
    assert "mcp__arcreel__" not in joined
    assert "confirm_script_review" not in joined
    assert "generate_video" not in joined
    assert "export" not in joined.lower()


def test_scrubbed_env_removes_provider_and_gateway_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from lib.claude_draft_bridge import build_scrubbed_env

    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    for key, value in SENSITIVE_ENV.items():
        monkeypatch.setenv(key, value)

    env = build_scrubbed_env(os.environ)

    assert env["HOME"] == "/home/tester"
    assert "PATH" in env
    for key in SENSITIVE_ENV:
        assert key not in env


def test_scrubbed_env_preserves_proxy_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    from lib.claude_draft_bridge import build_scrubbed_env

    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:18000")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:18000")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")

    env = build_scrubbed_env(os.environ)

    # Proxy vars must survive: the child `claude` reaches the API only through the relay.
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:18000"
    assert env["http_proxy"] == "http://127.0.0.1:18000"
    assert env["NO_PROXY"] == "localhost,127.0.0.1"
    # Provider secrets are still stripped.
    assert "ANTHROPIC_API_KEY" not in env


def test_context_packet_redacts_sensitive_fields_and_caps_large_text() -> None:
    from lib.claude_draft_bridge import build_context_packet

    packet = build_context_packet(
        project={
            "title": "Demo",
            "content_mode": "drama",
            "overview": {"synopsis": "A" * 9000, "secret": "must hide"},
            "api_key": "secret",
            "characters": {"阿离": {"description": "少女"}},
        },
        episode=1,
        step1_content={"title": "第一集", "scenes": [{"source_text": "B" * 9000}]},
        qa={"qa_gate_status": "blocked", "qa_summary": {"top_codes": ["missing_prop_reference"]}},
        workflow={"local_workflow_reviews": {}, "local_workflow_artifacts": {}},
        instruction="请审阅",
    )
    text = str(packet)

    assert packet["episode"] == 1
    assert packet["draft_only"] is True
    assert "secret" not in text
    assert "api_key" not in text
    assert "<truncated" in text
    assert packet["qa"]["qa_gate_status"] == "blocked"


def test_invalid_intent_is_rejected() -> None:
    from lib.claude_draft_bridge import validate_intent

    assert validate_intent("script_review_notes") == "script_review_notes"
    with pytest.raises(ValueError, match="unsupported draft intent"):
        validate_intent("generate_video")


def test_parse_output_accepts_json_and_falls_back_to_raw_text() -> None:
    from lib.claude_draft_bridge import parse_claude_output

    # Backward compat: stdout that is already the inner JSON object (pre-envelope).
    parsed = parse_claude_output('{"summary":"ok","findings":[{"code":"x"}]}')
    assert parsed["summary"] == "ok"
    assert parsed["findings"] == [{"code": "x"}]
    assert parsed["raw_text"] == ""
    assert parsed["is_error"] is False

    fallback = parse_claude_output("plain review notes")
    assert fallback["summary"] == "plain review notes"
    assert fallback["raw_text"] == "plain review notes"


def test_parse_output_unwraps_cli_result_envelope_with_inner_json() -> None:
    from lib.claude_draft_bridge import parse_claude_output

    # Real `claude -p --output-format json` shape: the model's JSON lives in `.result`
    # as a nested JSON string, wrapped in a result envelope.
    envelope = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps(
                {"summary": "review complete", "findings": [{"code": "weak_hook"}], "proposed_patch": None},
                ensure_ascii=False,
            ),
            "session_id": "abc123",
            "total_cost_usd": 0.0123,
        },
        ensure_ascii=False,
    )

    parsed = parse_claude_output(envelope)

    assert parsed["summary"] == "review complete"
    assert parsed["findings"] == [{"code": "weak_hook"}]
    assert parsed["raw_text"] == ""
    assert parsed["is_error"] is False


def test_parse_output_envelope_plain_text_result_goes_to_summary() -> None:
    from lib.claude_draft_bridge import parse_claude_output

    envelope = json.dumps(
        {"type": "result", "is_error": False, "result": "here are my freeform notes", "session_id": "x"}
    )

    parsed = parse_claude_output(envelope)

    assert parsed["summary"] == "here are my freeform notes"
    assert parsed["raw_text"] == "here are my freeform notes"
    assert parsed["is_error"] is False


def test_parse_output_flags_error_envelope_as_failure() -> None:
    from lib.claude_draft_bridge import parse_claude_output

    envelope = json.dumps(
        {"type": "result", "subtype": "error", "is_error": True, "result": "rate limited", "session_id": "x"}
    )

    parsed = parse_claude_output(envelope)

    assert parsed["is_error"] is True
    assert parsed["summary"] == "rate limited"
