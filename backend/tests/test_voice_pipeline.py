"""
求问 — 语音识别输出全链路测试
============================

测试完整语音链路：
  1. ASR 初始化 + 音频处理
  2. TTS 初始化 + 语音合成
  3. 唤醒词检测
  4. 语音指令识别
  5. ASR → 文本 → Agent → TTS 全链路
"""

import asyncio
import base64
import json
import struct
import pytest

from voice.tts import TTSService


class TestTTSInitialize:
    """TTS 初始化测试。"""

    @pytest.mark.asyncio
    async def test_tts_initialize(self):
        """TTS 可初始化。"""
        tts = TTSService()
        await tts.initialize()
        # 应该至少有一个引擎可用
        assert tts._use_edge_tts or tts._engine is not None
        print(f"\n  TTS 引擎: {'edge-tts' if tts._use_edge_tts else 'pyttsx3'}")

    @pytest.mark.asyncio
    async def test_tts_shutdown(self):
        """TTS 可关闭。"""
        tts = TTSService()
        await tts.initialize()
        await tts.shutdown()
        assert tts._engine is None

    def test_tts_voice_setting(self):
        """语音切换。"""
        tts = TTSService()
        tts.set_voice("zh-CN-YunxiNeural")
        assert tts._voice == "zh-CN-YunxiNeural"


class TestTTSSynthesize:
    """TTS 语音合成测试。"""

    @pytest.mark.asyncio
    async def test_synthesize_short_text(self):
        """合成短文本。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("你好，我是求问")

        assert "audio" in result
        assert "sample_rate" in result
        assert "duration_ms" in result
        assert "mouth_data" in result
        assert len(result["audio"]) > 0
        assert result["duration_ms"] > 0
        assert len(result["mouth_data"]) > 0
        print(f"\n  合成结果: {len(result['audio'])} 字符 audio, {result['duration_ms']}ms, {len(result['mouth_data'])} 帧口型")

    @pytest.mark.asyncio
    async def test_synthesize_empty_text(self):
        """空文本返回空结果。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("")
        assert result["audio"] == ""
        assert result["duration_ms"] == 0

    @pytest.mark.asyncio
    async def test_synthesize_long_text_truncated(self):
        """超长文本被截断。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("你好" * 300)  # 600 字符 > 500
        assert result["audio"] == ""

    @pytest.mark.asyncio
    async def test_synthesize_chinese(self):
        """中文语音合成。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("GitHub 怎么创建 Pull Request？请告诉我具体步骤。")
        assert len(result["audio"]) > 0
        print(f"\n  中文合成: {result['duration_ms']}ms")

    @pytest.mark.asyncio
    async def test_synthesize_mixed_content(self):
        """中英混合内容合成。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("请打开 VS Code，按 Ctrl+Shift+X 安装扩展。")
        assert len(result["audio"]) > 0

    @pytest.mark.asyncio
    async def test_mouth_data_proportional(self):
        """口型数据与音频时长成比例。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("测试口型同步")
        if result["duration_ms"] > 0:
            expected_frames = max(1, result["duration_ms"] // 100)
            assert len(result["mouth_data"]) == expected_frames
            # 口型值在合理范围
            for val in result["mouth_data"]:
                assert 0 <= val <= 1


class TestASRBasic:
    """ASR 基础测试（无需 Vosk 模型）。"""

    def test_asr_service_import(self):
        """ASR 服务可导入。"""
        from voice.asr import asr_service, ASRState
        assert asr_service is not None
        assert asr_service.state in (ASRState.IDLE, ASRState.LISTENING)

    @pytest.mark.asyncio
    async def test_asr_process_without_model(self):
        """无模型时返回空结果。"""
        from voice.asr import asr_service

        # 确保模型未加载
        asr_service._recognizer = None

        result = await asr_service.process_audio(base64.b64encode(b"\x00" * 1000).decode())
        assert result["text"] == ""
        assert result["is_wakeword"] is False
        assert result["is_command"] is False

    def test_wakeword_detection(self):
        """唤醒词检测。"""
        from voice.asr import asr_service

        assert asr_service._detect_wakeword("小求小求") is True
        assert asr_service._detect_wakeword("小球小球") is True
        assert asr_service._detect_wakeword("小秋小秋") is True
        assert asr_service._detect_wakeword("你好") is False
        assert asr_service._detect_wakeword("小求小求你好") is True  # 包含即可

    def test_command_detection(self):
        """指令检测。"""
        from voice.asr import asr_service

        assert asr_service._detect_command("闭嘴") is True
        assert asr_service._detect_command("小求闭嘴") is True
        assert asr_service._detect_command("小求，闭嘴") is True
        assert asr_service._detect_command("停") is True
        assert asr_service._detect_command("停止") is True
        assert asr_service._detect_command("你好") is False

    def test_asr_state_transitions(self):
        """状态转换。"""
        from voice.asr import asr_service, ASRState

        asr_service.set_state(ASRState.IDLE)
        assert asr_service.state == ASRState.IDLE

        asr_service.set_state(ASRState.LISTENING)
        assert asr_service.state == ASRState.LISTENING

        asr_service.set_state(ASRState.RECOGNIZING)
        assert asr_service.state == ASRState.RECOGNIZING


class TestVoicePipelineEndToEnd:
    """语音全链路测试。"""

    @pytest.mark.asyncio
    async def test_tts_output_format(self):
        """TTS 输出格式正确，前端可播放。"""
        tts = TTSService()
        await tts.initialize()

        result = await tts.synthesize("创建项目")

        # base64 可解码
        audio_bytes = base64.b64decode(result["audio"])
        assert len(audio_bytes) > 0

        # edge-tts 输出 MP3 或 OGG，pyttsx3 输出 WAV
        # 只检查有有效音频数据，不严格检查文件头
        assert len(audio_bytes) > 100  # 至少 100 bytes

        print(f"\n  音频格式: sample_rate={result['sample_rate']}, {len(audio_bytes)} bytes")

    @pytest.mark.asyncio
    async def test_tts_multiple_calls(self):
        """多次合成不崩溃。"""
        tts = TTSService()
        await tts.initialize()

        texts = ["你好", "创建项目", "GitHub 怎么用", "点击这个按钮"]
        for text in texts:
            result = await tts.synthesize(text)
            assert len(result["audio"]) > 0

        print(f"\n  连续合成 {len(texts)} 次，全部成功")

    @pytest.mark.asyncio
    async def test_tts_concurrent_synthesis(self):
        """并发合成不冲突。"""
        tts = TTSService()
        await tts.initialize()

        tasks = [
            tts.synthesize("第一个"),
            tts.synthesize("第二个"),
            tts.synthesize("第三个"),
        ]
        results = await asyncio.gather(*tasks)

        for i, result in enumerate(results):
            assert len(result["audio"]) > 0

        print(f"\n  并发合成 3 次，全部成功")

    @pytest.mark.asyncio
    async def test_wakeword_to_tts_chain(self):
        """唤醒词 → 状态切换 → TTS 输出 链路。"""
        from voice.asr import asr_service, ASRState
        from voice.tts import tts_service

        # 模拟唤醒
        asr_service.set_state(ASRState.LISTENING)
        assert asr_service._detect_wakeword("小求小求") is True
        asr_service.set_state(ASRState.RECOGNIZING)

        # 模拟识别结果 → TTS
        await tts_service.initialize()
        result = await tts_service.synthesize("我在，有什么可以帮你？")
        assert len(result["audio"]) > 0

        print(f"\n  唤醒→识别→TTS 链路: {result['duration_ms']}ms 音频")

    @pytest.mark.asyncio
    async def test_command_to_tts_chain(self):
        """语音指令 → TTS 确认 链路。"""
        from voice.asr import asr_service
        from voice.tts import tts_service

        # 模拟 "闭嘴" 指令
        is_command = asr_service._detect_command("闭嘴")
        assert is_command is True

        # TTS 确认
        await tts_service.initialize()
        result = await tts_service.synthesize("好的，我闭嘴了")
        assert len(result["audio"]) > 0

    @pytest.mark.asyncio
    async def test_full_mock_pipeline(self):
        """完整模拟链路：ASR 文本 → Agent 处理 → TTS 输出。"""
        from voice.tts import tts_service

        # 模拟 ASR 识别结果
        asr_text = "GitHub 怎么创建仓库"

        # 模拟 Agent 处理（直接用知识库答案）
        agent_response = "1. 登录 GitHub 后，点击右上角 + 号\n2. 选择 New repository\n3. 填写仓库名称\n4. 点击 Create repository"

        # TTS 合成
        await tts_service.initialize()
        result = await tts_service.synthesize(agent_response[:200])  # 截断到 200 字
        assert len(result["audio"]) > 0
        assert result["duration_ms"] > 0

        print(f"\n  全链路模拟: ASR('{asr_text[:20]}...') → Agent → TTS({result['duration_ms']}ms)")

    @pytest.mark.asyncio
    async def test_voice_setting_change(self):
        """语音切换后合成正常。"""
        tts = TTSService()
        await tts.initialize()

        # 默认语音
        r1 = await tts.synthesize("默认语音")
        assert len(r1["audio"]) > 0

        # 切换语音
        tts.set_voice("zh-CN-YunxiNeural")
        r2 = await tts.synthesize("男声语音")
        assert len(r2["audio"]) > 0

        print(f"\n  语音切换: 默认 → 男声，两次合成均成功")
