# Agent Backend Adapter

这是一个独立的后端适配层，作用是把你当前的 agent 能力包装成前端可调用的 HTTP 接口。

它不会替换你现有的 `main.py`，而是单独提供：

- `GET /health`
- `POST /api/chat`
- `POST /api/chat/stop`
- 支持普通 JSON 返回
- 支持 `text/event-stream` 流式输出

## 目录

- `app.py`: FastAPI Web 服务入口
- `agent_runtime.py`: 兼容导出，实际引用共享核心模块
- `../agent_core.py`: `main.py` 和后端共同使用的 agent 核心实现

## 运行

在项目根目录执行：

```bash
python -m agent_backend_adapter.app
```

默认监听：

```text
http://127.0.0.1:8000
```

你的前端配置可以填：

```text
http://127.0.0.1:8000/api/chat
```

## 环境变量来源

这个适配层默认读取项目根目录的 `.env`。

推荐方式：

1. 参考根目录 `.env.example`
2. 在根目录创建自己的 `.env`
3. 通过 `.env` 统一提供模型、LangSmith 和后端监听配置

## 请求格式

```json
{
  "request_id": "optional-request-id",
  "message": "帮我看一下数据库状态",
  "thread_id": "demo-thread-1",
  "session_id": "frontend-session-id",
  "history": [],
  "stream": true
}
```

说明：

- `request_id`: 当前流式请求的唯一 ID，可用于停止生成
- `message`: 本次用户输入
- `thread_id`: 逻辑线程 ID
- `session_id`: 前端会话 ID，会与 `thread_id` 组合，避免多个窗口串话
- `history`: 目前预留，当前版本主要依赖后端线程记忆
- `stream`: `true` 返回 SSE，`false` 返回普通 JSON

## 响应格式

非流式：

```json
{
  "reply": "这里是 agent 回复",
  "thread_id": "demo-thread-1:frontend-session-id"
}
```

流式：

```text
data: {"content":"你"}

data: {"content":"好"}

data: [DONE]
```

停止生成：

```json
{
  "request_id": "optional-request-id"
}
```

## 可选环境变量

- `AGENT_MODEL`
- `LLM_API_KEY`
- `AGENT_BASE_URL`
- `AGENT_TEMPERATURE`
- `AGENT_SYSTEM_PROMPT`
- `AGENT_BACKEND_HOST`
- `AGENT_BACKEND_PORT`
- `AGENT_CORS_ORIGINS`

默认会读取项目根目录的 `.env`。

## 注意

这个适配层假设以下依赖在你的 Python 环境中已经可用：

- `langchain_openai`
- `langchain_mcp_adapters`
- `langgraph`
- `fastapi`
- `uvicorn`
- `python-dotenv`

如果启动时报依赖错误，需要先整理当前 Python 环境版本。
