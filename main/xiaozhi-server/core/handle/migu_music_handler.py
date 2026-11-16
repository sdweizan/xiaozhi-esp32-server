"""咪咕音乐鉴权编排 + 下行消息发送。

职责边界：
    服务端只做「鉴权判定 + 关键词提取 + 下发」，不负责音乐搜索与播放。
    keyword / singer 由服务端 ASR + LLM 从用户语音中识别得到（即 play_music 工具入参），
    设备端不参与识别，只提供 SN。
    播放由客户端/固件的咪咕 SDK 完成（Mp3Player(sn, phone).play(MusicInfo)）。

流程：
    play_music / music_play 请求
      → 取 SN（请求携带 > conn.sn）
      → 调用咪咕 queryBySn 判断授权（按 SN 缓存）
      → 已授权：下发 {"type":"music_play","state":"authorized",...,"phone":"<密文>"}
      → 未授权：下发 state=unauthorized 并（可选）播报提示
      → 异常：按配置回退本地播放（返回 False）或下发 state=error

下行消息形态（服务端 → 客户端）：
    {"type":"music_play","state":"authorized","session_id":"...",
     "authStatus":1,"sn":"...","keyword":"稻香","singer":"周杰伦","song":"稻香","phone":"<密文>"}
"""

import json
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from config.logger import setup_logging
from core.utils.cache.manager import cache_manager, CacheType
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
from core.utils.dialogue import Message
from core.providers.migu.migu_auth_client import (
    query_by_sn,
    MiguAuthError,
    MiguAuthResult,
    ERR_PARAM,
    ERR_TIMEOUT,
    ERR_INTERNAL,
    DEFAULT_BASE_URL,
    DEFAULT_PATH,
)

TAG = __name__
logger = setup_logging()

MSG_TYPE = "music_play"
DEFAULT_PRODUCT_CODE = "TEST"
DEFAULT_TIMEOUT = 8.0
DEFAULT_CACHE_TTL = 300
DEFAULT_UNAUTHORIZED_TEXT = "该设备尚未授权咪咕音乐，请先在手机App中绑定手机号后再试。"


# ── 配置读取 ────────────────────────────────────────────────────
def get_migu_config(conn: "ConnectionHandler") -> Dict[str, Any]:
    """读取 plugins.migu_music 配置（不存在时返回空字典）"""
    if not isinstance(getattr(conn, "config", None), dict):
        return {}
    cfg = conn.config.get("plugins", {}).get("migu_music")
    return cfg if isinstance(cfg, dict) else {}


def should_use_migu(conn: "ConnectionHandler") -> bool:
    """判断本次连接是否走咪咕分支。

    条件：总开关开启 且 有 SN 且（设备声明 features.migu 或 require_client_feature=false）
    """
    cfg = get_migu_config(conn)
    if not cfg.get("enable", False):
        return False
    if not getattr(conn, "sn", None):
        return False
    if cfg.get("require_client_feature", True) and not getattr(
        conn, "migu_enabled", False
    ):
        return False
    return True


# ── 工具函数 ────────────────────────────────────────────────────
def _is_websocket_open(conn: "ConnectionHandler") -> bool:
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


async def _send(conn: "ConnectionHandler", payload: Dict[str, Any], session_id: str) -> None:
    """下发 music_play 消息（服务端 → 客户端）"""
    if not _is_websocket_open(conn):
        return
    message = {"type": MSG_TYPE, "session_id": session_id or conn.session_id}
    message.update(payload)
    try:
        await conn.websocket.send(json.dumps(message, ensure_ascii=False))
        logger.bind(tag=TAG).info(
            f"下发 music_play: {json.dumps(message, ensure_ascii=False)}"
        )
    except Exception as e:
        logger.bind(tag=TAG).error(f"下发 music_play 失败: {e}")


def speak_text(conn: "ConnectionHandler", text: str) -> None:
    """通过 TTS 播报一句提示（沿用现有 function_call 结果播报模式）"""
    if not text or not getattr(conn, "tts", None):
        return
    try:
        conn.tts.store_tts_text(conn.sentence_id, text)
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.FIRST,
                content_type=ContentType.ACTION,
            )
        )
        conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=text)
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
            )
        )
        conn.dialogue.put(Message(role="assistant", content=text))
    except Exception as e:
        logger.bind(tag=TAG).error(f"播报提示失败: {e}")


async def end_tts_session(conn: "ConnectionHandler") -> None:
    """收尾本轮 TTS 会话状态。

    send_stt_message() 在回显文本后已经发出 `tts state=start`（设备据此进入
    "服务端说话中"）。咪咕已授权分支默认不产生任何 TTS 音频，若不显式发 stop，
    设备会一直停在说话状态、无法开始下一轮交互。
    """
    try:
        from core.handle.sendAudioHandle import send_tts_message

        await send_tts_message(conn, "stop")
    except Exception as e:
        logger.bind(tag=TAG).error(f"结束 TTS 会话状态失败: {e}")


# ── 鉴权 + 缓存 ─────────────────────────────────────────────────
async def _query_auth(conn: "ConnectionHandler", sn: str, cfg: Dict[str, Any]) -> MiguAuthResult:
    """带缓存的鉴权查询（按 SN 缓存）"""
    cache_ttl = int(cfg.get("cache_ttl", DEFAULT_CACHE_TTL))
    if cache_ttl > 0:
        cached = cache_manager.get(CacheType.MIGU_AUTH, sn)
        if isinstance(cached, MiguAuthResult):
            logger.bind(tag=TAG).debug(f"命中咪咕鉴权缓存 sn={sn}")
            return cached

    result = await query_by_sn(
        sn,
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        product_code=cfg.get("product_code", DEFAULT_PRODUCT_CODE),
        base_url=cfg.get("base_url", DEFAULT_BASE_URL),
        path=cfg.get("path", DEFAULT_PATH),
        timeout=float(cfg.get("timeout", DEFAULT_TIMEOUT)),
    )

    if cache_ttl > 0:
        cache_manager.set(CacheType.MIGU_AUTH, sn, result, ttl=cache_ttl)
    return result


# ── 主入口 ──────────────────────────────────────────────────────
async def handle_migu_music(
    conn: "ConnectionHandler",
    keyword: str = "",
    singer: Optional[str] = None,
    sn: Optional[str] = None,
    session_id: str = "",
) -> bool:
    """咪咕音乐鉴权主入口。

    Returns:
        True  —— 已处理完毕（无需再走本地播放）
        False —— 未处理（建议调用方回退本地播放，仅当 fallback_to_local=true 的异常场景）
    """
    cfg = get_migu_config(conn)
    session_id = session_id or conn.session_id
    sn = (sn or getattr(conn, "sn", None) or "").strip()
    keyword = (keyword or "").strip()
    singer = (singer or "").strip() or None

    if not sn:
        await _send(
            conn,
            {"state": "error", "code": ERR_PARAM, "error": "缺少设备 SN"},
            session_id,
        )
        return True

    if not keyword:
        await _send(
            conn,
            {"state": "error", "code": ERR_PARAM, "error": "缺少歌曲关键词"},
            session_id,
        )
        return True

    try:
        result = await _query_auth(conn, sn, cfg)
    except MiguAuthError as e:
        logger.bind(tag=TAG).error(f"咪咕鉴权失败 sn={sn}: {e} (code={e.code})")
        return await _on_error(conn, cfg, session_id, keyword, str(e), e.code)
    except Exception as e:
        logger.bind(tag=TAG).exception(f"咪咕鉴权异常 sn={sn}: {e}")
        return await _on_error(
            conn, cfg, session_id, keyword, "音乐服务暂不可用", ERR_INTERNAL
        )

    if result.authorized:
        payload = {
            "state": "authorized",
            "authStatus": 1,
            "sn": sn,
            "keyword": keyword,
            "singer": singer or "",
            "song": keyword,
            "phone": result.phone or "",
        }
        await _send(conn, payload, session_id)

        speak = str(cfg.get("speak_text_on_authorized", "") or "")
        if speak:
            speak_text(conn, speak.format(keyword=keyword))
        else:
            # 不播报提示语时，必须显式收尾 TTS 会话（见 end_tts_session 说明），
            # 否则设备端会卡在"服务端说话中"。
            await end_tts_session(conn)
        return True

    # 未授权
    await _send(
        conn,
        {"state": "unauthorized", "authStatus": 0, "sn": sn, "keyword": keyword},
        session_id,
    )
    text = str(
        cfg.get("speak_text_on_unauthorized", DEFAULT_UNAUTHORIZED_TEXT)
        or DEFAULT_UNAUTHORIZED_TEXT
    )
    speak_text(conn, text)
    return True


async def _on_error(
    conn: "ConnectionHandler",
    cfg: Dict[str, Any],
    session_id: str,
    keyword: str,
    message: str,
    code: int,
) -> bool:
    """鉴权异常处理：可回退本地播放，否则下发错误并提示"""
    if cfg.get("fallback_to_local", True):
        logger.bind(tag=TAG).info("咪咕鉴权异常，回退本地播放")
        return False

    await _send(
        conn,
        {"state": "error", "code": code, "error": message, "keyword": keyword},
        session_id,
    )
    text = str(cfg.get("speak_text_on_error", "音乐服务暂时不可用，请稍后再试。"))
    speak_text(conn, text)
    return True
