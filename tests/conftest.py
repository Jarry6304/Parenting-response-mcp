"""驗收測試共用件:MemoryDatabase + in-memory MCP client(v3.0 零 LLM,無 FakeLLM)。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest
from fastmcp import Client

from parenting_response.db import MemoryDatabase
from parenting_response.orchestrator import Orchestrator
from parenting_response.server import build_server


def constraints_args(**over: Any) -> dict[str, Any]:
    """① 預設引數;canned 文本避開 G0 兩級詞表與輸出禁用詞。"""
    args: dict[str, Any] = {
        "facts": "妹妹拿走他的玩具車,他大叫並推了妹妹",
        "emotion": "生氣",
        "mode": "live",
    }
    args.update(over)
    return args


def prereq_args(session_id: str, **over: Any) -> dict[str, Any]:
    """② 預設引數(一般情境)。"""
    args: dict[str, Any] = {
        "session_id": session_id,
        "age_band": "4-6",
        "emotion_intensity": "中",
        "problem_category": "手足衝突",
    }
    args.update(over)
    return args


def data_of(result: Any) -> dict[str, Any]:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    return json.loads(result.content[0].text)


async def open_session(client: Client, **over: Any) -> str:
    """走完 ①,回 session_id(stage=constrained)。"""
    r = data_of(await client.call_tool("constraints", constraints_args(**over)))
    return r["session_id"]


async def ready_session(client: Client, **prereq_over: Any) -> str:
    """走完 ①②,回 session_id(stage=ready)。"""
    sid = await open_session(client)
    await client.call_tool("prerequisites", prereq_args(sid, **prereq_over))
    return sid


@pytest.fixture
def db() -> MemoryDatabase:
    return MemoryDatabase()


@pytest.fixture
def orch(db: MemoryDatabase) -> Orchestrator:
    return Orchestrator(db)


@pytest.fixture
async def client(orch: Orchestrator) -> AsyncIterator[Client]:
    async with Client(build_server(orch)) as c:
        yield c
