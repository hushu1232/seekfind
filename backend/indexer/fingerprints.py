"""
求问 — 浏览器指纹生成
====================

参考 Scrapling 的 engines/toolbelt/fingerprints.py。

使用 browserforge 生成真实的浏览器指纹 headers。
如果 browserforge 未安装，回退到内置的 User-Agent 池。

用法：
  from indexer.fingerprints import generate_stealth_headers
  headers = generate_stealth_headers()
  # → {"User-Agent": "Mozilla/5.0 ...", "Accept": "...", ...}
"""

import random
from functools import lru_cache

import structlog

logger = structlog.get_logger()

# 内置 User-Agent 池（browserforge 不可用时的降级）
_FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
]

# 完整的降级 headers 模板
_FALLBACK_HEADERS_TEMPLATES = [
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
    },
    {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
]


@lru_cache(maxsize=1)
def _get_header_generator():
    """延迟加载 browserforge HeaderGenerator（单例缓存）。"""
    try:
        from browserforge.headers import HeaderGenerator, Browser

        # 参考 Scrapling 的做法：限定主流浏览器版本范围
        browsers = [
            Browser(name="chrome", min_version=120),
            Browser(name="firefox", min_version=120),
            Browser(name="edge", min_version=120),
        ]
        generator = HeaderGenerator(
            browser=browsers,
            os=("windows", "macos", "linux"),
            device="desktop",
        )
        logger.info("browserforge HeaderGenerator 初始化成功")
        return generator
    except ImportError:
        logger.warning("browserforge 未安装，使用内置 UA 池降级")
        return None
    except Exception as e:
        logger.warning("browserforge 初始化失败，降级", error=str(e))
        return None


def generate_stealth_headers() -> dict:
    """
    生成真实浏览器指纹 headers。

    优先使用 browserforge 生成真实的浏览器指纹。
    如果 browserforge 不可用，使用内置的 User-Agent 池 + 固定 headers。

    Returns:
        dict: HTTP headers 字典
    """
    generator = _get_header_generator()

    if generator:
        try:
            headers = generator.generate()
            # 确保有 Referer（参考 Scrapling 的 _headers_job）
            if "referer" not in {k.lower() for k in headers}:
                headers["Referer"] = "https://www.google.com/"
            logger.debug(
                "browserforge 生成 headers",
                ua=headers.get("User-Agent", "")[:60],
            )
            return headers
        except Exception as e:
            logger.warning("browserforge 生成失败，降级到内置 UA", error=str(e))

    # 降级：随机选择 UA + 固定 headers
    ua = random.choice(_FALLBACK_USER_AGENTS)
    template = random.choice(_FALLBACK_HEADERS_TEMPLATES)
    headers = {"User-Agent": ua, **template}

    logger.debug("使用降级 headers", ua=ua[:60])
    return headers


def get_random_user_agent() -> str:
    """获取随机 User-Agent（仅 UA 字符串）。"""
    generator = _get_header_generator()
    if generator:
        try:
            headers = generator.generate()
            return headers.get("User-Agent", random.choice(_FALLBACK_USER_AGENTS))
        except Exception:
            pass
    return random.choice(_FALLBACK_USER_AGENTS)
