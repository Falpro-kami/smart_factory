import json
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend


ROOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT_DIR.parent
SKILLS_DIR = ROOT_DIR / "skills"
SKILLS_SOURCE = "/skills"


def load_project_env() -> None:
    """Load the repository root .env as the default config source."""
    load_dotenv(ROOT_DIR / ".env", override=False)


load_project_env()


def get_llm_api_key() -> str | None:
    """Return the provider-agnostic LLM API key."""
    return os.environ.get("LLM_API_KEY")


def stringify_tool_result(result: Any) -> str:
    """Normalize MCP tool outputs into plain text for the agent/LLM."""
    if result is None:
        return ""

    if isinstance(result, str):
        return result

    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "text") and getattr(item, "text"):
                parts.append(str(getattr(item, "text")))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return "\n".join(part for part in parts if part).strip()

    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, default=str)

    if hasattr(result, "text") and getattr(result, "text"):
        return str(getattr(result, "text"))

    return str(result)


def wrap_mcp_tool(tool: Any) -> StructuredTool:
    async def _arun(**kwargs: Any) -> str:
        result = await tool.ainvoke(kwargs)
        return stringify_tool_result(result)

    return StructuredTool.from_function(
        coroutine=_arun,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def extract_text_token(token: Any, metadata: dict[str, Any] | None) -> str:
    """Extract only assistant text chunks and skip tool-call chunks."""
    metadata = metadata or {}
    if metadata.get("langgraph_node") != "model":
        return ""

    if getattr(token, "content", None):
        return str(token.content)

    text_parts: list[str] = []
    for block in getattr(token, "content_blocks", []) or []:
        if block.get("type") in ("tool_call", "tool_call_chunk"):
            return ""
        if block.get("type") == "text" and block.get("text"):
            text_parts.append(str(block["text"]))
    return "".join(text_parts)


def build_pythonpath() -> str:
    paths = [
        str(PROJECT_ROOT),
        str(ROOT_DIR),
        str(ROOT_DIR / "mcp-neo4j-cypher" / "src"),
        str(ROOT_DIR / "mysql_mcp_server_pro" / "src"),
        str(ROOT_DIR / "split_mcp_server" / "src"),
    ]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    return os.pathsep.join(paths)


def get_local_langchain_tools() -> list[StructuredTool]:
    """Load local non-MCP tools exposed by the repository."""
    return []


class AgentRuntime:
    def __init__(self, *, use_memory: bool = True) -> None:
        self._use_memory = use_memory
        self._initialized = False
        self._agent = None
        self._client = None

    async def initialize(self) -> None:
        if self._initialized:
            return

        load_project_env()

        if os.environ.get("LANGSMITH_TRACING") is None:
            os.environ["LANGSMITH_TRACING"] = "false"
        if os.environ.get("LANGSMITH_PROJECT") is None:
            os.environ["LANGSMITH_PROJECT"] = "simens-agent-demo"

        model = ChatOpenAI(
            model=os.environ.get("AGENT_MODEL", "deepseek-chat"),
            temperature=float(os.environ.get("AGENT_TEMPERATURE", "0.2")),
            base_url=os.environ.get("AGENT_BASE_URL", "https://api.deepseek.com"),
            api_key=get_llm_api_key(),
            streaming=True,
        )

        server_env = dict(os.environ)
        server_env["PYTHONPATH"] = build_pythonpath()

        self._client = MultiServerMCPClient(
            {
                "neo4j_local": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "mcp_neo4j_cypher"],
                    "env": server_env,
                },
                "mysql_local": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "mysql_mcp_server_pro.server"],
                    "env": server_env,
                },
                "split_local": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "split_mcp_server"],
                    "env": server_env,
                },
            }
        )

        raw_tools = await self._client.get_tools()
        tools = [wrap_mcp_tool(tool) for tool in raw_tools]
        tools.extend(get_local_langchain_tools())

        create_kwargs = {
            "model": model,
            "tools": tools,
            "middleware": [
                SummarizationMiddleware(
                    model=model,
                    trigger=("tokens", 100000),
                    keep=("messages", 20),
                )
            ],
            "system_prompt": os.environ.get("AGENT_SYSTEM_PROMPT", "你是一个智能助手"),
            "backend": FilesystemBackend(root_dir=str(ROOT_DIR), virtual_mode=True),
            "skills": [SKILLS_SOURCE]
        }

        if self._use_memory:
            create_kwargs["checkpointer"] = InMemorySaver()

        self._agent = create_deep_agent(**create_kwargs)
        self._initialized = True

    async def stream_reply(
        self,
        user_message: str,
        *,
        thread_id: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        await self.initialize()

        messages: list[dict[str, str]] = []
        if not self._use_memory:
            for item in history or []:
                role = str(item.get("role", "")).strip()
                content = str(item.get("content", "")).strip()
                if role not in {"user", "assistant", "system"} or not content:
                    continue
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        config = {"configurable": {"thread_id": thread_id}} if self._use_memory and thread_id else None
        async for token, metadata in self._agent.astream(
            {"messages": messages},
            stream_mode="messages",
            config=config,
        ):
            text = extract_text_token(token, metadata)
            if text:
                yield text

    async def invoke_reply(
        self,
        user_message: str,
        *,
        thread_id: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.stream_reply(user_message, thread_id=thread_id, history=history):
            chunks.append(chunk)
        return "".join(chunks).strip()
