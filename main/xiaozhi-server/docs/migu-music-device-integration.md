# 咪咕音乐鉴权 · 设备端对接文档

> 适用对象：**无屏幕的小智设备固件**（ESP32-S3 等），全语音交互。  
> 服务端：xiaozhi-server（咪咕鉴权分支）。  
> 文档版本：2026-10-13（v1，无屏设备版）。

---

## 一、总览

一句话：**服务端负责"判断这台设备有没有咪咕授权"，设备端负责"用咪咕 SDK 把歌放出来"。**

设备端要做的只有三件事：

| # | 环节   | 设备端动作                                           |
| - | ---- | ----------------------------------------------- |
| 1 | 连接握手 | `hello` 里上报 `sn`，并在 `features` 中声明 `migu: true` |
| 2 | 用户点歌 | **正常说话即可**（如"我想听周杰伦的稻香"），不需要任何额外操作              |
| 3 | 接收结果 | 监听下行 `music_play` 消息，按 `state` 分别处理             |

设备端**不需要、也不能**做的事：

- ❌ 自己上传歌名 / 歌手（无屏设备没有这个通道，见第七节第 7 条）
- ❌ 做音乐搜索
- ❌ 判断 VIP 等级 / 版权
- ❌ 调咪咕鉴权接口

> **歌名/歌手由服务端识别**：设备端只上报音频和 SN，服务端 ASR + LLM 从用户语音里  
> 识别出 `keyword`（歌名）和 `singer`（歌手），再连同手机号（密文）一起下发。

---

## 二、握手：上报 SN 与能力

设备在 WebSocket 建连后的 `hello` 消息中，新增 `sn` 字段并声明 `migu` 特性：

```json
{
  "type": "hello",
  "version": 1,
  "transport": "websocket",
  "sn": "MG2026101300001",
  "features": { "migu": true, "mcp": true },
  "audio_params": {
    "format": "opus",
    "sample_rate": 24000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

| 字段              | 必选    | 类型     | 说明                                                                |
| --------------- | ----- | ------ | ----------------------------------------------------------------- |
| `sn`            | **是** | string | 设备序列号。服务端**原样透传**给咪咕查询接口，不做任何加工。**不上报 sn 的设备永远不会收到 `music_play`** |
| `features.migu` | **是** | bool   | 声明本设备支持咪咕音乐。未声明则服务端不会走鉴权分支                                        |

服务端 `welcome` 应答中会告知服务端能力：

```json
{
  "type": "hello",
  "version": 1,
  "transport": "websocket",
  "session_id": "xxxx",
  "audio_params": { "...": "..." },
  "features": { "music_play": true }
}
```

| 字段                    | 说明                                      |
| --------------------- | --------------------------------------- |
| `features.music_play` | `true` 表示服务端已支持咪咕鉴权下发。设备可据此决定是否启用咪咕播放能力 |

**注意事项**

- `sn` 必须在**每一次连接的 `hello`** 里带上。服务端**不落库**，断线重连后不重报就会失效。
- `sn` 建议与设备出厂序列号一致，长度与字符集不要自行改写（服务端与咪咕侧按原文比对）。

---

## 三、完整时序（设备端视角）

```
设备端                                             小智服务端
  │
  │── hello {sn, features:{migu:true}} ───────────▶│  记录 sn / migu 能力
  │◀─ welcome {features:{music_play:true}} ────────│
  │
  │   用户说："我想听周杰伦的稻香"
  │
  │── 音频帧（listen / opus）─────────────────────▶│  ASR 转文字
  │                                                │  LLM 识别意图 →
  │                                                │     play_music(song_name="稻香", singer="周杰伦")
  │                                                │  ← 歌名/歌手在服务端产生
  │                                                │  咪咕 queryBySn(sn, productCode) 鉴权
  │◀─ stt  {"type":"stt","text":"我想听周杰伦的稻香"}│  ① 文本回显（无屏设备可忽略）
  │◀─ tts  {"state":"start"} ──────────────────────│  ② 服务端开始说话（状态标记）
  │◀─ music_play {state:"authorized", ...} ────────│  ③ 鉴权结果
  │◀─ tts  {"state":"stop"} ───────────────────────│  ④ 收尾：服务端本轮说话结束
  │
  │   Mp3Player(codec, net, sn, phone)
  │       .play(MusicInfo{singer, song, keyword})   ← 设备端用咪咕 SDK 播放
  │   └─ SDK 内部完成：搜索 / VIP 判断 / 版权校验 / 播放
  │   └─ 返回码：0 成功 / -4 非会员 / -6 无版权 / -7 未找到
```

**关键点：服务端不会下发任何 TTS 音频。**

`play_music` 在服务端的意图处理里是**豁免分支**（`core/handle/intentHandler.py`），因此  
已授权时服务端**只发状态标记、不发语音**，不会出现"服务端提示音和咪咕音乐同时响"的问题。  
设备端收到的 `tts start` / `tts stop` 仅用于维护会话状态机，中间没有音频帧。

> 例外：若服务端把 `migu_music.speak_text_on_authorized` 配成非空文案，服务端会额外播报  
> 一句话（此时会有 TTS 音频帧，设备正常播放即可）。默认配置为空，不播报。

---

## 四、下行消息详解

服务端 → 设备的下行消息统一为 `type = "music_play"`，用 `state` 区分三种结果。

### 4.1 已授权 `state = "authorized"`

```json
{
  "type": "music_play",
  "session_id": "xxxx",
  "state": "authorized",
  "authStatus": 1,
  "sn": "MG2026101300001",
  "keyword": "稻香",
  "singer": "周杰伦",
  "song": "稻香",
  "phone": "xxxxxxxxxxxxxxxx"
}
```

| 字段           | 类型     | 说明                                     |
| ------------ | ------ | -------------------------------------- |
| `state`      | string | 固定 `authorized`                        |
| `authStatus` | int    | `1` 表示已授权                              |
| `sn`         | string | 设备 SN，**与本次鉴权所用 SN 一致**，建议直接用这个值构造 SDK |
| `keyword`    | string | 歌曲关键词（服务端从用户语音识别得到）                    |
| `singer`     | string | 歌手，**可能为空字符串**                         |
| `song`       | string | 歌曲名（当前与 `keyword` 相同）                  |
| `phone`      | string | 手机号**密文**，直接传给咪咕 SDK，**不要解码、不要二次编码**   |

**设备端动作**：立刻用 `Mp3Player(sn, phone)` + `MusicInfo(singer, song, keyword)` 发起播放。

### 4.2 未授权 `state = "unauthorized"`

```json
{
  "type": "music_play",
  "session_id": "xxxx",
  "state": "unauthorized",
  "authStatus": 0,
  "sn": "MG2026101300001",
  "keyword": "稻香"
}
```

- **不含 `phone` 字段**，设备端不要读取。
- 服务端同时会**语音播报**提示文案（默认："该设备尚未授权咪咕音乐，请先在手机App中绑定手机号后再试。"）。

**设备端动作**：不要再重复播报提示音（会和服务端播报叠音）。无屏设备建议只做指示灯 / 提示音（短促"咚"）或不处理。

### 4.3 异常 `state = "error"`

```json
{
  "type": "music_play",
  "session_id": "xxxx",
  "state": "error",
  "code": 3,
  "error": "咪咕鉴权接口超时",
  "keyword": "稻香"
}
```

| code | 含义              | 设备端建议                 |
| ---- | --------------- | --------------------- |
| 1    | 参数错误（**缺少 SN**） | 检查 `hello` 是否上报了 `sn` |
| 2    | 音乐服务不可用         | 提示"稍后再试"              |
| 3    | 鉴权接口超时 / 网络异常   | 提示"稍后再试"              |
| 4    | 服务端内部错误         | 提示"稍后再试"              |

> 服务端在 `error` 时也会语音播报 `speak_text_on_error` 文案，设备端同样不必重复播报。

---

## 五、咪咕 SDK 调用要点

设备端拿到 `authorized` 后：

```cpp
// codec / net 为设备已有实例
Mp3Player player(codec, net, msg.sn, msg.phone);   // phone 直接用下行里的密文
MusicInfo info;
info.singer  = msg.singer;   // 可能为空，SDK 需容错
info.song    = msg.song;
info.keyword = msg.keyword;
int rc = player.play(&info);
```

`play()` 返回码（**设备端自行处理，服务端不感知**）：

| 返回码 | 含义       | 建议提示          |
| --- | -------- | ------------- |
| 0   | 播放中      | —             |
| -4  | 非会员用户无权限 | "该歌曲需要开通会员"   |
| -6  | 没有版权     | "该歌曲暂无版权"     |
| -7  | 歌曲未找到    | "没找到这首，换一首试试" |

**注意事项**

1. `phone` 是**密文**：原样传给 SDK，任何解码 / 重新编码都会导致鉴权失败。
2. `singer` 可能为空字符串：只在 `keyword` 里带歌词名搜索即可。
3. 立刻播放：一条 `music_play(authorized)` 对应**一次**点播，收到就发起播放。
4. 更换手机号绑定后，服务端缓存最长 300 秒后才刷新（见下节第 6 条）。

---

## 六、异常与边界

| # | 场景                                     | 服务端行为                            | 设备端应如何处理                                                           |
| - | -------------------------------------- | -------------------------------- | ------------------------------------------------------------------ |
| 1 | 设备只说"播放音乐"（没点名歌曲）                      | **不会**下发 `music_play`，走服务端本地音乐播放 | 正常接收服务端音频流即可，不要等 `music_play`                                      |
| 2 | 未声明 `features.migu` / 未上报 `sn`         | **不会**下发 `music_play`，走原有本地播放    | 老逻辑不变                                                              |
| 3 | 服务端总开关 `enable = false`                | **不会**下发 `music_play`            | 同上                                                                 |
| 4 | 鉴权接口超时，且服务端 `fallback_to_local = true` | 回退到**服务端本地音乐播放**，不发 `music_play` | 会收到服务端音频流（含 TTS 引导语）。联调期建议让服务端把该开关设为 `false`，以便明确暴露问题 |
| 5 | 用户中途打断（说"停一下"）                         | 服务端终止本轮 TTS                      | 设备发 `abort` 停止服务端音频；**咪咕音乐的停止由设备端 SDK 自行控制**                       |
| 6 | 用户在手机端刚解绑 / 绑定手机号                      | 服务端按 SN 缓存鉴权结果（默认 300 秒）         | 缓存过期前结果可能仍是旧的；紧急场景可提示用户稍后再试                                        |
| 7 | 无屏设备想"手动点歌"                            | **没有这个通道**（上行 `music_play` 已移除）  | 只能通过语音点歌。如需支持，必须走语音识别链路                                            |
| 8 | 断线重连                                   | 服务端不保存连接状态                       | **必须在新的 `hello` 里重新上报 `sn` 与 `features.migu`**                     |
| 9 | 走本地播放、但本地曲库没有点播的这首（如"演员"）             | 播报「版权音乐无法播放，为您播放《xxx》」后随机播放一首本地音乐 | 正常收音频流即可，**不要**等 `music_play`。提示语中 `xxx` 与实际播放曲目一致           |
| 10 | 走本地播放、但本地曲库为空 / 音乐目录不存在              | 播报「版权音乐无法播放，本地曲库暂时没有可播放的歌曲。」      | 只有 TTS 无音频；不再静默无响应                                                |

---

## 七、联调 Checklist

- [ ] `hello` 里带上 `sn` 和 `features.migu = true`
- [ ] `welcome` 里能读到 `features.music_play = true`
- [ ] 说"播放稻香" → 收到 `stt` 回显 + `music_play(state=authorized)`，且 `phone` 非空
- [ ] 用 `sn` + `phone` 调咪咕 SDK 能正常播放
- [ ] 说"播放周杰伦的稻香" → 下行 `singer` 为"周杰伦"
- [ ] 说"播放音乐" → **不收到** `music_play`（走服务端本地播放）
- [ ] 用未授权 SN 验证 `state=unauthorized`，且服务端有语音播报、设备端无叠音
- [ ] 断网 / 改错 `client_secret` 验证 `state=error`（服务端 `fallback_to_local=false` 时）
- [ ] 断线重连后再次点歌仍然正常（验证 SN 重报）
- [ ] 验证播放咪咕音乐期间服务端**没有**下发音频帧（不抢播）

---

## 八、附：服务端相关配置（联调参考）

`config.yaml`：

```yaml
plugins:
  migu_music:
    enable: false                  # 总开关。关闭时行为与改造前完全一致
    product_code: "TEST"           # 产品编码；对接期固定 TEST，正式编码下发后替换
    timeout: 8                     # 鉴权接口超时（秒）
    cache_ttl: 300                 # 按 SN 缓存鉴权结果（秒），0 表示不缓存
    require_client_feature: true   # 是否要求客户端声明 features.migu
    fallback_to_local: true        # 鉴权异常时回退服务端本地音乐播放
    speak_text_on_authorized: ""   # 已授权时的服务端播报文案，留空则不播报（推荐留空）
    speak_text_on_unauthorized: "该设备尚未授权咪咕音乐，请先在手机App中绑定手机号后再试。"
    speak_text_on_error: "音乐服务暂时不可用，请稍后再试。"
  play_music:
    music_dir: "./music"           # 本地曲库目录（咪咕不可用时的回退播放源）
    # 本地曲库没有点播的歌 → 先播报该提示，再随机播放一首本地音乐
    # 占位符：{song}=点播歌名，{played}=实际播放歌名
    not_found_prompt: "版权音乐无法播放，为您播放《{played}》"
    empty_library_text: "版权音乐无法播放，本地曲库暂时没有可播放的歌曲。"
```

**只有以下条件同时满足，服务端才会走咪咕分支并下发 `music_play`：**

1. `migu_music.enable = true`；
2. 设备在 `hello` 中上报了 `sn`；
3. 设备在 `features` 中声明了 `migu: true`（当 `require_client_feature = true` 时）；
4. 用户语音中能被识别出**具体歌名**。

---

## 九、变更记录

| 版本 | 日期         | 说明                                                                    |
| -- | ---------- | --------------------------------------------------------------------- |
| v1 | 2026-10-13 | 首版。面向无屏设备；协议只保留"设备上报 SN + 服务端下发 `music_play`"单向链路，已移除带屏/App 手动点歌的上行通道 |
