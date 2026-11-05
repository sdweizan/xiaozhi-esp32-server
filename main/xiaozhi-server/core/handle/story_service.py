"""故事数据服务 — 本地 JSON 文件读取

从 resource/stories.json 读取故事数据，
提供故事列表（分页）和按 id 获取详情两个接口。
只展示中文内容（title_zh / content_zh）。
"""

import json
import os
import asyncio
from typing import Dict, Any, List, Optional
from config.logger import setup_logging
from core.utils.cache.manager import cache_manager, CacheType

TAG = __name__
logger = setup_logging()

# ── 数据文件路径 ──────────────────────────────────────────────
_DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                          "resource", "stories.json")

# ── 缓存 TTL（秒） ──────────────────────────────────────────────
_LIST_TTL = 2 * 3600    # 2 小时
_DETAIL_TTL = 24 * 3600 # 24 小时

# ── 默认分页 ────────────────────────────────────────────────────
DEFAULT_PAGE_SIZE = 20


def _load_stories() -> List[Dict[str, Any]]:
    """从 JSON 文件加载故事数据"""
    if not os.path.exists(_DATA_FILE):
        raise FileNotFoundError(f"故事数据文件不存在: {_DATA_FILE}")
    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def fetch_story_list(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Dict[str, Any]:
    """获取故事列表（分页），只返回中文字段"""
    cache_key = f"story_list_p{page}_ps{page_size}"
    cached = cache_manager.get(CacheType.STORY, cache_key)
    if cached:
        return cached

    try:
        stories = await asyncio.to_thread(_load_stories)
    except Exception as e:
        logger.bind(tag=TAG).error(f"加载故事数据失败: {e}", exc_info=True)
        raise RuntimeError(f"加载故事数据失败: {e}")

    total = len(stories)
    start = (page - 1) * page_size
    end = start + page_size
    page_stories = stories[start:end]

    result = {
        "stories": [
            {"id": s["id"], "title": s.get("title_zh", ""), "date": s.get("date", "")}
            for s in page_stories
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "totalPages": max(1, (total + page_size - 1) // page_size),
    }
    cache_manager.set(CacheType.STORY, cache_key, result, ttl=_LIST_TTL)
    return result


async def fetch_story_content(story_id: int) -> Optional[Dict[str, str]]:
    """按 id 获取故事详情，只返回中文字段"""
    cache_key = f"story_detail_{story_id}"
    cached = cache_manager.get(CacheType.STORY, cache_key)
    if cached:
        return cached

    try:
        stories = await asyncio.to_thread(_load_stories)
    except Exception as e:
        logger.bind(tag=TAG).error(f"加载故事数据失败: {e}", exc_info=True)
        raise RuntimeError(f"加载故事数据失败: {e}")

    for s in stories:
        if s.get("id") == story_id:
            result = {
                "id": s["id"],
                "title": s.get("title_zh", ""),
                "content": s.get("content_zh", ""),
            }
            cache_manager.set(CacheType.STORY, cache_key, result, ttl=_DETAIL_TTL)
            return result

    return None
