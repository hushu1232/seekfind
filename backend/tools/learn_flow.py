"""
求问 — 操作流学习工具
=====================

职责：
  - 录制用户操作序列（点击、输入、导航）
  - 将操作流存储到 Chroma flows 集合
  - 回放操作流生成分步指引

操作流数据结构：
  {
    "name": "创建项目",
    "url_pattern": "app.example.com/*",
    "steps": [
      {"order": 1, "action": "click", "selector": "#new-btn", "description": "点击新建按钮"},
      {"order": 2, "action": "input", "selector": "#name-input", "value": "项目名称", "description": "输入项目名称"},
      {"order": 3, "action": "click", "selector": "#submit-btn", "description": "点击提交"}
    ]
  }

用法：
  result = await learn_flow_tool.execute("start_recording", "创建项目")
  result = await learn_flow_tool.execute("stop_recording")
  result = await learn_flow_tool.execute("replay", "创建项目")
"""

import json
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class LearnFlowTool:
    """
    操作流学习工具。

    支持四种操作：
      start_recording — 开始录制
      stop_recording  — 停止录制
      replay          — 回放操作流
      list            — 列出已录制的操作流
    """

    name: str = "learn_flow"
    description: str = (
        "录制/回放用户操作流。"
        "当用户想要记录某个操作流程时使用（如'帮我记住怎么创建项目'）。"
    )
    schema: dict = None

    # 录制状态
    _is_recording: bool = False
    _current_flow_name: str = ""
    _current_steps: list = None

    def __post_init__(self):
        self._current_steps = []
        self.schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "操作类型",
                        "enum": ["start_recording", "stop_recording", "replay", "list"],
                    },
                    "flow_name": {
                        "type": "string",
                        "description": "操作流名称（start_recording 和 replay 时必填）",
                    },
                },
                "required": ["action"],
            },
        }

    async def execute(
        self,
        action: str,
        flow_name: str = "",
        long_term_memory=None,
    ) -> str:
        """
        执行操作流操作。

        Args:
            action: 操作类型
            flow_name: 操作流名称
            long_term_memory: LongTermMemory 实例

        Returns:
            JSON 操作结果
        """
        if action == "start_recording":
            return self._start_recording(flow_name)
        elif action == "stop_recording":
            return await self._stop_recording(long_term_memory)
        elif action == "replay":
            return await self._replay(flow_name, long_term_memory)
        elif action == "list":
            return await self._list_flows(long_term_memory)
        else:
            return json.dumps({"error": f"未知操作: {action}"})

    def _start_recording(self, flow_name: str) -> str:
        """开始录制操作流。"""
        if not flow_name:
            return json.dumps({"error": "请提供操作流名称"})

        self._is_recording = True
        self._current_flow_name = flow_name
        self._current_steps = []

        logger.info("开始录制操作流", name=flow_name)
        return json.dumps({
            "status": "recording",
            "message": f"开始录制「{flow_name}」，请执行操作...",
        }, ensure_ascii=False)

    async def _stop_recording(self, long_term_memory=None) -> str:
        """停止录制并保存。"""
        if not self._is_recording:
            return json.dumps({"error": "当前没有在录制"})

        self._is_recording = False
        flow_data = {
            "name": self._current_flow_name,
            "steps": self._current_steps,
            "step_count": len(self._current_steps),
        }

        # 保存到 Chroma
        if long_term_memory:
            await long_term_memory.add(
                collection="flows",
                texts=[json.dumps(flow_data, ensure_ascii=False)],
                metadatas=[{"flow_name": self._current_flow_name, "source": "recorded"}],
                ids=[f"flow_{self._current_flow_name}"],
            )

        logger.info("录制完成", name=self._current_flow_name, steps=len(self._current_steps))
        return json.dumps({
            "status": "saved",
            "flow_name": self._current_flow_name,
            "step_count": len(self._current_steps),
        }, ensure_ascii=False)

    def add_step(self, action: str, selector: str, description: str, value: str = "") -> None:
        """
        添加一个录制步骤（由 observer.ts 调用）。

        Args:
            action: 操作类型 (click/input/scroll/navigate)
            selector: 目标元素选择器
            description: 操作描述
            value: 输入值（input 操作时）
        """
        if not self._is_recording:
            return

        self._current_steps.append({
            "order": len(self._current_steps) + 1,
            "action": action,
            "selector": selector,
            "description": description,
            "value": value,
        })
        logger.debug("录制步骤", action=action, selector=selector)

    async def _replay(self, flow_name: str, long_term_memory=None) -> str:
        """回放操作流。"""
        if not long_term_memory:
            return json.dumps({"error": "记忆系统未初始化"})

        results = await long_term_memory.search(
            query=flow_name, collection="flows", top_k=1
        )

        if not results:
            return json.dumps({"error": f"未找到操作流「{flow_name}」"})

        flow_data = json.loads(results[0]["text"])
        logger.info("回放操作流", name=flow_name, steps=len(flow_data.get("steps", [])))

        return json.dumps({
            "status": "replaying",
            "flow": flow_data,
        }, ensure_ascii=False)

    async def _list_flows(self, long_term_memory=None) -> str:
        """列出所有已录制的操作流。"""
        if not long_term_memory:
            return json.dumps({"flows": []})

        # 从 Chroma 获取所有 flows
        try:
            coll = long_term_memory._collections.get("flows")
            if not coll:
                return json.dumps({"flows": []})
            results = coll.get()
            flows = []
            for meta in results.get("metadatas", []):
                flows.append(meta.get("flow_name", "unknown"))
            return json.dumps({"flows": flows}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"flows": [], "error": str(e)})


# ---------------------------------------------------------------------------
# 工具实例
# ---------------------------------------------------------------------------
learn_flow_tool = LearnFlowTool()
