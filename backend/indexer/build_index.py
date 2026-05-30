"""
求问 — 索引构建器
=================

职责：
  - 将爬取的文档分块（chunking）
  - 将分块写入 Chroma 向量库（自动 embedding）
  - 从内置常识库 JSON 文件构建索引

分块策略：
  - 固定大小分块：chunk_size=500 字符，overlap=50 字符
  - 为什么用固定大小而非语义分块：
    1. 实现简单，无额外依赖
    2. 对于操作文档（步骤列表），固定分块效果够用
    3. 语义分块（如 LangChain RecursiveCharacterTextSplitter）可后续升级

去重：
  使用 md5(url + chunk_start + chunk_end) 作为 chunk ID，
  相同文档重新索引时会覆盖（Chroma upsert 语义）。

用法：
  builder = IndexBuilder()
  count = await builder.build_from_url("https://docs.example.com", memory)
  count = await builder.build_from_builtin("knowledge/builtin", memory)
"""

import hashlib
import json
from pathlib import Path

import structlog

from indexer.crawler import CrawledDoc, DocCrawler

logger = structlog.get_logger()


class IndexBuilder:
    """
    索引构建器。

    Attributes:
        chunk_size: 每个分块的最大字符数
        chunk_overlap: 相邻分块的重叠字符数（保证上下文连续性）
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, doc: CrawledDoc) -> list[dict]:
        """
        将单个文档分块。

        Args:
            doc: 爬取的文档

        Returns:
            [{"id": "md5hash", "text": "分块文本", "metadata": {...}}, ...]

        分块规则：
          - 从文档开头开始，每 chunk_size 个字符切一刀
          - 相邻分块重叠 chunk_overlap 个字符，避免在句子中间断开
          - 每个分块记录来源 URL、标题、字符偏移量
        """
        text = doc.text
        chunks = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]

            # 生成确定性 ID（相同输入 → 相同 ID，支持 upsert）
            chunk_id = hashlib.md5(
                f"{doc.url}_{start}_{end}".encode()
            ).hexdigest()

            chunks.append({
                "id": chunk_id,
                "text": chunk_text,
                "metadata": {
                    "source_url": doc.url,
                    "title": doc.title,
                    "chunk_start": start,
                    "chunk_end": end,
                },
            })

            # 下一个分块的起始位置（有重叠）
            start += self.chunk_size - self.chunk_overlap

        return chunks

    async def build_from_url(self, url: str, long_term_memory) -> int:
        """
        从 URL 爬取并构建索引。

        Args:
            url: 文档站点起始 URL
            long_term_memory: LongTermMemory 实例

        Returns:
            写入的分块总数
        """
        crawler = DocCrawler()
        docs = await crawler.crawl(url)
        return await self.build_from_docs(docs, long_term_memory)

    async def build_from_docs(self, docs: list[CrawledDoc], long_term_memory) -> int:
        """
        从文档列表构建索引。

        Args:
            docs: CrawledDoc 列表
            long_term_memory: LongTermMemory 实例

        Returns:
            写入的分块总数
        """
        all_chunks = []
        for doc in docs:
            chunks = self.chunk_document(doc)
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.warning("无有效文档块")
            return 0

        # 批量写入 Chroma（自动 embedding）
        await long_term_memory.add(
            collection="docs",
            texts=[c["text"] for c in all_chunks],
            metadatas=[c["metadata"] for c in all_chunks],
            ids=[c["id"] for c in all_chunks],
        )

        logger.info(
            "索引构建完成",
            chunks=len(all_chunks),
            docs=len(docs),
            avg_chunk_size=sum(len(c["text"]) for c in all_chunks) // len(all_chunks),
        )
        return len(all_chunks)

    async def build_from_builtin(self, knowledge_dir: str, long_term_memory) -> int:
        """
        从内置常识库 JSON 文件构建索引。

        常识库格式：
          {
            "product": "GitHub",
            "version": "2026",
            "entries": [
              {"question": "怎么创建仓库？", "answer": "1. 点击...", "selectors": [...], "url_pattern": "..."}
            ]
          }

        每个 entry 会被转为一个文档块：
          "产品：GitHub\n问题：怎么创建仓库？\n回答：1. 点击..."

        Args:
            knowledge_dir: 常识库目录路径
            long_term_memory: LongTermMemory 实例

        Returns:
            写入的分块总数
        """
        knowledge_path = Path(knowledge_dir)
        if not knowledge_path.exists():
            logger.warning("内置常识库目录不存在", path=knowledge_dir)
            return 0

        all_chunks = []
        for json_file in sorted(knowledge_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                product = data.get("product", json_file.stem)

                for entry in data.get("entries", []):
                    # 生成确定性 ID
                    chunk_id = hashlib.md5(
                        f"{product}_{entry['question']}".encode()
                    ).hexdigest()

                    # 拼接为文档文本
                    text = (
                        f"产品：{product}\n"
                        f"问题：{entry['question']}\n"
                        f"回答：{entry['answer']}"
                    )

                    all_chunks.append({
                        "id": chunk_id,
                        "text": text,
                        "metadata": {
                            "product": product,
                            "question": entry["question"],
                            "selectors": json.dumps(entry.get("selectors", []), ensure_ascii=False),
                            "url_pattern": entry.get("url_pattern", ""),
                            "source": "builtin",
                        },
                    })

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("解析常识库失败", file=str(json_file), error=str(e))

        if all_chunks:
            await long_term_memory.add(
                collection="docs",
                texts=[c["text"] for c in all_chunks],
                metadatas=[c["metadata"] for c in all_chunks],
                ids=[c["id"] for c in all_chunks],
            )

        logger.info("内置常识库索引完成", chunks=len(all_chunks))
        return len(all_chunks)
