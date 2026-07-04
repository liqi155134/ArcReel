"""DreaminaCliImageBackend — 即梦官方 CLI 图片生成后端（Seedream）。

经本机 ``dreamina`` CLI（OAuth 登录态，无 API key）提交异步任务：无参考图走
text2image、带参考图走 image2image；submit 后自建轮询循环调 ``query_result
--download_dir``，以**文件实际落盘**为唯一完成判据（与视频侧同一底座，见
``lib.dreamina_cli_shared`` 的「实测校准点」注释）。registry 模型键以
``seedream-`` 前缀命名（如 seedream-5.0），下发 CLI 时剥前缀成 --model_version 值。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from lib.dreamina_cli_shared import (
    DEFAULT_CLI_PATH,
    IMAGE_SUFFIXES,
    DreaminaCliError,
    error_from_cli_output,
    parse_submit_id,
    poll_until_downloaded,
    run_dreamina,
)
from lib.image_backends.base import (
    ImageCapability,
    ImageCapabilityError,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from lib.providers import PROVIDER_DREAMINA_CLI
from lib.retry import with_retry_async

logger = logging.getLogger(__name__)

# registry 模型键（seedream-<ver>）；CLI --model_version 只吃裸版本号。
DEFAULT_MODEL = "seedream-5.0"
_MODEL_PREFIX = "seedream-"

# CLI help 实测：text2image / image2image 的 --ratio 白名单一致（8 种）。
_IMAGE_RATIOS = frozenset({"21:9", "16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16"})

# CLI help 实测：image2image 仅 4.0+ 支持（3.0/3.1 无 i2i），一次最多 10 张输入图。
_I2I_UNSUPPORTED_VERSIONS = frozenset({"3.0", "3.1"})
_MAX_INPUT_IMAGES = 10

# 图任务通常分钟级完成；submit 前 CLI 会同步上传输入图（≤10 张）。
_SUBMIT_TIMEOUT_SECONDS = 300.0
_QUERY_TIMEOUT_SECONDS = 300.0
_POLL_INTERVAL_SECONDS = 5.0
_MAX_WAIT_SECONDS = 900.0


def _is_rate_limited(exc: Exception) -> bool:
    """submit 重试谓词：仅 CLI 限流可重试；compliance/审核/其它 CLI 失败 fail-fast。"""
    return isinstance(exc, DreaminaCliError) and exc.retryable


class DreaminaCliImageBackend:
    """即梦官方 CLI 图片后端（异步 submit / 自建轮询，落盘判完成）。"""

    def __init__(self, *, cli_path: str | None = None, model: str | None = None) -> None:
        # cli_path 即凭证（无 secret）：填 "dreamina" 或绝对路径均可，缺省回落 PATH 查找。
        self._cli_path = cli_path or DEFAULT_CLI_PATH
        self._model = model or DEFAULT_MODEL
        self._capabilities: set[ImageCapability] = {ImageCapability.TEXT_TO_IMAGE}
        if self._model_version not in _I2I_UNSUPPORTED_VERSIONS:
            self._capabilities.add(ImageCapability.IMAGE_TO_IMAGE)

    @property
    def name(self) -> str:
        return PROVIDER_DREAMINA_CLI

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[ImageCapability]:
        return self._capabilities

    @property
    def _model_version(self) -> str:
        """registry 键 → CLI --model_version 值（剥 seedream- 前缀；裸版本号原样透传）。"""
        return self._model.removeprefix(_MODEL_PREFIX)

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        args = self._build_command(request)
        submit_id = await self._submit(args)
        logger.info("Dreamina 图片任务已提交: submit_id=%s command=%s model=%s", submit_id, args[0], self._model)
        return await self._await_result(submit_id, request)

    # ── 命令构建 ──────────────────────────────────────────────────

    def _build_command(self, request: ImageGenerationRequest) -> list[str]:
        """路由：带参考图 → image2image（--images 可重复）；否则 text2image。"""
        if request.reference_images:
            if ImageCapability.IMAGE_TO_IMAGE not in self._capabilities:
                raise ImageCapabilityError("image_endpoint_mismatch_no_i2i", model=self._model)
            paths = [Path(ref.path) for ref in request.reference_images]
            unreadable = [p.name or str(p) for p in paths if not p.is_file()]
            if unreadable:
                # 输入图缺失 fail-loud，不静默丢弃后照常扣积分
                raise ImageCapabilityError(
                    "image_reference_images_unreadable", model=self._model, names=", ".join(unreadable)
                )
            if len(paths) > _MAX_INPUT_IMAGES:
                # 无专用 i18n code：CLI 硬上限 10 张，超限按 service 层异常直抛（agent-facing 豁免）
                raise DreaminaCliError(f"dreamina image2image 一次最多 {_MAX_INPUT_IMAGES} 张输入图，收到 {len(paths)} 张")
            args = ["image2image", *(f"--images={p}" for p in paths), f"--prompt={request.prompt}"]
        else:
            args = ["text2image", f"--prompt={request.prompt}"]

        args.append(f"--ratio={self._validated_ratio(request.aspect_ratio)}")
        args.append(f"--model_version={self._model_version}")
        if request.image_size:
            # 档位透传（1k/2k/4k），大小写归一为 CLI 口径；档位×模型组合由 CLI 校验
            args.append(f"--resolution_type={request.image_size.lower()}")
        return args

    def _validated_ratio(self, aspect_ratio: str) -> str:
        """比例白名单预校验：不受支持时 fail-fast，避免浪费一次 submit（agent-facing，i18n 豁免）。"""
        if aspect_ratio not in _IMAGE_RATIOS:
            raise DreaminaCliError(
                f"dreamina 图片不支持比例 {aspect_ratio}（支持: {', '.join(sorted(_IMAGE_RATIOS))}）"
            )
        return aspect_ratio

    # ── submit / poll / 落盘 ──────────────────────────────────────

    @with_retry_async(retry_if=_is_rate_limited)
    async def _submit(self, args: list[str]) -> str:
        """提交生成任务，返回 submit_id。exit code 不可信：解析出 submit_id 即认提交成功。"""
        code, output = await run_dreamina(self._cli_path, args, timeout=_SUBMIT_TIMEOUT_SECONDS)
        submit_id = parse_submit_id(output)
        if submit_id is not None:
            if code != 0:
                logger.warning("Dreamina submit 非零退出（code=%d）但已解析到 submit_id=%s，按已提交处理", code, submit_id)
            return submit_id
        raise error_from_cli_output(output, context=f"{args[0]} 提交")

    async def _await_result(self, submit_id: str, request: ImageGenerationRequest) -> ImageGenerationResult:
        download_dir = request.output_path.parent / f".dreamina-{submit_id}"
        files = await poll_until_downloaded(
            cli_path=self._cli_path,
            submit_id=submit_id,
            download_dir=download_dir,
            suffixes=IMAGE_SUFFIXES,
            poll_interval=_POLL_INTERVAL_SECONDS,
            max_wait=_MAX_WAIT_SECONDS,
            query_timeout=_QUERY_TIMEOUT_SECONDS,
            label="Dreamina",
        )

        def _finalize() -> None:
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            # generate_num 恒为 1（不下发该参数），目录里只应有一张图，防御性取最新
            shutil.move(str(files[-1]), str(request.output_path))
            shutil.rmtree(download_dir, ignore_errors=True)

        await asyncio.to_thread(_finalize)
        logger.info("Dreamina 图片已落盘: %s (submit_id=%s)", request.output_path, submit_id)

        return ImageGenerationResult(
            image_path=request.output_path,
            provider=PROVIDER_DREAMINA_CLI,
            model=self._model,
        )
