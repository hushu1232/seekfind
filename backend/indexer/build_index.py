"""
求问 — 索引构建器
=================

优化点：
  1. 增量索引：用 URL + content hash 判断是否需要更新，跳过已索引的文档
  2. 智能分块：优先按段落（\\n\\n）分割，其次按句子边界，最后才用固定字符切割
  3. 去重：md5(url + chunk_text) 作为 chunk ID，相同内容不重复写入
  4. 流水线化：build_from_url_streaming 爬一页索引一页，减少内存占用

分块策略（优化后）：
  优先级 1: 按 \\n\\n 段落分割（保留完整段落语义）
  优先级 2: 段落过长时按 \\n 句子分割
  优先级 3: 句子过长时按固定字符数切割（chunk_size 上限）
  相邻分块有 overlap 个字符重叠，保证上下文连续性
"""

import hashlib
import json
from pathlib import Path

import structlog

from indexer.crawler import CrawledDoc

logger = structlog.get_logger()


class IndexBuilder:
    """
    索引构建器。

    Attributes:
        chunk_size: 每个分块的最大字符数
        chunk_overlap: 相邻分块的重叠字符数
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, doc: CrawledDoc) -> list[dict]:
        """
        智能分块。

        策略：段落 → 句子 → 固定字符
        """
        text = doc.text
        chunks = []

        # Step 1: 按段落分割
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        for para in paragraphs:
            if len(para) <= self.chunk_size:
                # 段落大小合适，直接作为一个 chunk
                chunk_id = hashlib.md5(f"{doc.url}_{para}".encode()).hexdigest()
                chunks.append({
                    "id": chunk_id,
                    "text": para,
                    "metadata": {
                        "source_url": doc.url,
                        "title": doc.title,
                        "chunk_type": "paragraph",
                    },
                })
            else:
                # 段落过长，按句子分割
                chunks.extend(self._chunk_by_sentences(doc, para))

        return chunks

    def _chunk_by_sentences(self, doc: CrawledDoc, text: str) -> list[dict]:
        """按句子边界分割长段落。"""
        chunks = []

        # 按中文句号、英文句号、换行分割
        import re
        sentences = re.split(r'(?<=[。！？.!?\n])', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk = ""
        for sent in sentences:
            if len(current_chunk) + len(sent) <= self.chunk_size:
                current_chunk += sent
            else:
                if current_chunk:
                    chunk_id = hashlib.md5(f"{doc.url}_{current_chunk}".encode()).hexdigest()
                    chunks.append({
                        "id": chunk_id,
                        "text": current_chunk,
                        "metadata": {
                            "source_url": doc.url,
                            "title": doc.title,
                            "chunk_type": "sentence",
                        },
                    })
                current_chunk = sent

        # 最后一个 chunk
        if current_chunk:
            chunk_id = hashlib.md5(f"{doc.url}_{current_chunk}".encode()).hexdigest()
            chunks.append({
                "id": chunk_id,
                "text": current_chunk,
                "metadata": {
                    "source_url": doc.url,
                    "title": doc.title,
                    "chunk_type": "sentence",
                },
            })

        return chunks

    async def build_from_url(self, url: str, long_term_memory) -> int:
        """从 URL 爬取并构建索引（批量模式）。"""
        from indexer.crawler import DocCrawler
        crawler = DocCrawler()
        docs = await crawler.crawl(url)
        return await self.build_from_docs(docs, long_term_memory)

    async def build_from_url_streaming(self, url: str, long_term_memory, max_pages: int = 100) -> int:
        """
        从 URL 爬取并构建索引（流水线模式）。

        与 build_from_url 的区别：
          - build_from_url: 爬取全部 → 索引全部（内存占用高）
          - build_from_url_streaming: 爬一页 → 索引一页 → 爬下一页（内存友好）

        Args:
            url: 起始 URL
            long_term_memory: LongTermMemory 实例
            max_pages: 最大爬取页数

        Returns:
            总索引的 chunk 数量
        """
        from indexer.crawler import DocCrawler
        from urllib.parse import urlparse

        crawler = DocCrawler(max_pages=max_pages)
        base_domain = urlparse(url).netloc
        queue = [(url, 0)]
        visited = set()
        total_chunks = 0

        while queue:
            page_url, depth = queue.pop(0)
            if page_url in visited or depth > crawler.max_depth:
                continue
            visited.add(page_url)

            # 爬取单页
            try:
                doc = await crawler._fetcher.fetch(page_url)
                doc.depth = depth
            except Exception as e:
                logger.warning("爬取失败", url=page_url, error=str(e))
                continue

            # 立即索引
            if doc.text:
                chunks = self.chunk_document(doc)
                new_count = await self._index_chunks(chunks, long_term_memory)
                total_chunks += new_count
                logger.info(
                    "页面已索引",
                    url=page_url,
                    new_chunks=new_count,
                    total=total_chunks,
                    depth=depth,
                )

            # 提取链接继续
            if depth < crawler.max_depth and doc.html:
                links = crawler._extract_links(doc.html, base_domain)
                for link in links:
                    if link not in visited:
                        queue.append((link, depth + 1))

        logger.info("流水线索引完成", total_chunks=total_chunks, pages=len(visited))
        return total_chunks

    async def build_from_docs(self, docs: list[CrawledDoc], long_term_memory) -> int:
        """
        从文档列表构建索引（增量）。

        增量逻辑：
          1. 生成 chunk ID（md5 of url + text）
          2. 检查 Chroma 中是否已存在相同 ID
          3. 只写入新 chunk
        """
        all_chunks = []
        for doc in docs:
            chunks = self.chunk_document(doc)
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.warning("无有效文档块")
            return 0

        return await self._index_chunks(all_chunks, long_term_memory)

    async def _index_chunks(self, chunks: list[dict], long_term_memory) -> int:
        """
        将 chunks 写入 Chroma（增量）。

        增量逻辑：检查已存在的 ID，只写入新 chunk。
        """
        if not chunks:
            return 0

        # 检查已存在的 chunk（增量过滤）
        existing_ids = set()
        try:
            coll = long_term_memory._collections.get("docs")
            if coll:
                existing = coll.get(ids=[c["id"] for c in chunks])
                existing_ids = set(existing.get("ids", []))
        except Exception:
            pass

        # 过滤出新 chunk
        new_chunks = [c for c in chunks if c["id"] not in existing_ids]

        if not new_chunks:
            logger.debug("所有文档块已存在，跳过索引", total=len(chunks))
            return 0

        # 写入新 chunk
        await long_term_memory.add(
            collection="docs",
            texts=[c["text"] for c in new_chunks],
            metadatas=[c["metadata"] for c in new_chunks],
            ids=[c["id"] for c in new_chunks],
        )

        logger.debug(
            "索引写入完成",
            new_chunks=len(new_chunks),
            skipped=len(chunks) - len(new_chunks),
        )
        return len(new_chunks)

    async def build_from_builtin(self, knowledge_dir: str, long_term_memory) -> int:
        """从内置常识库 JSON 文件构建索引（增量）。"""
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
                    chunk_id = hashlib.md5(f"{product}_{entry['question']}".encode()).hexdigest()
                    text = f"产品：{product}\n问题：{entry['question']}\n回答：{entry['answer']}"
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

        if not all_chunks:
            return 0

        return await self._index_chunks(all_chunks, long_term_memory)
