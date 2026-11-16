"""text_tts 接入指南

## 概述

`text_tts` 是设备与服务器之间的纯文字转语音通道，设备发送文字，服务端
直接将文字通过 TTS 合成为 Opus 音频流播放给设备，**不经过 LLM**。

## 消息流程

```
设备 ──{type:text_tts, text:"..."}──▶ 服务端
服务端 ──{type:tts, state:"start"}──▶ 设备（播放中状态）
服务端 ──[Opus 音频流]────────────▶ 设备（播放音频）
服务端 ──{type:tts, state:"stop"}──▶ 设备（播放结束）
```

## 设备端接入方式

### 1. Hello 握手时声明支持

设备在发送 `hello` 消息时，在 `features` 中声明支持 `text_tts`：

```json
{
  "type": "hello",
  "version": 1,
  "transport": "websocket",
  "audio_params": {
    "format": "opus",
    "sample_rate": 24000,
    "channels": 1,
    "frame_duration": 60
  },
  "features": {
    "text_tts": true
  }
}
```

### 2. 发送 text_tts 消息

准备好要播报的文字后，发送如下 JSON 消息：

```json
{
  "type": "text_tts",
  "text": "这是要播报的内容"
}
```

- `type` — 固定为 `"text_tts"`
- `text` — 要播放的文字内容（必填，不能为空）

### 3. 接收服务端响应

服务端会按顺序发送以下消息：

| 消息类型 | state | 含义 |
|---------|-------|------|
| `tts` | `start` | TTS 开始合成，设备应准备播放 |
| (二进制) | — | Opus 音频帧，持续发送 |
| `tts` | `stop` | TTS 播放结束 |
| `text_tts` | `error` | 发生错误，包含 `error` 字段说明原因 |

## 服务端代码

服务端已内置 `TextTtsMessageHandler`，无需额外配置。

核心处理逻辑在：
- `core/handle/textHandler/textTtsMessageHandler.py` — 处理器
- `core/handle/textMessageType.py` — 消息类型枚举
- `core/handle/textMessageHandlerRegistry.py` — 注册表

## 测试脚本

使用提供的测试脚本验证：

```bash
# 安装依赖（如需要）
pip install websockets websocket-client

# 基本测试
python test_text_tts.py --text "你好，请播放这段文字"

# 连接远程服务器
python test_text_tts.py \
  --ws-url ws://192.168.1.100:8000/xiaozhi/v1/ \
  --text "第一条" \
  --text "第二条语音测试"

# 自动模式（逐条等待播放完成）
python test_text_tts.py --auto --text "你好" --text "测试完成"
```

## 与现有流程的区别

| 特性 | text_tts | listen/detect |
|------|----------|---------------|
| 触发方式 | 设备主动发送文字 | 设备语音输入 |
| 是否经过 LLM | ❌ 不经过 | ✅ 经过 LLM |
| 适用场景 | 固定内容播报、通知 | 智能对话、问答 |
| 延迟 | 低（仅 TTS） | 较高（ASR+LLM+TTS） |
| 上下文 | 无 | 有对话历史 |

## ESP32 端 C/C++ 伪代码

```c
// 1. 建立 WebSocket 连接后发送 hello
char hello_msg[] = "{\"type\":\"hello\",\"version\":1,"
                   "\"features\":{\"text_tts\":true}}";
ws_send(hello_msg);

// 2. 收到 hello 响应后，发送 text_tts
void speak(const char* text) {
    char msg[512];
    snprintf(msg, sizeof(msg), "{\"type\":\"text_tts\",\"text\":\"%s\"}", text);
    ws_send(msg);
    // 等待 tts state=stop 或超时
    ws_wait_for_state("tts", "stop", 30000);
}

// 3. 使用示例
speak("你好，我是小智，这是文字合成语音测试");
```

## 注意事项

1. **TTS 并发**: 同一连接串行处理，上一条播完才能发下一条
2. **打断支持**: 发送 `abort` 消息可中断当前播放
3. **网络延迟**: 文字内容建议不超过 500 字，避免超时
4. **音频格式**: 默认 Opus，采样率 24kHz，与 hello 协商一致
"""
