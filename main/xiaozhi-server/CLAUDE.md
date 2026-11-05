# xiaozhi-esp32-server 项目手册

## 项目概述

小智 ESP32 Server 是一个面向 ESP32 硬件设备的语音助手后端服务。设备通过 WebSocket 连接，支持语音唤醒、语音识别（ASR）、大语言模型对话（LLM）、语音合成（TTS）、工具调用（MCP/IoT/插件）和 OTA 固件升级。

**技术栈**: Python 3.10+, aiohttp, websockets, async/await
**入口**: `main/xiaozhi-server/app.py`
**配置**: `main/xiaozhi-server/config.yaml`（默认），`data/.config.yaml`（用户覆盖）

---

## 目录结构

```
main/xiaozhi-server/
├── app.py                          # 启动入口：加载配置 → 启动 WS + HTTP 服务器
├── config.yaml                     # 默认配置（TTS/ASR/LLM/VAD/Intent/插件等）
├── config/
│   ├── config_loader.py            # 配置加载：优先读 .config.yaml，fallback 到 config.yaml
│   ├── settings.py                 # 配置校验与文件检测
│   ├── logger.py                   # 日志初始化
│   └── manage_api_client.py        # 智控台 API 客户端（全模块部署时从 API 拉配置）
├── core/
│   ├── connection.py               # ConnectionHandler — 每个设备连接一个实例，管理完整生命周期
│   ├── websocket_server.py         # WebSocket 服务器：认证 → 创建 ConnectionHandler → 路由消息
│   ├── http_server.py              # HTTP 服务器：OTA 接口 + 视觉分析接口
│   ├── auth.py                     # JWT 认证
│   ├── handle/                     # 消息处理链路
│   │   ├── textHandle.py           # 文本消息入口 → textMessageProcessor
│   │   ├── textMessageType.py      # 消息类型枚举：hello/abort/listen/iot/mcp/server/ping
│   │   ├── textMessageHandler.py     # 基类 TextMessageHandler
│   │   ├── textMessageHandlerRegistry.py  # 处理器注册表
│   │   ├── textMessageProcessor.py  # 按 type 分发到对应 handler
│   │   ├── helloHandle.py          # hello 握手：音频参数、MCP 特性协商
│   │   ├── sendAudioHandle.py      # TTS 音频发送、显示消息
│   │   ├── receiveAudioHandle.py   # 接收音频 → VAD → ASR → 意图识别
│   │   ├── intentHandler.py        # 意图识别：function_call / intent_llm / nointent
│   │   ├── reportHandle.py         # 聊天记录上报到智控台
│   │   ├── textHandler/            # 各消息类型处理器
│   │   │   ├── helloMessageHandler.py
│   │   │   ├── abortMessageHandler.py
│   │   │   ├── listenMessageHandler.py   # 语音输入状态机
│   │   │   ├── iotMessageHandler.py      # IoT 设备描述符/状态
│   │   │   ├── mcpMessageHandler.py      # MCP 协议消息
│   │   │   ├── serverMessageHandler.py   # 服务器管理指令
│   │   │   └── pingMessageHandler.py
│   │   └── mcp_weather_handler.py    # ★ 新增：天气 MCP 消息处理
│   │   └── mcp_weather_service.py    # ★ 新增：天气数据服务层（和风 V7 API）
│   ├── providers/                  # 可插拔组件
│   │   ├── asr/                    # 语音识别：FunASR/Doubao/Aliyun/Tencent/OpenAI/Vosk 等
│   │   ├── tts/                    # 语音合成：Edge/Doubao/FishSpeech/Aliyun/Tencent 等
│   │   ├── llm/                    # 大语言模型：OpenAI/Coze/Dify/Gemini/Ollama 等
│   │   ├── memory/                 # 记忆：mem0ai/powermem/mem_local_short/nomem
│   │   ├── intent/                 # 意图：function_call/intent_llm/nointent
│   │   └── tools/                  # 工具系统
│   │       ├── unified_tool_handler.py   # 统一工具处理器
│   │       ├── unified_tool_manager.py   # 工具管理器（注册/执行/缓存）
│   │       ├── device_iot/             # 设备端 IoT 工具
│   │       ├── device_mcp/             # 设备端 MCP 工具
│   │       ├── server_plugins/         # 服务端插件执行器
│   │       ├── server_mcp/             # 服务端 MCP 执行器
│   │       └── mcp_endpoint/           # MCP 接入点执行器
│   ├── api/                        # HTTP API handlers
│   │   ├── ota_handler.py          # OTA 固件升级接口
│   │   └── vision_handler.py       # 视觉分析接口
│   └── utils/                      # 工具模块
│       ├── cache/                  # 缓存系统（LRU + TTL）
│       ├── dialogue.py             # 对话管理（Message/Dialogue）
│       ├── prompt_manager.py       # 提示词管理
│       └── util.py                 # 通用工具
│
├── plugins_func/                   # 功能插件
│   ├── register.py                 # @register_function 装饰器、Action/ActionResponse
│   ├── loadplugins.py              # 插件自动发现与加载
│   └── functions/                  # 内置插件
│       ├── get_weather.py          # 天气查询（LLM function_call 流程，HTML 爬取）
│       ├── play_music.py           # 音乐播放
│       ├── change_role.py          # 角色切换
│       └── ...
│
└── data/                           # 运行时数据（gitignore）
    └── .config.yaml                # 用户自定义覆盖配置
```

---

## 核心架构

### 1. 连接生命周期

```
WebSocketServer.start()
  └→ _handle_connection(ws)
       ├─ 提取 device-id / client-id / authorization
       ├─ _handle_auth(ws)          # JWT token 验证（可选）
       ├─ ConnectionHandler(config, vad, asr, llm, memory, intent, server)
       └─ handler.handle_connection(ws)
            ├─ 后台异步初始化配置和组件 (_background_initialize)
            └─ async for message in ws:
                 └─ _route_message(message)
                      ├─ str → handleTextMessage → textMessageProcessor
                      └─ bytes → asr_audio_queue → ASR 处理
```

**关键**: `ConnectionHandler` 是每个设备的独立上下文，包含：
- `websocket` — WebSocket 连接
- `config` — 该设备的差异化配置（从智控台拉取或本地配置）
- `func_handler` — 统一工具处理器
- `dialogue` — 对话历史
- `iot_descriptors` — 已注册的 IoT 设备描述符
- `features` — 客户端特性（如 `{"mcp": true}`）

### 2. 消息处理链路

所有设备→服务器的 JSON 消息走同一入口：

```
handleTextMessage(conn, raw_message)
  → textMessageProcessor.process_message(conn, message_dict)
    → 解析 message["type"]
    → registry.get_handler(type).handle(conn, message)
```

**现有消息类型**:

| type | 用途 | Handler | 说明 |
|------|------|---------|------|
| `hello` | 连接握手 | HelloTextMessageHandler | 音频参数协商、MCP 特性启用 |
| `abort` | 打断 | AbortTextMessageHandler | 中断 TTS 播报 |
| `listen` | 语音输入 | ListenTextMessageHandler | start/stop/detect 状态机 |
| `iot` | IoT 控制 | IotTextMessageHandler | descriptors/states 上报 |
| `mcp` | MCP 协议 | McpTextMessageHandler | 初始化/工具列表/工具调用 |
| `server` | 服务器管理 | ServerTextMessageHandler | 配置更新/重启 |
| `ping` | 心跳 | PingTextMessageHandler | 保活 |

**新增**:
| `app` | 应用数据 | AppTextMessageHandler | 纯数据请求（天气等） |
| `text_tts` | 纯文字转语音 | TextTtsMessageHandler | 不经过 LLM，直接 TTS |
| `audio_play` | 播放 URL 音频 | AudioPlayMessageHandler | 流式拉取音频并转码 Opus 直推设备播放 |

> **下行消息（无上行 handler）**：服务端会主动下发 `type: music_play`，承载咪咕音乐鉴权结果
> （授权状态 + 歌曲关键词 + 手机号密文），由设备端咪咕 SDK 完成播放。
> 触发点在 `plugins_func/functions/play_music.py` → `core/handle/migu_music_handler.py`，
> 协议详见 `docs/migu-music-device-integration.md`。

### 3. 工具系统

```
UnifiedToolHandler
  ├─ ToolManager（统一调度）
  │   ├─ ServerPluginExecutor  → plugins_func/functions/*.py
  │   ├─ ServerMCPExecutor     → 服务端 MCP 工具
  │   ├─ DeviceIoTExecutor     → 设备端 IoT 工具
  │   ├─ DeviceMCPExecutor     → 设备端 MCP 工具
  │   └─ MCPEndpointExecutor   → MCP 接入点工具
```

插件注册使用 `@register_function("name", desc, ToolType)` 装饰器，自动从 `plugins_func.functions` 目录发现加载。

### 4. LLM 对话流程

```
用户说话 → VAD 检测结束 → ASR 转文字
  → intentHandler.analyze_intent()
    → function_call 模式: LLM 直接返回 tool_calls
    → intent_llm 模式: LLM 判断意图后路由
  → func_handler.handle_llm_function_call()
    → ToolManager.execute_tool(name, args)
    → 执行对应 Executor
    → ActionResponse(RESPONSE/REQLLM/ERROR/NOTFOUND)
  → TTS 播报结果 → Opus 编码 → WebSocket 发送给设备
```

---

## 配置系统

### 配置优先级

```
data/.config.yaml  (用户覆盖，最高优先级)
    ↓ fallback
config.yaml  (默认配置)
    ↓ (全模块部署时)
智控台 API 动态配置（最高优先级，覆盖一切本地配置）
```

### 关键配置段

- `server.*` — 端口、认证、MQTT 网关
- `plugins.get_weather.*` — 和风天气 API 密钥
- `selected_module.*` — 当前启用的组件（VAD/ASR/LLM/TTS/Memory/Intent）
- `Intent.*.functions` — 启用的插件列表
- `context_providers` — 上下文源 URL 列表
- `mcp_endpoint` — 外部 MCP 接入点地址

### 天气插件配置

```yaml
plugins:
  get_weather:
    api_host: "mj7p3y7naa.re.qweatherapi.com"  # 和风 API host
    api_key: "your_key"                         # 和风 API key
    default_location: "广州"                     # 默认城市
```

---

## 开发约定

### 添加新消息类型

1. 在 `core/handle/textMessageType.py` 的 `TextMessageType` 枚举中添加值
2. 在 `core/handle/textHandler/` 下创建 `<type>MessageHandler.py`，继承 `TextMessageHandler`
3. 在 `textMessageHandlerRegistry.py` 的 `_register_default_handlers()` 中注册
4. 在 `helloHandle.py` 的 `welcome_msg` 中声明支持的特性（如 `"app": true`）

### 添加新插件

1. 在 `plugins_func/functions/` 下创建 `<plugin_name>.py`
2. 使用 `@register_function("name", FUNCTION_DESC, ToolType.SYSTEM_CTL)` 装饰
3. 函数签名: `def func(conn: ConnectionHandler, **kwargs) -> ActionResponse`
4. 在 `config.yaml` 的 `Intent.*.functions` 列表中注册

### 添加新的 MCP 消息类型（数据通道）

参考 `mcp_weather_handler.py` 的模式：

1. 在 `mcpMessageHandler.py` 的 `handle()` 方法开头拦截特定 `payload.type`
2. 创建独立的 service 模块处理业务逻辑
3. 通过 `conn.websocket.send(json.dumps({...}))` 直接发送响应
4. **不走**标准 MCP 协议（不经过 `handle_mcp_message()`）

### 消息格式规范

- 所有 JSON 消息必须包含 `type` 字段标识消息类型
- 服务端→设备消息建议包含 `session_id` 用于关联
- 错误响应统一使用 `{"code": N, "error": "描述"}` 格式
- 使用 `json.dumps(msg, ensure_ascii=False)` 确保中文正确编码

### 异步编程规范

- 所有 I/O 操作使用 `asyncio` + `aiohttp`，禁止阻塞调用
- 耗时计算用 `conn.executor.submit()` 放在线程池
- 超时控制用 `asyncio.wait_for(future, timeout=N)`
- 事件循环访问用 `asyncio.run_coroutine_threadsafe(coro, conn.loop)`

### 缓存使用

```python
from core.utils.cache.manager import cache_manager, CacheType

# 读取
cached = cache_manager.get(CacheType.WEATHER, cache_key)

# 写入 (TTL 秒)
cache_manager.set(CacheType.WEATHER, cache_key, value, ttl=900)
```

支持的 CacheType: `IP_INFO`, `WEATHER`, `CONFIG` 等。

### 日志

```python
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()
logger.bind(tag=TAG).info("message")
logger.bind(tag=TAG).error("error", exc_info=True)
```

---

## 运行与调试

### 启动

```bash
cd main/xiaozhi-server
python app.py
```

默认监听 `ws://0.0.0.0:8000/xiaozhi/v1/`，HTTP 端口 8003。

### 测试 WebSocket

```bash
# 使用 wscat
wscat -c ws://localhost:8000/xiaozhi/v1/

# 使用 Python
python test_weather_mcp.py --auto
```

### 常见问题排查

- **连接失败**: 检查 `device-id` header 是否正确，auth 是否启用
- **TTS 失败**: 检查 TTS 配置和 API key，查看日志中的 TTS 相关错误
- **ASR 识别乱码**: 检查采样率配置（设备 24kHz，部分 ASR 需要 16kHz）
- **工具调用超时**: 调整 `tool_call_timeout` 配置（默认 30s）
- **天气查询失败**: 检查 `plugins.get_weather.api_key` 和 `api_host` 配置
