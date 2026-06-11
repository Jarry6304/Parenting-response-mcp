"""FSM 順序 / 吸收態 / 併發不變量 / 零 LLM(spec v3.0 驗收 1・4・10)。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, open_session, prereq_args, ready_session
from parenting_response.db import MemoryDatabase
from parenting_response.orchestrator import Orchestrator
from parenting_response.schema import PRError


async def test_constraints_missing_inputs_no_session(client: Client, db: MemoryDatabase) -> None:
    """① 缺 facts/emotion/mode → E_MISSING_AXIS,不建 session。"""
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("constraints", constraints_args(mode=None))
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("constraints", constraints_args(facts=None))
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("constraints", constraints_args(mode="觀察"))
    assert db._sessions == {}


async def test_unopened_session_blocks_234(client: Client) -> None:
    """驗收1:① 未過 → 呼叫 ②③④ 一律 E_INVALID_STATE。"""
    calls: list[tuple[str, dict[str, Any]]] = [
        ("prerequisites", {"session_id": "nope", "age_band": "4-6", "emotion_intensity": "中"}),
        ("core_tags", {"session_id": "nope"}),
        ("finalize", {"session_id": "nope", "outcome": "resolved", "draft": "好。"}),
    ]
    for tool, args in calls:
        with pytest.raises(ToolError, match="E_INVALID_STATE"):
            await client.call_tool(tool, args)


async def test_stage_constrained_blocks_34(client: Client) -> None:
    """過 ① 未過 ② → ③④ 仍鎖(stage 守衛)。"""
    sid = await open_session(client)
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {"session_id": sid, "outcome": "resolved", "draft": "好。"})


async def test_missing_axis_stays_at_2(client: Client) -> None:
    """驗收4:缺軸 → E_MISSING_AXIS 且停在 ②(非死局,補齊可解鎖)。"""
    sid = await open_session(client)
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("prerequisites", prereq_args(sid, age_band=None))
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("prerequisites", prereq_args(sid, age_band="0-2"))  # 範圍外
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("prerequisites", prereq_args(sid, emotion_intensity="超高"))
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid})  # 仍鎖在 ②
    r = data_of(await client.call_tool("prerequisites", prereq_args(sid)))
    assert r == {"next": "core_tags"}


async def test_problem_category_vocab(client: Client) -> None:
    sid = await open_session(client)
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("prerequisites", prereq_args(sid, problem_category="亂寫"))


async def test_round0_null_reaction_contract(client: Client) -> None:
    """round 0 = NULL;乒乓輪必須帶六類之一。"""
    sid = await ready_session(client)
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})
    await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid})  # round>0 缺 reaction
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "亂寫"})


async def test_round_no_increments_and_no_card(client: Client, db: MemoryDatabase) -> None:
    """rounds PK 遞增由 server 取號;v3 輪次無卡(card=NULL)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "否認堅持"})
    await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})
    rounds = await db.get_rounds(sid)
    assert [r["round_no"] for r in rounds] == [0, 1, 2]
    assert all(r["card"] is None for r in rounds)


async def test_terminal_finalized_absorbs(client: Client) -> None:
    """終態 finalized 為吸收態:②③④ 全擋。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved",
        "draft": "我們一起想辦法。", "claimed_sources": ["pd"],
    }))
    assert "record_id" in r
    blocked: list[tuple[str, dict[str, Any]]] = [
        ("prerequisites", prereq_args(sid)),
        ("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"}),
        ("finalize", {"session_id": sid, "outcome": "resolved", "draft": "好。"}),
    ]
    for tool, args in blocked:
        with pytest.raises(ToolError, match="E_INVALID_STATE"):
            await client.call_tool(tool, args)


async def test_finalize_requires_core_tags_round(client: Client) -> None:
    """#3:stage=ready 但 0 rounds → ④ 擋下(學派引導不可整段繞過);跑過 ③ 即放行。"""
    sid = await ready_session(client)
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {"session_id": sid, "outcome": "resolved", "draft": "好。"})
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想辦法。"}))
    assert "record_id" in r
    # short 模式無 rounds 仍可 finalize:test_gates.test_positive_skip_short_chain 覆蓋


async def test_invalid_link(client: Client) -> None:
    """linked_plan_id 須指向存在且 planned 的 record(承 v2.2 A2)。"""
    with pytest.raises(ToolError, match="E_INVALID_LINK"):
        await client.call_tool("constraints", constraints_args(linked_plan_id="ghost"))


async def test_concurrent_double_finalize_exactly_one(
    orch: Orchestrator, db: MemoryDatabase
) -> None:
    """DB 不變量:併發雙 finalize 恰一成功(條件式 WHERE status='open')。"""
    r = await orch.constraints(**constraints_args(), child_id="C1", linked_plan_id=None)
    sid = r["session_id"]
    await orch.prerequisites(session_id=sid, age_band="4-6", emotion_intensity="中",
                             problem_category=None, script_decision=None)
    await orch.core_tags(session_id=sid, child_reaction=None, reaction_note=None)

    async def fin() -> dict[str, Any] | PRError:
        try:
            return await orch.finalize(
                session_id=sid, outcome="resolved", draft="一起想辦法。",
                claimed_sources=None, maslow_need=None,
                outcome_note=None, parent_self_note=None, followup=None,
            )
        except PRError as exc:
            return exc

    r1, r2 = await asyncio.gather(fin(), fin())
    oks = [x for x in (r1, r2) if isinstance(x, dict)]
    errs = [x for x in (r1, r2) if isinstance(x, PRError)]
    assert len(oks) == 1 and len(errs) == 1 and errs[0].code == "E_INVALID_STATE"
    assert len(db._records) == 1


def test_zero_llm_assertable() -> None:
    """驗收10:server 全程零 LLM——無 llm 參數、無 llm 模組、無 llm 屬性。"""
    assert "llm" not in inspect.signature(Orchestrator.__init__).parameters
    assert importlib.util.find_spec("parenting_response.llm") is None
    orch = Orchestrator(MemoryDatabase())
    assert not hasattr(orch, "llm")
