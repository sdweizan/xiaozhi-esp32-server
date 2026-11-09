"""古诗词数据服务 — 本地 JSON 文件读取

从 resource/300.json 读取古诗词数据，
提供诗词列表（按类型筛选）和按 id 获取详情两个接口。
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
                          "resource", "300.json")

# ── 缓存 TTL（秒） ──────────────────────────────────────────────
_LIST_TTL = 24 * 3600   # 24 小时
_DETAIL_TTL = 24 * 3600 # 24 小时


def _load_poems() -> List[Dict[str, Any]]:
    """从 JSON 文件加载诗词数据（非异步，调用方在 executor 中执行或确保已缓存）"""
    if not os.path.exists(_DATA_FILE):
        raise FileNotFoundError(f"诗词数据文件不存在: {_DATA_FILE}")
    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def fetch_poem_list(poem_type: Optional[str] = None) -> Dict[str, Any]:
    """获取诗词列表，支持按 type 筛选

    返回格式:
    {
        "poems": [{"id": 1, "title": "...", "author": "...", "type": "..."}],
        "total": N,
        "filter_type": "五言古诗" | null
    }
    """
    cache_key = f"poem_list_{poem_type or 'all'}"
    cached = cache_manager.get(CacheType.POEM, cache_key)
    if cached:
        return cached

    try:
        poems = await asyncio.to_thread(_load_poems)
    except Exception as e:
        logger.bind(tag=TAG).error(f"加载诗词数据失败: {e}", exc_info=True)
        raise RuntimeError(f"加载诗词数据失败: {e}")

    # 按类型筛选
    if poem_type:
        filtered = [p for p in poems if p.get("type") == poem_type]
    else:
        filtered = poems

    result = {
        "poems": [
            {"id": p["id"], "title": p["title"], "author": p["author"], "type": p["type"]}
            for p in filtered
        ],
        "total": len(filtered),
        "filter_type": poem_type,
    }
    cache_manager.set(CacheType.POEM, cache_key, result, ttl=_LIST_TTL)
    return result


async def fetch_poem_by_id(poem_id: int) -> Optional[Dict[str, Any]]:
    """按 id 获取诗词详情"""
    cache_key = f"poem_detail_{poem_id}"
    cached = cache_manager.get(CacheType.POEM, cache_key)
    if cached:
        return cached

    try:
        poems = await asyncio.to_thread(_load_poems)
    except Exception as e:
        logger.bind(tag=TAG).error(f"加载诗词数据失败: {e}", exc_info=True)
        raise RuntimeError(f"加载诗词数据失败: {e}")

    for p in poems:
        if p.get("id") == poem_id:
            result = {
                "id": p["id"],
                "title": p["title"],
                "author": p["author"],
                "type": p["type"],
                "contents": p["contents"],
            }
            cache_manager.set(CacheType.POEM, cache_key, result, ttl=_DETAIL_TTL)
            return result

    return None


async def fetch_poem_types() -> List[str]:
    """获取所有诗词类型列表"""
    cache_key = "poem_types"
    cached = cache_manager.get(CacheType.POEM, cache_key)
    if cached:
        return cached

    try:
        poems = await asyncio.to_thread(_load_poems)
    except Exception as e:
        logger.bind(tag=TAG).error(f"加载诗词数据失败: {e}", exc_info=True)
        raise RuntimeError(f"加载诗词数据失败: {e}")

    types = sorted(set(p.get("type", "") for p in poems if p.get("type")))
    cache_manager.set(CacheType.POEM, cache_key, types, ttl=_LIST_TTL)
    return types
