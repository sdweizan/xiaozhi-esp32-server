"""古诗词消息处理器

设备通过 MCP 通道发送诗词请求，服务端从本地 JSON 读取数据
并直接返回结构化 JSON。不经过 LLM / TTS 流程。
"""

import json
import asyncio
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from config.logger import setup_logging
from .poem_service import fetch_poem_list, fetch_poem_by_id

TAG = __name__
logger = setup_logging()


# ── 错误码映射 ──────────────────────────────────────────────────
def _error_response(action: str, code: int, message: str) -> dict:
    return {
        "type": "poem",
        "action": action,
        "code": code,
        "error": message,
    }


# ── 发送响应到设备 ──────────────────────────────────────────────
async def send_poem_response(
    conn: "ConnectionHandler", payload: dict, session_id: str = ""
) -> None:
    """将诗词结果通过 WebSocket 发回设备"""
    message = {
        "session_id": session_id or conn.session_id,
        "type": "mcp",
        "payload": payload,
    }
    logger.bind(tag=TAG).info(f"返回诗词响应给设备：{json.dumps(message, ensure_ascii=False)}")
    await conn.websocket.send(json.dumps(message))


# ── 主入口 ──────────────────────────────────────────────────────
async def handle_poem_request(
    conn: "ConnectionHandler", payload: Dict[str, Any], session_id: str = ""
) -> None:
    """根据 payload.type == "poem" 分发处理"""
    action = payload.get("action", "")

    if action == "list":
        poem_type = payload.get("poem_type") or None
        await _dispatch_list(conn, poem_type, session_id)
    elif action == "get":
        poem_id = payload.get("id")
        if poem_id is None:
            await send_poem_response(
                conn, _error_response("get", 1, "缺少 id 参数"), session_id
            )
            return
        await _dispatch_get(conn, int(poem_id), session_id)
    else:
        await send_poem_response(
            conn, _error_response(action, 4, f"未知 action: {action}"), session_id
        )


# ── 诗词列表 ────────────────────────────────────────────────────
async def _dispatch_list(
    conn: "ConnectionHandler",
    poem_type: str | None,
    session_id: str,
) -> None:
    try:
        result = await fetch_poem_list(poem_type)
        response = {
            "type": "poem",
            "action": "list",
            "code": 0,
            "data": result,
        }
        await send_poem_response(conn, response, session_id)
    except Exception as e:
        logger.bind(tag=TAG).error(f"诗词列表失败: {e}")
        await send_poem_response(
            conn, _error_response("list", 4, str(e)), session_id
        )


# ── 诗词详情 ────────────────────────────────────────────────────
async def _dispatch_get(
    conn: "ConnectionHandler",
    poem_id: int,
    session_id: str,
) -> None:
    try:
        poem = await fetch_poem_by_id(poem_id)
        if poem is None:
            await send_poem_response(
                conn, _error_response("get", 1, f"未找到 id={poem_id} 的诗词"), session_id
            )
            return
        response = {
            "type": "poem",
            "action": "get",
            "code": 0,
            "data": poem,
        }
        await send_poem_response(conn, response, session_id)
    except Exception as e:
        logger.bind(tag=TAG).error(f"诗词详情失败: {e}")
        await send_poem_response(
            conn, _error_response("get", 4, str(e)), session_id
        )
