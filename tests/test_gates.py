"""G0 兩級 / 正向紀錄硬閘 / short 鏈 / ④ 後檢(spec v3.0 驗收 2・5・6・8)。"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, open_session, prereq_args, ready_session
from parenting_response.db import MemoryDatabase


async def test_g0_shortcircuit_locks_everything(client: Client, db: MemoryDatabase) -> None:
    """驗收2:G0 短路 → session=redflag_stopped 且後續鎖死;回轉介。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    assert r["redflag"]["hit"] is True
    assert "113" in r["referral"]
    assert r["card"] is None
    s = db._sessions[sid]
    assert s["status"] == "redflag_stopped" and s["stage"] == "redflag_stopped"
    assert s["severity"] == "高"
    blocked = [
        ("prerequisites", prereq_args(sid)),
        ("core_tags", {"session_id": sid}),
        ("finalize", {"session_id": sid, "outcome": "escalated_to_redflag", "draft": None}),
    ]
    for tool, args in blocked:
        with pytest.raises(ToolError, match="E_INVALID_STATE"):
            await client.call_tool(tool, args)


async def test_g0_warning_raises_severity_at_1(client: Client, db: MemoryDatabase) -> None:
    """警訊級不停案,severity 直升「高」。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他不收玩具,我吼了他說要把你丟掉", emotion="後悔")))
    sid = r["session_id"]
    assert "redflag" not in r
    assert db._sessions[sid]["severity"] == "高"
    assert db._sessions[sid]["status"] == "open"


async def test_g0_recheck_escalates_with_auto_record(client: Client, db: MemoryDatabase) -> None:
    """③ 每輪 reaction 複檢 G0:命中 → redflag_stopped + 自動 record。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發",
        "reaction_note": "他撞牆說想消失",
    }))
    assert r["redflag"]["hit"] is True and "113" in r["referral"]
    s = db._sessions[sid]
    assert s["status"] == "redflag_stopped" and s["stage"] == "redflag_stopped"
    rec = await db.get_record_by_session(sid)
    assert rec is not None and rec["outcome"] == "escalated_to_redflag"
    assert rec["draft"] is None
    with pytest.raises(ToolError, match="E_INVALID_STATE"):  # 終態吸收
        await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})


async def test_reaction_warning_raises_severity(client: Client, db: MemoryDatabase) -> None:
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持",
        "reaction_note": "我氣到拿出衣架嚇他",
    })
    assert db._sessions[sid]["severity"] == "高"
    assert db._sessions[sid]["status"] == "open"  # 警訊不停案


async def test_positive_log_ask_gate(client: Client) -> None:
    """驗收5:正向紀錄缺 script_decision → ask-gate,③④ 不解鎖。"""
    sid = await open_session(client, facts="他今天主動把碗收到水槽", emotion="開心")
    r = data_of(await client.call_tool("prerequisites", prereq_args(
        sid, problem_category="正向紀錄", emotion_intensity="低")))
    assert r["requires"] == "script_decision"
    assert "skip" in r["ask"] and "generate" in r["ask"]
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {"session_id": sid, "outcome": "resolved", "draft": None})


async def test_positive_skip_short_chain(client: Client, db: MemoryDatabase) -> None:
    """驗收6:skip → short ④(draft=NULL,不跑 pattern_check、不開 ③)。"""
    sid = await open_session(client, facts="他今天主動把碗收到水槽", emotion="開心")
    r = data_of(await client.call_tool("prerequisites", prereq_args(
        sid, problem_category="正向紀錄", emotion_intensity="低", script_decision="skip")))
    assert r == {"next": "finalize", "mode": "short"}
    with pytest.raises(ToolError, match="E_INVALID_STATE"):  # short 不開 ③
        await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):  # short 拒收 draft
        await client.call_tool("finalize", {"session_id": sid, "outcome": "resolved", "draft": "劇本"})
    r2 = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "outcome_note": "今天特別主動",
    }))
    rec = await db.get_record_by_session(sid)
    assert rec is not None and rec["record_id"] == r2["record_id"]
    assert rec["draft"] is None
    s = db._sessions[sid]
    assert s["is_positive_log"] is True and s["stage"] == "finalized"


async def test_positive_generate_goes_normal_chain(client: Client) -> None:
    """generate → 一般鏈(③ 解鎖)。"""
    sid = await open_session(client, facts="他今天主動把碗收到水槽", emotion="開心")
    r = data_of(await client.call_tool("prerequisites", prereq_args(
        sid, problem_category="正向紀錄", emotion_intensity="低", script_decision="generate")))
    assert r == {"next": "core_tags"}
    r2 = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    assert len(r2["response_tags"]) == 6


async def test_pattern_check_rejects_then_accepts(client: Client, db: MemoryDatabase) -> None:
    """驗收8:draft 含禁用詞 → 拒落庫回違規詞;session 仍 open 可重交。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial",
        "draft": "你就是不聽話,每次都這樣。",
    }))
    assert r["rejected"] is True
    assert any("你就是" in v for v in r["violations"])
    assert any("每次都" in v for v in r["violations"])
    assert db._sessions[sid]["status"] == "open"
    assert await db.get_record_by_session(sid) is None
    r2 = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial",
        "draft": "我看到你很生氣,我們先深呼吸,等一下一起想辦法。",
        "claimed_sources": ["gottman", "pd"],
    }))
    assert "record_id" in r2


async def test_normal_finalize_requires_draft(client: Client) -> None:
    """一般模式須交 draft(否則 host 可繞過後檢)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {"session_id": sid, "outcome": "resolved"})


async def test_finalize_vocab_guards(client: Client) -> None:
    """outcome / claimed_sources / maslow_need 受控詞表硬驗。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {"session_id": sid, "outcome": "great", "draft": "好。"})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {
            "session_id": sid, "outcome": "resolved", "draft": "好。",
            "claimed_sources": ["freud"]})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("finalize", {
            "session_id": sid, "outcome": "resolved", "draft": "好。",
            "maslow_need": ["自我實現"]})
