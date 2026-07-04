"""Dreamina CLI backend 单元测试（mock subprocess，不打真实即梦 CLI）。

测试覆盖：
- ``dreamina_cli_shared``：submit_id 解析、query 状态归一化、错误分类、产物扫描、
  ``run_dreamina`` 子进程封装（含超时杀进程）。
- ``DreaminaCliVideoBackend``：能力声明、命令路由（text2video / image2video /
  frames2video / multimodal2video）、submit 错误处理（compliance fail-fast、
  rate_limit 重试）、generate 端到端（mock 轮询 + 落盘）、resume。
- ``DreaminaCliImageBackend``：能力声明、命令构建、generate 端到端。
- 后端注册：video / image registry 含 ``dreamina-cli``。

所有 dreamina 子进程调用经 mock（``run_dreamina`` / ``asyncio.create_subprocess_exec``），
不依赖本机登录态或积分。

⚠️ 校准标记（运行时输出格式待校准）
   dreamina CLI 的运行时 stdout 格式未实测（需 OAuth 登录后才能校准）。以下解析
   测试按代码**当前解析逻辑**（先 JSON 后正则，宽容匹配）编写，用于固化「期望格式」。
   真实输出校准后如需收窄解析，对应测试应同步更新。已识别的脆弱点：

   1. ``parse_submit_id`` 正则 ``[0-9A-Za-z_-]{6,}`` 较宽 —— 可能误匹配输出中无关
      十六进制串（如错误码 / 时间戳）。校准时应收窄为 CLI 实际 submit_id 格式。
   2. ``parse_query_outcome`` 状态词白名单为硬编码（done/success/completed/...）——
      真实 CLI 可能使用不同的完成态措辞，未命中的会按 ``running`` 继续轮询。
   3. ``classify_cli_error`` 用子串匹配（如 ``"429"``）—— 可能误匹配含 429 的无关
      文本。校准时应据真实错误 JSON 结构精确匹配。
   4. ``poll_until_downloaded`` 在「状态=done 但产物未落盘」时继续轮询到 max_wait ——
      若 CLI 报完成但下载静默失败，会空转到超时。校准时应评估是否加快速失败。
   5. submit 的 exit code 被忽略（只要解析出 submit_id 即认成功）—— 非零退出 +
      可解析 submit_id 的场景按已提交处理，避免重提扣积分；校准时确认此语义正确。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.dreamina_cli_shared import (
    AUDIO_SUFFIXES,
    DEFAULT_CLI_PATH,
    IMAGE_SUFFIXES,
    VIDEO_SUFFIXES,
    DreaminaCliError,
    DreaminaTaskNotFoundError,
    classify_cli_error,
    error_from_cli_output,
    find_downloaded_media,
    is_task_not_found,
    parse_query_outcome,
    parse_submit_id,
    poll_until_downloaded,
    run_dreamina,
)
from lib.providers import PROVIDER_DREAMINA_CLI
from lib.video_backends.base import (
    ResumeExpiredError,
    VideoCapability,
    VideoCapabilityError,
    VideoGenerationRequest,
)

# ──────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────


def _make_fake_proc(
    *,
    returncode: int = 0,
    stdout: bytes = b"",
) -> MagicMock:
    """构造一个假的 asyncio 子进程对象供 ``run_dreamina`` 测试用。

    用 MagicMock 而非 AsyncMock 做 base：AsyncMock 会对任意属性访问自动创建
    coroutine，导致 "coroutine never awaited" 警告。只把 communicate/wait 显式
    设为 AsyncMock 即可。
    """
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _video_request(**overrides) -> VideoGenerationRequest:
    """构造一个默认的 text2video 请求（task_id=None 跳过持久化）。"""
    defaults = dict(
        prompt="猫咪在阳台晒太阳",
        output_path=Path("/tmp/test-output/dreamina.mp4"),
        aspect_ratio="9:16",
        duration_seconds=5,
    )
    defaults.update(overrides)
    return VideoGenerationRequest(**defaults)


def _image_request(**overrides):
    from lib.image_backends.base import ImageGenerationRequest

    defaults = dict(
        prompt="赛博朋克城市夜景",
        output_path=Path("/tmp/test-output/dreamina.png"),
        aspect_ratio="9:16",
    )
    defaults.update(overrides)
    return ImageGenerationRequest(**defaults)


@pytest.fixture
def no_sleep():
    """让 retry 装饰器内的 asyncio.sleep 瞬时完成，避免 rate_limit 重试测试慢。"""
    with patch("asyncio.sleep", new=AsyncMock()):
        yield


# ══════════════════════════════════════════════════════════════
# 1. parse_submit_id —— 输出解析（校准点：格式未实测）
# ══════════════════════════════════════════════════════════════


class TestParseSubmitId:
    """submit_id 解析：先逐行试 JSON（键名 submit_id/submitId），回退正则。

    校准点：以下用例按代码当前解析逻辑编写。真实 CLI 输出格式校准后，
    若 JSON 键名或 submit_id 格式不同，需同步更新。
    """

    def test_json_top_level(self):
        assert parse_submit_id('{"submit_id": "3f6eb41f425d23a3"}') == "3f6eb41f425d23a3"

    def test_json_camel_case(self):
        assert parse_submit_id('{"submitId": "abc123def"}') == "abc123def"

    def test_json_nested_envelope(self):
        """CLI 可能用 data/result 信封包裹 submit_id。"""
        assert parse_submit_id('{"code":0,"data":{"submit_id":"nested-id-001"}}') == "nested-id-001"

    def test_json_int_value(self):
        """submit_id 为整数时转字符串。"""
        assert parse_submit_id('{"submit_id": 123456}') == "123456"

    def test_json_on_second_line(self):
        output = 'Submitting task...\n{"submit_id": "line2-id"}\nDone.'
        assert parse_submit_id(output) == "line2-id"

    def test_json_array_envelope(self):
        output = '[{"submit_id": "arr-id"}]'
        assert parse_submit_id(output) == "arr-id"

    def test_regex_fallback_colon(self):
        """非 JSON 输出时，正则抓 submit_id: <hex>。"""
        assert parse_submit_id("submit_id: 3f6eb41f425d23a3") == "3f6eb41f425d23a3"

    def test_regex_fallback_equals(self):
        assert parse_submit_id("submit_id=3f6eb41f425d23a3") == "3f6eb41f425d23a3"

    def test_regex_fallback_quoted(self):
        """正则也匹配 submit_id\"...\" 形式。"""
        assert parse_submit_id('submit_id"abcdef123456"') == "abcdef123456"

    def test_no_match_returns_none(self):
        assert parse_submit_id("任务提交中，请稍候...") is None

    def test_empty_output_returns_none(self):
        assert parse_submit_id("") is None

    def test_none_json_lines_skipped(self):
        """非 JSON 行（不以 { 或 [ 开头）跳过，不报错。"""
        assert parse_submit_id("普通文本\n不是JSON\nsubmit_id: found-it") == "found-it"

    def test_malformed_json_skipped(self):
        """残缺 JSON 行不报错，回退正则。"""
        assert parse_submit_id('{broken json\nsubmit_id: regex-fallback') == "regex-fallback"

    # ⚠️ 校准点：正则 [0-9A-Za-z_-]{6,} 较宽，可能误匹配无关文本
    def test_regex_could_over_match_short_context(self):
        """正则 {6,} 在长文本中可能匹配到无关的十六进制串。

        这是已知脆弱点：校准时应收窄 submit_id 格式或改用结构化解析。
        此测试固化当前行为（会匹配），非断言正确性。
        """
        # 以下文本含 "submit_id" 后跟较长十六进制 —— 正则会匹配
        result = parse_submit_id("error code submit_id=deadbeefcafebabe in module")
        assert result == "deadbeefcafebabe"


# ══════════════════════════════════════════════════════════════
# 2. parse_query_outcome —— 状态归一化（校准点：状态词未实测）
# ══════════════════════════════════════════════════════════════


class TestParseQueryOutcome:
    """query_result 输出归一化：done / failed / running。

    校准点：状态词白名单为硬编码，真实 CLI 可能使用不同措辞。
    """

    @pytest.mark.parametrize("status", ["done", "success", "succeed", "succeeded", "completed", "finished"])
    def test_done_statuses(self, status):
        output = json.dumps({"status": status})
        outcome = parse_query_outcome(output)
        assert outcome.status == "done"

    @pytest.mark.parametrize("status", ["failed", "fail", "error"])
    def test_failed_statuses(self, status):
        output = json.dumps({"status": status})
        outcome = parse_query_outcome(output)
        assert outcome.status == "failed"

    @pytest.mark.parametrize("status", ["running", "processing", "pending", "queued"])
    def test_running_statuses(self, status):
        output = json.dumps({"status": status})
        outcome = parse_query_outcome(output)
        assert outcome.status == "running"

    def test_nested_status_in_data(self):
        output = json.dumps({"code": 0, "data": {"status": "done"}})
        assert parse_query_outcome(output).status == "done"

    def test_unrecognized_status_as_running(self):
        """未识别的状态词按 running 处理（继续轮询）。"""
        output = json.dumps({"status": "generating"})
        assert parse_query_outcome(output).status == "running"

    def test_no_status_field_as_running(self):
        """无 status 字段按 running 处理。"""
        output = json.dumps({"progress": 50})
        assert parse_query_outcome(output).status == "running"

    def test_regex_fallback_status(self):
        """非 JSON 输出时正则抓 status=<word>。"""
        outcome = parse_query_outcome("status=done task complete")
        assert outcome.status == "done"

    def test_empty_output_as_running(self):
        assert parse_query_outcome("").status == "running"

    def test_raw_preserved(self):
        """raw 字段保留原始输出供错误消息使用。"""
        output = '{"status": "failed"}'
        assert parse_query_outcome(output).raw == output


# ══════════════════════════════════════════════════════════════
# 3. classify_cli_error —— 错误分类（校准点：文案未实测）
# ══════════════════════════════════════════════════════════════


class TestClassifyError:
    """错误分类优先级：compliance > moderation > rate_limit > cli。"""

    def test_compliance(self):
        assert classify_cli_error("AigcComplianceConfirmationRequired") == "compliance"

    def test_compliance_case_insensitive(self):
        assert classify_cli_error("aigccomplianceconfirmationrequired") == "compliance"

    @pytest.mark.parametrize("text", ["内容审核不通过", "审核失败", "content moderation", "risk control"])
    def test_moderation(self, text):
        assert classify_cli_error(text) == "moderation"

    @pytest.mark.parametrize("text", ["rate limit exceeded", "429 too many requests", "限流", "请求过于频繁"])
    def test_rate_limit(self, text):
        assert classify_cli_error(text) == "rate_limit"

    def test_cli_default(self):
        assert classify_cli_error("some unknown cli error") == "cli"

    def test_compliance_takes_priority_over_moderation(self):
        """compliance 文案里可能含「审核」措辞，优先判 compliance。"""
        assert classify_cli_error("AigcComplianceConfirmationRequired 内容审核") == "compliance"


class TestErrorFromCliOutput:
    def test_compliance_not_retryable(self):
        exc = error_from_cli_output("AigcComplianceConfirmationRequired", context="submit")
        assert isinstance(exc, DreaminaCliError)
        assert exc.kind == "compliance"
        assert exc.retryable is False

    def test_moderation_not_retryable(self):
        exc = error_from_cli_output("内容审核不通过", context="submit")
        assert exc.kind == "moderation"
        assert exc.retryable is False

    def test_rate_limit_retryable(self):
        exc = error_from_cli_output("rate limit exceeded", context="submit")
        assert exc.kind == "rate_limit"
        assert exc.retryable is True

    def test_cli_not_retryable(self):
        exc = error_from_cli_output("unknown error", context="submit")
        assert exc.kind == "cli"
        assert exc.retryable is False

    def test_message_truncated(self):
        """超长输出截断到 300 字符，避免灌入 error_message。"""
        long_output = "x " * 500
        exc = error_from_cli_output(long_output, context="submit")
        # 原始 1000 字符截断为 300
        assert len(exc.args[0]) < 400  # 截断 + 固定文案


class TestIsTaskNotFound:
    @pytest.mark.parametrize("text", ["task not found", "no such task", "任务不存在", "已过期", "expired"])
    def test_not_found(self, text):
        assert is_task_not_found(text) is True

    def test_not_not_found(self):
        assert is_task_not_found("task running") is False


# ══════════════════════════════════════════════════════════════
# 4. find_downloaded_media —— 产物落盘扫描
# ══════════════════════════════════════════════════════════════


class TestFindDownloadedMedia:
    def test_finds_video_files(self, tmp_path):
        (tmp_path / "video1.mp4").write_bytes(b"data1")
        (tmp_path / "video2.mov").write_bytes(b"data2")
        (tmp_path / "readme.txt").write_bytes(b"ignore")
        result = find_downloaded_media(tmp_path, VIDEO_SUFFIXES)
        assert len(result) == 2
        assert all(p.suffix in VIDEO_SUFFIXES for p in result)

    def test_finds_image_files(self, tmp_path):
        (tmp_path / "img.png").write_bytes(b"data")
        result = find_downloaded_media(tmp_path, IMAGE_SUFFIXES)
        assert len(result) == 1
        assert result[0].suffix == ".png"

    def test_skips_zero_byte_files(self, tmp_path):
        (tmp_path / "empty.mp4").write_bytes(b"")
        (tmp_path / "real.mp4").write_bytes(b"data")
        result = find_downloaded_media(tmp_path, VIDEO_SUFFIXES)
        assert len(result) == 1
        assert result[0].name == "real.mp4"

    def test_skips_hidden_and_temp_files(self, tmp_path):
        (tmp_path / ".hidden.mp4").write_bytes(b"data")
        (tmp_path / "partial.part").write_bytes(b"data")
        (tmp_path / "temp.tmp").write_bytes(b"data")
        (tmp_path / "dl.download").write_bytes(b"data")
        (tmp_path / "real.mp4").write_bytes(b"data")
        result = find_downloaded_media(tmp_path, VIDEO_SUFFIXES)
        assert len(result) == 1
        assert result[0].name == "real.mp4"

    def test_sorted_by_mtime(self, tmp_path):
        import os
        import time

        old = tmp_path / "old.mp4"
        new = tmp_path / "new.mp4"
        old.write_bytes(b"old")
        time.sleep(0.05)
        new.write_bytes(b"new")
        # set distinct mtimes
        os.utime(old, (1, 1))
        os.utime(new, (2, 2))
        result = find_downloaded_media(tmp_path, VIDEO_SUFFIXES)
        assert result[0] == old
        assert result[1] == new

    def test_nonexistent_dir_returns_empty(self):
        assert find_downloaded_media(Path("/nonexistent-dir-xyz"), VIDEO_SUFFIXES) == []

    def test_finds_files_in_subdirs(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.mp4").write_bytes(b"data")
        result = find_downloaded_media(tmp_path, VIDEO_SUFFIXES)
        assert len(result) == 1

    def test_audio_suffixes(self, tmp_path):
        (tmp_path / "audio.mp3").write_bytes(b"data")
        (tmp_path / "audio.wav").write_bytes(b"data")
        result = find_downloaded_media(tmp_path, AUDIO_SUFFIXES)
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════
# 5. run_dreamina —— 子进程封装（mock asyncio.create_subprocess_exec）
# ══════════════════════════════════════════════════════════════


class TestRunDreamina:
    """run_dreamina 子进程封装：exec（不经 shell）、超时杀进程、stderr 合流。"""

    @pytest.mark.asyncio
    async def test_success(self):
        proc = _make_fake_proc(returncode=0, stdout=b'{"submit_id": "abc123"}')
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            code, output = await run_dreamina("dreamina", ["text2video", "--prompt=hi"], timeout=10)
        assert code == 0
        assert "abc123" in output

    @pytest.mark.asyncio
    async def test_nonzero_returncode(self):
        proc = _make_fake_proc(returncode=1, stdout=b"some error")
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            code, output = await run_dreamina("dreamina", ["text2video"], timeout=10)
        assert code == 1
        assert "some error" in output

    @pytest.mark.asyncio
    async def test_stdout_decoded_utf8(self):
        proc = _make_fake_proc(returncode=0, stdout="中文输出".encode())
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            _, output = await run_dreamina("dreamina", ["text2video"], timeout=10)
        assert "中文输出" in output

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self):
        """超时后 kill 进程并 wait，抛出 TimeoutError。"""
        proc = _make_fake_proc(returncode=0, stdout=b"")
        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
            patch("asyncio.wait_for", new=AsyncMock(side_effect=TimeoutError)),
        ):
            with pytest.raises(TimeoutError):
                await run_dreamina("dreamina", ["text2video"], timeout=0.01)
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()

    @pytest.mark.filterwarnings("ignore:coroutine.*never awaited:RuntimeWarning")
    @pytest.mark.asyncio
    async def test_none_returncode_becomes_negative(self):
        """proc.returncode 为 None 时返回 -1。"""
        proc = _make_fake_proc(returncode=0, stdout=b"")
        proc.returncode = None
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            code, _ = await run_dreamina("dreamina", ["text2video"], timeout=10)
        assert code == -1

    @pytest.mark.asyncio
    async def test_args_passed_as_list_not_shell(self):
        """参数以 list 传给 create_subprocess_exec，不经 shell（中文 prompt 安全）。"""
        proc = _make_fake_proc(returncode=0, stdout=b"")
        mock_exec = AsyncMock(return_value=proc)
        with patch("asyncio.create_subprocess_exec", new=mock_exec):
            await run_dreamina("dreamina", ["text2video", "--prompt=猫咪"], timeout=10)
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args.args[0] == "dreamina"
        assert call_args.args[1] == "text2video"
        assert "--prompt=猫咪" in call_args.args


# ══════════════════════════════════════════════════════════════
# 6. poll_until_downloaded —— 轮询循环（mock run_dreamina）
# ══════════════════════════════════════════════════════════════


class TestPollUntilDownloaded:
    @pytest.mark.asyncio
    async def test_file_appears_returns_immediately(self, tmp_path):
        """第一轮查询后产物落盘，立即返回。"""
        media = tmp_path / "out.mp4"
        media.write_bytes(b"video-data")

        async def fake_run(cli, args, *, timeout):
            return 0, '{"status": "done"}'

        with patch("lib.dreamina_cli_shared.run_dreamina", side_effect=fake_run):
            result = await poll_until_downloaded(
                cli_path="dreamina",
                submit_id="test-id",
                download_dir=tmp_path,
                suffixes=VIDEO_SUFFIXES,
                poll_interval=0.01,
                max_wait=5,
                query_timeout=2,
                label="Test",
            )
        # file already exists from start
        assert len(result) == 1
        assert result[0].suffix == ".mp4"

    @pytest.mark.asyncio
    async def test_task_not_found_raises(self, tmp_path):
        async def fake_run(cli, args, *, timeout):
            return 0, "task not found"

        with (
            patch("lib.dreamina_cli_shared.run_dreamina", side_effect=fake_run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(DreaminaTaskNotFoundError) as exc_info:
                await poll_until_downloaded(
                    cli_path="dreamina",
                    submit_id="gone-id",
                    download_dir=tmp_path,
                    suffixes=VIDEO_SUFFIXES,
                    poll_interval=0.01,
                    max_wait=5,
                    query_timeout=2,
                    label="Test",
                )
            assert exc_info.value.submit_id == "gone-id"

    @pytest.mark.asyncio
    async def test_compliance_raises_immediately(self, tmp_path):
        """compliance 错误立即终态失败，不轮询。"""
        call_count = 0

        async def fake_run(cli, args, *, timeout):
            nonlocal call_count
            call_count += 1
            return 0, "AigcComplianceConfirmationRequired"

        with (
            patch("lib.dreamina_cli_shared.run_dreamina", side_effect=fake_run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(DreaminaCliError) as exc_info:
                await poll_until_downloaded(
                    cli_path="dreamina",
                    submit_id="comp-id",
                    download_dir=tmp_path,
                    suffixes=VIDEO_SUFFIXES,
                    poll_interval=0.01,
                    max_wait=5,
                    query_timeout=2,
                    label="Test",
                )
            assert exc_info.value.kind == "compliance"
            assert call_count == 1  # fail-fast, no retry

    @pytest.mark.asyncio
    async def test_failed_status_raises(self, tmp_path):
        async def fake_run(cli, args, *, timeout):
            return 0, '{"status": "failed"}'

        with (
            patch("lib.dreamina_cli_shared.run_dreamina", side_effect=fake_run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(DreaminaCliError):
                await poll_until_downloaded(
                    cli_path="dreamina",
                    submit_id="fail-id",
                    download_dir=tmp_path,
                    suffixes=VIDEO_SUFFIXES,
                    poll_interval=0.01,
                    max_wait=5,
                    query_timeout=2,
                    label="Test",
                )

    @pytest.mark.asyncio
    async def test_timeout_when_no_file(self, tmp_path):
        """无产物 + 一直 running → 超时抛 TimeoutError。"""
        async def fake_run(cli, args, *, timeout):
            return 0, '{"status": "running"}'

        with (
            patch("lib.dreamina_cli_shared.run_dreamina", side_effect=fake_run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(TimeoutError):
                await poll_until_downloaded(
                    cli_path="dreamina",
                    submit_id="slow-id",
                    download_dir=tmp_path,
                    suffixes=VIDEO_SUFFIXES,
                    poll_interval=0.01,
                    max_wait=0.05,
                    query_timeout=0.02,
                    label="Test",
                )

    @pytest.mark.asyncio
    async def test_single_query_timeout_continues(self, tmp_path):
        """单轮查询超时（TimeoutError）不终态，继续下一轮。"""
        media = tmp_path / "delayed.mp4"
        call_count = 0

        async def fake_run(cli, args, *, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError
            # second call: create the file then return done
            media.write_bytes(b"data")
            return 0, '{"status": "done"}'

        with (
            patch("lib.dreamina_cli_shared.run_dreamina", side_effect=fake_run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await poll_until_downloaded(
                cli_path="dreamina",
                submit_id="timeout-id",
                download_dir=tmp_path,
                suffixes=VIDEO_SUFFIXES,
                poll_interval=0.01,
                max_wait=5,
                query_timeout=2,
                label="Test",
            )
            assert len(result) == 1
            assert call_count >= 2


# ══════════════════════════════════════════════════════════════
# 7. DreaminaCliVideoBackend —— 能力声明
# ══════════════════════════════════════════════════════════════


class TestVideoBackendCapabilities:
    def test_name(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        backend = DreaminaCliVideoBackend()
        assert backend.name == PROVIDER_DREAMINA_CLI

    def test_default_model(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        assert DreaminaCliVideoBackend().model == "seedance2.0fast"

    def test_custom_model(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        assert DreaminaCliVideoBackend(model="seedance1.0").model == "seedance1.0"

    def test_capabilities(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        backend = DreaminaCliVideoBackend()
        assert VideoCapability.TEXT_TO_VIDEO in backend.capabilities
        assert VideoCapability.IMAGE_TO_VIDEO in backend.capabilities

    def test_video_capabilities_2x_family(self):
        """2.0 家族：首帧 + 尾帧 + 多参考图（不与首帧叠加）。"""
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        caps = DreaminaCliVideoBackend().video_capabilities
        assert caps.first_frame is True
        assert caps.last_frame is True
        assert caps.reference_images is True
        assert caps.reference_images_with_start_frame is False

    def test_video_capabilities_1x_family(self):
        """1.0 系：首帧支持，无多参考；1.5pro 支持尾帧。"""
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        caps_10 = DreaminaCliVideoBackend(model="seedance1.0").video_capabilities
        assert caps_10.first_frame is True
        assert caps_10.last_frame is False

        caps_15pro = DreaminaCliVideoBackend(model="seedance1.5pro").video_capabilities
        assert caps_15pro.first_frame is True
        assert caps_15pro.last_frame is True

    def test_cli_path_default(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        assert DreaminaCliVideoBackend()._cli_path == DEFAULT_CLI_PATH

    def test_custom_cli_path(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        assert DreaminaCliVideoBackend(cli_path="/usr/local/bin/dreamina")._cli_path == "/usr/local/bin/dreamina"


# ══════════════════════════════════════════════════════════════
# 8. DreaminaCliVideoBackend —— 命令路由与参数构建
# ══════════════════════════════════════════════════════════════


class TestVideoBuildCommand:
    def _backend(self, **kw):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        return DreaminaCliVideoBackend(**kw)

    def test_text2video(self):
        backend = self._backend()
        args = backend._build_command(_video_request(prompt="跳舞", aspect_ratio="16:9", duration_seconds=10))
        assert args[0] == "text2video"
        assert "--prompt=跳舞" in args
        assert "--ratio=16:9" in args
        assert "--duration=10" in args
        assert "--model_version=seedance2.0fast" in args

    def test_image2video(self, tmp_path):
        img = tmp_path / "start.png"
        img.write_bytes(b"img")
        backend = self._backend()
        args = backend._build_command(_video_request(start_image=img))
        assert args[0] == "image2video"
        assert any(a.startswith("--image=") for a in args)
        assert "--prompt=" in " ".join(args)

    def test_frames2video(self, tmp_path):
        start = tmp_path / "first.png"
        end = tmp_path / "last.png"
        start.write_bytes(b"s")
        end.write_bytes(b"e")
        backend = self._backend()
        args = backend._build_command(_video_request(start_image=start, end_image=end))
        assert args[0] == "frames2video"
        assert any(a.startswith("--first=") for a in args)
        assert any(a.startswith("--last=") for a in args)

    def test_multimodal2video(self, tmp_path):
        ref1 = tmp_path / "ref1.png"
        ref2 = tmp_path / "ref2.png"
        ref1.write_bytes(b"1")
        ref2.write_bytes(b"2")
        backend = self._backend()
        args = backend._build_command(_video_request(reference_images=[ref1, ref2]))
        assert args[0] == "multimodal2video"
        image_flags = [a for a in args if a.startswith("--image=")]
        assert len(image_flags) == 2

    def test_multimodal2video_routes_video_and_audio(self, tmp_path):
        img = tmp_path / "ref.png"
        vid = tmp_path / "ref.mp4"
        aud = tmp_path / "ref.mp3"
        for f in (img, vid, aud):
            f.write_bytes(b"x")
        backend = self._backend()
        args = backend._build_command(_video_request(reference_images=[img, vid, aud]))
        assert args[0] == "multimodal2video"
        assert any(a.startswith("--image=") for a in args)
        assert any(a.startswith("--video=") for a in args)
        assert any(a.startswith("--audio=") for a in args)

    def test_rejects_bad_ratio(self):
        backend = self._backend()
        with pytest.raises(DreaminaCliError, match="不支持比例"):
            backend._build_command(_video_request(aspect_ratio="2:1"))

    def test_rejects_out_of_range_duration_2x(self):
        """2.0 家族时长范围 4-15s。"""
        backend = self._backend()
        with pytest.raises(VideoCapabilityError):
            backend._build_command(_video_request(duration_seconds=3))
        with pytest.raises(VideoCapabilityError):
            backend._build_command(_video_request(duration_seconds=20))

    def test_duration_range_1x(self):
        """1.0 系时长范围 3-10s。"""
        backend = self._backend(model="seedance1.0fast")
        # 3s valid for 1.0
        args = backend._build_command(_video_request(duration_seconds=3))
        assert "--duration=3" in args
        # 15s invalid for 1.0
        with pytest.raises(VideoCapabilityError):
            backend._build_command(_video_request(duration_seconds=15))

    def test_rejects_references_with_frames(self, tmp_path):
        """参考素材与首/尾帧互斥（fail-loud，不静默丢帧）。"""
        ref = tmp_path / "ref.png"
        start = tmp_path / "start.png"
        ref.write_bytes(b"r")
        start.write_bytes(b"s")
        backend = self._backend()
        with pytest.raises(VideoCapabilityError, match="reference_images_with_frames"):
            backend._build_command(_video_request(reference_images=[ref], start_image=start))

    def test_rejects_end_without_start(self, tmp_path):
        end = tmp_path / "last.png"
        end.write_bytes(b"e")
        backend = self._backend()
        with pytest.raises(VideoCapabilityError, match="end_image_requires_start"):
            backend._build_command(_video_request(end_image=end))

    def test_resolution_flag_appended(self):
        backend = self._backend()
        args = backend._build_command(_video_request(resolution="1080p"))
        assert any(a == "--video_resolution=1080p" for a in args)

    def test_resolution_lowercased(self):
        backend = self._backend()
        args = backend._build_command(_video_request(resolution="4K"))
        assert "--video_resolution=4k" in args

    def test_unreadable_start_image_raises(self):
        backend = self._backend()
        with pytest.raises(VideoCapabilityError, match="start_image_unreadable"):
            backend._build_command(_video_request(start_image=Path("/nonexistent/start.png")))

    def test_exceeds_max_reference_images(self, tmp_path):
        """multimodal2video 最多 9 张参考图。"""
        refs = []
        for i in range(10):
            p = tmp_path / f"ref{i}.png"
            p.write_bytes(b"x")
            refs.append(p)
        backend = self._backend()
        with pytest.raises(VideoCapabilityError, match="reference_images_exceeded"):
            backend._build_command(_video_request(reference_images=refs))


# ══════════════════════════════════════════════════════════════
# 9. DreaminaCliVideoBackend —— submit 错误处理（mock run_dreamina）
# ══════════════════════════════════════════════════════════════


class TestVideoSubmit:
    def _backend(self):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        return DreaminaCliVideoBackend()

    @pytest.mark.asyncio
    async def test_submit_success(self):
        async def fake_run(cli, args, *, timeout):
            return 0, '{"submit_id": "submit-abc"}'

        backend = self._backend()
        with patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run):
            submit_id = await backend._submit(["text2video", "--prompt=hi"])
        assert submit_id == "submit-abc"

    @pytest.mark.asyncio
    async def test_submit_nonzero_exit_but_parses_id(self):
        """非零退出但能解析 submit_id → 认提交成功（避免重提扣积分）。"""
        async def fake_run(cli, args, *, timeout):
            return 1, '{"submit_id": "submit-xyz"}'

        backend = self._backend()
        with patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run):
            submit_id = await backend._submit(["text2video"])
        assert submit_id == "submit-xyz"

    @pytest.mark.asyncio
    async def test_submit_compliance_fail_fast(self, no_sleep):
        """compliance 错误不可重试，立即抛出。"""
        call_count = 0

        async def fake_run(cli, args, *, timeout):
            nonlocal call_count
            call_count += 1
            return 1, "AigcComplianceConfirmationRequired"

        backend = self._backend()
        with patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run):
            with pytest.raises(DreaminaCliError) as exc_info:
                await backend._submit(["text2video"])
            assert exc_info.value.kind == "compliance"
        assert call_count == 1  # no retry

    @pytest.mark.asyncio
    async def test_submit_rate_limit_retries_then_succeeds(self, no_sleep):
        """rate_limit 可重试，第二次成功。"""
        call_count = 0

        async def fake_run(cli, args, *, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 1, "rate limit exceeded, 429"
            return 0, '{"submit_id": "retry-ok"}'

        backend = self._backend()
        with patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run):
            submit_id = await backend._submit(["text2video"])
        assert submit_id == "retry-ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_submit_rate_limit_exhausts_retries(self, no_sleep):
        """rate_limit 重试 3 次后仍失败，抛出。"""
        call_count = 0

        async def fake_run(cli, args, *, timeout):
            nonlocal call_count
            call_count += 1
            return 1, "429 too many requests"

        backend = self._backend()
        with patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run):
            with pytest.raises(DreaminaCliError) as exc_info:
                await backend._submit(["text2video"])
            assert exc_info.value.kind == "rate_limit"
        assert call_count == 3  # DEFAULT_MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_submit_no_submit_id_raises(self):
        """输出无 submit_id → 按失败分类抛出。"""
        async def fake_run(cli, args, *, timeout):
            return 0, "some unrecognized output"

        backend = self._backend()
        with patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run):
            with pytest.raises(DreaminaCliError):
                await backend._submit(["text2video"])


# ══════════════════════════════════════════════════════════════
# 10. DreaminaCliVideoBackend —— generate 端到端（mock submit + poll）
# ══════════════════════════════════════════════════════════════


class TestVideoGenerate:
    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path):
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        output_path = tmp_path / "output.mp4"
        backend = DreaminaCliVideoBackend()

        # mock submit: run_dreamina 返回含 submit_id 的输出
        async def fake_run(cli, args, *, timeout):
            return 0, '{"submit_id": "gen-001"}'

        # mock poll: 返回一个临时文件路径（模拟落盘）
        fake_video = tmp_path / "downloaded.mp4"
        fake_video.write_bytes(b"fake-video-bytes")

        async def fake_poll(**kw):
            return [fake_video]

        request = _video_request(output_path=output_path, task_id=None)
        with (
            patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run),
            patch("lib.video_backends.dreamina_cli.poll_until_downloaded", side_effect=fake_poll),
        ):
            result = await backend.generate(request)

        assert result.video_path == output_path
        assert result.provider == PROVIDER_DREAMINA_CLI
        assert result.model == "seedance2.0fast"
        assert result.task_id == "gen-001"
        assert result.generate_audio is True  # 2.x 家族原生带声
        # 文件已移动到 output_path
        assert output_path.read_bytes() == b"fake-video-bytes"

    @pytest.mark.asyncio
    async def test_generate_1x_no_audio(self, tmp_path):
        """1.x 模型成片无声，generate_audio=False。"""
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        output_path = tmp_path / "output.mp4"
        backend = DreaminaCliVideoBackend(model="seedance1.0")

        async def fake_run(cli, args, *, timeout):
            return 0, '{"submit_id": "gen-1x"}'

        fake_video = tmp_path / "downloaded.mp4"
        fake_video.write_bytes(b"data")

        async def fake_poll(**kw):
            return [fake_video]

        with (
            patch("lib.video_backends.dreamina_cli.run_dreamina", side_effect=fake_run),
            patch("lib.video_backends.dreamina_cli.poll_until_downloaded", side_effect=fake_poll),
        ):
            result = await backend.generate(_video_request(output_path=output_path))
        assert result.generate_audio is False

    @pytest.mark.asyncio
    async def test_resume_success(self, tmp_path):
        """resume_video 只轮询不重新提交。"""
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        output_path = tmp_path / "resume.mp4"
        backend = DreaminaCliVideoBackend()

        fake_video = tmp_path / "resumed.mp4"
        fake_video.write_bytes(b"resumed-data")

        async def fake_poll(**kw):
            return [fake_video]

        with patch("lib.video_backends.dreamina_cli.poll_until_downloaded", side_effect=fake_poll):
            result = await backend.resume_video("existing-job-id", _video_request(output_path=output_path))

        assert result.video_path == output_path
        assert result.task_id == "existing-job-id"
        assert output_path.read_bytes() == b"resumed-data"

    @pytest.mark.asyncio
    async def test_resume_task_not_found_raises_resume_expired(self, tmp_path):
        """resume 时任务不存在 → ResumeExpiredError。"""
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        backend = DreaminaCliVideoBackend()

        async def fake_poll(**kw):
            raise DreaminaTaskNotFoundError("gone-id", message="not found")

        with patch("lib.video_backends.dreamina_cli.poll_until_downloaded", side_effect=fake_poll):
            with pytest.raises(ResumeExpiredError):
                await backend.resume_video("gone-id", _video_request(output_path=tmp_path / "x.mp4"))


# ══════════════════════════════════════════════════════════════
# 11. DreaminaCliImageBackend —— 能力 + 命令 + generate
# ══════════════════════════════════════════════════════════════


class TestImageBackend:
    def _backend(self, **kw):
        from lib.image_backends.dreamina_cli import DreaminaCliImageBackend

        return DreaminaCliImageBackend(**kw)

    def test_name_and_model(self):
        backend = self._backend()
        assert backend.name == PROVIDER_DREAMINA_CLI
        assert backend.model == "seedream-5.0"

    def test_capabilities_default_has_i2i(self):
        """5.0 支持 i2i。"""
        from lib.image_backends.base import ImageCapability

        backend = self._backend()
        assert ImageCapability.TEXT_TO_IMAGE in backend.capabilities
        assert ImageCapability.IMAGE_TO_IMAGE in backend.capabilities

    def test_capabilities_3x_no_i2i(self):
        """3.0/3.1 不支持 i2i。"""
        from lib.image_backends.base import ImageCapability

        backend = self._backend(model="seedream-3.0")
        assert ImageCapability.TEXT_TO_IMAGE in backend.capabilities
        assert ImageCapability.IMAGE_TO_IMAGE not in backend.capabilities

    def test_model_version_strips_prefix(self):
        """registry 键 seedream-5.0 → CLI --model_version=5.0。"""
        assert self._backend()._model_version == "5.0"
        assert self._backend(model="seedream-3.1")._model_version == "3.1"
        assert self._backend(model="4.0")._model_version == "4.0"  # 裸版本号原样透传

    def test_text2image_command(self):
        backend = self._backend()
        args = backend._build_command(_image_request(prompt="风景", aspect_ratio="1:1"))
        assert args[0] == "text2image"
        assert "--prompt=风景" in args
        assert "--ratio=1:1" in args
        assert "--model_version=5.0" in args

    def test_image2image_command(self, tmp_path):
        from lib.image_backends.base import ReferenceImage

        ref1 = tmp_path / "ref1.png"
        ref2 = tmp_path / "ref2.png"
        ref1.write_bytes(b"1")
        ref2.write_bytes(b"2")
        backend = self._backend()
        args = backend._build_command(
            _image_request(reference_images=[ReferenceImage(path=str(ref1)), ReferenceImage(path=str(ref2))])
        )
        assert args[0] == "image2image"
        image_flags = [a for a in args if a.startswith("--images=")]
        assert len(image_flags) == 2

    def test_rejects_bad_ratio(self):
        backend = self._backend()
        with pytest.raises(DreaminaCliError, match="不支持比例"):
            backend._build_command(_image_request(aspect_ratio="5:4"))

    def test_rejects_i2i_on_unsupported_version(self, tmp_path):
        """3.0 不支持 i2i，带参考图时抛 ImageCapabilityError。"""
        from lib.image_backends.base import ImageCapabilityError, ReferenceImage

        ref = tmp_path / "ref.png"
        ref.write_bytes(b"x")
        backend = self._backend(model="seedream-3.0")
        with pytest.raises(ImageCapabilityError):
            backend._build_command(_image_request(reference_images=[ReferenceImage(path=str(ref))]))

    def test_rejects_unreadable_reference(self, tmp_path):
        from lib.image_backends.base import ImageCapabilityError, ReferenceImage

        backend = self._backend()
        with pytest.raises(ImageCapabilityError, match="unreadable"):
            backend._build_command(
                _image_request(reference_images=[ReferenceImage(path="/nonexistent/ref.png")])
            )

    def test_rejects_too_many_references(self, tmp_path):
        from lib.image_backends.base import ReferenceImage

        refs = []
        for i in range(11):
            p = tmp_path / f"r{i}.png"
            p.write_bytes(b"x")
            refs.append(ReferenceImage(path=str(p)))
        backend = self._backend()
        with pytest.raises(DreaminaCliError, match="最多"):
            backend._build_command(_image_request(reference_images=refs))

    def test_image_size_flag(self):
        backend = self._backend()
        args = backend._build_command(_image_request(image_size="2k"))
        assert "--resolution_type=2k" in args

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path):
        from lib.image_backends.dreamina_cli import DreaminaCliImageBackend

        output_path = tmp_path / "out.png"
        backend = DreaminaCliImageBackend()

        async def fake_run(cli, args, *, timeout):
            return 0, '{"submit_id": "img-001"}'

        fake_image = tmp_path / "downloaded.png"
        fake_image.write_bytes(b"fake-image-bytes")

        async def fake_poll(**kw):
            return [fake_image]

        with (
            patch("lib.image_backends.dreamina_cli.run_dreamina", side_effect=fake_run),
            patch("lib.image_backends.dreamina_cli.poll_until_downloaded", side_effect=fake_poll),
        ):
            result = await backend.generate(_image_request(output_path=output_path))

        assert result.image_path == output_path
        assert result.provider == PROVIDER_DREAMINA_CLI
        assert result.model == "seedream-5.0"
        assert output_path.read_bytes() == b"fake-image-bytes"


# ══════════════════════════════════════════════════════════════
# 12. 后端注册
# ══════════════════════════════════════════════════════════════


class TestRegistration:
    def test_video_backend_registered(self):
        from lib.video_backends import get_registered_backends

        assert PROVIDER_DREAMINA_CLI in get_registered_backends()

    def test_image_backend_registered(self):
        from lib.image_backends import get_registered_backends

        assert PROVIDER_DREAMINA_CLI in get_registered_backends()

    def test_create_video_backend(self):
        from lib.video_backends import create_backend
        from lib.video_backends.dreamina_cli import DreaminaCliVideoBackend

        backend = create_backend(PROVIDER_DREAMINA_CLI)
        assert isinstance(backend, DreaminaCliVideoBackend)

    def test_create_image_backend(self):
        from lib.image_backends import create_backend
        from lib.image_backends.dreamina_cli import DreaminaCliImageBackend

        backend = create_backend(PROVIDER_DREAMINA_CLI)
        assert isinstance(backend, DreaminaCliImageBackend)

    def test_create_video_backend_with_kwargs(self):
        from lib.video_backends import create_backend

        backend = create_backend(PROVIDER_DREAMINA_CLI, model="seedance1.0")
        assert backend.model == "seedance1.0"

    def test_unknown_backend_raises(self):
        from lib.video_backends import create_backend

        with pytest.raises(ValueError, match="Unknown video backend"):
            create_backend("nonexistent-backend")
