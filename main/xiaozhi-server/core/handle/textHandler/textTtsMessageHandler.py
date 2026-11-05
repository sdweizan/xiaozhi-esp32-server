"""Text TTS 消息处理器

设备通过此消息类型直接发送文字内容，服务端无需经过 LLM，
直接将文字通过 TTS 合成为语音流式播放给设备。
"""

import json
import uuid
import asyncio
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message
from core.providers.tts.dto.dto import SentenceType
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class TextTtsMessageHandler(TextMessageHandler):
    """Text TTS 消息处理器 — 纯文字转语音，不经过 LLM"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.TEXT_TTS

    async def handle(self, conn: "ConnectionHandler", msg_json: Dict[str, Any]) -> None:
        text = msg_json.get("text", "").strip()
        if not text:
            logger.bind(tag=TAG).warning("收到空 text_tts 消息")
            await conn.websocket.send(json.dumps({
                "type": "text_tts",
                "state": "error",
                "error": "text 不能为空",
                "session_id": conn.session_id,
            }))
            return

        # 确保 TTS 已初始化
        if not conn.tts:
            logger.bind(tag=TAG).error("TTS 尚未初始化")
            await conn.websocket.send(json.dumps({
                "type": "text_tts",
                "state": "error",
                "error": "TTS 服务未就绪",
                "session_id": conn.session_id,
            }))
            return

        logger.bind(tag=TAG).info(f"text_tts 请求: {text}")

        # 生成新的 sentence_id
        sentence_id = str(uuid.uuid4().hex)
        conn.sentence_id = sentence_id
        conn.client_abort = False

        # 发送 TTS 开始信号
        await send_tts_message(conn, "start")

        try:
            # 同步调用 TTS 生成音频（避免阻塞事件循环）
            audio_datas = await asyncio.to_thread(conn.tts.to_tts, text)

            if not audio_datas:
                logger.bind(tag=TAG).error("TTS 返回空音频")
                await conn.websocket.send(json.dumps({
                    "type": "text_tts",
                    "state": "error",
                    "error": "TTS 合成失败",
                    "session_id": conn.session_id,
                }))
                return

            # 发送音频数据
            await sendAudioMessage(conn, SentenceType.FIRST, audio_datas, text, sentence_id)
            await sendAudioMessage(conn, SentenceType.LAST, [], None, sentence_id)

            logger.bind(tag=TAG).info(f"text_tts 播放完成: {text}")

        except Exception as e:
            logger.bind(tag=TAG).error(f"text_tts 处理异常: {e}", exc_info=True)
            await conn.websocket.send(json.dumps({
                "type": "text_tts",
                "state": "error",
                "error": str(e),
                "session_id": conn.session_id,
            }))
            # 确保清理播放状态
            try:
                await send_tts_message(conn, "stop", None)
            except Exception:
                pass
