"""MCP 天气消息处理器

设备通过 MCP 通道发送天气查询/城市搜索请求，服务端直接返回结构化 JSON。
不经过 LLM / TTS 流程，纯数据响应。
"""

import json
import asyncio
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from config.logger import setup_logging
from .mcp_weather_service import (
    get_weather_data,
    search_cities,
    close_weather_session,
)

TAG = __name__
logger = setup_logging()


# ── 错误码映射 ──────────────────────────────────────────────────
_ERROR_MAP = {
    ValueError: (1, "未找到该城市"),
    TimeoutError: (3, "请求超时，请稍后重试"),
    RuntimeError: (4, "服务器内部错误"),
}


def _error_response(action: str, code: int, message: str) -> dict:
    return {
        "type": "weather",
        "action": action,
        "code": code,
        "error": message,
    }


# ── 发送响应到设备 ──────────────────────────────────────────────
async def send_weather_response(
    conn: "ConnectionHandler", payload: dict, session_id: str = ""
) -> None:
    """将天气结果通过 WebSocket 发回设备"""
    message = {
        "session_id": session_id or conn.session_id,
        "type": "mcp",
        "payload": payload,
    }
    logger.bind(tag=TAG).info(f"返回天气响应给设备：{json.dumps(message, ensure_ascii=False)}")
    await conn.websocket.send(json.dumps(message))


# ── 自动定位 ────────────────────────────────────────────────────
def resolve_location(conn: "ConnectionHandler") -> str:
    """按优先级解析位置：客户端 IP → 默认城市"""
    client_ip = conn.client_ip
    if client_ip:
        try:
            from core.utils.util import get_ip_info
            ip_info = get_ip_info(client_ip, logger)
            if ip_info and ip_info.get("city"):
                return ip_info["city"]
        except Exception:
            pass

    # 回退到配置中的默认城市
    weather_config = conn.config.get("plugins", {}).get("get_weather", {})
    return weather_config.get("default_location", "广州")


# ── 主入口 ──────────────────────────────────────────────────────
async def handle_weather_request(
    conn: "ConnectionHandler", payload: Dict[str, Any], session_id: str = ""
) -> None:
    """根据 payload.type == "weather" 分发处理"""
    action = payload.get("action", "")
    city = payload.get("city", "auto")
    lang = payload.get("language", "zh-CN")

    # 读取天气 API 配置
    weather_config = conn.config.get("plugins", {}).get("get_weather", {})
    api_key = weather_config.get("api_key", "a861d0d5e7bf4ee1a83d9a9e4f96d4da")
    api_host = weather_config.get("api_host", "mj7p3y7naa.re.qweatherapi.com")
    default_location = weather_config.get("default_location", "广州")

    if action == "query":
        await _dispatch_query(conn, city, api_key, api_host, default_location, session_id)
    elif action == "search":
        await _dispatch_search(conn, payload, session_id)
    else:
        await send_weather_response(
            conn, _error_response(action, 4, f"未知 action: {action}"), session_id
        )


# ── 天气查询 ────────────────────────────────────────────────────
async def _dispatch_query(
    conn: "ConnectionHandler",
    city: str,
    api_key: str,
    api_host: str,
    default_location: str,
    session_id: str,
) -> None:
    try:
        if city in ("auto", ""):
            city = resolve_location(conn)

        data = await get_weather_data(city, api_key, api_host, default_location)

        response = {
            "type": "weather",
            "action": "query",
            "code": 0,
            "data": data,
        }
        await send_weather_response(conn, response, session_id)

    except (ValueError, TimeoutError, RuntimeError) as e:
        for exc_type, (code, msg) in _ERROR_MAP.items():
            if isinstance(e, exc_type):
                logger.bind(tag=TAG).error(f"天气查询失败 (code={code}): {e}")
                await send_weather_response(
                    conn, _error_response("query", code, msg), session_id
                )
                return
        # 兜底
        await send_weather_response(
            conn, _error_response("query", 4, str(e)), session_id
        )

    except Exception as e:
        logger.bind(tag=TAG).exception(f"天气查询异常: {e}")
        await send_weather_response(
            conn, _error_response("query", 4, "服务器内部错误"), session_id
        )


# ── 城市搜索 ────────────────────────────────────────────────────
async def _dispatch_search(
    conn: "ConnectionHandler",
    payload: Dict[str, Any],
    session_id: str,
) -> None:
    keyword = payload.get("keyword", "")
    api_key = conn.config.get("plugins", {}).get("get_weather", {}).get(
        "api_key", "a861d0d5e7bf4ee1a83d9a9e4f96d4da"
    )
    api_host = conn.config.get("plugins", {}).get("get_weather", {}).get(
        "api_host", "mj7p3y7naa.re.qweatherapi.com"
    )

    try:
        cities = await search_cities(keyword, api_key, api_host)
        response = {
            "type": "weather",
            "action": "search",
            "code": 0,
            "data": {"cities": cities},
        }
        await send_weather_response(conn, response, session_id)
    except Exception as e:
        logger.bind(tag=TAG).exception(f"城市搜索异常: {e}")
        await send_weather_response(
            conn, _error_response("search", 4, str(e)), session_id
        )
