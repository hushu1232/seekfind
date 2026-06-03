"""
求问 — 多级缓存管理器
====================

职责：
  1. 本地内存缓存（L1）
  2. Redis 分布式缓存（L2）
  3. 缓存失效和更新
  4. 缓存统计

缓存策略：
  - 查询缓存：相同查询直接返回缓存结果
  - 会话缓存：会话上下文缓存
  - 文档缓存：检索结果缓存
"""

import hashlib
import json
import time
from typing import Optional, Any
from datetime import datetime, timedelta
from collections import OrderedDict

import structlog

logger = structlog.get_logger()


class LRUCache:
    """
    LRU 缓存实现

    使用 OrderedDict 实现简单的 LRU 缓存。
    """

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self._cache:
            value, expire_at = self._cache[key]
            if time.time() < expire_at:
                # 移到最后（最近使用）
                self._cache.move_to_end(key)
                self._hits += 1
                return value
            else:
                # 过期，删除
                del self._cache[key]

        self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl: float = 300):
        """设置缓存"""
        # 如果已存在，更新
        if key in self._cache:
            del self._cache[key]

        # 检查容量
        while len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = (value, time.time() + ttl)

    def delete(self, key: str):
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        """清空缓存"""
        self._cache.clear()

    def size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)

    def stats(self) -> dict:
        """获取缓存统计"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }


class CacheManager:
    """
    多级缓存管理器

    L1: 本地内存缓存（快，容量小）
    L2: Redis 分布式缓存（慢，容量大）
    """

    def __init__(self, redis_client=None, l1_max_size: int = 1000):
        self._redis = redis_client
        self._l1 = LRUCache(max_size=l1_max_size)
        self._l1_ttl = 300  # 5 分钟
        self._l2_ttl = 3600  # 1 小时

    def _generate_key(self, prefix: str, params: dict) -> str:
        """生成缓存键"""
        # 对参数排序，确保相同参数生成相同键
        sorted_params = json.dumps(params, sort_keys=True)
        hash_value = hashlib.md5(sorted_params.encode()).hexdigest()
        return f"{prefix}:{hash_value}"

    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存

        优先从 L1 获取，L1 未命中则从 L2 获取。
        """
        # L1 缓存
        value = self._l1.get(key)
        if value is not None:
            return value

        # L2 缓存
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    value = json.loads(data)
                    # 写入 L1
                    self._l1.set(key, value, self._l1_ttl)
                    return value
            except Exception as e:
                logger.debug("Redis 获取失败", key=key, error=str(e))

        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        设置缓存

        同时写入 L1 和 L2。
        """
        # L1 缓存
        self._l1.set(key, value, ttl or self._l1_ttl)

        # L2 缓存
        if self._redis:
            try:
                data = json.dumps(value)
                await self._redis.setex(
                    key,
                    ttl or self._l2_ttl,
                    data,
                )
            except Exception as e:
                logger.debug("Redis 设置失败", key=key, error=str(e))

    async def delete(self, key: str):
        """删除缓存"""
        self._l1.delete(key)

        if self._redis:
            try:
                await self._redis.delete(key)
            except Exception as e:
                logger.debug("Redis 删除失败", key=key, error=str(e))

    async def invalidate_pattern(self, pattern: str):
        """
        按模式失效缓存

        Args:
            pattern: 键模式（如 "search:*"）
        """
        # L1 缓存（简单遍历）
        keys_to_delete = [
            k for k in self._l1._cache.keys()
            if k.startswith(pattern.rstrip("*"))
        ]
        for k in keys_to_delete:
            self._l1.delete(k)

        # L2 缓存
        if self._redis:
            try:
                keys = await self._redis.keys(pattern)
                if keys:
                    await self._redis.delete(*keys)
            except Exception as e:
                logger.debug("Redis 模式删除失败", pattern=pattern, error=str(e))

    async def clear(self):
        """清空所有缓存"""
        self._l1.clear()

        if self._redis:
            try:
                await self._redis.flushdb()
            except Exception as e:
                logger.debug("Redis 清空失败", error=str(e))

    def stats(self) -> dict:
        """获取缓存统计"""
        return {
            "l1": self._l1.stats(),
            "l2_available": self._redis is not None,
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """获取缓存管理器单例"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
