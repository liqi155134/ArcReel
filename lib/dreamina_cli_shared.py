"""Dreamina 即梦官方 CLI 共享工具 —— 子进程调用、输出解析与错误分类。

dreamina CLI 走 OAuth 本机登录态（无 API key）；所有生成子命令异步返回 submit_id，
``query_result --submit_id --download_dir`` 负责查询并在完成时把产物下载到目录。
本模块是 image/video 两个 backend 的共用底座，收口三件事：

1. 子进程一律 ``asyncio.create_subprocess_exec`` + args list —— 实测经 shell 字符串
   传中文 prompt 时 quoting 差异会让任务被 server 静默丢弃，故禁 shell 拼接。
2. CLI stdout 的机器可读格式未实测（登录后才能校准），解析函数集中在此、写宽容
   （先试 JSON、回退正则），各处标注「实测校准点」，backend 侧只消费结构化结果。
3. ``--poll`` 的 exit code 实测不可信 —— 不使用 --poll，自建轮询循环调 query_result，
   以 ``--download_dir`` 中**文件实际落盘**为唯一完成判据。

CLI 参数面已按 ``dreamina <subcommand> -h``（2026-07 实测）校准；仅运行时输出格式待校准。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 未配置 cli_path 时的兜底：依赖 PATH 上的官方安装位置（~/.local/bin/dreamina）。
DEFAULT_CLI_PATH = "dreamina"

# ── 错误分类 ──────────────────────────────────────────────────────
# 三类关键错误（实测坑单）：
# - compliance：AigcComplianceConfirmationRequired，需到 Dreamina Web 端完成授权确认，不可重试；
# - moderation：内容审核失败，重试不会变好，不可重试；
# - rate_limit：限流，可重试。
ERROR_KIND_COMPLIANCE = "compliance"
ERROR_KIND_MODERATION = "moderation"
ERROR_KIND_RATE_LIMIT = "rate_limit"
ERROR_KIND_CLI = "cli"


class DreaminaCliError(RuntimeError):
    """dreamina CLI 调用失败，携带分类 kind 供重试谓词与上层分流。"""

    def __init__(self, message: str, *, kind: str = ERROR_KIND_CLI) -> None:
        self.kind = kind
        super().__init__(message)

    @property
    def retryable(self) -> bool:
        # 仅限流可重试；compliance/moderation 是确定性失败，CLI 级失败（登录态失效 /
        # 参数错误等）重试也不会变好，一律 fail-fast 让错误尽早可见。
        return self.kind == ERROR_KIND_RATE_LIMIT


class DreaminaTaskNotFoundError(DreaminaCliError):
    """query_result 报任务不存在 / 已过期 —— resume 路径据此转 ResumeExpiredError。"""

    def __init__(self, submit_id: str, message: str = "") -> None:
        super().__init__(message or f"dreamina 任务不存在或已过期: submit_id={submit_id}", kind=ERROR_KIND_CLI)
        self.submit_id = submit_id


# 实测校准点：错误文案匹配模式。CLI help 已确认 AigcComplianceConfirmationRequired 的
# 拼写；审核 / 限流的具体文案未实测，先按中英文常见措辞宽容匹配，登录后据真实输出收窄。
_COMPLIANCE_PATTERNS = ("aigccomplianceconfirmationrequired",)
_MODERATION_PATTERNS = (
    "内容审核",
    "审核不通过",
    "审核未通过",
    "审核失败",
    "内容安全",
    "content moderation",
    "content policy",
    "risk control",
    "sensitive content",
)
_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "ratelimit",
    "too many requests",
    "429",
    "限流",
    "频率过高",
    "请求过于频繁",
    "qps",
)
_NOT_FOUND_PATTERNS = (
    "not found",
    "no such task",
    "task does not exist",
    "不存在",
    "已过期",
    "expired",
)


def classify_cli_error(output: str) -> str:
    """CLI 输出全文 → 错误分类 kind。

    优先级：compliance > moderation > rate_limit > cli。compliance 文案里常同时出现
    "安全/审核" 类措辞，先判 compliance 避免被 moderation 误吞（二者处置不同：
    前者去 Web 端授权、后者改 prompt）。
    """
    lowered = output.lower()
    if any(p in lowered for p in _COMPLIANCE_PATTERNS):
        return ERROR_KIND_COMPLIANCE
    if any(p in lowered for p in _MODERATION_PATTERNS):
        return ERROR_KIND_MODERATION
    if any(p in lowered for p in _RATE_LIMIT_PATTERNS):
        return ERROR_KIND_RATE_LIMIT
    return ERROR_KIND_CLI


def is_task_not_found(output: str) -> bool:
    """query_result 输出是否表示任务不存在 / 已过期（实测校准点：具体文案未实测）。"""
    lowered = output.lower()
    return any(p in lowered for p in _NOT_FOUND_PATTERNS)


def error_from_cli_output(output: str, *, context: str) -> DreaminaCliError:
    """把 CLI 失败输出包成分类异常；消息截断，避免把整段 CLI 输出灌进 task.error_message。"""
    kind = classify_cli_error(output)
    excerpt = " ".join(output.split())[:300]
    if kind == ERROR_KIND_COMPLIANCE:
        return DreaminaCliError(
            f"dreamina {context} 失败: 需先在 Dreamina Web 端完成 AIGC 授权确认"
            f"（AigcComplianceConfirmationRequired），不可自动重试。原始输出: {excerpt}",
            kind=kind,
        )
    if kind == ERROR_KIND_MODERATION:
        return DreaminaCliError(f"dreamina {context} 失败: 内容审核未通过，请调整 prompt/素材后重试。原始输出: {excerpt}", kind=kind)
    if kind == ERROR_KIND_RATE_LIMIT:
        return DreaminaCliError(f"dreamina {context} 失败: 触发限流。原始输出: {excerpt}", kind=kind)
    return DreaminaCliError(f"dreamina {context} 失败: {excerpt}", kind=kind)


# ── 子进程调用 ────────────────────────────────────────────────────


async def run_dreamina(cli_path: str, args: list[str], *, timeout: float) -> tuple[int, str]:
    """执行一次 dreamina 子命令，返回 (returncode, 合流输出文本)。

    stderr 合流进 stdout：CLI 的人类可读输出与错误提示混在两个流里（未实测具体分布），
    解析统一对全文做，避免关键字散落在 stderr 被漏读。超时杀进程后抛 TimeoutError，
    交调用方按阶段决定语义（submit 阶段视为歧义、轮询阶段继续下一轮）。
    """
    proc = await asyncio.create_subprocess_exec(
        cli_path,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode if proc.returncode is not None else -1, stdout.decode("utf-8", errors="replace")


# ── 输出解析（实测校准点集中区） ──────────────────────────────────

# 实测校准点：submit 输出格式未实测。先整体 / 逐行试 JSON（键名候选 submit_id/submitId），
# 回退正则抓 "submit_id=<hex>" / "submit_id: <hex>" 类文案（help 示例的 submit_id 形如
# 3f6eb41f425d23a3，按泛化的 [0-9A-Za-z_-]+ 抓取）。登录后据真实输出收窄。
_SUBMIT_ID_JSON_KEYS = ("submit_id", "submitId")
_SUBMIT_ID_RE = re.compile(r"submit_?id[\"'：:=\s]+([0-9A-Za-z_-]{6,})", re.IGNORECASE)


def _submit_id_from_json(value: object) -> str | None:
    """递归在 JSON 对象里找 submit_id 键（顶层或嵌套 data/result 信封均覆盖）。"""
    if isinstance(value, dict):
        for key in _SUBMIT_ID_JSON_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
            if isinstance(candidate, int):
                return str(candidate)
        for child in value.values():
            found = _submit_id_from_json(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _submit_id_from_json(child)
            if found is not None:
                return found
    return None


def parse_submit_id(output: str) -> str | None:
    """从生成子命令输出解析 submit_id；解析不出返回 None（由调用方按失败处理）。"""
    for line in output.splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        found = _submit_id_from_json(parsed)
        if found is not None:
            return found
    match = _SUBMIT_ID_RE.search(output)
    if match:
        return match.group(1)
    return None


# 实测校准点：query_result 的状态文案未实测。归一化只用于识别「明确失败」提前终止轮询；
# 完成不依赖状态字段（以文件落盘为准），未识别的状态一律当 running 继续轮询到 max_wait。
_QUERY_STATUS_RE = re.compile(r"\bstatus[\"'：:=\s]+([A-Za-z_]+)", re.IGNORECASE)
_DONE_STATUSES = frozenset({"done", "success", "succeed", "succeeded", "completed", "finished"})
_FAILED_STATUSES = frozenset({"failed", "fail", "error"})


@dataclass(frozen=True)
class QueryOutcome:
    """一次 query_result 的归一化结果。status ∈ done / failed / running。"""

    status: str
    raw: str


def _status_from_json(value: object) -> str | None:
    """递归在 JSON 对象里找 status 键（顶层或嵌套 data/result 信封均覆盖）。"""
    if isinstance(value, dict):
        candidate = value.get("status")
        if isinstance(candidate, str) and candidate:
            return candidate
        for child in value.values():
            found = _status_from_json(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _status_from_json(child)
            if found is not None:
                return found
    return None


def parse_query_outcome(output: str) -> QueryOutcome:
    """从 query_result 输出归一化任务状态（宽容解析，识别不出按 running 处理）。"""
    status_raw: str | None = None
    for line in output.splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        status_raw = _status_from_json(parsed)
        if status_raw is not None:
            break
    if status_raw is None:
        match = _QUERY_STATUS_RE.search(output)
        if match:
            status_raw = match.group(1)
    lowered = (status_raw or "").lower()
    if lowered in _DONE_STATUSES:
        return QueryOutcome(status="done", raw=output)
    if lowered in _FAILED_STATUSES:
        return QueryOutcome(status="failed", raw=output)
    return QueryOutcome(status="running", raw=output)


# ── 产物落盘扫描 ──────────────────────────────────────────────────

VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".avi", ".mkv"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"})


def find_downloaded_media(download_dir: Path, suffixes: frozenset[str]) -> list[Path]:
    """扫描 download_dir 中已落盘的目标产物，按 mtime 升序返回。

    扫描发生在 query_result 进程退出之后（下载由该进程同步完成），无「写一半」竞态；
    仍防御性剔除 0 字节与隐藏 / 临时文件（``.part`` / ``.tmp`` / ``.download``）。
    """
    if not download_dir.is_dir():
        return []
    results: list[Path] = []
    for path in download_dir.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            if path.stat().st_size == 0:
                continue
        except OSError:
            continue
        results.append(path)
    results.sort(key=lambda p: p.stat().st_mtime)
    return results


# ── 轮询循环（video / image backend 共用） ────────────────────────


async def poll_until_downloaded(
    *,
    cli_path: str,
    submit_id: str,
    download_dir: Path,
    suffixes: frozenset[str],
    poll_interval: float,
    max_wait: float,
    query_timeout: float,
    label: str,
) -> list[Path]:
    """轮询 query_result 直到产物落盘，返回落盘文件列表（mtime 升序）。

    完成判据只认文件落盘：``--poll``/exit code 均实测不可信。每轮把 CLI 输出过一遍
    错误分类 —— compliance / moderation / 明确 failed 提前终态失败，任务不存在抛
    ``DreaminaTaskNotFoundError``（resume 路径据此转 ResumeExpiredError；submit 后
    立即 not-found 视为 server 静默丢弃，同样应终态而非空转到超时）；限流与其它
    CLI 瞬态失败继续下一轮（幂等查询，重试无副作用），单轮超时同理。
    """
    await asyncio.to_thread(download_dir.mkdir, parents=True, exist_ok=True)
    args = ["query_result", f"--submit_id={submit_id}", f"--download_dir={download_dir}"]
    start = time.monotonic()
    while True:
        output = ""
        try:
            code, output = await run_dreamina(cli_path, args, timeout=query_timeout)
        except TimeoutError:
            # 单轮查询超时（含成片下载中被卡住）：幂等查询，直接进下一轮
            logger.warning("%s query_result 超时（%ds），将重试 submit_id=%s", label, int(query_timeout), submit_id)
            code = -1

        files = await asyncio.to_thread(find_downloaded_media, download_dir, suffixes)
        if files:
            return files

        if output:
            if is_task_not_found(output):
                raise DreaminaTaskNotFoundError(submit_id, message=f"{label} 任务不存在或已过期: {output[:200]}")
            kind = classify_cli_error(output)
            outcome = parse_query_outcome(output)
            if kind in (ERROR_KIND_COMPLIANCE, ERROR_KIND_MODERATION) or outcome.status == "failed":
                raise error_from_cli_output(output, context=f"{label} 任务（submit_id={submit_id}）")
            if outcome.status == "done":
                # 状态说完成但目录里没有产物 —— 不信状态文案，继续轮询等文件落盘
                logger.warning("%s 状态为完成但产物未落盘，继续轮询 submit_id=%s", label, submit_id)
            elif code != 0:
                logger.warning("%s query_result 非零退出（code=%d），将重试 submit_id=%s", label, code, submit_id)

        if time.monotonic() - start >= max_wait:
            raise TimeoutError(f"{label} 任务超时（{max_wait:.0f}秒）: submit_id={submit_id}")
        await asyncio.sleep(poll_interval)
