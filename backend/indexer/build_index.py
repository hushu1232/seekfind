"""
求问 — 索引构建器
将爬取的文档分块、embedding、存入 Chroma + BM25。
"""

import json
import hashlib
from pathlib import Path

import jieba
import structlog

from indexer.crawler import CrawledDoc, DocCrawler

logger = structlog.get_logger()


class IndexBuilder:
    """索引构建器。"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, doc: CrawledDoc) -> list[dict]:
        """将文档分块。"""
        text = doc.text
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            chunk_id = hashlib.md5(
                f"{doc.url}_{start}_{end}".encode()
            ).hexdigest()
            chunks.append(
                {
                    "id": chunk_id,
                    "text": chunk_text,
                    "metadata": {
                        "source_url": doc.url,
                        "title": doc.title,
                        "chunk_start": start,
                        "chunk_end": end,
                    },
                }
            )
            start += self.chunk_size - self.chunk_overlap
        return chunks

    async def build_from_url(self, url: str, long_term_memory) -> int:
        """从 URL 爬取并构建索引。"""
        crawler = DocCrawler()
        docs = await crawler.crawl(url)
        return await self.build_from_docs(docs, long_term_memory)

    async def build_from_docs(self, docs: list[CrawledDoc], long_term_memory) -> int:
        """从文档列表构建索引。"""
        all_chunks = []
        for doc in docs:
            chunks = self.chunk_document(doc)
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.warning("无有效文档块")
            return 0

        # 批量写入 Chroma
        await long_term_memory.add(
            collection="docs",
            texts=[c["text"] for c in all_chunks],
            metadatas=[c["metadata"] for c in all_chunks],
            ids=[c["id"] for c in all_chunks],
        )

        logger.info("索引构建完成", chunks=len(all_chunks), docs=len(docs))
        return len(all_chunks)

    async def build_from_builtin(self, knowledge_dir: str, long_term_memory) -> int:
        """从内置常识库构建索引。"""
        knowledge_path = Path(knowledge_dir)
        if not knowledge_path.exists():
            logger.warning("内置常识库目录不存在", path=knowledge_dir)
            return 0

        all_chunks = []
        for json_file in knowledge_path.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                product = data.get("product", json_file.stem)
                for entry in data.get("entries", []):
                    chunk_id = hashlib.md5(
                        f"{product}_{entry['question']}".encode()
                    ).hexdigest()
                    text = f"产品：{product}\n问题：{entry['question']}\n回答：{entry['answer']}"
                    all_chunks.append(
                        {
                            "id": chunk_id,
                            "text": text,
                            "metadata": {
                                "product": product,
                                "question": entry["question"],
                                "selectors": json.dumps(entry.get("selectors", [])),
                                "url_pattern": entry.get("url_pattern", ""),
                                "source": "builtin",
                            },
                        }
                    )
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
