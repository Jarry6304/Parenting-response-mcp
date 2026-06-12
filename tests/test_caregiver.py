"""v3.0 K 件:多照顧者——caregiver 由已驗 sub 映射(不收輸入)、local 預設爸、
未映射 fail-fast、報告自照計數、比較句 tripwire。"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, prereq_args, ready_session
from parenting_response.db import MemoryDatabase
from parenting_response.orchestrator import Orchestrator
from parenting_response.server import build_server
from parenting_response.wordlists import semantic_warnings


async def test_local_mode_defaults_dad(client: Client, db: MemoryDatabase) -> None:
    """local(無 sub)→ caregiver 預設「爸」。"""
    r = data_of(await client.call_tool("constraints", constraints_args()))
    assert db._sessions[r["session_id"]]["caregiver"] == "爸"


async def test_sub_maps_to_caregiver(
    db: MemoryDatabase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """authkit:sub 經 CAREGIVER_MAP 映射;媽的 token 建的案記「媽」。"""
    monkeypatch.setattr("parenting_response.orchestrator.current_sub", lambda: "user_mom")
    orch = Orchestrator(db, caregiver_map={"user_mom": "媽", "user_dad": "爸"})
    async with Client(build_server(orch)) as c:
        r = data_of(await c.call_tool("constraints", constraints_args()))
    assert db._sessions[r["session_id"]]["caregiver"] == "媽"


async def test_unmapped_sub_fails_fast(
    db: MemoryDatabase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sub 不在 map → E_INVALID_STATE + events caregiver_unmapped(不建案)。"""
    monkeypatch.setattr("parenting_response.orchestrator.current_sub", lambda: "user_stranger")
    orch = Orchestrator(db, caregiver_map={"user_dad": "爸"})
    async with Client(build_server(orch)) as c:
        with pytest.raises(ToolError, match="E_INVALID_STATE"):
            await c.call_tool("constraints", constraints_args())
    assert db._sessions == {}
    evs = [e for e in db._events if e["kind"] == "caregiver_unmapped"]
    assert len(evs) == 1 and evs[0]["payload"]["sub"] == "user_stranger"


async def test_caregiver_not_an_input_parameter(client: Client, db: MemoryDatabase) -> None:
    """① 不收 caregiver 參數——傳了直接被拒(身分只來自 token,host/家長不可代填)。"""
    with pytest.raises(ToolError):
        await client.call_tool("constraints", {**constraints_args(), "caregiver": "媽"})
    assert db._sessions == {}  # 不建案


async def test_report_aggregates_caregiver_dist(
    db: MemoryDatabase, monkeypatch: pytest.MonkeyPatch, client: Client,
) -> None:
    """季聚合 caregiver_dist:各自照數(中性計數,stats 節呈現)。"""
    sid = await ready_session(client)  # 爸(local)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想辦法。"})
    monkeypatch.setattr("parenting_response.orchestrator.current_sub", lambda: "user_mom")
    orch2 = Orchestrator(db, caregiver_map={"user_mom": "媽"})
    async with Client(build_server(orch2)) as c2:
        await c2.call_tool("constraints", constraints_args())
        r = data_of(await c2.call_tool("report", {"scope": "quarter", "ref": "2026Q2"}))
    assert r["aggregates"]["caregiver_dist"] == {"爸": 1, "媽": 1}
    stats = next(s for s in r["skeleton"] if s["id"] == "stats")
    assert "照顧紀錄" in stats["content"]


def test_caregiver_compare_tripwire() -> None:
    """比較句 tripwire:「爸爸比媽媽會帶」警示;一般並述不警示。"""
    hits = semantic_warnings("爸爸比媽媽會帶小孩,真的。")
    assert len(hits) == 1 and "比" in hits[0]["term"]
    assert semantic_warnings("這季爸爸帶了 1 次,媽媽也常陪他。") == []
    hits2 = semantic_warnings("媽媽不如爸爸有耐心。")
    assert len(hits2) == 1
