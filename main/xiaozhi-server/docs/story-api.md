# 故事 MCP 接口对接手册

## 概述

设备通过 MCP 通道发送 `type: "story"` 消息请求故事数据，服务端从本地 `resource/stories.json` 读取数据并直接返回结构化 JSON，不经过 LLM / TTS 流程。

- 数据量：**22 篇**中文故事
- 响应格式：`{type: "mcp", payload: {...}, session_id: "..."}`
- 数据字段：仅展示中文（`title_zh` / `content_zh`）
- 错误响应：`{type: "story", action, code, error}`

---

## 支持的消息 action

| action | 说明 |
|--------|------|
| `list` | 获取故事列表，支持分页，默认每页 20 条 |
| `get`  | 按 id 获取故事详情（含全文） |

---

## 1. 获取故事列表 `list`

### 请求格式

```json
{
  "type": "mcp",
  "session_id": "<session_id>",
  "payload": {
    "type": "story",
    "action": "list",
    "page": 1          // 可选，默认第 1 页
  }
}
```

### 响应格式（成功）

```json
{
  "session_id": "<session_id>",
  "type": "mcp",
  "payload": {
    "type": "story",
    "action": "list",
    "code": 0,
    "data": {
      "stories": [
        {"id": 1, "title": "狐狸和兔子妈妈的故事", "date": ""},
        {"id": 2, "title": "狐狸和野山鸡",         "date": ""},
        ...
      ],
      "total": 22,
      "page": 1,
      "page_size": 20,
      "totalPages": 2
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
    "type": "story",
    "action": "list",
    "code": 4,
    "error": "服务器内部错误"
  }
}
```

---

## 2. 获取故事详情 `get`

### 请求格式

```json
{
  "type": "mcp",
  "session_id": "<session_id>",
  "payload": {
    "type": "story",
    "action": "get",
    "id": 1
  }
}
```

### 响应格式（成功）

```json
{
  "session_id": "<session_id>",
  "type": "mcp",
  "payload": {
    "type": "story",
    "action": "get",
    "code": 0,
    "data": {
      "id": 1,
      "title": "狐狸和兔子妈妈的故事",
      "content": "兔妈妈有一个兔宝宝..."
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
    "type": "story",
    "action": "get",
    "code": 1,
    "error": "未找到 id=99 的故事"
  }
}
```

---

## 错误码

| code | 说明 |
|------|------|
| 0    | 成功 |
| 1    | 请求参数错误（如缺少 id）|
| 4    | 服务器内部错误 |

---

## 完整示例：设备侧调用流程

```
设备点击"故事"
  → 发送 list 请求（page=1）
  → 服务端返回第 1 页 20 条故事标题列表
  → 设备展示列表，用户选择
  → 发送 get 请求（id: <选中id>）
  → 服务端返回完整故事内容
  → 设备 TTS 朗读 content 字段
```

### 示例一：获取第 1 页故事列表

```json
// 请求
{"type": "mcp", "session_id": "abc123", "payload": {"type": "story", "action": "list"}}

// 响应
{"type": "mcp", "session_id": "abc123", "payload": {"type": "story", "action": "list", "code": 0, "data": {"stories": [...20条...], "total": 22, "page": 1, "page_size": 20, "totalPages": 2}}}
```

### 示例二：获取第 2 页故事列表

```json
// 请求
{"type": "mcp", "session_id": "abc123", "payload": {"type": "story", "action": "list", "page": 2}}

// 响应
{"type": "mcp", "session_id": "abc123", "payload": {"type": "story", "action": "list", "code": 0, "data": {"stories": [...2条...], "total": 22, "page": 2, "page_size": 20, "totalPages": 2}}}
```

### 示例三：获取故事详情

```json
// 请求
{"type": "mcp", "session_id": "abc123", "payload": {"type": "story", "action": "get", "id": 1}}

// 响应
{"type": "mcp", "session_id": "abc123", "payload": {"type": "story", "action": "get", "code": 0, "data": {"id": 1, "title": "狐狸和兔子妈妈的故事", "content": "兔妈妈有一个兔宝宝..."}}}
```

---

## 注意事项

1. `content` 字段为完整故事正文，可能较长，设备需支持滚动或分页展示
2. 列表接口仅返回摘要（id/title/date），不含 content；获取全文需调用 `get`
3. 数据缓存在服务端（列表 2 小时，详情 24 小时），首次请求后后续调用几乎无延迟
4. 故事共 22 篇，第 1 页返回前 20 篇，第 2 页返回最后 2 篇
