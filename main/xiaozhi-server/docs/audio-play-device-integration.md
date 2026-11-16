# 设备端对接文档 — 音频播放 (audio_play)

> 适用对象：ESP32 等设备固件开发者。目标是在设备上实现「向服务端请求播放一个音频直链」的能力。
> 服务端实现与接口总览见 [`audio-play-api.md`](./audio-play-api.md)。

---

## 1. 能力简介

设备发送一条 JSON 消息，携带一个音频文件直链（`.mp3` 等）。服务端**流式**拉取并转码为
Opus 帧，逐帧推送给设备；设备按普通 TTS 播放的方式解码播放即可。

- 服务端**不限制播放控制**：只播放，不支持 play/pause/seek；播放中可发 `abort` 打断
- 音频格式固定为 **Opus / 单声道 / 采样率 24000Hz / 帧长 60ms**（与 hello 协商一致）
- 首帧延迟低：服务端边下边播，设备无需等待整段文件

**如果你的固件已经实现了 TTS 音频播放（接收 `tts start` → 解码二进制帧 → `tts stop`），
那么接入本功能只需再加「发送一条 `audio_play` 消息」，播放侧代码无需改动。**

---

## 2. 前置条件

### 2.1 建立 WebSocket 连接

| 项 | 值 |
|----|----|
| 地址 | `ws://<服务器IP或域名>:8000/xiaozhi/v1/`（正式环境用 `wss://`） |
| 端口 | WebSocket 默认 `8000`（见服务端 `server.port`） |
| 必填请求头 | `device-id`：设备唯一标识（**缺失则服务端直接关闭连接**） |
| 可选请求头 | `client-id`、`authorization`：仅当服务端开启认证（`server.auth.enabled: true`）时需要 |

> `device-id` / `client-id` / `authorization` 也可以作为 URL 查询参数传入，例如：
> `ws://ip:8000/xiaozhi/v1/?device-id=AA:BB:CC:DD:EE:FF&client-id=xxx&authorization=Bearer%20xxx`

### 2.2 发送 hello 握手（必须在 audio_play 之前）

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
  }
}
```

服务端应答（`session_id` 后续建议用于日志关联）：

```json
{
  "type": "hello",
  "version": 1,
  "transport": "websocket",
  "session_id": "xxxxxxxx",
  "audio_params": { "format": "opus", "sample_rate": 24000, "channels": 1, "frame_duration": 60 }
}
```

> 采样率以服务端应答为准。若你的服务端配置改了 `sample_rate`，设备需按应答值初始化解码器。

---

## 3. 播放时序

```
设备                                              服务端
 |                                                 |
 |---- hello ------------------------------------>|
 |<--- hello(响应: session_id, audio_params) ------|
 |                                                 |
 |---- audio_play {url} ------------------------->|  (服务端开始下载+转码)
 |<--- {"type":"tts","state":"start"} ------------|  (准备播放)
 |<=== Opus 二进制帧流 (持续，服务端按实时节奏推送)==|
 |<--- {"type":"tts","state":"stop"} -------------|  (播放结束)
 |                                                 |
 |  (设备本地可能还剩少量已缓冲帧，播完即回 idle)      |
```

失败时（在 start 之前或推流中断）：

```json
{ "type": "audio_play", "state": "error", "error": "音频拉取/解码失败(ffmpeg rc=1): ...", "session_id": "xxxx" }
```

---

## 4. 消息定义

### 4.1 设备 → 服务端：发起播放

```json
{
  "type": "audio_play",
  "url": "http://cdn.content.komect.com/cnttwo/zynr/TLYP0367/RES/hjysdgf01.mp3?AWSAccessKeyId=...&Expires=...&Signature=..."
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `type`  | 是 | 固定 `"audio_play"` |
| `url`   | 是 | 音频直链，**仅支持 `http://` / `https://`**；格式由服务端 ffmpeg 识别（mp3/aac/m4a/wav/ogg 等） |
| `session_id` | 否 | 会话标识，缺省时服务端回执使用其内部 session |

> 链接若带签名（`Expires` / `Signature`），过期后服务端拉取会失败并回 `state:"error"`，
> 设备需重新获取有效链接。

### 4.2 服务端 → 设备：播放状态与音频

| 报文 | 类型 | 说明 |
|------|------|------|
| `{"type":"tts","state":"start"}` | 文本 | 开始播放，设备切换到「播放中」状态 |
| Opus 帧 | **二进制** | 原始 Opus 数据包，持续推送 |
| `{"type":"tts","state":"stop"}` | 文本 | 播放结束，设备播完缓冲后回到「空闲」 |
| `{"type":"audio_play","state":"error","error":"..."}` | 文本 | 出错，设备回到「空闲」并可按需提示 |

**注意**：本功能的播放协议复用了 TTS 的 `tts` 状态消息，因此：
- 不会出现 `sentence_start`（那是 TTS 分段文本才有的）
- 设备**不需要**发送任何 ack

### 4.3 常见错误原因（`error` 字符串）

| error 内容片段 | 原因 | 设备侧建议 |
|----------------|------|-----------|
| `url 不能为空` | 请求未带 url | 检查消息体 |
| `仅支持 http/https 音频链接` | 协议不支持 | 换 http/https 直链 |
| `音频加载超时，请检查链接是否可访问` | 网络不可达或链接失效 | 检查网络 / 重新获取链接 |
| `音频拉取/解码失败(ffmpeg rc=...)` | 链接 404/403、签名过期、格式不支持 | 重新获取有效链接 |
| `未从该链接解码出任何音频数据` | 拉到的不是音频内容 | 确认链接指向音频文件 |

---

## 5. 音频数据格式（重要）

| 项 | 值 |
|----|----|
| 编码 | Opus |
| 采样率 | 24000 Hz（以 hello 协商为准） |
| 声道 | 1（单声道） |
| 帧长 | 60 ms / 帧（= 1440 采样点/帧） |
| 传输 | WebSocket **二进制帧**，直接发送，普通模式下**无额外包头** |

> **MQTT 网关模式例外**：当连接来自 MQTT 网关时，服务端会在每个 Opus 包前加 **16 字节头部**
> （`[0]=type`、`[2:4]=payload长度(大端)`、`[4:8]=sequence`、`[8:12]=timestamp`、`[12:16]=opus长度`），
> 设备需先剥离 16 字节再解码。可通过连接路径是否含 `?from=mqtt_gateway` 判断。

设备需为 24000Hz / 单声道初始化 Opus 解码器，每帧解码出 1440 个 16bit 采样点（2880 字节 PCM）。

---

## 6. 设备端状态机

```
IDLE ──发送 audio_play──▶ WAIT_START ──收到 tts:start──▶ PLAYING
  ▲                            │                            │
  │                            └──收到 audio_play:error──┬───┘
  └────────────────────── tts:stop 且缓冲播完 ───────────┘
```

- `PLAYING` 状态：收到二进制帧 → 塞入解码/播放队列
- 收到 `tts:stop` 后，继续播完本地已缓冲的帧，再回到 `IDLE`
- 收到 `audio_play:error` 立即回到 `IDLE`

---

## 7. 播放实现要点

1. **帧队列**：服务端已按实时节奏推送（前 5 帧约 300ms 预缓冲后按 60ms/帧节流），设备只需
   一个小的环形/抖动缓冲（建议 ≥ 500ms 容量），收到即解码入队，由 I2S 定时器消费。
2. **采样率对齐**：解码器必须用 hello 应答里的 `sample_rate`。若固件内部统一用 16kHz 播放，
   需自行重采样，否则会变调变速。
3. **不要假设成对出现**：`start` 之后可能紧接二进制帧；`stop` 可能在 0 帧之后直接到达（错误场景）。
4. **打断**：需要停止当前播放时，发送 `{"type":"abort"}`，服务端会立即终止拉流并回 `tts:stop`。
5. **串行**：同一连接上一次只能播一段。新发 `audio_play` 会覆盖当前轮次。
6. **内存受限设备**：服务端是流式推送，设备无需缓存整段音频，边收边播即可；10 分钟音频也不会撑爆内存。

---

## 8. 参考实现（ESP32 / ESP-IDF 伪代码）

```c
// ── 1. 建立 WebSocket 连接（需带 device-id 头） ─────────────────────
esp_websocket_client_config_t cfg = {0};
cfg.uri = "ws://192.168.1.100:8000/xiaozhi/v1/";
cfg.headers = "device-id: AA:BB:CC:DD:EE:FF\r\n";
client = esp_websocket_client_init(&cfg);
esp_websocket_client_start(client);

// ── 2. 连接成功后发送 hello ────────────────────────────────────────
static const char *HELLO =
  "{\"type\":\"hello\",\"version\":1,\"transport\":\"websocket\","
  "\"audio_params\":{\"format\":\"opus\",\"sample_rate\":24000,"
  "\"channels\":1,\"frame_duration\":60}}";
esp_websocket_client_send_text(client, HELLO, strlen(HELLO), portMAX_DELAY);

// ── 3. 请求播放一个音频链接 ─────────────────────────────────────────
void play_audio_url(const char *url) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "audio_play");
    cJSON_AddStringToObject(root, "url", url);
    char *msg = cJSON_PrintUnformatted(root);
    esp_websocket_client_send_text(client, msg, strlen(msg), portMAX_DELAY);
    cJSON_free(msg);
}

// ── 4. 接收回调：区分文本与二进制 ───────────────────────────────────
static void ws_event_handler(void *arg, esp_event_base_t base,
                             int32_t event_id, void *event_data) {
    esp_websocket_event_data_t *d = (esp_websocket_event_data_t *)event_data;
    if (event_id != WEBSOCKET_EVENT_DATA || d->op_code == 0x08) return;

    if (d->op_code == 0x02) {              // 二进制：Opus 帧
        // 若为 MQTT 网关模式，先跳过前 16 字节
        const uint8_t *payload = (const uint8_t *)d->data_ptr;
        int len = d->data_len;
        if (is_mqtt_gateway_mode()) { payload += 16; len -= 16; }
        if (len > 0) audio_ringbuf_push(payload, len);   // 入队，由播放任务解码
        return;
    }

    // 文本：JSON 状态
    cJSON *resp = cJSON_ParseWithLength(d->data_ptr, d->data_len);
    if (!resp) return;
    const char *type  = cJSON_GetStringValue(cJSON_GetObjectItem(resp, "type"));
    const char *state = cJSON_GetStringValue(cJSON_GetObjectItem(resp, "state"));
    if (type && strcmp(type, "tts") == 0 && state) {
        if (strcmp(state, "start") == 0) player_set_state(PLAYING);
        else if (strcmp(state, "stop") == 0) player_set_state(DRAINING); // 播完缓冲回 IDLE
    } else if (type && strcmp(type, "audio_play") == 0 && state &&
               strcmp(state, "error") == 0) {
        ESP_LOGE("audio", "play error: %s",
                 cJSON_GetStringValue(cJSON_GetObjectItem(resp, "error")));
        player_set_state(IDLE);
    }
    cJSON_Delete(resp);
}

// ── 5. 播放任务：从环形缓冲取 Opus 帧 → 解码 → 写 I2S ────────────────
void audio_play_task(void *arg) {
    OpusDecoder *dec = opus_decoder_create(24000, 1, &err);  // 与 hello 采样率一致
    int16_t pcm[1440];                                       // 60ms @ 24kHz
    uint8_t frame[512];
    while (1) {
        int n = audio_ringbuf_pop(frame, sizeof(frame), timeout_ms);
        if (n <= 0) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }
        int samples = opus_decode(dec, frame, n, pcm, 1440, 0);
        if (samples > 0) i2s_write(pcm, samples * 2, portMAX_DELAY);
        if (player_state() == DRAINING && audio_ringbuf_empty()) player_set_state(IDLE);
    }
}

// ── 6. 需要打断时 ──────────────────────────────────────────────────
void stop_play(void) {
    const char *abort = "{\"type\":\"abort\"}";
    esp_websocket_client_send_text(client, abort, strlen(abort), portMAX_DELAY);
}
```

---

## 9. 联调步骤

1. 设备正常连上服务端并完成 hello（能收到 hello 应答即 OK）。
2. 发送 `{"type":"audio_play","url":"<有效音频直链>"}`。
3. 观察：应先收到 `tts:start`，随后持续收到二进制帧，最后 `tts:stop`。
4. 若长时间只收到 `tts:start` 无二进制帧，多为链接不可达/签名过期（可用服务端日志确认 ffmpeg 报错）。

> 服务端自带的联调脚本（PC 端）：`python test_audio_play.py --url "<音频直链>"`，
> 会打印各状态与收到的 Opus 帧数，可用于先验证服务端链路是否正常。

---

## 10. 常见问题（FAQ）

| 现象 | 排查方向 |
|------|----------|
| 连接立刻被关闭 | 是否带了 `device-id` 头/参数；若开了认证，检查 `client-id` + `authorization` |
| 收到 `audio_play:error: 仅支持 http/https` | url 协议不对（如 `ftp://`、缺协议头） |
| 一直无音频帧 | 链接失效/签字过期/非音频内容；看服务端日志的 ffmpeg 报错 |
| 播放变调、变速 | 解码器采样率不是 hello 协商的 24000Hz |
| 播放有杂音/断音 | 抖动缓冲太小或 I2S 写入阻塞；建议缓冲 ≥ 500ms |
| 收到帧前多出 16 字节导致解码失败 | MQTT 网关模式未剥离 16 字节包头 |
| 收到 `tts:start` 后长时间没有 `tts:stop` | **正常现象**：服务端可能几秒内就拉取完整段音频，随后按实时节奏推送，`stop` 要等整段音频时长（如 7.5 分钟音频约 450 秒）。判断链路是否正常应看「是否持续收到二进制帧」，而非等 `stop` |
| 播完不回到空闲 | 需在收到 `tts:stop` 后等本地缓冲播完再置 IDLE，或用超时兜底 |

---

## 11. 对接检查清单

- [ ] 连接时携带 `device-id`
- [ ] 连接后先发 `hello` 并解析应答中的 `sample_rate`
- [ ] Opus 解码器按 24000Hz / 单声道 / 60ms 帧初始化
- [ ] 能区分 WebSocket 文本帧（JSON）与二进制帧（Opus）
- [ ] 二进制帧入环形缓冲，异步解码 → I2S 播放
- [ ] 处理 `tts:start` / `tts:stop` / `audio_play:error` 三个状态
- [ ] （如需）发送 `abort` 打断
- [ ] MQTT 网关模式下剥离 16 字节包头
