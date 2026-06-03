"""
求问 — 索引构建 CLI
用法：
  python -m indexer.cli --url https://docs.example.com
  python -m indexer.cli --builtin
  python -m indexer.cli --file ./my_doc.md
"""

import argparse
import asyncio
import os
import sys

# 确保 backend 目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.long_term import LongTermMemory

from indexer.build_index import IndexBuilder
from indexer.crawler import CrawledDoc


async def main():
    parser = argparse.ArgumentParser(description="求问文档索引构建工具")
    parser.add_argument("--url", type=str, help="文档站点 URL")
    parser.add_argument("--file", type=str, help="本地文件路径")
    parser.add_argument("--builtin", action="store_true", help="加载内置常识库")
    parser.add_argument("--knowledge-dir", type=str, default="knowledge/builtin", help="常识库目录")
    args = parser.parse_args()

    memory = LongTermMemory()
    await memory.initialize()
    builder = IndexBuilder()

    if args.url:
        print(f"正在爬取 {args.url} ...")
        count = await builder.build_from_url(args.url, memory)
        print(f"索引构建完成，共 {count} 个文档块")
    elif args.file:
        from pathlib import Path
        path = Path(args.file)
        if not path.exists():
            print(f"文件不存在: {args.file}")
            return
        text = path.read_text(encoding="utf-8")
        doc = CrawledDoc(url=str(path), title=path.name, text=text)
        count = await builder.build_from_docs([doc], memory)
        print(f"索引构建完成，共 {count} 个文档块")
    elif args.builtin:
        count = await builder.build_from_builtin(args.knowledge_dir, memory)
        print(f"内置常识库加载完成，共 {count} 个文档块")
    else:
        parser.print_help()

    await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
