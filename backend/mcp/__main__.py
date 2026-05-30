"""
求问 — MCP Server 启动入口

用法：
  python -m mcp.server          # stdio 模式（供 Claude Desktop 等使用）
"""

from mcp.server import main

if __name__ == "__main__":
    main()
