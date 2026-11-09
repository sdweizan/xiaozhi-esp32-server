import asyncio
import json
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.providers.tools.device_mcp import handle_mcp_message
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class McpTextMessageHandler(TextMessageHandler):
    """MCP消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.MCP

    async def handle(self, conn: "ConnectionHandler", msg_json: Dict[str, Any]) -> None:
        payload = msg_json.get("payload")
        logger.bind(tag=TAG).info(f"收到mcp消息：{json.dumps(msg_json, ensure_ascii=False)}")
        if not isinstance(payload, dict):
            return

        # ── 天气消息拦截（不走标准 MCP 协议） ──────────────────────
        if payload.get("type") == "weather":
            session_id = msg_json.get("session_id", "")
            from core.handle.mcp_weather_handler import handle_weather_request
            await handle_weather_request(conn, payload, session_id)
            return
        # ── 故事消息拦截（不走标准 MCP 协议） ──────────────────────
        if payload.get("type") == "story":
            session_id = msg_json.get("session_id", "")
            from core.handle.story_handler import handle_story_request
            await handle_story_request(conn, payload, session_id)
            return
        # ── 诗词消息拦截（不走标准 MCP 协议） ──────────────────────
        if payload.get("type") == "poem":
            session_id = msg_json.get("session_id", "")
            from core.handle.poem_handler import handle_poem_request
            await handle_poem_request(conn, payload, session_id)
            return
        # ───────────────────────────────────────────────────────────

        if "payload" in msg_json:
            asyncio.create_task(
                handle_mcp_message(conn, conn.mcp_client, msg_json["payload"])
            )