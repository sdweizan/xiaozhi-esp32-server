"""天气数据服务 — 和风天气 V7 API"""

import asyncio
import aiohttp
from typing import Dict, Any, List, Optional
from config.logger import setup_logging
from core.utils.cache.manager import cache_manager, CacheType

TAG = __name__
logger = setup_logging()


# ── 缓存 TTL（秒） ──────────────────────────────────────────────
_WEATHER_TTL = 15 * 60   # 15 分钟
_CITY_SEARCH_TTL = 60 * 60  # 1 小时


# ── HTTP 客户端（单例） ────────────────────────────────────────
_session: Optional[aiohttp.ClientSession] = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_weather_session():
    """关闭天气 HTTP 会话（清理时用）"""
    global _session
    if _session and not _session.closed:
        await _session.close()


# ── HTTP 响应检查 ─────────────────────────────────────────────
async def _check_response(resp: aiohttp.ClientResponse, context: str) -> None:
    """检查 HTTP 响应状态码，非 200 时读取原始体并记录日志"""
    if resp.status == 200:
        return
    text = await resp.text(errors="replace")
    logger.bind(tag=TAG).error(
        f"HTTP {resp.status} ({context}): url={resp.url}, body={text[:500]}"
    )
    raise RuntimeError(f"{context}: HTTP {resp.status} — {text[:200]}")


# ── 城市定位 ──────────────────────────────────────────────────
async def resolve_city(
    location_hint: str, api_key: str, api_host: str
) -> Optional[str]:
    """将城市名/别名解析为和风天气 city_id（如 101280601）

    返回 None 表示未找到。
    """
    cache_key = f"city_resolve_{location_hint}"
    cached = cache_manager.get(CacheType.WEATHER, cache_key)
    if cached:
        return cached

    try:
        session = _get_session()
        url = f"https://{api_host}/geo/v2/city/lookup"
        params = {"key": api_key, "location": location_hint, "lang": "zh"}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            await _check_response(resp, f"城市定位({location_hint})")
            data = await resp.json()
    except Exception as e:
        logger.bind(tag=TAG).warning(f"城市定位失败 ({location_hint}): {e}")
        return None

    locations = data.get("location", [])
    if not locations:
        logger.bind(tag=TAG).info(f"未找到城市: {location_hint}")
        return None

    city_id = locations[0]["id"]
    cache_manager.set(CacheType.WEATHER, cache_key, city_id, ttl=_CITY_SEARCH_TTL)
    return city_id


async def search_cities(
    keyword: str, api_key: str, api_host: str
) -> List[Dict[str, str]]:
    """搜索匹配的城市列表"""
    cache_key = f"city_search_{keyword}"
    cached = cache_manager.get(CacheType.WEATHER, cache_key)
    if cached:
        return cached

    try:
        session = _get_session()
        url = f"https://{api_host}/geo/v2/city/lookup"
        params = {"key": api_key, "location": keyword, "lang": "zh"}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            await _check_response(resp, f"城市搜索({keyword})")
            data = await resp.json()
    except Exception as e:
        logger.bind(tag=TAG).warning(f"城市搜索失败 ({keyword}): {e}")
        return []

    locations = data.get("location", [])
    cities = [{"name": c["name"], "id": c["id"]} for c in locations[:10]]
    cache_manager.set(CacheType.WEATHER, cache_key, cities, ttl=_CITY_SEARCH_TTL)
    return cities


# ── 实时天气 ──────────────────────────────────────────────────
async def fetch_current_weather(
    location: str, api_key: str, api_host: str
) -> Dict[str, Any]:
    """获取实时天气数据（结构化 dict）

    location 可以是城市名或 city_id。
    """
    cache_key = f"structured_weather_{location}"
    cached = cache_manager.get(CacheType.WEATHER, cache_key)
    if cached:
        return cached

    # 先尝试解析为 city_id
    city_id = location
    if not location.isdigit():
        resolved = await resolve_city(location, api_key, api_host)
        if resolved:
            city_id = resolved

    try:
        session = _get_session()
        url = f"https://{api_host}/v7/weather/now"
        params = {"key": api_key, "location": city_id, "lang": "zh"}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            await _check_response(resp, "实时天气查询")
            data = await resp.json()
    except asyncio.TimeoutError:
        raise TimeoutError("天气查询超时")
    except Exception as e:
        raise RuntimeError(f"天气查询失败: {e}")

    if data.get("code", "Unknown") != "200":
        code = data.get("code", "Unknown")
        logger.bind(tag=TAG).warning(f"实时天气 API 错误: code={code}, location={location}, resp={data}")
        if code == "NotFound":
            raise ValueError(f"未找到城市: {location}")
        raise RuntimeError(f"天气 API 错误: {code}")

    result = {
        "location": {"name": data.get("now", {}).get("obsTime", "")},
        "current": data.get("now", {}),
    }
    cache_manager.set(CacheType.WEATHER, cache_key, result, ttl=_WEATHER_TTL)
    return result


# ── 7 天预报 ──────────────────────────────────────────────────
async def fetch_forecast_weather(
    location: str, api_key: str, api_host: str
) -> List[Dict[str, Any]]:
    """获取未来 7 天天气预报"""
    cache_key = f"structured_forecast_{location}"
    cached = cache_manager.get(CacheType.WEATHER, cache_key)
    if cached:
        return cached

    city_id = location
    if not location.isdigit():
        resolved = await resolve_city(location, api_key, api_host)
        if resolved:
            city_id = resolved

    try:
        session = _get_session()
        url = f"https://{api_host}/v7/weather/7d"
        params = {"key": api_key, "location": city_id, "lang": "zh"}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            await _check_response(resp, "天气预报查询")
            data = await resp.json()
    except asyncio.TimeoutError:
        raise TimeoutError("预报查询超时")
    except Exception as e:
        raise RuntimeError(f"预报查询失败: {e}")

    if data.get("code", "Unknown") != "200":
        code = data.get("code", "Unknown")
        logger.bind(tag=TAG).warning(f"预报天气 API 错误: code={code}, location={location}, resp={data}")
        if code == "NotFound":
            raise ValueError(f"未找到城市: {location}")
        raise RuntimeError(f"预报 API 错误: {code}")

    forecasts = []
    for day in data.get("daily", [])[:7]:
        forecasts.append({
            "date": day.get("date", ""),
            "weather": day.get("textDay", day.get("textNight", "")),
            "high": day.get("tempMax", ""),
            "low": day.get("tempMin", ""),
        })

    cache_manager.set(CacheType.WEATHER, cache_key, forecasts, ttl=_WEATHER_TTL)
    return forecasts


# ── 统一入口（供 handler 调用） ─────────────────────────────────
async def get_weather_data(
    city: str,
    api_key: str,
    api_host: str,
    default_location: str = "广州",
) -> Dict[str, Any]:
    """根据城市名获取完整天气数据（当前 + 预报）

    Returns:
        {
            "city": "北京",
            "temperature": 25,
            "description": "晴",
            "aqi": 32,
            "humidity": 45,
            "high": 28,
            "low": 18,
            "forecast": [...]
        }
    """
    # 自动定位
    if city in ("auto", ""):
        from core.utils.util import get_ip_info
        city = default_location

    try:
        current = await fetch_current_weather(city, api_key, api_host)
        forecast_list = await fetch_forecast_weather(city, api_key, api_host)
    except (ValueError, TimeoutError, RuntimeError) as e:
        raise

    cur = current.get("current", {})
    aqi_data = cur.get("aqi", {})

    # 构建 3 天预报（取前 3 天，带友好日期名）
    forecast_output = []
    day_names = ["今天", "明天", "后天"]
    for i, d in enumerate(forecast_list[:3]):
        forecast_output.append({
            "day": day_names[i] if i < len(day_names) else d.get("date", ""),
            "high": int(d["high"]) if d["high"] and d["high"] != "--" else 0,
            "low": int(d["low"]) if d["low"] and d["low"] != "--" else 0,
            "description": d.get("weather", ""),
        })

    return {
        "city": cur.get("reportTime", city),
        "temperature": int(cur.get("temp", 0)),
        "description": cur.get("text", ""),
        "aqi": aqi_data.get("humidity", 0) if aqi_data else 0,
        "humidity": int(cur.get("humidity", 0)),
        "high": int(cur.get("temp", 0)) if cur.get("tempMax") and cur["tempMax"] != "--" else 0,
        "low": int(cur.get("temp", 0)) if cur.get("tempMin") and cur["tempMin"] != "--" else 0,
        "forecast": forecast_output,
    }
