"""Audio Play 消息处理器

设备通过此消息类型发送一个音频文件链接（.mp3 等，由 ffmpeg 识别格式），
服务端流式拉取该音频并实时转码为 Opus 帧，直接播放给设备，不经过 LLM / TTS。

消息格式：
    设备 → 服务端
        {"type": "audio_play", "url": "http://.../xxx.mp3?...", "session_id": "..."}

    服务端 → 设备（复用现有 TTS 播放协议，设备播放状态机无需改动）
        {"type": "tts", "state": "start"}
        [Opus 二进制帧流]
        {"type": "tts", "state": "stop"}
    错误时：
        {"type": "audio_play", "state": "error", "error": "...", "session_id": "..."}

实现说明：
    1. 播放逻辑放在**后台任务**中执行，handle() 立即返回。因为消息路由是串行 await 的
       （connection._route_message → handler.handle），若在此长时间阻塞，会导致设备发送的
       abort / ping 等消息在整段播放期间都无法被处理。
    2. 使用 sendAudio / send_tts_message 原语而非 sendAudioMessage，避免依赖 conn.tts。
    3. 若同一连接又发起一次 audio_play，会先取消上一个播放任务。
"""

import json
import uuid
import asyncio
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.handle.sendAudioHandle import sendAudio, send_tts_message
from core.handle.audio_play_service import (
    iter_opus_batches,
    AudioPlayError,
    DEFAULT_OPUS_BITRATE,
    DEFAULT_MAX_DURATION_SEC,
)
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


def _is_websocket_open(conn: "ConnectionHandler") -> bool:
    """判断连接的 WebSocket 是否仍然可用（无法判断时按可用处理）"""
    ws = getattr(conn, "websocket", None)
    if ws is None:
        return False
    state = getattr(ws, "state", None)
    if state is not None and hasattr(state, "name"):
        return state.name == "OPEN"
    closed = getattr(ws, "closed", None)
    if closed is not None:
        return not closed
    return True


class AudioPlayMessageHandler(TextMessageHandler):
    """Audio Play 消息处理器 — 拉取并播放 URL 音频，不经过 LLM / TTS"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.AUDIO_PLAY

    async def handle(self, conn: "ConnectionHandler", msg_json: Dict[str, Any]) -> None:
        url = str(msg_json.get("url", "") or "").strip()

        if not url:
            logger.bind(tag=TAG).warning("收到空 url 的 audio_play 消息")
            await self._send_error(conn, "url 不能为空")
            return

        if not (url.startswith("http://") or url.startswith("https://")):
            logger.bind(tag=TAG).warning(f"audio_play 不支持的链接协议: {url[:80]}")
            await self._send_error(conn, "仅支持 http/https 音频链接")
            return

        # 读取可选配置（不配置则用默认值）
        cfg = conn.config.get("audio_play") if isinstance(conn.config, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        max_duration = int(cfg.get("max_duration_sec", DEFAULT_MAX_DURATION_SEC))
        bitrate = int(cfg.get("opus_bitrate", DEFAULT_OPUS_BITRATE))

        # 若上一段播放还在进行，先取消（同一连接上的播放是串行的）
        prev = getattr(conn, "audio_play_task", None)
        if prev is not None and not prev.done():
            prev.cancel()
            try:
                await prev
            except (asyncio.CancelledError, Exception):
                pass

        # 开启新一轮播放：生成新的 sentence_id，重置打断标志
        conn.sentence_id = str(uuid.uuid4().hex)
        conn.client_abort = False

        logger.bind(tag=TAG).info(f"audio_play 请求: {url}")

        # 后台执行播放，handle() 立即返回以保证消息读循环不被阻塞
        conn.audio_play_task = asyncio.create_task(
            self._run_playback(conn, url, max_duration, bitrate)
        )

    async def _run_playback(
        self,
        conn: "ConnectionHandler",
        url: str,
        max_duration: int,
        bitrate: int,
    ) -> None:
        """后台播放任务：拉流 → 推流 → 发送结束/错误状态"""
        sentence_id = conn.sentence_id
        sent_frames = 0
        try:
            # 复用 TTS 播放协议通知设备准备播放
            await send_tts_message(conn, "start")

            gen = iter_opus_batches(
                conn, url, max_duration_sec=max_duration, bitrate=bitrate
            )
            try:
                async for batch in gen:
                    if conn.client_abort or not _is_websocket_open(conn):
                        break
                    if sentence_id != conn.sentence_id:
                        # 已被新的播放请求取代
                        break
                    await sendAudio(conn, batch)
                    sent_frames += len(batch)
            finally:
                # 确保回收 ffmpeg 子进程
                await gen.aclose()

            if conn.client_abort or not _is_websocket_open(conn):
                logger.bind(tag=TAG).info("audio_play 已中止（打断或连接关闭）")
                return
            if sentence_id != conn.sentence_id:
                logger.bind(tag=TAG).info("audio_play 已被新的播放请求取代")
                return

            if sent_frames == 0:
                raise AudioPlayError("未能解码出任何音频数据")

            # 等待音频推送完成并发送播放结束信号
            await send_tts_message(conn, "stop")
            logger.bind(tag=TAG).info(f"audio_play 播放完成，共推送 {sent_frames} 帧")

        except asyncio.CancelledError:
            logger.bind(tag=TAG).info("audio_play 任务被取消")
            raise
        except AudioPlayError as e:
            logger.bind(tag=TAG).error(f"audio_play 失败: {e}")
            await self._send_error(conn, str(e))
            await self._safe_stop(conn)
        except Exception as e:
            logger.bind(tag=TAG).error(f"audio_play 处理异常: {e}", exc_info=True)
            await self._send_error(conn, str(e))
            await self._safe_stop(conn)
        finally:
            if getattr(conn, "audio_play_task", None) is asyncio.current_task():
                conn.audio_play_task = None

    @staticmethod
    async def _send_error(conn: "ConnectionHandler", message: str) -> None:
        """向设备发送错误回执"""
        if not _is_websocket_open(conn):
            return
        try:
            await conn.websocket.send(
                json.dumps(
                    {
                        "type": "audio_play",
                        "state": "error",
                        "error": message,
                        "session_id": conn.session_id,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass

    @staticmethod
    async def _safe_stop(conn: "ConnectionHandler") -> None:
        """确保播放状态被清理（异常路径下尽力发送 stop）"""
        try:
            await send_tts_message(conn, "stop")
        except Exception:
            pass
