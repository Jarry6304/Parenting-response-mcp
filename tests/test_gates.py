"""G0 兩級 / 正向紀錄硬閘 / short 鏈 / ④ 後檢(spec v3.0 驗收 2・5・6・8)。"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, open_session, prereq_args, ready_session
from parenting_response.db import MemoryDatabase


async def test_g0_shortcircuit_signals_not_stops(client: Client, db: MemoryDatabase) -> None:
    """v3.2 A 件:① G0 短路 → 訊號不停案——照常建案,旗標+severity=高,
    回傳含 referral 與 safety_mode 標記,FSM 照常推進(② 可走)。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    assert r["redflag"]["hit"] is True
    assert "113" in r["referral"]
    assert r["safety_mode"] is True
    assert r["constraints"]["red_lines"] and r["inquiry_probes"]  # ① 本職照回,不斷供
    s = db._sessions[sid]
    assert s["status"] == "open" and s["stage"] == "constrained"
    assert s["redflag_active"] is True and s["redflag_vector"] == "child"
    assert s["severity"] == "高"
    r2 = data_of(await client.call_tool("prerequisites", prereq_args(sid)))  # FSM 不鎖
    assert r2 == {"next": "core_tags"}


async def test_g0_warning_raises_severity_at_1(client: Client, db: MemoryDatabase) -> None:
    """警訊級不停案,severity 直升「高」。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他不收玩具,我吼了他說要把你丟掉", emotion="後悔")))
    sid = r["session_id"]
    assert "redflag" not in r
    assert db._sessions[sid]["severity"] == "高"
    assert db._sessions[sid]["status"] == "open"


async def test_g0_recheck_flags_and_switches_to_safety(
    client: Client, db: MemoryDatabase
) -> None:
    """v3.2 A 件:③ 複檢命中 → 訊號(旗標+severity),照常記輪;該輪起回傳換
    安全約束集(無一般管教 TAG),不自動收案、不產 record。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發",
        "reaction_note": "他撞牆說想消失",
    }))
    assert r["redflag"]["hit"] is True and "113" in r["referral"]
    assert r["safety_mode"] is True
    assert "response_tags" not in r  # 一般管教 TAG 斷供,換軌安全約束集
    assert r["safety_tags"]["vector"] == "child"
    assert r["safety_tags"]["base"]["source"]
    assert r["dev_stages"]["erikson"]  # 發展段位與風險無關,照回
    s = db._sessions[sid]
    assert s["status"] == "open" and s["redflag_active"] is True
    assert s["severity"] == "高"
    assert await db.get_record_by_session(sid) is None  # 不再自動收案
    assert len(await db.get_rounds(sid)) == 2  # 命中輪照常記
    r2 = data_of(await client.call_tool("core_tags", {  # 後續輪維持 safety 換軌
        "session_id": sid, "child_reaction": "鬆動配合"}))
    assert r2["safety_mode"] is True and "response_tags" not in r2
    assert r2["converged"] is False  # safety_mode 下不出收斂訊號


async def test_reaction_warning_raises_severity(client: Client, db: MemoryDatabase) -> None:
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持",
        "reaction_note": "我氣到拿出衣架嚇他",
    })
    assert db._sessions[sid]["severity"] == "高"
    assert db._sessions[sid]["status"] == "open"  # 警訊不停案


async def test_high_tension_round_requires_note(client: Client, db: MemoryDatabase) -> None:
    """#4:高張力輪缺 reaction_note → ask-gate(不 insert round);補 note 含短路詞
    → 旗標訊號 + 安全約束集(v3.2:不停案)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發"}))
    assert r["requires"] == "reaction_note"
    assert len(await db.get_rounds(sid)) == 1  # ask-gate 不落輪
    r2 = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他說他不想活了"}))
    assert r2["redflag"]["hit"] is True and r2["safety_mode"] is True
    s = db._sessions[sid]
    assert s["status"] == "open" and s["redflag_active"] is True

    sid2 = await ready_session(client)  # 退縮害怕同屬高張力
    await client.call_tool("core_tags", {"session_id": sid2})
    r3 = data_of(await client.call_tool("core_tags", {
        "session_id": sid2, "child_reaction": "退縮害怕"}))
    assert r3["requires"] == "reaction_note"


async def test_non_high_tension_note_optional(client: Client) -> None:
    """#4:非高張力輪不強制轉述(無 note 照常回 TAG;已知軟點,文件如實陳述)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持"}))
    assert len(r["response_tags"]) == 6


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


async def test_finalize_selfnote_shortcircuit_referral(client: Client, db: MemoryDatabase) -> None:
    """#2+v3.2:④ parent_self_note 含短路詞 → 訊號已落;無 referral_ack 先擋
    (E_MISSING_AXIS,轉介必達的 code 強制),補 ack 後案照收且 record.redflag=true。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    args = {
        "session_id": sid, "outcome": "partial",
        "draft": "我看到你很生氣,我們先深呼吸。",
        "parent_self_note": "我快忍不住打他了,怕自己傷害孩子",
    }
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("finalize", args)
    s = db._sessions[sid]
    assert s["severity"] == "高" and s["redflag_active"] is True  # 擋下但訊號不丟
    assert s["redflag_vector"] == "parent"
    r = data_of(await client.call_tool("finalize", {**args, "referral_ack": True}))
    assert "record_id" in r
    assert r["redflag"]["hit"] is True and "113" in r["referral"]
    assert db._sessions[sid]["status"] == "finalized"  # 不拒收
    rec = await db.get_record_by_session(sid)
    assert rec is not None and rec["redflag"] is True


async def test_short_finalize_g0_not_skipped(client: Client, db: MemoryDatabase) -> None:
    """#2+v3.2:short 只略過 pattern_check,不略過 G0——命中同樣要 referral_ack。"""
    sid = await open_session(client, facts="他今天主動把碗收到水槽", emotion="開心")
    await client.call_tool("prerequisites", prereq_args(
        sid, problem_category="正向紀錄", emotion_intensity="低", script_decision="skip"))
    args = {"session_id": sid, "outcome": "resolved",
            "outcome_note": "他說最近想消失,我很擔心"}
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("finalize", args)
    r = data_of(await client.call_tool("finalize", {**args, "referral_ack": True}))
    assert "record_id" in r
    assert r["redflag"]["hit"] is True and "113" in r["referral"]
    assert db._sessions[sid]["severity"] == "高"
    rec = await db.get_record_by_session(sid)
    assert rec is not None and rec["redflag"] is True


async def test_finalize_followup_warning(client: Client, db: MemoryDatabase) -> None:
    """#2:followup 含警訊詞 → severity 高 + 回傳 warnings。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial", "draft": "我們一起想辦法。",
        "followup": "下次他再鬧我想罰跪處理",
    }))
    assert "record_id" in r and "redflag" not in r
    assert any("罰跪" in w for w in r["warnings"])
    assert db._sessions[sid]["severity"] == "高"


async def test_finalize_clean_shape_unchanged(client: Client) -> None:
    """#2:全文本乾淨 → 回傳形狀固定 {record_id, next=archive}(v3.2 收尾鏈)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想辦法。"}))
    assert set(r) == {"record_id", "next"} and r["next"] == "archive"


async def test_pattern_reject_keeps_g0_signal(client: Client, db: MemoryDatabase) -> None:
    """#2+v3.2:G0 命中 + draft 踩 pattern——referral_ack 閘先行(安全優先),
    補 ack 後 pattern 拒收照常,G0 訊號全程不丟。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    args = {
        "session_id": sid, "outcome": "partial",
        "draft": "你就是講不聽。",
        "parent_self_note": "我已經失手打過他一次",
    }
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):  # 先要求轉介送達
        await client.call_tool("finalize", args)
    assert db._sessions[sid]["severity"] == "高"  # 擋下但訊號已落
    r = data_of(await client.call_tool("finalize", {**args, "referral_ack": True}))
    assert r["rejected"] is True and "113" in r["referral"]
    s = db._sessions[sid]
    assert s["status"] == "open"  # 拒收不落庫,但不無聲


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
