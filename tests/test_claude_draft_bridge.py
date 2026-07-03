from __future__ import annotations

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

    parsed = parse_claude_output('{"summary":"ok","findings":[{"code":"x"}]}')
    assert parsed["summary"] == "ok"
    assert parsed["findings"] == [{"code": "x"}]
    assert parsed["raw_text"] == ""

    fallback = parse_claude_output("plain review notes")
    assert fallback["summary"] == "plain review notes"
    assert fallback["raw_text"] == "plain review notes"
