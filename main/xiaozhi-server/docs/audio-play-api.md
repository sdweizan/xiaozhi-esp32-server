# 音频播放接口对接手册 (audio_play)

> 服务端实现与协议总览。**设备固件对接请看** [`audio-play-device-integration.md`](./audio-play-device-integration.md)（含连接握手、状态机、C/ESP32 参考实现）。

## 概述

设备通过 WebSocket 发送 `type: "audio_play"` 消息，携带一个音频文件链接（`.mp3` 等，
格式由服务端 ffmpeg 自动识别）。服务端**流式拉取**该音频——边下载边转码为 Opus 帧——
并直接推送播放给设备，**不经过 LLM / TTS**。

- 触发方式：设备主动发送 JSON 消息
- 音频来源：任意可访问的 http/https 直链
- 输出格式：Opus，采样率与设备 hello 协商一致（默认 24000Hz），单声道，60ms/帧
- 播放控制：仅播放，**不支持 play/stop 等指令**；播放中设备发送 `abort` 可打断
- 首帧延迟：低（边下边播，无需等整段下载 / 转码）

---

## 消息流程

```
设备 ──{type:audio_play, url:"http://.../xxx.mp3"}──▶ 服务端
服务端 ──{type:"tts", state:"start"}──────────────▶ 设备（准备播放）
服务端 ──[Opus 二进制帧流]──────────────────────▶ 设备（持续播放）
服务端 ──{type:"tts", state:"stop"}───────────────▶ 设备（播放结束）
```

失败时服务端发送：

```json
{ "type": "audio_play", "state": "error", "error": "原因", "session_id": "<session_id>" }
```

> 播放协议与 TTS 的 `start` / `stop` 完全一致，设备端播放状态机无需改动。

---

## 1. 设备发送播放请求

```json
{
  "type": "audio_play",
  "url": "http://cdn.content.komect.com/cnttwo/zynr/TLYP0367/RES/hjysdgf01.mp3?AWSAccessKeyId=...&Expires=...&Signature=..."
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 是 | 固定为 `"audio_play"` |
| `url`  | 是 | 音频文件直链，仅支持 `http://` / `https://` |
| `session_id` | 否 | 会话标识，缺省时回执使用服务端会话 id |

> 链接若带签名（如 `Expires` / `Signature`），过期后需由设备侧重新获取有效链接。

---

## 2. 服务端响应

| 消息 | 含义 |
|------|------|
| `{"type":"tts","state":"start"}` | 已开始处理，设备应准备播放 |
| 二进制帧 | Opus 音频帧，持续推送 |
| `{"type":"tts","state":"stop"}` | 播放结束 |
| `{"type":"audio_play","state":"error","error":"..."}` | 出错，含原因 |

### 错误示例

```json
{ "type": "audio_play", "state": "error", "error": "仅支持 http/https 音频链接", "session_id": "abc123" }
{ "type": "audio_play", "state": "error", "error": "音频拉取/解码失败(ffmpeg rc=1): ...", "session_id": "abc123" }
{ "type": "audio_play", "state": "error", "error": "url 不能为空", "session_id": "abc123" }
```

---

## 3. 可选配置

在 `data/.config.yaml` 中（不配置则使用默认值）：

```yaml
audio_play:
  opus_bitrate: 32000        # Opus 比特率(bps)，默认 32000；纯音乐可提到 48000~64000
  max_duration_sec: 1800     # 单次播放最长时长(秒)，默认 1800，超出则截断
```

---

## 服务端代码

- 处理器：`core/handle/textHandler/audioPlayMessageHandler.py`
- 流式转码：`core/handle/audio_play_service.py`
- 消息类型：`core/handle/textMessageType.py`（`AUDIO_PLAY = "audio_play"`）
- 注册表：`core/handle/textMessageHandlerRegistry.py`

实现要点：

1. 使用 `ffmpeg -i <url> -f s16le -ac 1 -ar <conn.sample_rate> pipe:1` 直接读取网络流，
   读取到的 PCM 实时经 `OpusEncoderUtils` 编码为 Opus 帧。
2. 采样率取 `conn.sample_rate`（hello 协商值，默认 24000），**不使用** `audio_to_data()`
   中硬编码的 16000，避免变速/变调。
3. 通过 `sendAudio` + `send_tts_message` 原语推流，不依赖 TTS 服务（`conn.tts`）。
4. 循环内检测 `conn.client_abort`、WebSocket 状态与 `sentence_id`，设备发 `abort` 时立即终止 ffmpeg 并停止推送。
5. 播放逻辑运行在**后台任务**中（`conn.audio_play_task`），`handle()` 立即返回。因为消息路由是串行
   `await` 的，若在 `handle()` 里跑完整段播放（可能十几分钟），设备发送的 `abort` / `ping` 等消息
   在此期间都将无法被处理。

---

## 测试脚本

```bash
# 基本用法
python test_audio_play.py --url "http://cdn.content.komect.com/.../xxx.mp3?..."
```

脚本会完成 hello 握手、发送 `audio_play`，并打印服务端回执与收到的 Opus 帧数。

---

## ESP32 端 C/C++ 伪代码

```c
// 1. 建立 WebSocket 连接后发送 hello
char hello_msg[] = "{\"type\":\"hello\",\"version\":1,"
                   "\"audio_params\":{\"format\":\"opus\",\"sample_rate\":24000,"
                   "\"channels\":1,\"frame_duration\":60}}";
ws_send(hello_msg);

// 2. 收到 hello 响应后，发送 audio_play
void play_audio_url(const char* url) {
    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "audio_play");
    cJSON_AddStringToObject(root, "url", url);
    char* msg = cJSON_PrintUnformatted(root);
    ws_send(msg);
    cJSON_free(msg);
    // 收到 tts state=stop 前持续解码播放二进制 Opus 帧
    // 需要停止时：ws_send("{\"type\":\"abort\"}");
}
```

---

## 注意事项

1. **首帧延迟**：流式方案下，设备在服务端收到首块 PCM 后即可开始播放，无需等整段下载。
2. **格式支持**：取决于服务端 ffmpeg 的解码能力，mp3/aac/m4a/wav/ogg 等常见格式均可。
3. **串行播放**：同一连接上的播放是串行的。播放中若再次收到 `audio_play`，服务端会**取消上一段播放**
   并开始新的播放；发送 `abort` 同样可中断当前播放（服务端会终止 ffmpeg 拉流）。
4. **依赖**：服务端必须安装 ffmpeg（启动时 `check_ffmpeg_installed()` 已校验）。
5. **安全**：目前不做域名白名单，但仍限制仅 http/https 协议；如后续需要可扩展白名单与大小限制。
6. **打断**：设备发送 `{"type":"abort"}` 即可中断当前播放，服务端会终止 ffmpeg 拉流。
