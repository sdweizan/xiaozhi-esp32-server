# 古诗词接口对接手册

## 概述

设备通过 MCP 通道发送 `type: "poem"` 消息请求古诗词数据，服务端从本地 `resource/300.json` 读取数据并直接返回结构化 JSON，不经过 LLM / TTS 流程。

- 数据量：**319 首**，8 种诗体
- 响应格式：`{type: "mcp", payload: {...}, session_id: "..."}`
- 错误响应：`{type: "poem", action, code, error}`

---

## 支持的消息 action

| action | 说明 |
|--------|------|
| `list` | 获取诗词列表，支持按诗体筛选 |
| `get`  | 按 id 获取诗词详情（含全文） |

---

## 1. 获取诗词列表 `list`

### 请求格式

```json
{
  "type": "mcp",
  "session_id": "<session_id>",
  "payload": {
    "type": "poem",
    "action": "list",
    "poem_type": "五言绝句"   // 可选，不传则返回全部 319 首
  }
}
```

> `payload.type` 为消息协议标识，`payload.type`（诗体）为可选筛选参数。

### 支持筛选的诗体

| 诗体 | 数量 |
|------|------|
| 五言古诗 | 35 |
| 五言绝句 | 36 |
| 五言律诗 | 81 |
| 七言古诗 | 27 |
| 七言绝句 | 60 |
| 七言律诗 | 54 |
| 七言乐府 | 15 |
| 五言乐府 | 11 |

### 响应格式（成功）

```json
{
  "session_id": "<session_id>",
  "type": "mcp",
  "payload": {
    "type": "poem",
    "action": "list",
    "code": 0,
    "data": {
      "poems": [
        {
          "id": 224,
          "title": "竹里馆",
          "author": "王维",
          "type": "五言绝句"
        },
        {
          "id": 233,
          "title": "静夜思",
          "author": "李白",
          "type": "五言绝句"
        }
      ],
      "total": 36,
      "filter_type": "五言绝句"
    }
  }
}
```

### 响应格式（失败）

```json
{
  "session_id": "<session_id>",
  "type": "mcp",
  "payload": {
    "type": "poem",
    "action": "list",
    "code": 4,
    "error": "服务器内部错误"
  }
}
```

---

## 2. 获取诗词详情 `get`

### 请求格式

```json
{
  "type": "mcp",
  "session_id": "<session_id>",
  "payload": {
    "type": "poem",
    "action": "get",
    "id": 6
  }
}
```

### 响应格式（成功）

```json
{
  "session_id": "<session_id>",
  "type": "mcp",
  "payload": {
    "type": "poem",
    "action": "get",
    "code": 0,
    "data": {
      "id": 6,
      "title": "月下独酌",
      "author": "李白",
      "type": "五言古诗",
      "contents": "花间一壶酒，独酌无相亲。\n举杯邀明月，对影成三人。\n月既不解饮，影徒随我身。\n暂伴月将影，行乐须及春。\n我歌月徘徊，我舞影零乱。\n醒时同交欢，醉后各分散。\n永结无情游，相期邈云汉。"
    }
  }
}
```

### 响应格式（失败 - 未找到）

```json
{
  "session_id": "<session_id>",
  "type": "mcp",
  "payload": {
    "type": "poem",
    "action": "get",
    "code": 1,
    "error": "未找到 id=999 的诗词"
  }
}
```

---

## 错误码

| code | 说明 |
|------|------|
| 0    | 成功 |
| 1    | 请求参数错误（如缺少 id）|
| 3    | 请求超时（暂未使用）|
| 4    | 服务器内部错误 |

---

## 完整示例：设备侧调用流程

```
设备点击"随机古诗"
  → 发送 list 请求（不传 type，获取全部）
  → 服务端返回 319 首诗的标题+作者列表
  → 设备随机选一首，显示标题和作者
  → 设备点击"朗读"
  → 发送 get 请求（id: <选中id>）
  → 服务端返回完整诗词内容
  → 设备 TTS 朗读 contents 字段
```

### 示例一：获取全部诗词列表

```json
// 请求
{"type": "mcp", "session_id": "abc123", "payload": {"type": "poem", "action": "list"}}

// 响应
{"type": "mcp", "session_id": "abc123", "payload": {"type": "poem", "action": "list", "code": 0, "data": {"poems": [...319首...], "total": 319, "filter_type": null}}}
```

### 示例二：按诗体筛选列表

```json
// 请求
{"type": "mcp", "session_id": "abc123", "payload": {"type": "poem", "action": "list", "poem_type": "五言绝句"}}

// 响应
{"type": "mcp", "session_id": "abc123", "payload": {"type": "poem", "action": "list", "code": 0, "data": {"poems": [...36首...], "total": 36, "filter_type": "五言绝句"}}}
```

### 示例三：获取诗词详情

```json
// 请求
{"type": "mcp", "session_id": "abc123", "payload": {"type": "poem", "action": "get", "id": 6}}

// 响应
{"type": "mcp", "session_id": "abc123", "payload": {"type": "poem", "action": "get", "code": 0, "data": {"id": 6, "title": "月下独酌", "author": "李白", "type": "五言古诗", "contents": "花间一壶酒..."}}}
```

---

## 注意事项

1. `contents` 字段内 `\n` 为换行符，设备渲染时按行展示
2. 列表接口返回 `poems` 仅含摘要（id/title/author/type），不含 contents；获取全文需调用 `get`
3. 数据缓存在服务端 24 小时，首次请求后后续调用几乎无延迟
