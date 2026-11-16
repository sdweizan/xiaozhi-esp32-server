# 咪咕音乐鉴权对接 · 改动规划

> **状态：已实现（2026-10-13）**，规划中的方案已落地。
> 最新协议与设备端接入说明以 **[`migu-music-device-integration.md`](./migu-music-device-integration.md)** 为准；
> 本文保留作为服务端侧的接口依据与影响分析记录。

> 目标：小智服务端在收到「播放 xxx 音乐/歌曲」时，先调用咪咕鉴权接口查询该设备是否已授权；
> 已授权则把 **歌曲关键词 + 手机号（密文）** 下发给小智客户端，由客户端/固件的咪咕 SDK 完成搜索与播放；
> 未授权则返回未授权提示。

---

## 一、需求依据

### 1. 咪咕鉴权接口（《厂商查询咪咕授权信息》）

| 项 | 内容 |
|----|------|
| 鉴权凭据 | `clientId = 7ed737ca335746af956924b64ad25e69`、`clientSecret = 50a4686d49da4a99aa751d8a96109136`（璇玑颁发，**按厂商配置化**） |
| 签名规则 | `signature = SHA1(clientSecret + timestamp + paramStr)` |
| paramStr | POST 时 = **请求体 JSON 本身**；其中 KEY 必须**按升序排列**，加密严格要求（序列化格式需与咪咕完全一致） |
| timestamp | 毫秒时间戳 |
| 请求 URL | `POST https://a2link.komect.com/lx-device-manager/cloud/json/miniprogram/migu/auth/queryBySn` |
| 请求头 | `clientId`、`timestamp`、`signature` |
| 请求体 | `sn`（设备 SN）、`productCode`（产品编码，对接期传 `TEST`，正式待申请） |
| 返回 | `resultCode`(0=成功)、`resultCodeDesc`、`resultCodeMessage`、`data.phone`(手机号，**已加密**)、`data.authStatus`(1=已授权 / 0=未授权) |
| 未授权返回 | 无 `data` 字段，仅 `resultCode=0` + `resultCodeDesc=success` |

### 2. 时序图（业务编排）

```
端侧/AI平台: 音乐播放自然语言 "我想听周杰伦的稻香"
  → 客户AI平台 提取关键词（歌手：周杰伦，歌曲：稻香）
  → 客户AI平台 按 SN 调咪咕「查询手机号/授权」接口
  → 已授权：返回 关键词 + 手机号(+SN) → 咪咕模组IoT平台
      → 音乐搜索 / 用户VIP等级判断 / 歌曲播放
      → 返回结果（VIP等级不够 / 歌曲无授权 / 正常播放）
  → 未授权：返回未授权提示
（解绑流程：设备解绑 → 调用解除咪咕授权接口，本期不在范围内）
```

### 3. 固件侧约束（《ESP32S3 MP3 流式播放器设计文档》）

- `Mp3Player(esp_codec_dev_handle_t, NetworkInterface*, const std::string& sn, const std::string& 用户绑定咪咕的手机号(密文))`
  → **构造需要 SN + 手机号（密文）**，两者缺一不可。
- `play(MusicInfo*)` 返回错误码：`-4` 非会员无权限、`-6` 没有版权、`-7` 歌曲未找到。
  → **搜索、VIP 判断、版权校验都在客户端/固件完成**，服务端只负责"授权判定 + 下发关键词与手机号"。

**结论：服务端的职责边界 = 鉴权判定 + 关键词提取 + 下发行 `{关键词, 手机号(密文)}`。**

---

## 二、现有链路梳理（关键代码点）

| 环节 | 位置 | 说明 |
|------|------|------|
| 工具注册 | `plugins_func/functions/play_music.py` | `@register_function("play_music", desc, ToolType.SYSTEM_CTL)`，由 LLM function_call 触发 |
| 工具执行 | 同上 `play_music()` → `handle_music_command()` → `play_local_music()` | 异步任务挂在 `conn.loop`，通过 `conn.tts.tts_text_queue` 推"引导语 + FILE(本地 mp3)" |
| 特殊处理 | `core/handle/intentHandler.py:198` | `elif function_name != "play_music"` —— play_music **自行处理 TTS，不走 speak_txt**（改动时要保持） |
| 设备标识 | `core/connection.py:211` `self.device_id = headers.get("device-id")` | 目前**全局无 SN 概念**，device-id 一般是 MAC |
| 设备下行范例 | `core/handle/textHandler/audioPlayMessageHandler.py`、`story_handler.py` | 前者是新 `type` 直接 `websocket.send`；后者是 `mcp.payload` 请求-响应风格 |
| 消息类型注册 | `core/handle/textMessageType.py` + `textMessageHandlerRegistry.py` | 新增下行/上行 type 的登记处 |
| 特性协商 | `core/handle/helloHandle.py` | hello 时读 `features`，可在此声明/读取 `migu` 能力 |
| 配置段 | `config.yaml` 的 `plugins:` 与 `plugins.play_music` | 新增 `plugins.migu_music` 配置 |

**现有逻辑与咪咕需求的差异**：
- 现有是"服务端直接播本地 mp3"；咪咕是"服务端只鉴权+下发，播放交给客户端 SDK"。
- 现有无 SN、无手机号、无外部鉴权 HTTP 调用、无"未授权"分支。
- 现有 `play_music(song_name)` 参数可复用（song_name 即用户点播的原始关键词）。

---

## 三、目标流程（新）

```
用户说"播放稻香"
  → ASR → LLM function_call: play_music(song_name="稻香")
  → play_music() 判断：本连接是否走咪咕分支？
       ├─ 否 → 原本地播放逻辑（完全不变）
       └─ 是 → 提取关键词（singer/song）
              → 取 SN → 调咪咕 queryBySn(sn, productCode)
                   ├─ authStatus == 1（已授权）
                   │    → 下发设备：{"type":"music_play","keyword":"稻香","singer":"周杰伦",
                   │                 "phone":"<密文>","authStatus":1,"session_id":...}
                   │    → 客户端 Mp3Player(sn, phone).play(MusicInfo) 自行播放
                   │    → （客户端播放失败 -4/-6/-7 自行处理，见第四节可选项）
                   ├─ authStatus == 0（未授权）
                   │    → 下发/播报"该设备未授权咪咕音乐，请先绑定"
                   └─ 接口异常/超时
                        → 可配置降级：回退本地播放 或 播报"音乐服务暂不可用"
```

---

## 四、改动清单

### 新增（约 3 个文件）

| # | 文件 | 职责 |
|---|------|------|
| 1 | `core/providers/migu/migu_auth_client.py`（或 `core/utils/`） | 咪咕鉴权客户端：SHA1 签名、`queryBySn()`、超时/重试、结果对象化 |
| 2 | `core/handle/migu_music_handler.py` | 业务编排：取 SN → 鉴权 → 关键词提取 → 组装下行消息 → 发送；含未授权/异常分支 |
| 3 | `docs/migu-music-integration.md` | 对接手册（请求示例、下行协议、错误码），供固件方对齐 |

> 可选：`core/utils/cache` 里加 `MIGU_AUTH` 缓存类型，按 SN 缓存 `phone+authStatus`（TTL 可配），减少接口调用与手机号密文反复获取。

### 修改（约 4 处）

| # | 文件 | 改动 |
|---|------|------|
| 1 | `plugins_func/functions/play_music.py` | `handle_music_command()` 入口加分支：`migu 启用 且 本连接支持咪咕` → 走鉴权流程，否则原逻辑。**工具名/参数不变** |
| 2 | `config.yaml` | 新增 `plugins.migu_music`：`enable`/`base_url`/`clientId`/`clientSecret`/`product_code`(默认 TEST)/`cache_ttl`/`fallback_to_local` |
| 3 | `core/handle/textMessageType.py` + `textMessageHandlerRegistry.py` | 若采用"新下行 type"，登记 `music_play`（若复用 mcp.payload 则改 `mcpMessageHandler` 拦截，**无需新增 type**） |
| 4 | `core/handle/helloHandle.py`（+ `connection.py` 少量字段） | 读 hello `features.migu`，在 `conn` 上标记 `conn.migu_enabled`；并在 `welcome_msg` 声明服务端能力 |

### 明确不改

- `intentHandler.py`：无需动（`play_music` 已有豁免分支，保持自行 TTS 的行为）。
- 其它插件（weather/story/poem/audio_play/text_tts）：互不影响。
- 现有本地播放路径：默认关闭咪咕时行为与今天完全一致。

---

## 五、兼容现有逻辑的策略

| 风险 | 兼容手段 |
|------|----------|
| 影响现网设备 | **总开关** `plugins.migu_music.enable` 默认 `false`，关闭时零行为变化 |
| 设备固件不支持咪咕 | 由设备在 hello `features` 声明 `{"migu": true}`，服务端**按连接**决定是否走咪咕分支；未声明的老设备自动走本地播放 |
| LLM 工具契约 | `play_music` 工具名、参数（`song_name`）**不变**，LLM 侧无需改提示词 |
| 接口故障 | `fallback_to_local: true` 时接口异常/超时降级为本地播放；`false` 时播报"音乐服务暂不可用" |
| 手机号重复获取 | 按 SN 缓存密文（TTL 可配），避免每首歌都请求 |
| 播放职责冲突 | 咪咕分支**不再**往 `tts_text_queue` 塞 FILE（播放交给客户端），避免服务端本地播放与客户端 SDK 抢播 |
| TTS 行为 | 沿用 `play_music` 自行 TTS 的既有模式（`intentHandler` 的豁免分支保持不变） |

---

## 六、工作量评估：**改动不大（中等偏小）**

| 维度 | 评估 |
|------|------|
| 代码量 | 新增 ~2 个 Python 文件（客户端 + 编排），改 1 个核心文件（play_music），配置 + 文档少量 |
| 复杂度 | 逻辑本身简单（一次 HTTP + 分支）；**难点不在代码量**，而在三处外部对齐（见第七节） |
| 风险 | 低——有总开关 + 按连接特性 + 降级策略三重隔离，不影响存量功能 |
| 关键路径 | `SN 来源` 与 `下行协议与固件对齐` 是阻塞项，需先敲定才能开工 |

**一句话：代码改造量小（1~2 天量级），主要成本在跨端约定与联调。**

---

## 七、关键待确认问题（开工前必须拍板）

1. **SN 从哪里取？**
   现在代码只有 `device-id`（通常=MAC），而咪咕要求 `sn`。需要确认：SN = `device-id`？还是 hello 消息里新增字段？还是由小程序/H5 绑定阶段透传并落库、服务端按 device-id 反查？
   —— **这是最大阻塞项，直接决定取数方式与是否要新增存储。**
2. **`data.phone` 是否需要服务端解密？**
   文档标注"已加密"。是服务端原样透传给客户端（客户端/SDK 解密），还是需要服务端解开再下发？解密算法与密钥由谁提供？
3. **`productCode`**：对接期用 `TEST`，正式码何时申请下发？是否需要按产品多套配置？
4. **下行协议形态**：新增顶层 `type`（如 `music_play`）还是复用 `mcp.payload`？需与固件方约定字段名（`keyword`/`singer`/`song`/`phone`）与语义。
5. **关键词是否需要 LLM 二次提取？**
   直接复用 `song_name` 原串（简单），还是拆成"歌手 + 歌曲"两个字段（更贴合客户端 `MusicInfo`）？若拆，由 LLM 抽取还是规则解析？
6. **签名序列化的精确格式**：`paramStr`="请求体本身"且 key 升序，需跟咪咕确认 JSON 是否含空格、是否转义中文（极易踩坑，需以实际调通为准）。
7. **接口凭据粒度**：`clientId/clientSecret` 是"璇玑按厂商颁发"，是否每个厂商/客户不同 → 是否要支持多套凭据？
8. **绑定/解绑是否在服务端范围**：时序图的"解绑 → 调用解除咪咕授权接口"本期是否要做？（建议本期只读查询，不做解绑）

---

## 八、建议实施顺序

1. 先落地**接口客户端 + 单测**（用 `sn` 固定值直接对咪咕 `TEST` 环境打通签名与返回解析）。
2. 确定 SN 来源与下行协议（与固件方对齐），补齐 `docs/migu-music-integration.md`。
3. 接入 `play_music` 分支（默认关闭），加缓存与降级。
4. 联调：设备说"播放稻香" → 服务端下发关键词+手机号 → 客户端 SDK 播放 / 返回 -4/-6/-7。
5. 灰度：单设备/白名单打开开关验证后再全量。
