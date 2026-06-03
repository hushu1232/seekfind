"""
求问 — 语音合成模块 (TTS)
=========================

职责：
  - 将文本转为语音（PCM 音频）
  - 支持 edge-tts（微软在线 TTS，质量高）
  - 支持 sherpa-onnx（离线 TTS，延迟低）
  - 返回音频数据供前端播放 + 口型同步

edge-tts 优势：
  - 中文语音质量高（zh-CN-XiaoxiaoNeural）
  - 免费，无需 API Key
  - 支持 SSML（语音合成标记语言）

音频格式：
  - 输出：PCM 16kHz 16bit 单声道
  - 前端通过 WebSocket 接收 base64 编码的音频数据
  - 前端使用 Web Audio API 播放

口型同步：
  - TTS 返回音频时，同时返回音量振幅序列
  - 前端根据振幅实时更新球体口型（setMouthOpen）
"""

import base64

import structlog

logger = structlog.get_logger()


class TTSService:
    """
    语音合成服务。

    生命周期：initialize() → synthesize() × N → shutdown()
    """

    def __init__(self):
        self._engine = None
        self._voice = "zh-CN-XiaoxiaoNeural"  # 默认中文女声
        self._use_edge_tts = True

    async def initialize(self) -> None:
        """
        初始化 TTS 引擎。

        优先使用 edge-tts（在线，质量高），
        备选 pyttsx3（离线，跨平台）。
        """
        # 优先 edge-tts（在线）
        try:
            import importlib.util
            if importlib.util.find_spec("edge_tts") is not None:
                self._use_edge_tts = True
                logger.info("TTS 引擎初始化完成", engine="edge-tts", voice=self._voice)
                return
        except (ImportError, ValueError):
            pass

        # 降级到 pyttsx3（离线）
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 150)  # 语速
            self._engine.setProperty("volume", 0.9)  # 音量
            self._use_edge_tts = False
            logger.info("TTS 引擎初始化完成（离线模式）", engine="pyttsx3")
            return
        except Exception as e:
            logger.warning("pyttsx3 初始化失败", error=str(e))

        # 全部不可用
        self._use_edge_tts = False
        self._engine = None
        logger.warning("TTS 功能不可用（edge-tts 和 pyttsx3 均不可用）")

    async def shutdown(self) -> None:
        self._engine = None

    def set_voice(self, voice: str) -> None:
        """
        切换语音。

        可用语音：
          zh-CN-XiaoxiaoNeural   — 中文女声（默认）
          zh-CN-YunxiNeural      — 中文男声
          zh-CN-XiaoyiNeural     — 中文女声（活泼）
          en-US-JennyNeural      — 英文女声
        """
        self._voice = voice
        logger.info("TTS 语音切换", voice=voice)

    async def synthesize(self, text: str) -> dict:
        """
        将文本转为语音。

        Args:
            text: 要朗读的文本（建议 < 200 字）

        Returns:
            {
                "audio": "base64 编码的音频",
                "sample_rate": 16000,
                "duration_ms": 3000,
                "mouth_data": [0.2, 0.5, 0.8, ...]  # 口型同步振幅序列
            }
        """
        if not text or len(text) > 500:
            return {"audio": "", "sample_rate": 16000, "duration_ms": 0, "mouth_data": []}

        if self._use_edge_tts:
            return await self._synthesize_edge_tts(text)
        elif self._engine:
            return await self._synthesize_pyttsx3(text)
        else:
            return {"audio": "", "sample_rate": 16000, "duration_ms": 0, "mouth_data": []}

    async def _synthesize_pyttsx3(self, text: str) -> dict:
        """使用 pyttsx3 合成语音（离线模式）。"""
        try:
            import os
            import tempfile

            # 保存到临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            self._engine.save_to_file(text, temp_path)
            self._engine.runAndWait()

            # 读取音频文件
            if os.path.exists(temp_path):
                with open(temp_path, "rb") as f:
                    audio_data = f.read()
                os.unlink(temp_path)

                audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                # WAV 文件大约 16kHz * 2bytes = 32KB/s
                duration_ms = len(audio_data) * 1000 // 32000

                # 生成口型同步数据
                mouth_frames = max(1, duration_ms // 100)
                mouth_data = [0.3 + 0.4 * (i % 3) / 2 for i in range(mouth_frames)]

                logger.info("pyttsx3 合成完成", text_len=len(text), duration_ms=duration_ms)

                return {
                    "audio": audio_base64,
                    "sample_rate": 16000,
                    "duration_ms": duration_ms,
                    "mouth_data": mouth_data,
                }

        except Exception as e:
            logger.error("pyttsx3 合成失败", error=str(e))

        return {"audio": "", "sample_rate": 16000, "duration_ms": 0, "mouth_data": []}

    async def _synthesize_edge_tts(self, text: str) -> dict:
        """使用 edge-tts 合成语音。"""
        try:

            import edge_tts

            # 创建通信实例
            communicate = edge_tts.Communicate(text, self._voice)

            # 收集音频数据
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]

            if not audio_data:
                return {"audio": "", "sample_rate": 16000, "duration_ms": 0, "mouth_data": []}

            # edge-tts 输出是 MP3，需要转为 PCM
            # 简化处理：直接返回 MP3 base64，前端用 Audio API 播放
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            # 估算时长（MP3 约 16kbps）
            duration_ms = len(audio_data) * 8 // 16

            # 生成口型同步数据（简化：均匀分布）
            mouth_frames = max(1, duration_ms // 100)
            mouth_data = [0.3 + 0.4 * (i % 3) / 2 for i in range(mouth_frames)]

            logger.info("TTS 合成完成", text_len=len(text), audio_len=len(audio_data), duration_ms=duration_ms)

            return {
                "audio": audio_base64,
                "sample_rate": 24000,  # edge-tts 默认 24kHz
                "duration_ms": duration_ms,
                "mouth_data": mouth_data,
            }

        except Exception as e:
            logger.error("TTS 合成失败", error=str(e))
            return {"audio": "", "sample_rate": 16000, "duration_ms": 0, "mouth_data": []}


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
tts_service = TTSService()
