"""events 稽核證據鏈(defect-fixes #7/#8):G0 命中與 ④ 拒收一律落庫,含欄位與節錄。"""

from __future__ import annotations

from fastmcp import Client

from conftest import constraints_args, data_of, ready_session
from parenting_response.db import MemoryDatabase


async def test_g0_at_constraints_logs_evidence(client: Client, db: MemoryDatabase) -> None:
    """① 短路:回傳與 events 都帶欄位/詞組/節錄;轉介送達有持久化證明。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    assert r["redflag"]["field"] == "facts" and r["redflag"]["phrase"] == "不想活"
    evs = await db.get_events(sid)
    assert [e["kind"] for e in evs] == ["g0_shortcircuit"]
    p = evs[0]["payload"]
    assert p["source"] == "①" and p["field"] == "facts"
    assert "不想活" in p["excerpt"]
    assert p["referral_delivered"] is True


async def test_g0_recheck_event_carries_round_and_field(
    client: Client, db: MemoryDatabase
) -> None:
    """③ 複檢命中:event 帶 round_no 與欄位;record 的 outcome_note 也標欄位。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他撞牆說想消失"})
    evs = await db.get_events(sid)
    hit = [e for e in evs if e["kind"] == "g0_shortcircuit"]
    assert len(hit) == 1
    p = hit[0]["payload"]
    assert p["source"] == "③" and p["round_no"] == 1
    assert p["field"] == "reaction_note" and p["phrase"] == "想消失"
    rec = await db.get_record_by_session(sid)
    assert rec is not None and "reaction_note" in str(rec["outcome_note"])


async def test_finalize_g0_contact_traceable_without_stopping(
    client: Client, db: MemoryDatabase
) -> None:
    """④ 短路不拒收(#2 取捨)的紅旗接觸案:record 外觀正常,但 events 可列出。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial",
        "draft": "我看到你很生氣,我們先深呼吸。",
        "parent_self_note": "我快忍不住打他了,怕自己傷害孩子",
    }))
    assert "record_id" in r  # 案照收
    evs = [e for e in await db.get_events(sid) if e["kind"] == "g0_shortcircuit"]
    assert len(evs) == 1
    p = evs[0]["payload"]
    assert p["source"] == "④" and p["field"] == "parent_self_note"
    assert p["referral_delivered"] is True  # severity=高 的緣由可重建


async def test_finalize_rejection_logged_with_violations(
    client: Client, db: MemoryDatabase
) -> None:
    """④ 拒收稽核:violations 與嘗試之 outcome 落庫;重生通過後拒收軌跡仍在。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial", "draft": "你就是不聽話,每次都這樣。"}))
    assert r["rejected"] is True
    await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial",
        "draft": "我看到你很生氣,我們先深呼吸,等一下一起想辦法。"})
    rejected = [e for e in await db.get_events(sid) if e["kind"] == "finalize_rejected"]
    assert len(rejected) == 1
    p = rejected[0]["payload"]
    assert p["outcome"] == "partial" and p["redflag_hit"] is False
    assert any("你就是" in v for v in p["violations"])


async def test_warning_events_carry_field(client: Client, db: MemoryDatabase) -> None:
    """警訊級(①③④)同樣稽核:severity=高 不再是無緣由的孤值。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他不收玩具,我吼了他說要把你丟掉", emotion="後悔")))
    sid = r["session_id"]
    evs = await db.get_events(sid)
    assert [e["kind"] for e in evs] == ["g0_warning"]
    assert evs[0]["payload"]["hits"] == [{"field": "facts", "phrase": "把你丟掉"}]

    sid2 = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid2})
    await client.call_tool("finalize", {
        "session_id": sid2, "outcome": "partial", "draft": "我們一起想辦法。",
        "followup": "下次他再鬧我想罰跪處理"})
    evs2 = [e for e in await db.get_events(sid2) if e["kind"] == "g0_warning"]
    assert len(evs2) == 1
    assert evs2[0]["payload"]["source"] == "④"
    assert evs2[0]["payload"]["hits"] == [{"field": "followup", "phrase": "罰跪"}]
