"""text_tts 设备接入测试脚本

用法:
    # 基本用法 - 发送纯文字让设备播放
    python test_text_tts.py --text "你好，这是一段测试语音"

    # 连接到指定服务器
    python test_text_tts.py --ws-url ws://192.168.1.100:8000/xiaozhi/v1/ --text "晚上好"

    # 自动发送多条消息
    python test_text_tts.py --auto --text "第一条" --text "第二条 语音合成测试"
"""

import asyncio
import json
import sys
import argparse
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


async def hello_phase(ws):
    """发送 hello 握手消息"""
    hello_msg = {
        "type": "hello",
        "version": 1,
        "transport": "websocket",
        "audio_params": {
            "format": "opus",
            "sample_rate": 24000,
            "channels": 1,
            "frame_duration": 60,
        },
        # 声明支持 text_tts 功能
        "features": {
            "text_tts": True,
        },
    }
    await ws.send(json.dumps(hello_msg))
    print(f"[发送] hello: {json.dumps(hello_msg)}")

    # 等待服务端响应
    resp = await asyncio.wait_for(ws.recv(), timeout=5)
    resp_json = json.loads(resp)
    print(f"[接收] 服务端响应: {json.dumps(resp_json, ensure_ascii=False)[:200]}")
    return resp_json.get("session_id", "")


async def send_text_tts(ws, text: str):
    """发送 text_tts 消息（纯文字→TTS播放，不经过LLM）"""
    msg = {
        "type": "text_tts",
        "text": text,
    }
    await ws.send(json.dumps(msg))
    print(f"[发送] text_tts: {json.dumps(msg, ensure_ascii=False)}")


async def wait_for_response(ws, timeout: float = 30.0):
    """等待并打印服务端响应消息"""
    end_time = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_time:
        try:
            remaining = end_time - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            data = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
            try:
                resp = json.loads(data)
                msg_type = resp.get("type", "")
                state = resp.get("state", "")
                error = resp.get("error", "")

                if msg_type == "text_tts":
                    if state == "error":
                        print(f"  ✗ TTS错误: {error}")
                    else:
                        print(f"  ✓ TTS状态: {state}")
                elif msg_type == "tts":
                    print(f"  [TTS事件] {state} - {resp.get('text', '')}")
                elif msg_type == "stt":
                    print(f"  [STT] {resp.get('text', '')}")
                elif msg_type == "listening":
                    print(f"  [监听状态] {state}")
                else:
                    print(f"  [{msg_type}] {json.dumps(resp, ensure_ascii=False)[:150]}")
            except json.JSONDecodeError:
                # 二进制音频数据，跳过打印
                pass
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print(f"  接收消息异常: {e}")
            break


async def main():
    parser = argparse.ArgumentParser(description="text_tts 设备接入测试")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8000/xiaozhi/v1/",
                        help="WebSocket 地址 (默认: ws://127.0.0.1:8000/xiaozhi/v1/)")
    parser.add_argument("--text", action="append", help="要发送的文字（可多次使用）")
    parser.add_argument("--auto", action="store_true",
                        help="自动模式：发送后等待播放完成再发送下一条")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="每条消息等待超时秒数（默认: 30）")
    args = parser.parse_args()

    import websockets
    uri = args.ws_url

    print(f"\n🔌 连接到: {uri}")
    print("=" * 50)

    async with websockets.connect(uri, additional_headers={"device-id": "test-device-001"}) as ws:
        print("\n📋 步骤 1: 握手 (hello)")
        session_id = await hello_phase(ws)
        print(f"   Session ID: {session_id}")

        texts = args.text or ["你好，这是一段测试语音"]
        print(f"\n📝 步骤 2: 发送 text_tts 消息 ({len(texts)} 条)")

        for i, text in enumerate(texts, 1):
            print(f"\n  --- 第 {i}/{len(texts)} 条 ---")
            await send_text_tts(ws, text)

            if args.auto:
                # 等待该条消息的 TTS 播放完成
                print(f"   等待 TTS 播放完成...")
                await wait_for_response(ws, timeout=args.timeout)
            else:
                # 非 auto 模式，短暂等待
                await asyncio.sleep(0.5)

        if not args.auto:
            print(f"\n⏳ 等待服务端响应 ({args.timeout}s)...")
            await wait_for_response(ws, timeout=args.timeout)

    print("\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
