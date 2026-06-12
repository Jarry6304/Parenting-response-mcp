"""v3.2 B 件:retro 事後覆盤 mode——② parent_action 必填、③×1 回覆盤鏡頭、
converged=null、record.parent_action 落庫。"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, open_session, prereq_args
from parenting_response.db import MemoryDatabase
from parenting_response.schema import RESPONSE_CORES

RETRO_FACTS = "今天早上他不肯穿鞋,鬧了快二十分鐘"
RETRO_ACTION = "我當時很急,直接把他抱起來塞進車裡,他一路哭"


async def retro_session(client: Client, **prereq_over: object) -> str:
    sid = await open_session(client, mode="retro", facts=RETRO_FACTS, emotion="懊惱")
    args = prereq_args(sid, parent_action=RETRO_ACTION)
    args.update(prereq_over)
    await client.call_tool("prerequisites", args)
    return sid


async def test_retro_requires_parent_action(client: Client) -> None:
    """② retro 缺 parent_action → E_MISSING_AXIS(停在 ②,補齊可解鎖)。"""
    sid = await open_session(client, mode="retro", facts=RETRO_FACTS, emotion="懊惱")
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("prerequisites", prereq_args(sid))
    r = data_of(await client.call_tool("prerequisites",
                                       prereq_args(sid, parent_action=RETRO_ACTION)))
    assert r == {"next": "core_tags"}


async def test_live_mode_parent_action_optional(client: Client) -> None:
    """live 不強制 parent_action(回溯相容:② 形狀不變)。"""
    sid = await open_session(client)
    r = data_of(await client.call_tool("prerequisites", prereq_args(sid)))
    assert r == {"next": "core_tags"}


async def test_retro_round_returns_review_tags(client: Client, db: MemoryDatabase) -> None:
    """③ retro:六校覆盤鏡頭(視角/操作/示範)+ 一般 TAG 並回;converged=null。"""
    sid = await retro_session(client)
    r = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    review = r["review_tags"]
    assert [t["school"] for t in review] == list(RESPONSE_CORES)
    for t in review:
        assert set(t["tag"]) == {"視角", "操作", "示範"}
        assert all(t["tag"].values())
    assert r["converged"] is None  # 覆盤無乒乓,收斂訊號不適用
    assert len(r["response_tags"]) == 6  # 「下次怎麼回」仍供耦合
    assert r["next"] == "finalize"


async def test_retro_single_round_only(client: Client) -> None:
    """③ retro 限一輪:第二呼 E_INVALID_STATE(覆盤無乒乓)。"""
    sid = await retro_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})


async def test_retro_record_carries_parent_action(client: Client, db: MemoryDatabase) -> None:
    """④:record.parent_action = ② 所交之當時處理(覆盤的事實錨)。"""
    sid = await retro_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial",
        "draft": "下次我會先蹲下來說:你還想自己穿對嗎?我等你一分鐘。",
        "claimed_sources": ["pd"]}))
    rec = await db.get_record(r["record_id"])
    assert rec is not None
    assert rec["parent_action"] == RETRO_ACTION
    assert rec["status"] == "done"  # retro 是實際發生過的處理,非計畫


async def test_retro_parent_action_hits_g0(client: Client, db: MemoryDatabase) -> None:
    """② parent_action 進 G0 複檢:自陳失手 → 旗標+轉介,照常推進(訊號不停案)。"""
    sid = await open_session(client, mode="retro", facts=RETRO_FACTS, emotion="自責")
    r = data_of(await client.call_tool("prerequisites", prereq_args(
        sid, parent_action="我已經失手打了他一巴掌")))
    assert r["redflag"]["hit"] is True and "113" in r["referral"]
    assert r["safety_mode"] is True and r["next"] == "core_tags"
    s = db._sessions[sid]
    assert s["redflag_active"] is True and s["redflag_vector"] == "parent"
    evs = [e for e in await db.get_events(sid) if e["kind"] == "g0_shortcircuit"]
    assert len(evs) == 1 and evs[0]["payload"]["source"] == "②"
    assert evs[0]["payload"]["field"] == "parent_action"
    r3 = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    assert r3["safety_tags"]["vector"] == "parent"  # 覆盤也換安全約束集


async def test_retro_parent_action_warning_raises_severity(
    client: Client, db: MemoryDatabase
) -> None:
    """② parent_action 警訊級(罰跪)→ severity 高、不立旗、照常推進。"""
    sid = await open_session(client, mode="retro", facts=RETRO_FACTS, emotion="後悔")
    r = data_of(await client.call_tool("prerequisites", prereq_args(
        sid, parent_action="我叫他罰跪了半小時")))
    assert r == {"next": "core_tags"}
    s = db._sessions[sid]
    assert s["severity"] == "高" and s["redflag_active"] is False


async def test_retro_mode_accepted_at_entry(client: Client, db: MemoryDatabase) -> None:
    """① mode=retro 為合法受控詞;session.mode 落庫。"""
    r = data_of(await client.call_tool("constraints", constraints_args(mode="retro")))
    assert db._sessions[r["session_id"]]["mode"] == "retro"
