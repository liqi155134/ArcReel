"""DreaminaCliVideoBackend — 即梦官方 CLI 视频生成后端（Seedance）。

经本机 ``dreamina`` CLI（OAuth 登录态，无 API key）提交异步任务：按请求内容路由
text2video / image2video / frames2video / multimodal2video 四条子命令，submit 拿到
submit_id 后经 mixin 持久化，再自建轮询循环调 ``query_result --download_dir``，
以**文件实际落盘**为唯一完成判据（``--poll`` 的 exit code 实测不可信，不使用）。
CLI 参数面按 ``dreamina <subcommand> -h`` 实测校准；运行时输出解析集中在
``lib.dreamina_cli_shared``（见其中「实测校准点」注释）。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from lib.dreamina_cli_shared import (
    DEFAULT_CLI_PATH,
    VIDEO_SUFFIXES,
    DreaminaCliError,
    DreaminaTaskNotFoundError,
    error_from_cli_output,
    parse_submit_id,
    poll_until_downloaded,
    run_dreamina,
)
from lib.providers import PROVIDER_DREAMINA_CLI
from lib.retry import with_retry_async
from lib.video_backends.base import (
    ProviderJobIdPersistenceMixin,
    ResumeExpiredError,
    VideoCapabilities,
    VideoCapability,
    VideoCapabilityError,
    VideoGenerationRequest,
    VideoGenerationResult,
)

logger = logging.getLogger(__name__)

# CLI text2video 的默认模型；registry 默认模型与此对齐。
DEFAULT_MODEL = "seedance2.0fast"

# text2video / multimodal2video 的 --ratio 白名单（CLI help 实测）；image2video / frames2video
# 的比例从输入图推断，不下发 --ratio。
_VIDEO_RATIOS = frozenset({"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"})

# 各模型时长范围（CLI help 实测：1.0 系 3-10s、1.5pro 4-12s、2.0 家族 4-15s）。
_MODEL_DURATION_RANGES: dict[str, tuple[int, int]] = {
    "seedance1.0fast": (3, 10),
    "seedance1.0": (3, 10),
    "seedance1.5pro": (4, 12),
}
_DEFAULT_DURATION_RANGE = (4, 15)

# multimodal2video 的参考素材上限（CLI help 实测：image<=9, video<=3, audio<=3）。
_MAX_REFERENCE_IMAGES = 9
_MAX_REFERENCE_VIDEOS = 3
_MAX_REFERENCE_AUDIO = 3

_REFERENCE_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".avi", ".mkv"})
_REFERENCE_AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"})

# submit 前 CLI 会同步上传本地素材（最多 9 图 + 3 视频 + 3 音频），给足上传时间。
_SUBMIT_TIMEOUT_SECONDS = 600.0
# query_result 命中完成态时会同步下载成片，单轮超时按下载耗时给。
_QUERY_TIMEOUT_SECONDS = 600.0
_POLL_INTERVAL_SECONDS = 15.0
_MAX_WAIT_SECONDS = 3600.0


def _is_rate_limited(exc: Exception) -> bool:
    """submit 重试谓词：仅 CLI 限流可重试；compliance/审核/其它 CLI 失败 fail-fast。"""
    return isinstance(exc, DreaminaCliError) and exc.retryable


class DreaminaCliVideoBackend(ProviderJobIdPersistenceMixin):
    """即梦官方 CLI 视频后端（异步 submit / 自建轮询 / 支持 resume）。"""

    def __init__(self, *, cli_path: str | None = None, model: str | None = None) -> None:
        # cli_path 即凭证（无 secret）：填 "dreamina" 或绝对路径均可，缺省回落 PATH 查找。
        self._cli_path = cli_path or DEFAULT_CLI_PATH
        self._model = model or DEFAULT_MODEL
        self._capabilities: set[VideoCapability] = {
            VideoCapability.TEXT_TO_VIDEO,
            VideoCapability.IMAGE_TO_VIDEO,
        }

    @property
    def name(self) -> str:
        return PROVIDER_DREAMINA_CLI

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[VideoCapability]:
        return self._capabilities

    @property
    def video_capabilities(self) -> VideoCapabilities:
        # 首帧（image2video）+ 首尾帧（frames2video）+ 多参考（multimodal2video）。
        # multimodal2video 无「首帧」语义槽（参考图靠 prompt @图片N 指代），参考图不与
        # 首帧叠加，故 reference_images_with_start_frame=False；两者同给时 fail-loud。
        # 1.x 模型不支持 multimodal / frames 的能力差异由 registry ModelInfo 声明，
        # 这里按 2.0 家族（默认模型所在家族）如实上报。
        if self._model.startswith("seedance1"):
            last_frame = self._model == "seedance1.5pro"  # frames2video 白名单含 1.5pro，不含 1.0 系
            return VideoCapabilities(first_frame=True, last_frame=last_frame)
        return VideoCapabilities(
            first_frame=True,
            last_frame=True,
            reference_images=True,
            max_reference_images=_MAX_REFERENCE_IMAGES,
            reference_images_with_start_frame=False,
        )

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        args = self._build_command(request)
        submit_id = await self._submit(args)
        logger.info("Dreamina 视频任务已提交: submit_id=%s command=%s model=%s", submit_id, args[0], self._model)
        await self._persist_provider_job_id(request, submit_id, provider=PROVIDER_DREAMINA_CLI)
        return await self._await_result(submit_id, request)

    async def resume_video(self, job_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        """接续已 submit 的任务：仅轮询 + 落盘，不重新提交（ADR 0007）。"""
        try:
            return await self._await_result(job_id, request)
        except DreaminaTaskNotFoundError as exc:
            raise ResumeExpiredError(job_id=job_id, provider=PROVIDER_DREAMINA_CLI) from exc

    # ── 命令路由与参数构建 ────────────────────────────────────────

    def _build_command(self, request: VideoGenerationRequest) -> list[str]:
        """按请求内容路由子命令并构建 args list（不含 cli_path，不经 shell）。

        路由优先级：首+尾帧 → frames2video；有参考素材 → multimodal2video；仅首帧 →
        image2video；纯文本 → text2video。参考素材与首/尾帧互斥（fail-loud，不静默丢帧）。
        """
        self._reject_out_of_range_duration(request.duration_seconds)

        references = [Path(p) for p in (request.reference_images or []) if str(p)]
        start_image = request.start_image if request.start_image and str(request.start_image) else None
        end_image = request.end_image if request.end_image and str(request.end_image) else None

        if references and (start_image is not None or end_image is not None):
            raise VideoCapabilityError("video_reference_images_with_frames_unsupported", model=self._model)
        if end_image is not None and start_image is None:
            raise VideoCapabilityError("video_end_image_requires_start_image", model=self._model)

        duration_flag = f"--duration={request.duration_seconds}"
        model_flag = f"--model_version={self._model}"

        if start_image is not None and end_image is not None:
            self._require_readable(start_image, "video_start_image_unreadable")
            self._require_readable(end_image, "video_end_image_unreadable")
            args = [
                "frames2video",
                f"--first={start_image}",
                f"--last={end_image}",
                f"--prompt={request.prompt}",
                duration_flag,
                model_flag,
            ]
        elif references:
            args = self._build_multimodal_args(request, references)
        elif start_image is not None:
            self._require_readable(start_image, "video_start_image_unreadable")
            args = [
                "image2video",
                f"--image={start_image}",
                f"--prompt={request.prompt}",
                duration_flag,
                model_flag,
            ]
        else:
            args = [
                "text2video",
                f"--prompt={request.prompt}",
                duration_flag,
                f"--ratio={self._validated_ratio(request.aspect_ratio)}",
                model_flag,
            ]

        if request.resolution:
            # 档位值透传（720p/1080p/4k；4k 仅 seedance2.0_vip），大小写归一为 CLI 口径
            args.append(f"--video_resolution={request.resolution.lower()}")
        return args

    def _build_multimodal_args(self, request: VideoGenerationRequest, references: list[Path]) -> list[str]:
        """multimodal2video（全能参考）：按后缀把参考素材分流到 --image/--video/--audio。"""
        images: list[Path] = []
        videos: list[Path] = []
        audios: list[Path] = []
        unreadable: list[str] = []
        for path in references:
            if not path.is_file():
                unreadable.append(path.name or str(path))
                continue
            suffix = path.suffix.lower()
            if suffix in _REFERENCE_VIDEO_SUFFIXES:
                videos.append(path)
            elif suffix in _REFERENCE_AUDIO_SUFFIXES:
                audios.append(path)
            else:
                images.append(path)
        if unreadable:
            # 参考素材缺失 fail-loud，不静默丢弃后照常扣积分
            raise VideoCapabilityError(
                "video_reference_images_unreadable", model=self._model, names=", ".join(unreadable)
            )
        if len(images) > _MAX_REFERENCE_IMAGES:
            raise VideoCapabilityError(
                "video_reference_images_exceeded",
                model=self._model,
                count=len(images),
                limit=_MAX_REFERENCE_IMAGES,
            )
        # 视频/音频参考超限没有专用 i18n code（现有产品链路只产图参考），按 service 层异常直抛
        if len(videos) > _MAX_REFERENCE_VIDEOS:
            raise DreaminaCliError(f"dreamina multimodal2video 最多支持 {_MAX_REFERENCE_VIDEOS} 个参考视频，收到 {len(videos)} 个")
        if len(audios) > _MAX_REFERENCE_AUDIO:
            raise DreaminaCliError(f"dreamina multimodal2video 最多支持 {_MAX_REFERENCE_AUDIO} 个参考音频，收到 {len(audios)} 个")

        args = ["multimodal2video"]
        args.extend(f"--image={p}" for p in images)
        args.extend(f"--video={p}" for p in videos)
        args.extend(f"--audio={p}" for p in audios)
        args.extend(
            [
                f"--prompt={request.prompt}",
                f"--duration={request.duration_seconds}",
                f"--ratio={self._validated_ratio(request.aspect_ratio)}",
                f"--model_version={self._model}",
            ]
        )
        return args

    def _validated_ratio(self, aspect_ratio: str) -> str:
        """比例白名单预校验：不受支持时 fail-fast，避免浪费一次 submit（agent-facing，i18n 豁免）。"""
        if aspect_ratio not in _VIDEO_RATIOS:
            raise DreaminaCliError(
                f"dreamina 视频不支持比例 {aspect_ratio}（支持: {', '.join(sorted(_VIDEO_RATIOS))}）"
            )
        return aspect_ratio

    def _reject_out_of_range_duration(self, duration_seconds: int) -> None:
        low, high = _MODEL_DURATION_RANGES.get(self._model, _DEFAULT_DURATION_RANGE)
        if not low <= duration_seconds <= high:
            raise VideoCapabilityError(
                "video_duration_not_supported",
                model=self._model,
                duration=duration_seconds,
                supported=f"{low}-{high}",
            )

    def _require_readable(self, path: Path, error_code: str) -> None:
        """CLI 自己读文件，但提交前先验存在性：缺图 fail-fast，不把必败任务送出去扣积分。"""
        if not Path(path).is_file():
            raise VideoCapabilityError(error_code, model=self._model, name=Path(path).name or str(path))

    # ── submit / poll / 落盘 ──────────────────────────────────────

    @with_retry_async(retry_if=_is_rate_limited)
    async def _submit(self, args: list[str]) -> str:
        """提交生成任务，返回 submit_id。仅限流重试；其余分类失败 fail-fast。

        exit code 不可信（实测坑单）：只要能解析出 submit_id 就认提交成功（任务已在
        server 建立，重提会重复扣积分），非零退出仅记 warning；解析不出才按失败分类抛出。
        """
        code, output = await run_dreamina(self._cli_path, args, timeout=_SUBMIT_TIMEOUT_SECONDS)
        submit_id = parse_submit_id(output)
        if submit_id is not None:
            if code != 0:
                logger.warning("Dreamina submit 非零退出（code=%d）但已解析到 submit_id=%s，按已提交处理", code, submit_id)
            return submit_id
        raise error_from_cli_output(output, context=f"{args[0]} 提交")

    async def _await_result(self, submit_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        """轮询到成片落盘，把产物挪到 output_path 并清理临时下载目录。"""
        download_dir = request.output_path.parent / f".dreamina-{submit_id}"
        files = await poll_until_downloaded(
            cli_path=self._cli_path,
            submit_id=submit_id,
            download_dir=download_dir,
            suffixes=VIDEO_SUFFIXES,
            poll_interval=_POLL_INTERVAL_SECONDS,
            max_wait=_MAX_WAIT_SECONDS,
            query_timeout=_QUERY_TIMEOUT_SECONDS,
            label="Dreamina",
        )

        def _finalize() -> None:
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            # 单视频任务：目录里只应有一个成片，防御性取最新（mtime 最大）
            shutil.move(str(files[-1]), str(request.output_path))
            shutil.rmtree(download_dir, ignore_errors=True)

        await asyncio.to_thread(_finalize)
        logger.info("Dreamina 视频已落盘: %s (submit_id=%s)", request.output_path, submit_id)

        return VideoGenerationResult(
            video_path=request.output_path,
            provider=PROVIDER_DREAMINA_CLI,
            model=self._model,
            duration_seconds=request.duration_seconds,
            task_id=submit_id,
            # CLI 无音频开关（故不声明 GENERATE_AUDIO 能力）：2.0 家族成片原生带声、1.x 无声，
            # 按模型家族如实回填元数据，供下游（版本元数据 / 剪映导出）判断成片有无声
            generate_audio=self._model.startswith("seedance2"),
        )
