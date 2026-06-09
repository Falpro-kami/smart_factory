import json
import os
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
import pymysql
import uvicorn

from .agent_runtime import AgentRuntime
from .ontology_api import ENTITY_CONFIG, build_live_ontology_payload, build_topologies_payload, get_agv_tasks_payload, get_data_payload, get_entity_detail, get_schema_payload, list_entities, read_mysql_tables
from agent_core import load_project_env


load_project_env()
runtime = AgentRuntime(use_memory=True)
active_stream_tasks: dict[str, asyncio.Task[Any]] = {}
digital_twin_event_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


@dataclass
class ChatRequest:
    message: str
    request_id: str = ""
    thread_id: str = "demo-thread-1"
    session_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    stream: bool = True


def normalize_thread_id(payload: ChatRequest) -> str:
    if payload.session_id:
        return f"{payload.thread_id}:{payload.session_id}"
    return payload.thread_id


async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "agent-backend-adapter"})


async def index() -> PlainTextResponse:
    return PlainTextResponse(
        "Agent backend adapter is running.\n"
        "POST /api/chat to talk with the agent.\n"
        "GET /health for health checks.\n"
    )


async def chat(request: Request):
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    payload = parse_chat_request(data)
    if not payload.message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    thread_id = normalize_thread_id(payload)

    if payload.stream:
        return StreamingResponse(
            sse_event_stream(payload.message, thread_id, payload.request_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    reply = await runtime.invoke_reply(payload.message, thread_id=thread_id)
    return JSONResponse({"reply": reply, "thread_id": thread_id})


async def stop_chat(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    request_id = str(data.get("request_id", "")).strip()
    if not request_id:
        return JSONResponse({"error": "request_id is required"}, status_code=400)

    task = active_stream_tasks.pop(request_id, None)
    if task is None:
        return JSONResponse({"ok": True, "stopped": False})

    task.cancel()
    return JSONResponse({"ok": True, "stopped": True})


def mysql_connection(database: str):
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def safe_table_name(table_name: str) -> str:
    return f"`{table_name.replace('`', '``')}`"


def json_safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_safe_value(value) for key, value in row.items()}


def read_mysql_database(database: str, *, row_limit: int = 50) -> dict[str, Any]:
    load_project_env()
    with mysql_connection(database) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            table_key = f"Tables_in_{database}"
            table_names = [row.get(table_key) or next(iter(row.values())) for row in cursor.fetchall()]

            tables = []
            for table_name in table_names:
                cursor.execute(f"SELECT * FROM {safe_table_name(str(table_name))} LIMIT %s", (row_limit,))
                rows = [json_safe_row(row) for row in cursor.fetchall()]
                tables.append(
                    {
                        "name": table_name,
                        "columns": list(rows[0].keys()) if rows else [],
                        "rows": rows,
                    }
                )

    return {"database": database, "tables": tables}


async def digital_twin_devices() -> JSONResponse:
    try:
        config = ENTITY_CONFIG["device"]
        tables = read_mysql_tables(config["database"], config["include_keywords"], config["exclude_keywords"])
        tables = [table for table in tables if str(table.get("name") or "").lower() == "devices"]
        return JSONResponse({"ok": True, "database": config["database"], "tables": tables})
    except Exception as exc:
        return JSONResponse({"ok": False, "database": "device", "error": str(exc), "tables": []})


async def digital_twin_store() -> JSONResponse:
    try:
        config = ENTITY_CONFIG["material"]
        tables = read_mysql_tables(config["database"], (*config["include_keywords"], "product"), config["exclude_keywords"])
        return JSONResponse({"ok": True, "database": config["database"], "tables": tables})
    except Exception as exc:
        return JSONResponse({"ok": False, "database": "store", "error": str(exc), "tables": []})


async def publish_digital_twin_event(request: Request) -> JSONResponse:
    try:
        event = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    if not isinstance(event, dict):
        return JSONResponse({"error": "event object is required"}, status_code=400)

    payload = {
        "type": str(event.get("type") or "digital_twin_changed"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "data": event.get("data") if isinstance(event.get("data"), dict) else {},
    }
    for queue in tuple(digital_twin_event_subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass
    return JSONResponse({"ok": True, "subscriber_count": len(digital_twin_event_subscribers)})


async def digital_twin_events() -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
    digital_twin_event_subscribers.add(queue)

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            connected = json.dumps({"type": "connected", "created_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False)
            yield f"data: {connected}\n\n".encode("utf-8")
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25)
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"data: {data}\n\n".encode("utf-8")
                except asyncio.TimeoutError:
                    yield b": heartbeat\n\n"
        finally:
            digital_twin_event_subscribers.discard(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def parse_chat_request(data: dict[str, Any]) -> ChatRequest:
    return ChatRequest(
        request_id=str(data.get("request_id", "")).strip(),
        message=str(data.get("message", "")).strip(),
        thread_id=str(data.get("thread_id", "demo-thread-1")).strip() or "demo-thread-1",
        session_id=str(data.get("session_id", "")).strip(),
        history=list(data.get("history", []) or []),
        stream=bool(data.get("stream", True)),
    )


async def sse_event_stream(
    user_message: str,
    thread_id: str,
    request_id: str,
) -> AsyncIterator[bytes]:
    current_task = asyncio.current_task()
    if request_id and current_task is not None:
        active_stream_tasks[request_id] = current_task

    try:
        async for chunk in runtime.stream_reply(user_message, thread_id=thread_id):
            data = json.dumps({"content": chunk}, ensure_ascii=False)
            yield f"data: {data}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
    except asyncio.CancelledError:
        yield b"data: [DONE]\n\n"
        raise
    except Exception as exc:
        error = json.dumps({"error": str(exc)}, ensure_ascii=False)
        yield f"data: {error}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
    finally:
        if request_id:
            active_stream_tasks.pop(request_id, None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_project_env()
    await runtime.initialize()
    yield


app = FastAPI(
    debug=True,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("AGENT_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_api_route("/", index, methods=["GET"])
app.add_api_route("/health", health, methods=["GET"])
app.add_api_route("/api/chat", chat, methods=["POST"])
app.add_api_route("/api/chat/stop", stop_chat, methods=["POST"])
app.add_api_route("/api/digital-twin/devices", digital_twin_devices, methods=["GET"])
app.add_api_route("/api/digital-twin/store", digital_twin_store, methods=["GET"])
app.add_api_route("/api/digital-twin/events", digital_twin_events, methods=["GET"])
app.add_api_route("/api/digital-twin/events", publish_digital_twin_event, methods=["POST"])
app.add_api_route("/api/digital-twin/ontology/live", lambda: JSONResponse(build_live_ontology_payload()), methods=["GET"])
app.add_api_route("/api/digital-twin/topologies", lambda: JSONResponse(build_topologies_payload()), methods=["GET"])
app.add_api_route("/api/digital-twin/data", lambda: JSONResponse(get_data_payload()), methods=["GET"])
app.add_api_route("/api/digital-twin/agv/tasks", lambda: JSONResponse(get_agv_tasks_payload()), methods=["GET"])
app.add_api_route("/api/digital-twin/schema", lambda: JSONResponse(get_schema_payload()), methods=["GET"])
app.add_api_route("/api/digital-twin/entities/{entity_type}", lambda entity_type, limit=50, q=None: JSONResponse(list_entities(entity_type, int(limit), q)), methods=["GET"])
app.add_api_route("/api/digital-twin/entities/{entity_type}/{entity_id:path}", lambda entity_type, entity_id: JSONResponse(get_entity_detail(entity_type, entity_id)), methods=["GET"])


def main() -> None:
    load_project_env()
    uvicorn.run(
        "agent_backend_adapter.app:app",
        host=os.environ.get("AGENT_BACKEND_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGENT_BACKEND_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
