"""故事消息处理器

设备通过 MCP 通道发送故事请求，服务端从本地 JSON 读取数据
并直接返回结构化 JSON。不经过 LLM / TTS 流程。
"""

import json
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from config.logger import setup_logging
from .story_service import fetch_story_list, fetch_story_content

TAG = __name__
logger = setup_logging()


# ── 错误响应 ────────────────────────────────────────────────────
def _error_response(action: str, code: int, message: str) -> dict:
    return {
        "type": "story",
        "action": action,
        "code": code,
        "error": message,
    }


# ── 发送响应到设备 ──────────────────────────────────────────────
async def send_story_response(
    conn: "ConnectionHandler", payload: dict, session_id: str = ""
) -> None:
    """将故事结果通过 WebSocket 发回设备"""
    message = {
        "session_id": session_id or conn.session_id,
        "type": "mcp",
        "payload": payload,
    }
    logger.bind(tag=TAG).info(f"返回故事响应给设备：{json.dumps(message, ensure_ascii=False)}")
    await conn.websocket.send(json.dumps(message))


# ── 主入口 ──────────────────────────────────────────────────────
async def handle_story_request(
    conn: "ConnectionHandler", payload: Dict[str, Any], session_id: str = ""
) -> None:
    """根据 payload.type == "story" 分发处理"""
    action = payload.get("action", "")

    if action == "list":
        page = payload.get("page", 1)
        await _dispatch_list(conn, int(page), session_id)
    elif action == "get":
        story_id = payload.get("id")
        if story_id is None:
            await send_story_response(
                conn, _error_response("get", 1, "缺少 id 参数"), session_id
            )
            return
        await _dispatch_get(conn, int(story_id), session_id)
    else:
        await send_story_response(
            conn, _error_response(action, 4, f"未知 action: {action}"), session_id
        )


# ── 故事列表（分页） ────────────────────────────────────────────
async def _dispatch_list(
    conn: "ConnectionHandler",
    page: int,
    session_id: str,
) -> None:
    try:
        result = await fetch_story_list(page)
        response = {
            "type": "story",
            "action": "list",
            "code": 0,
            "data": result,
        }
        await send_story_response(conn, response, session_id)
    except Exception as e:
        logger.bind(tag=TAG).error(f"故事列表失败: {e}")
        await send_story_response(
            conn, _error_response("list", 4, str(e)), session_id
        )


# ── 故事详情 ────────────────────────────────────────────────────
async def _dispatch_get(
    conn: "ConnectionHandler",
    story_id: int,
    session_id: str,
) -> None:
    try:
        story = await fetch_story_content(story_id)
        if story is None:
            await send_story_response(
                conn, _error_response("get", 1, f"未找到 id={story_id} 的故事"), session_id
            )
            return
        response = {
            "type": "story",
            "action": "get",
            "code": 0,
            "data": story,
        }
        await send_story_response(conn, response, session_id)
    except Exception as e:
        logger.bind(tag=TAG).error(f"故事详情失败: {e}")
        await send_story_response(
            conn, _error_response("get", 4, str(e)), session_id
        )
