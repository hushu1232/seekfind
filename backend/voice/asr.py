"""
求问 — 语音识别 (ASR)
Phase 4 实现阶段，当前为骨架代码。
支持 Vosk 本地识别。
"""

import structlog

logger = structlog.get_logger()


class ASRService:
    """语音识别服务。"""

    def __init__(self):
        self._model = None

    async def initialize(self):
        """加载 ASR 模型。"""
        logger.info("ASR 模型加载中...")
        # TODO: Phase 4 实现 - 加载 Vosk 模型
        logger.info("ASR 模型就绪")

    async def transcribe(self, audio_data: bytes) -> str:
        """
        将音频转为文本。

        Args:
            audio_data: PCM 音频数据

        Returns:
            识别的文本
        """
        # TODO: Phase 4 实现
        logger.info("语音识别", audio_len=len(audio_data))
        return ""

    async def detect_wakeword(self, audio_data: bytes) -> bool:
        """
        检测唤醒词"小求小求"。

        Returns:
            是否检测到唤醒词
        """
        # TODO: Phase 4 实现
        return False
