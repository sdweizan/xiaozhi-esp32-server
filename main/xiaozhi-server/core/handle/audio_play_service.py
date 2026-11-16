"""音频播放服务 — 从 URL 流式拉取音频并实时转码为 Opus 帧

设备通过 audio_play 消息发送音频文件 URL（mp3/m4a/wav 等，格式由 ffmpeg 自动识别），
服务端使用 ffmpeg 直接读取该网络音频流（边下边播），实时重采样为设备协商的采样率
并编码为 Opus 帧，交由上层经 WebSocket 流控推送给设备播放。

为什么是流式：
    10 分钟级的音频若「整段下载 → 整段转码 → 再播放」，首帧要等下载 + 转码全时长
    （十几秒甚至更久）。流式方案把首帧延迟降到「首块 PCM 到达」，内存占用也恒定。

依赖：
    ffmpeg（启动时已由 check_ffmpeg_installed 校验）、opuslib_next。
"""

import asyncio
import shutil
from typing import TYPE_CHECKING, AsyncIterator, List

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from config.logger import setup_logging
from core.utils.opus_encoder_utils import OpusEncoderUtils

TAG = __name__
logger = setup_logging()

# Opus 帧长（ms），与设备 hello 协商的 frame_duration 一致
AUDIO_FRAME_DURATION = 60
# 每次从 ffmpeg 读取的 PCM 字节数
READ_CHUNK_SIZE = 8192
# 每批推送给设备的 Opus 帧数
SEND_BATCH_SIZE = 5
# 默认 Opus 比特率（bps）。语音提示足够；纯音乐可提高到 48000~64000
DEFAULT_OPUS_BITRATE = 32000
# 单次播放最长时长（秒），防止异常超长流
DEFAULT_MAX_DURATION_SEC = 1800
# 首块 PCM 到达的超时（秒）
FIRST_FRAME_TIMEOUT = 20.0


class AudioPlayError(Exception):
    """音频播放过程中的可预期错误（URL 无效、下载失败、无音频数据等）"""


def _ffmpeg_exe() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _build_ffmpeg_cmd(url: str, sample_rate: int) -> List[str]:
    """构造 ffmpeg 命令：读取 url，输出 16bit 单声道 PCM 到 stdout"""
    return [
        _ffmpeg_exe(),
        "-nostdin",           # 不再从标准输入读取，避免阻塞
        "-loglevel", "error",  # 只输出错误，减少 stderr 噪音
        "-i", url,            # 直接以 URL 作为输入
        "-vn",                # 丢弃视频流（若容器内混有）
        "-f", "s16le",        # 输出裸 PCM，16bit 小端
        "-acodec", "pcm_s16le",
        "-ac", "1",           # 单声道
        "-ar", str(sample_rate),
        "pipe:1",             # 输出到 stdout
    ]


async def iter_opus_batches(
    conn: "ConnectionHandler",
    url: str,
    *,
    max_duration_sec: int = DEFAULT_MAX_DURATION_SEC,
    bitrate: int = DEFAULT_OPUS_BITRATE,
    first_frame_timeout: float = FIRST_FRAME_TIMEOUT,
) -> AsyncIterator[List[bytes]]:
    """边下边播：ffmpeg 读取 url → 实时编码 Opus → 按批 yield。

    Yields:
        List[bytes]：一批 Opus 帧（长度 <= SEND_BATCH_SIZE）。

    Raises:
        AudioPlayError：URL 下载/解码失败，或未产出任何音频数据。
    """
    sample_rate = int(getattr(conn, "sample_rate", 24000) or 24000)

    cmd = _build_ffmpeg_cmd(url, sample_rate)
    logger.bind(tag=TAG).info(f"audio_play 开始流式拉取: {url} (sr={sample_rate})")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # 异步抽干 stderr，避免 ffmpeg 因管道写满而阻塞
    stderr_chunks: List[bytes] = []

    async def _drain_stderr():
        try:
            stderr_chunks.append(await proc.stderr.read())
        except Exception:
            pass

    drain_task = asyncio.create_task(_drain_stderr())

    encoder = OpusEncoderUtils(
        sample_rate=sample_rate, channels=1, frame_size_ms=AUDIO_FRAME_DURATION
    )
    try:
        # 提高比特率（Encoder 构造时固定为 24kbps，这里按需覆盖）
        encoder.encoder.bitrate = int(bitrate)
    except Exception:
        logger.bind(tag=TAG).debug("设置自定义 Opus 比特率失败，沿用默认值")

    batch: List[bytes] = []
    total_samples = 0
    max_samples = int(max_duration_sec) * sample_rate
    aborted = False
    got_first_frame = False
    eof_reached = False
    truncated = False

    def _emit(opus_frame):
        if opus_frame:
            batch.append(opus_frame)

    try:
        while True:
            if getattr(conn, "client_abort", False):
                aborted = True
                logger.bind(tag=TAG).info("audio_play 被设备打断，停止拉流")
                break

            if not got_first_frame:
                try:
                    data = await asyncio.wait_for(
                        proc.stdout.read(READ_CHUNK_SIZE), timeout=first_frame_timeout
                    )
                except asyncio.TimeoutError:
                    raise AudioPlayError("音频加载超时，请检查链接是否可访问")
            else:
                data = await proc.stdout.read(READ_CHUNK_SIZE)

            if not data:
                eof_reached = True
                break

            got_first_frame = True
            total_samples += len(data) // 2
            encoder.encode_pcm_to_opus_stream(
                data, end_of_stream=False, callback=_emit
            )

            while len(batch) >= SEND_BATCH_SIZE:
                yield batch[:SEND_BATCH_SIZE]
                del batch[:SEND_BATCH_SIZE]

            if total_samples >= max_samples:
                truncated = True
                logger.bind(tag=TAG).warning(
                    f"audio_play 超过最大时长 {max_duration_sec}s，提前截断"
                )
                break

        if not aborted:
            # 冲刷编码器缓冲区（最后不足一帧的部分补零）
            encoder.encode_pcm_to_opus_stream(b"", end_of_stream=True, callback=_emit)
            if batch:
                yield batch
                batch = []
    finally:
        # 结束 ffmpeg 子进程：正常读完则优雅退出，其余情况（打断/截断/异常）直接杀掉，
        # 否则 ffmpeg 会因 stdout 管道写满而阻塞，导致等待超时。
        try:
            if proc.returncode is None:
                if eof_reached and not aborted:
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                else:
                    proc.kill()
                    await proc.wait()
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.bind(tag=TAG).debug(f"回收 ffmpeg 进程异常: {e}")

        try:
            await drain_task
        except Exception:
            pass

        encoder.close()

    if aborted or getattr(conn, "client_abort", False):
        return

    # 被截断时 ffmpeg 是被主动 kill 的，returncode 非 0 属正常，不报错
    if proc.returncode not in (0, None) and not truncated:
        detail = b"".join(c for c in stderr_chunks if c).decode("utf-8", "ignore").strip()
        raise AudioPlayError(f"音频拉取/解码失败(ffmpeg rc={proc.returncode}): {detail[:300]}")

    if total_samples == 0:
        raise AudioPlayError("未从该链接解码出任何音频数据")

    logger.bind(tag=TAG).info(
        f"audio_play 流式拉取结束，时长约 {total_samples / sample_rate:.1f}s"
    )
