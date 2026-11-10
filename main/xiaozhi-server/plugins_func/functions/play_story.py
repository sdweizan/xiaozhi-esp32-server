import os
import re
import time
import random
import difflib
import traceback
from pathlib import Path
from core.handle.sendAudioHandle import send_stt_message
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

STORY_CACHE = {}

play_story_function_desc = {
    "type": "function",
    "function": {
        "name": "play_story",
        "description": (
            "当用户要求你讲故事、播放故事时调用"
            "当用户表达出想听故事时调用"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "story_name": {
                    "type": "string",
                    "description": "故事名称，如果用户没有指定具体故事名则为'random', 明确指定的时返回故事的名字 示例: ```用户:播放两只老虎\n参数：两只老虎``` ```用户:播放故事 \n参数：random ```",
                }
            },
            "required": ["story_name"],
        },
    },
}


@register_function("play_story", play_story_function_desc, ToolType.SYSTEM_CTL)
def play_story(conn: "ConnectionHandler", story_name: str):
    try:
        story_intent = (
            f"播放故事 {story_name}" if story_name != "random" else "随机播放故事"
        )

        # 检查事件循环状态
        if not conn.loop.is_running():
            conn.logger.bind(tag=TAG).error("事件循环未运行，无法提交任务")
            return ActionResponse(
                action=Action.RESPONSE, result="系统繁忙", response="请稍后再试"
            )

        # 提交异步任务
        task = conn.loop.create_task(
            handle_story_command(conn, story_intent)  # 封装异步逻辑
        )

        # 非阻塞回调处理
        def handle_done(f):
            try:
                f.result()  # 可在此处理成功逻辑
                conn.logger.bind(tag=TAG).info("播放完成")
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"播放失败: {e}")

        task.add_done_callback(handle_done)

        return ActionResponse(
            action=Action.NONE, result="指令已接收", response="正在为您播放故事"
        )
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"处理故事意图错误: {e}")
        return ActionResponse(
            action=Action.RESPONSE, result=str(e), response="播放故事时出错了"
        )


def _extract_story_name(text):
    """从用户输入中提取故事名"""
    for keyword in ["播放故事"]:
        if keyword in text:
            parts = text.split(keyword)
            if len(parts) > 1:
                return parts[1].strip()
    return None


def _find_best_match(potential_story, story_files):
    """查找最匹配的故事"""
    best_match = None
    highest_ratio = 0

    for story_file in story_files:
        story_name = os.path.splitext(story_file)[0]
        ratio = difflib.SequenceMatcher(None, potential_story, story_name).ratio()
        if ratio > highest_ratio and ratio > 0.4:
            highest_ratio = ratio
            best_match = story_file
    return best_match


def get_story_files(story_dir, story_ext):
    story_dir = Path(story_dir)
    story_files = []
    story_file_names = []
    for file in story_dir.rglob("*"):
        # 判断是否是文件
        if file.is_file():
            # 获取文件扩展名
            ext = file.suffix.lower()
            # 判断扩展名是否在列表中
            if ext in story_ext:
                # 添加相对路径
                story_files.append(str(file.relative_to(story_dir)))
                story_file_names.append(
                    os.path.splitext(str(file.relative_to(story_dir)))[0]
                )
    return story_files, story_file_names


def initialize_story_handler(conn: "ConnectionHandler"):
    global STORY_CACHE
    if STORY_CACHE == {}:
        plugins_config = conn.config.get("plugins", {})
        if "play_story" in plugins_config:
            STORY_CACHE["story_config"] = plugins_config["play_story"]
            STORY_CACHE["story_dir"] = os.path.abspath(
                STORY_CACHE["story_config"].get("story_dir", "./story")  # 默认路径修改
            )
            STORY_CACHE["story_ext"] = STORY_CACHE["story_config"].get(
                "story_ext", (".mp3", ".wav", ".p3")
            )
            STORY_CACHE["refresh_time"] = STORY_CACHE["story_config"].get(
                "refresh_time", 60
            )
        else:
            STORY_CACHE["story_dir"] = os.path.abspath("./story")
            STORY_CACHE["story_ext"] = (".mp3", ".wav", ".p3")
            STORY_CACHE["refresh_time"] = 60
        # 获取故事文件列表
        STORY_CACHE["story_files"], STORY_CACHE["story_file_names"] = get_story_files(
            STORY_CACHE["story_dir"], STORY_CACHE["story_ext"]
        )
        STORY_CACHE["scan_time"] = time.time()
    return STORY_CACHE


async def handle_story_command(conn: "ConnectionHandler", text):
    initialize_story_handler(conn)
    global STORY_CACHE

    """处理故事播放指令"""
    clean_text = re.sub(r"[^\w\s]", "", text).strip()
    conn.logger.bind(tag=TAG).debug(f"检查是否是故事命令: {clean_text}")

    # 尝试匹配具体故事名
    if os.path.exists(STORY_CACHE["story_dir"]):
        if time.time() - STORY_CACHE["scan_time"] > STORY_CACHE["refresh_time"]:
            # 刷新故事文件列表
            STORY_CACHE["story_files"], STORY_CACHE["story_file_names"] = (
                get_story_files(STORY_CACHE["story_dir"], STORY_CACHE["story_ext"])
            )
            STORY_CACHE["scan_time"] = time.time()

        potential_story = _extract_story_name(clean_text)
        if potential_story:
            best_match = _find_best_match(potential_story, STORY_CACHE["story_files"])
            if best_match:
                conn.logger.bind(tag=TAG).info(f"找到最匹配的故事: {best_match}")
                await play_local_story(conn, specific_file=best_match)
                return True
    # 检查是否是通用播放故事命令
    await play_local_story(conn)
    return True


def _get_random_play_prompt(story_name):
    """生成随机播放引导语"""
    # 移除文件扩展名
    clean_name = os.path.splitext(story_name)[0]
    prompts = [
        f"正在为您播放，《{clean_name}》",
        f"请欣赏故事，《{clean_name}》",
        f"即将为您播放，《{clean_name}》",
        f"现在为您带来，《{clean_name}》",
    ]
    # 直接使用random.choice，不设置seed
    return random.choice(prompts)


async def play_local_story(conn: "ConnectionHandler", specific_file=None):
    global STORY_CACHE
    """播放本地故事文件"""
    try:
        if not os.path.exists(STORY_CACHE["story_dir"]):
            conn.logger.bind(tag=TAG).error(
                f"故事目录不存在: " + STORY_CACHE["story_dir"]
            )
            return

        # 确保路径正确性
        if specific_file:
            selected_story = specific_file
            story_path = os.path.join(STORY_CACHE["story_dir"], specific_file)
        else:
            if not STORY_CACHE["story_files"]:
                conn.logger.bind(tag=TAG).error("未找到MP3故事文件")
                return
            selected_story = random.choice(STORY_CACHE["story_files"])
            story_path = os.path.join(STORY_CACHE["story_dir"], selected_story)

        if not os.path.exists(story_path):
            conn.logger.bind(tag=TAG).error(f"选定的故事文件不存在: {story_path}")
            return
        text = _get_random_play_prompt(selected_story)
        await send_stt_message(conn, text)
        conn.dialogue.put(Message(role="assistant", content=text))

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
                content_file=story_path,
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
        conn.logger.bind(tag=TAG).error(f"播放故事失败: {str(e)}")
        conn.logger.bind(tag=TAG).error(f"详细错误: {traceback.format_exc()}")
