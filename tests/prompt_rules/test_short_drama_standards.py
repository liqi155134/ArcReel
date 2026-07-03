from pathlib import Path

import pytest

from lib.prompt_builders_script import (
    build_drama_prompt,
    build_narration_prompt,
    build_normalize_prompt,
    render_drama_content_for_step2,
)

REPO = Path(__file__).resolve().parents[2]


def _load_standards() -> tuple[str, str, str, str]:
    try:
        from lib.prompt_rules.creative_quality import CREATIVE_QUALITY_RULES
        from lib.prompt_rules.seedance_policy import SEEDANCE_PROMPT_POLICY
        from lib.prompt_rules.short_drama_standards import render_short_drama_standards_section
        from lib.prompt_rules.storyboard_continuity import STORYBOARD_CONTINUITY_RULES
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing standards module: {exc.name}")

    return (
        render_short_drama_standards_section("drama"),
        SEEDANCE_PROMPT_POLICY,
        STORYBOARD_CONTINUITY_RULES,
        CREATIVE_QUALITY_RULES,
    )


def _sample_prompts() -> list[str]:
    overview = {"synopsis": "女主重生复仇", "genre": "短剧", "theme": "逆袭", "world_setting": "现代豪门"}
    characters = {"林清": {}}
    scenes = {"客厅": {}}
    props = {"信纸": {}}

    narration_prompt = build_narration_prompt(
        project_overview=overview,
        style="写实",
        style_description="电影感",
        characters=characters,
        scenes=scenes,
        props=props,
        step1_segments=[
            {
                "segment_id": "E1S01",
                "duration_seconds": 6,
                "segment_break": True,
                "characters_in_segment": ["林清"],
                "scenes": ["客厅"],
                "props": ["信纸"],
                "novel_text": "林清拆开信纸。",
            }
        ],
        episode=1,
    )
    drama_content = render_drama_content_for_step2(
        [
            {
                "scene_id": "E1S01",
                "duration_seconds": 6,
                "segment_break": True,
                "characters_in_scene": ["林清"],
                "scenes": ["客厅"],
                "props": ["信纸"],
                "scene_description": "林清拆开信纸。",
                "utterances": [],
                "source_text": "林清拆开信纸。",
            }
        ]
    )
    drama_prompt = build_drama_prompt(
        project_overview=overview,
        style="写实",
        style_description="电影感",
        scenes_content=drama_content,
        episode=1,
    )
    normalize_prompt = build_normalize_prompt(
        novel_text="林清拆开信纸。",
        project_overview=overview,
        style="写实",
        characters=characters,
        scenes=scenes,
        props=props,
        default_duration=6,
        supported_durations=[4, 6, 8],
        episode=1,
    )
    return [narration_prompt, drama_prompt, normalize_prompt]


def test_standards_keywords_and_phase1_boundary() -> None:
    section, _, _, _ = _load_standards()

    assert "Seedance" in section
    assert "supported_durations" in section
    assert "C/S/P" in section
    assert "first-frame / last-frame" in section
    assert "paywall marker" in section
    assert "Phase 1" in section
    assert "block" in section
    assert "新模型供应商" not in section


def test_standards_keep_subjective_checks_soft_and_manual() -> None:
    _, policy, continuity, quality = _load_standards()
    text = "\n".join([policy, continuity, quality])

    assert "宜" in text
    assert "warn" in text
    assert "只有机械可判定" in text
    assert "必须调用" not in text
    assert "无人值守" not in text


def test_unknown_mode_raises() -> None:
    try:
        from lib.prompt_rules.short_drama_standards import render_short_drama_standards_section
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing standards module: {exc.name}")

    with pytest.raises(ValueError, match="unknown content_mode"):
        render_short_drama_standards_section("unknown")


def test_docs_mirror_importable_standards() -> None:
    doc_path = REPO / "docs/short_drama_standards/phase1-standards-pack.md"
    assert doc_path.exists(), "missing human-review standards pack document"
    doc = doc_path.read_text(encoding="utf-8")

    for expected in [
        "Seedance visual prompt policy",
        "C/S/P",
        "Creative quality checklist",
        "deterministic mechanical failures block",
    ]:
        assert expected in doc


def test_prompt_builders_inject_short_drama_standards_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCREEL_PROMPT_RULES_V2", raising=False)
    _, policy, continuity, quality = _load_standards()

    for prompt in _sample_prompts():
        assert "短剧 / Seedance 制作标准（Phase 1）" in prompt
        assert policy in prompt
        assert continuity in prompt
        assert quality in prompt


def test_prompt_builders_omit_standards_when_v2_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCREEL_PROMPT_RULES_V2", "off")

    for prompt in _sample_prompts():
        assert "短剧 / Seedance 制作标准（Phase 1）" not in prompt
        assert "Seedance 视觉提示词策略" not in prompt
