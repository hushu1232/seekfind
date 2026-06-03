"""
求问 — 语音识别模块 (ASR)
=========================

职责：
  - 接收 PCM 音频数据，转为文本
  - 唤醒词"小求小求"检测
  - 语音指令识别（如"小求，闭嘴"）

技术选型：
  - Vosk：离线语音识别，支持中文，轻量（模型 ~50MB）
  - 备选：Whisper.cpp（更准但更重）

唤醒词检测：
  - "小求小求" — 唤醒球体，进入监听状态
  - "小求，闭嘴" — 关闭语音监听

音频格式：
  - 输入：PCM 16kHz 16bit 单声道
  - 浏览器通过 WebSocket 发送 base64 编码的 PCM 数据
"""

import json
from enum import StrEnum

import structlog

logger = structlog.get_logger()


class ASRState(StrEnum):
    """ASR 状态。"""
    IDLE = "idle"           # 空闲
    LISTENING = "listening"  # 监听唤醒词
    RECOGNIZING = "recognizing"  # 识别中


class ASRService:
    """
    语音识别服务。

    生命周期：initialize() → process_audio() × N → shutdown()
    """

    def __init__(self):
        self._model = None
        self._recognizer = None
        self._state = ASRState.IDLE
        self._wakeword_buffer = ""  # 唤醒词检测缓冲区

    async def initialize(self) -> None:
        """
        加载 Vosk 模型。

        模型路径：models/vosk-model-small-cn-0.22（约 50MB）
        如果模型不存在，ASR 功能降级（返回空文本）。
        """
        try:
            from vosk import KaldiRecognizer, Model

            model_path = "models/vosk-model-small-cn-0.22"
            self._model = Model(model_path)
            self._recognizer = KaldiRecognizer(self._model, 16000)
            self._state = ASRState.LISTENING
            logger.info("ASR 模型加载完成", path=model_path)
        except Exception as e:
            logger.warning("ASR 模型加载失败，语音功能不可用", error=str(e))
            self._state = ASRState.IDLE

    async def shutdown(self) -> None:
        self._model = None
        self._recognizer = None
        self._state = ASRState.IDLE

    @property
    def state(self) -> ASRState:
        return self._state

    def set_state(self, state: ASRState) -> None:
        self._state = state
        logger.info("ASR 状态切换", state=state.value)

    async def process_audio(self, audio_base64: str) -> dict:
        """
        处理音频数据。

        Args:
            audio_base64: base64 编码的 PCM 音频数据

        Returns:
            {
                "text": "识别的文本",
                "is_wakeword": false,
                "is_command": false,
                "state": "recognizing"
            }
        """
        if not self._recognizer:
            return {"text": "", "is_wakeword": False, "is_command": False, "state": self._state.value}

        try:
            import base64
            audio_bytes = base64.b64decode(audio_base64)

            # 送入识别器
            if self._recognizer.AcceptWaveform(audio_bytes):
                result = json.loads(self._recognizer.Result())
                text = result.get("text", "").strip()
            else:
                partial = json.loads(self._recognizer.PartialResult())
                text = partial.get("partial", "").strip()

            if not text:
                return {"text": "", "is_wakeword": False, "is_command": False, "state": self._state.value}

            # 检测唤醒词
            if self._detect_wakeword(text):
                self._state = ASRState.RECOGNIZING
                return {"text": "", "is_wakeword": True, "is_command": False, "state": "listening"}

            # 检测控制指令
            if self._detect_command(text):
                return {"text": "", "is_wakeword": False, "is_command": True, "state": "idle"}

            # 正常识别结果
            if self._state == ASRState.RECOGNIZING:
                return {"text": text, "is_wakeword": False, "is_command": False, "state": "recognizing"}

            return {"text": "", "is_wakeword": False, "is_command": False, "state": self._state.value}

        except Exception as e:
            logger.error("音频处理失败", error=str(e))
            return {"text": "", "is_wakeword": False, "is_command": False, "state": "error"}

    def _detect_wakeword(self, text: str) -> bool:
        """
        检测唤醒词"小求小求"。

        支持变体：
          - 小求小求
          - 小球小球
          - 小秋小秋
        """
        wakewords = ["小求小求", "小球小球", "小秋小秋"]
        return any(wk in text for wk in wakewords)

    def _detect_command(self, text: str) -> bool:
        """
        检测控制指令。

        指令：
          - "小求，闭嘴" / "闭嘴" — 关闭监听
          - "小求，停" / "停" — 停止说话
        """
        commands = ["闭嘴", "小求闭嘴", "小求，闭嘴", "停", "停止"]
        if any(cmd in text for cmd in commands):
            self._state = ASRState.LISTENING
            return True
        return False


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
asr_service = ASRService()
