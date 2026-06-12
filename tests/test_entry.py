"""v3.0 C 件:入口分流 ask-gate + resume(+ D 件收束 ask-gate / round 軟上限)。"""

from __future__ import annotations

import datetime as _dt

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, open_session, prereq_args, ready_session
from parenting_response.db import MemoryDatabase

# ── C 件:入口 ask-gate ──────────────────────────────────────────


async def test_entry_gate_lists_options_and_opens(client: Client, db: MemoryDatabase) -> None:
    """mode 缺 → ask-gate{options, open_sessions}(不建案、不報錯);facts 截斷 30 字。"""
    sid = await ready_session(client)
    n_before = len(db._sessions)
    r = data_of(await client.call_tool("constraints", {}))
    assert r["requires"] == "mode"
    assert r["options"] == ["live", "retro", "resume"]
    assert len(db._sessions) == n_before  # 不建案
    opens = r["open_sessions"]
    assert [o["session_id"] for o in opens] == [sid]
    assert opens[0]["stage"] == "ready" and opens[0]["mode"] == "live"
    assert len(opens[0]["facts"]) <= 30
    assert opens[0]["last_active"]  # ISO 時間戳(host 呈現「上次聊到」)


async def test_entry_gate_empty_when_no_opens(client: Client) -> None:
    r = data_of(await client.call_tool("constraints", {}))
    assert r["requires"] == "mode" and r["open_sessions"] == []


async def test_entry_gate_isolates_by_child(client: Client) -> None:
    """open 案清單按 child_id 隔離(別的孩子的案不混入)。"""
    await open_session(client, child_id="C2")
    r = data_of(await client.call_tool("constraints", {"child_id": "C1"}))
    assert r["open_sessions"] == []


# ── C 件:resume ────────────────────────────────────────────────


async def test_resume_rebuilds_context_and_touches(client: Client, db: MemoryDatabase) -> None:
    """resume:回三軸+輪摘要(受控詞序列,無 reaction_note)、不動 stage、續期。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "大哭摔積木"})
    before = db._sessions[sid]["updated_at"]
    r = data_of(await client.call_tool("constraints", {"mode": "resume", "session_id": sid}))
    assert r["resumed"] is True and r["session_id"] == sid
    assert r["stage"] == "ready" and r["next"] == "core_tags"
    assert r["axes"]["age_band"] == "4-6"
    assert r["rounds_summary"] == {"count": 2, "reactions": ["情緒爆發"]}
    assert "reaction_note" not in str(r["rounds_summary"])  # 自由文本不回放
    assert db._sessions[sid]["updated_at"] >= before  # touch 續期
    assert db._sessions[sid]["stage"] == "ready"  # 不動 FSM
    r2 = data_of(await client.call_tool("core_tags", {  # 接著走原 stage
        "session_id": sid, "child_reaction": "鬆動配合"}))
    assert "response_tags" in r2


async def test_resume_requires_open_session(client: Client) -> None:
    """resume 不存在 / 已終態 → E_INVALID_STATE;缺 session_id → E_MISSING_AXIS。"""
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("constraints", {"mode": "resume"})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("constraints", {"mode": "resume", "session_id": "ghost"})
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想辦法。"})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("constraints", {"mode": "resume", "session_id": sid})


async def test_resume_extends_ttl(client: Client, db: MemoryDatabase) -> None:
    """resume 是活動:接近過期的案 resume 後續期,後續清掃不棄;
    真正逾期(>30 天無活動)的案在 resume 時已被懶清掃 → 不可續。"""
    sid = await open_session(client)
    db._sessions[sid]["created_at"] -= _dt.timedelta(days=31)
    db._sessions[sid]["updated_at"] -= _dt.timedelta(days=29)  # 接近但未過期
    await client.call_tool("constraints", {"mode": "resume", "session_id": sid})  # touch
    await open_session(client)  # 觸發清掃:錨已更新,不棄
    assert db._sessions[sid]["status"] == "open"

    stale = await open_session(client)
    db._sessions[stale]["created_at"] -= _dt.timedelta(days=31)
    db._sessions[stale]["updated_at"] -= _dt.timedelta(days=31)  # 真逾期
    with pytest.raises(ToolError, match="E_INVALID_STATE"):  # 懶清掃先行,棄案不可續
        await client.call_tool("constraints", {"mode": "resume", "session_id": stale})
    assert db._sessions[stale]["status"] == "expired"


async def test_resume_surfaces_safety_mode(client: Client) -> None:
    """resume 紅旗在案 → 回 safety_mode=true(接手即知此案在安全軌)。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    r2 = data_of(await client.call_tool("constraints", {"mode": "resume", "session_id": sid}))
    assert r2["safety_mode"] is True and r2["next"] == "prerequisites"


# ── D 件:收束 ask-gate + round 軟上限 ───────────────────────────


async def test_convergence_ask_gate_then_continue(client: Client, db: MemoryDatabase) -> None:
    """上輪 converged=true → 本輪 ③ 回收束 ask-gate(不記輪);
    帶 parent_decision=continue → 照常記輪。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r1 = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "鬆動配合"}))
    assert r1["converged"] is True
    r2 = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持"}))
    assert r2["requires"] == "parent_decision"
    assert r2["options"] == ["continue", "finalize"]
    assert len(await db.get_rounds(sid)) == 2  # ask-gate 不落輪
    r3 = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持", "parent_decision": "continue"}))
    assert "response_tags" in r3
    assert len(await db.get_rounds(sid)) == 3


async def test_convergence_gate_then_finalize_path(client: Client) -> None:
    """收束 ask-gate 後家長選收尾:直接 ④ 正常落庫(gate 不影響 finalize)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想了辦法。"}))
    assert "record_id" in r


async def test_convergence_gate_live_only(client: Client) -> None:
    """rehearsal 不觸發收束 gate(無真實乒乓);parent_decision 亂寫 → E_INVALID_STATE。"""
    sid = await open_session(client, mode="rehearsal")
    await client.call_tool("prerequisites", prereq_args(sid))
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持"}))  # 無需 decision
    assert "response_tags" in r
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {
            "session_id": sid, "child_reaction": "否認堅持", "parent_decision": "亂寫"})


async def test_round_soft_cap_suggests_pause(client: Client) -> None:
    """第 5 輪起回傳附 suggest_pause=true(軟上限:建議不強制,FSM 照走)。"""
    sid = await ready_session(client)
    r = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    for i in range(1, 7):
        args: dict[str, object] = {"session_id": sid, "child_reaction": "否認堅持"}
        r = data_of(await client.call_tool("core_tags", args))
        if i < 5:
            assert "suggest_pause" not in r, i
        else:
            assert r["suggest_pause"] is True, i  # 第 5 輪起建議暫停
    assert "response_tags" in r  # 不擋:TAG 照回
