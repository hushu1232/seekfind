"""
求问 — 浏览器控制模块
====================

通过 Chrome Extension Content Script 控制浏览器，
参考 agent-browser 的无障碍树快照 + @eN 引用系统。

架构：
  后端工具 → WS 消息 → Service Worker → Content Script → DOM 操作 → 结果返回
"""
