"""Seedance / short-video prompt policy shared by prompt builders.

The text describes production constraints and review language only. It does not
add a provider integration, execution path, queue, or automated media workflow.
"""

SEEDANCE_PROMPT_POLICY = """Seedance 视觉提示词策略：
- 时长只使用项目视频模型声明的 supported_durations；不要在提示词中发明模型未支持的秒数。
- image_prompt 聚焦单帧可见信息：主体、环境、光线、氛围至少覆盖三层，避免抽象内心戏、BGM、剪辑说明。
- video_prompt 聚焦一个镜头内可观察的连续动作：主体动作、物件互动、环境动态宜相互呼应，避免把多段蒙太奇塞进同一镜头。
- 参考图 / 资产名必须与项目登记保持一致；缺资产时先提示补齐，不要用近义词替换角色、场景、道具名称。
- 中文短剧默认竖屏节奏更紧：开场先给冲突或危机画面，再补世界观，不用介绍性远景拖慢进入。""".strip()


__all__ = ["SEEDANCE_PROMPT_POLICY"]
