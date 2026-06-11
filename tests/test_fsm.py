"""FSM 順序驗收:違序 = 明確錯誤、零核心呼叫;守衛先於一切 LLM;DB 不變量恰一成功。"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.exceptions import ToolError

from parenting_response.schema import PRError

from conftest import analyze_args, data_of


async def test_missing_axis_no_session_no_llm(client, fake_llm, db):
    args = analyze_args()
    del args["emotion"]
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("analyze_situation", args)
    assert fake_llm.count() == 0
    assert db._sessions == {}


async def test_age_band_0_2_rejected(client, fake_llm):
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("analyze_situation", analyze_args(age_band="0-2"))
    assert fake_llm.count() == 0


async def test_next_round_nonexistent_session(client, fake_llm):
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool(
            "next_round", {"session_id": "nope", "child_reaction": "鬆動配合"}
        )
    assert fake_llm.count() == 0


async def test_skip_analyze_direct_next_round_blocked(client, fake_llm):
    # 顯式防回歸:跳過 analyze 直接 next_round 必錯(等同 session 不存在)。
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool(
            "next_round", {"session_id": "never-analyzed", "child_reaction": "否認堅持"}
        )
    assert fake_llm.count() == 0


async def test_finalize_nonexistent_session(client, fake_llm):
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize_record", {"session_id": "nope", "outcome": "resolved"})
    assert fake_llm.count() == 0


async def test_invalid_reaction(client, fake_llm):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    before = fake_llm.count()
    with pytest.raises(ToolError, match="E_INVALID_REACTION"):
        await client.call_tool(
            "next_round", {"session_id": res["session_id"], "child_reaction": "亂講一通"}
        )
    assert fake_llm.count() == before


async def test_invalid_link(client, fake_llm):
    with pytest.raises(ToolError, match="E_INVALID_LINK"):
        await client.call_tool(
            "analyze_situation", analyze_args(linked_plan_id="不存在的record")
        )
    assert fake_llm.count() == 0


async def test_terminal_finalized_absorbs(client, fake_llm):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    sid = res["session_id"]
    await client.call_tool("finalize_record", {"session_id": sid, "outcome": "resolved"})
    before = fake_llm.count()
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("next_round", {"session_id": sid, "child_reaction": "鬆動配合"})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize_record", {"session_id": sid, "outcome": "partial"})
    assert fake_llm.count() == before  # 終態上的呼叫:零 LLM


async def test_terminal_redflag_absorbs(client, fake_llm):
    res = data_of(
        await client.call_tool(
            "analyze_situation", analyze_args(facts="他在房間大喊說他想死,不想上學")
        )
    )
    sid = res["session_id"]
    before = fake_llm.count()
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("next_round", {"session_id": sid, "child_reaction": "鬆動配合"})
    assert fake_llm.count() == before


async def test_concurrent_double_finalize_exactly_one(orch, db):
    res = await orch.analyze(analyze_args())
    sid = res.session_id
    results = await asyncio.gather(
        orch.finalize(sid, "resolved"),
        orch.finalize(sid, "partial"),
        return_exceptions=True,
    )
    oks = [r for r in results if isinstance(r, dict)]
    errs = [r for r in results if isinstance(r, PRError)]
    assert len(oks) == 1 and len(errs) == 1
    assert "E_INVALID_STATE" in str(errs[0])
    assert len(db._records) == 1  # records 恰一列
