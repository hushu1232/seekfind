"""
求问 — 语音合成 (TTS)
Phase 4 实现阶段，当前为骨架代码。
支持 edge-tts 和 sherpa-onnx。
"""

import structlog

logger = structlog.get_logger()


class TTSService:
    """语音合成服务。"""

    def __init__(self):
        self._engine = None

    async def initialize(self):
        """初始化 TTS 引擎。"""
        logger.info("TTS 引擎初始化中...")
        # TODO: Phase 4 实现 - 初始化 edge-tts
        logger.info("TTS 引擎就绪")

    async def synthesize(self, text: str) -> bytes:
        """
        将文本转为音频。

        Args:
            text: 要朗读的文本

        Returns:
            PCM 音频数据
        """
        # TODO: Phase 4 实现
        logger.info("语音合成", text_len=len(text))
        return b""
