import os
import time
import random
import difflib
import traceback
from pathlib import Path
from core.handle.sendAudioHandle import send_stt_message
from core.handle.migu_music_handler import should_use_migu, handle_migu_music
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

MUSIC_CACHE = {}

# 曲库找不到指定歌曲时的提示语模板，可用占位符：{song} 用户点播的歌名、{played} 实际播放的歌名
DEFAULT_NOT_FOUND_PROMPT = "版权音乐无法播放，为您播放《{played}》"
# 曲库为空（或目录不存在）时的提示语
DEFAULT_EMPTY_LIBRARY_TEXT = "版权音乐无法播放，本地曲库暂时没有可播放的歌曲。"

play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "当用户要求播放音乐、歌曲时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "歌曲名称，如果用户没有指定具体歌名则为'random', 明确指定的时返回音乐的名字 示例: ```用户:播放两只老虎\n参数：两只老虎``` ```用户:播放音乐 \n参数：random ```",
                },
                "singer": {
                    "type": "string",
                    "description": "歌手名称，仅当用户明确提到歌手时返回，否则返回空字符串 示例: ```用户:播放周杰伦的稻香\n参数：周杰伦``` ```用户:播放稻香\n参数：```",
                },
            },
            "required": ["song_name"],
        },
    },
}


@register_function("play_music", play_music_function_desc, ToolType.SYSTEM_CTL)
async def play_music(conn: "ConnectionHandler", song_name: str, singer: str = None):
    try:
        await handle_music_command(conn, song_name, singer)
        return ActionResponse(
            action=Action.RECORD, result="指令已接收", response="正在为您播放音乐"
        )
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"处理音乐意图错误: {e}")
        return ActionResponse(
            action=Action.RESPONSE, result=str(e), response="播放音乐时出错了"
        )


def _find_best_match(potential_song, music_files):
    """查找最匹配的歌曲"""
    best_match = None
    highest_ratio = 0

    for music_file in music_files:
        song_name = os.path.splitext(music_file)[0]
        ratio = difflib.SequenceMatcher(None, potential_song, song_name).ratio()
        if ratio > highest_ratio and ratio > 0.4:
            highest_ratio = ratio
            best_match = music_file
    return best_match


def get_music_files(music_dir, music_ext):
    music_dir = Path(music_dir)
    music_files = []
    music_file_names = []
    for file in music_dir.rglob("*"):
        # 判断是否是文件
        if file.is_file():
            # 获取文件扩展名
            ext = file.suffix.lower()
            # 判断扩展名是否在列表中
            if ext in music_ext:
                # 添加相对路径
                music_files.append(str(file.relative_to(music_dir)))
                music_file_names.append(
                    os.path.splitext(str(file.relative_to(music_dir)))[0]
                )
    return music_files, music_file_names


def initialize_music_handler(conn: "ConnectionHandler"):
    global MUSIC_CACHE
    if MUSIC_CACHE == {}:
        plugins_config = conn.config.get("plugins", {})
        if "play_music" in plugins_config:
            MUSIC_CACHE["music_config"] = plugins_config["play_music"]
            MUSIC_CACHE["music_dir"] = os.path.abspath(
                MUSIC_CACHE["music_config"].get("music_dir", "./music")  # 默认路径修改
            )
            MUSIC_CACHE["music_ext"] = MUSIC_CACHE["music_config"].get(
                "music_ext", (".mp3", ".wav", ".p3")
            )
            MUSIC_CACHE["refresh_time"] = MUSIC_CACHE["music_config"].get(
                "refresh_time", 60
            )
        else:
            MUSIC_CACHE["music_dir"] = os.path.abspath("./music")
            MUSIC_CACHE["music_ext"] = (".mp3", ".wav", ".p3")
            MUSIC_CACHE["refresh_time"] = 60
        # 获取音乐文件列表
        MUSIC_CACHE["music_files"], MUSIC_CACHE["music_file_names"] = get_music_files(
            MUSIC_CACHE["music_dir"], MUSIC_CACHE["music_ext"]
        )
        MUSIC_CACHE["scan_time"] = time.time()
    return MUSIC_CACHE


async def handle_music_command(conn: "ConnectionHandler", song_name=None, singer=None):
    """处理音乐播放指令"""
    initialize_music_handler(conn)
    global MUSIC_CACHE

    # ── 咪咕音乐鉴权分支 ────────────────────────────────────────
    # keyword / singer 均由服务端从用户语音识别得到（LLM 调用 play_music 时的入参），
    # 设备端只负责提供 SN，不参与识别。
    # 条件：配置开启 + 客户端声明 features.migu + 已上报 SN + 识别出具体歌名。
    # 已授权 → 下发关键词+手机号（密文）给客户端；未授权 → 播报提示；
    # 鉴权异常且配置了 fallback_to_local → 返回 False，继续走本地播放。
    # 注：用户只说"播放音乐"（song_name 为 random/空）时识别不出歌名，跳过咪咕走本地随机播放。
    keyword = "" if song_name in (None, "", "random") else str(song_name).strip()
    if keyword and should_use_migu(conn):
        handled = await handle_migu_music(conn, keyword=keyword, singer=singer)
        if handled:
            return True
        conn.logger.bind(tag=TAG).info("咪咕分支未处理，回退本地播放")
    # ───────────────────────────────────────────────────────────

    conn.logger.bind(tag=TAG).debug(f"本地音乐播放: song_name={song_name}")

    # 尝试匹配具体歌名
    if os.path.exists(MUSIC_CACHE["music_dir"]):
        if time.time() - MUSIC_CACHE["scan_time"] > MUSIC_CACHE["refresh_time"]:
            # 刷新音乐文件列表
            MUSIC_CACHE["music_files"], MUSIC_CACHE["music_file_names"] = (
                get_music_files(MUSIC_CACHE["music_dir"], MUSIC_CACHE["music_ext"])
            )
            MUSIC_CACHE["scan_time"] = time.time()

        if song_name and song_name != "random":
            best_match = _find_best_match(str(song_name), MUSIC_CACHE["music_files"])
            if best_match:
                conn.logger.bind(tag=TAG).info(f"找到最匹配的歌曲: {best_match}")
                await play_local_music(conn, specific_file=best_match)
                return True
            # 曲库里没有这首歌 → 提示版权限制，再随机播一首本地歌曲
            conn.logger.bind(tag=TAG).info(
                f"曲库未找到《{song_name}》，改为随机播放本地音乐"
            )
            await play_local_music(conn, notice_song=str(song_name))
            return True
    else:
        conn.logger.bind(tag=TAG).error(f"音乐目录不存在: " + MUSIC_CACHE["music_dir"])

    # 检查是否是通用播放音乐命令（无指定歌名，或曲库不可用）
    await play_local_music(conn)
    return True


def _get_random_play_prompt(song_name):
    """生成随机播放引导语"""
    # 移除文件扩展名
    clean_name = os.path.splitext(song_name)[0]
    prompts = [
        f"正在为您播放，《{clean_name}》",
        f"请欣赏歌曲，《{clean_name}》",
        f"即将为您播放，《{clean_name}》",
        f"现在为您带来，《{clean_name}》",
        f"让我们一起聆听，《{clean_name}》",
        f"接下来请欣赏，《{clean_name}》",
        f"此刻为您献上，《{clean_name}》",
    ]
    # 直接使用random.choice，不设置seed
    return random.choice(prompts)


def _get_not_found_prompt(song_name, selected_music):
    """曲库找不到用户点播的歌曲时的提示语。

    文案可在 config.yaml 的 plugins.play_music.not_found_prompt 中覆盖，
    支持 {song}（用户点播的歌名）与 {played}（实际播放的歌名）两个占位符。
    """
    played = os.path.splitext(selected_music)[0]
    cfg = MUSIC_CACHE.get("music_config") or {}
    template = str(cfg.get("not_found_prompt") or DEFAULT_NOT_FOUND_PROMPT)
    try:
        return template.format(song=os.path.splitext(str(song_name))[0], played=played)
    except (KeyError, IndexError, ValueError):
        return f"版权音乐无法播放，为您播放《{played}》"


def _get_empty_library_text():
    """曲库为空时的提示语（可在配置中覆盖）"""
    cfg = MUSIC_CACHE.get("music_config") or {}
    return str(cfg.get("empty_library_text") or DEFAULT_EMPTY_LIBRARY_TEXT)


def _queue_announce(conn: "ConnectionHandler", text: str):
    """只播报一句提示、不播放音频文件（曲库为空等场景）"""
    conn.tts.store_tts_text(conn.sentence_id, text)
    if conn.intent_type == "intent_llm":
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.FIRST,
                content_type=ContentType.ACTION,
            )
        )
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=text,
        )
    )
    if conn.intent_type == "intent_llm":
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
            )
        )


async def play_local_music(conn: "ConnectionHandler", specific_file=None, notice_song=None):
    """播放本地音乐文件

    Args:
        specific_file: 指定要播放的文件（相对 music_dir 的路径），不传则随机
        notice_song: 用户原本点播的歌名。传入时播报「版权音乐无法播放，为您播放《xxx》」，
                     而不是常规的「正在为您播放」引导语。
    """
    global MUSIC_CACHE
    try:
        if not os.path.exists(MUSIC_CACHE["music_dir"]):
            conn.logger.bind(tag=TAG).error(
                f"音乐目录不存在: " + MUSIC_CACHE["music_dir"]
            )
            _queue_announce(conn, _get_empty_library_text())
            return

        # 确保路径正确性
        if specific_file:
            selected_music = specific_file
            music_path = os.path.join(MUSIC_CACHE["music_dir"], specific_file)
        else:
            if not MUSIC_CACHE["music_files"]:
                conn.logger.bind(tag=TAG).error("未找到MP3音乐文件")
                _queue_announce(conn, _get_empty_library_text())
                return
            selected_music = random.choice(MUSIC_CACHE["music_files"])
            music_path = os.path.join(MUSIC_CACHE["music_dir"], selected_music)

        if not os.path.exists(music_path):
            conn.logger.bind(tag=TAG).error(f"选定的音乐文件不存在: {music_path}")
            _queue_announce(conn, _get_empty_library_text())
            return
        if notice_song:
            text = _get_not_found_prompt(notice_song, selected_music)
            conn.logger.bind(tag=TAG).info(
                f"曲库无《{notice_song}》，提示后播放: {selected_music}"
            )
        else:
            text = _get_random_play_prompt(selected_music)
        conn.tts.store_tts_text(conn.sentence_id, text)
        # conn.dialogue.put(Message(role="assistant", content=text))

        if conn.intent_type == "intent_llm":
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                )
            )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=text,
            )
        )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.FILE,
                content_file=music_path,
            )
        )
        if conn.intent_type == "intent_llm":
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )

    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"播放音乐失败: {str(e)}")
        conn.logger.bind(tag=TAG).error(f"详细错误: {traceback.format_exc()}")
