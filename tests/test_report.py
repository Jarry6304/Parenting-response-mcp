"""v3.2 F 件(report 兩段式)+ H 件(語意紅線三層)驗收。

phase1 = 聚合+骨架+guardian(零 LLM 聚合);phase2 = 五道驗證 → 確定性組裝
→ 落庫 version+1。語意警示:tripwire 不拒收 → 稽核 → 下季回放。
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import data_of, open_session, prereq_args, ready_session
from parenting_response.db import MemoryDatabase

EVENT_SLOTS = {
    "what_worked": "先蹲下來反映他的生氣,等他點頭後才談輪流的規則,他願意聽。",
    "next_time": "想在他大叫前就先介入,給他和妹妹各自的玩具時段。",
    "quotes": "「你很生氣,因為車子被拿走了對不對?」他點頭之後就慢慢平靜了。",
}
QUARTER_SLOTS = {
    "positive_moments": "他主動把碗收到水槽,還幫妹妹蓋被子;睡前說今天玩得開心。",
    "growth": "我開始先講感受再講規則,衝突時間有變短,我自己也比較不吼了。",
    "next_quarter": "想練習在情緒上來前先深呼吸,並且多用有限選擇。",
}


async def finalized_session(client: Client, **over: object) -> str:
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {"session_id": sid, "child_reaction": "鬆動配合"})
    await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved",
        "draft": "我看到你很生氣,我們先深呼吸。", "claimed_sources": ["gottman"]})
    return sid


# ── event ───────────────────────────────────────────────────────


async def test_event_phase1_aggregates_and_skeleton(client: Client) -> None:
    """phase1:九維聚合 + 骨架(fixed 已組裝/slot 帶上限與 hint)+ guardian。"""
    sid = await finalized_session(client)
    r = data_of(await client.call_tool("report", {"scope": "event", "ref": sid}))
    agg = r["aggregates"]
    assert agg["rounds_count"] == 2 and agg["reactions"] == ["鬆動配合"]
    assert agg["outcome"] == "resolved" and agg["converged_final"] is True
    assert agg["redflag_hits"] == 0
    ids = [s["id"] for s in r["skeleton"]]
    assert ids == ["overview", "safety", "what_worked", "next_time", "quotes"]
    fixed = {s["id"]: s for s in r["skeleton"] if s["type"] == "fixed"}
    assert "模式:live" in fixed["overview"]["content"]
    assert fixed["safety"]["content"] == "本案無安全警訊。"
    slot = next(s for s in r["skeleton"] if s["id"] == "what_worked")
    assert slot["max_chars"] == 150 and slot["hint"]
    assert len(r["guardian"]) == 5  # H 第三層:生成前自查
    assert r["raw_quota"] == 2


async def test_event_phase2_deterministic_body(client: Client, db: MemoryDatabase) -> None:
    """phase2:組裝落庫 version=1;同 slots 重交 → version=2 且 body 逐位元相同
    (無時間戳,確定性可重現)。"""
    sid = await finalized_session(client)
    r1 = data_of(await client.call_tool("report", {
        "scope": "event", "ref": sid, "slots": EVENT_SLOTS}))
    assert r1["version"] == 1
    assert "## 這次有效的" in r1["body"] and EVENT_SLOTS["quotes"] in r1["body"]
    r2 = data_of(await client.call_tool("report", {
        "scope": "event", "ref": sid, "slots": EVENT_SLOTS}))
    assert r2["version"] == 2
    assert r2["body"] == r1["body"]  # 逐位元相同
    audits = [e for e in db._events if e["kind"] == "report_audit"]
    assert len(audits) == 2 and audits[0]["session_id"] is None
    assert audits[0]["payload"]["ref_key"] == sid


async def test_event_requires_finalized_case(client: Client) -> None:
    """④ 未完成(無 record)→ E_INVALID_STATE;ref 不存在亦同。"""
    sid = await ready_session(client)
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("report", {"scope": "event", "ref": sid})
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("report", {"scope": "event", "ref": "ghost"})


async def test_event_redflag_uses_template(client: Client) -> None:
    """紅旗案事件卡:safety 節 = 模板句(N 次高警訊,均已附轉介)。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他說他想死"})
    await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial", "draft": "我先陪著你。",
        "referral_ack": True})
    r = data_of(await client.call_tool("report", {"scope": "event", "ref": sid}))
    fixed = {s["id"]: s for s in r["skeleton"] if s["type"] == "fixed"}
    assert fixed["safety"]["content"] == "本案共 1 次高警訊,均已附轉介。"


# ── quarter ─────────────────────────────────────────────────────


async def test_quarter_phase1_aggregates_period(client: Client) -> None:
    """季聚合:期內案量/正向數/收斂數正確;首期 prev_audit 空。"""
    await finalized_session(client)
    sid2 = await open_session(client, facts="他今天主動把碗收到水槽", emotion="開心")
    await client.call_tool("prerequisites", prereq_args(
        sid2, problem_category="正向紀錄", emotion_intensity="低", script_decision="skip"))
    await client.call_tool("finalize", {"session_id": sid2, "outcome": "resolved"})
    r = data_of(await client.call_tool("report", {"scope": "quarter", "ref": "2026Q2"}))
    agg = r["aggregates"]
    assert agg["sessions_total"] == 2 and agg["records_total"] == 2
    assert agg["positive_log_count"] == 1
    assert agg["pingpong_count"] == 1 and agg["converged_count"] == 1
    assert r["prev_audit"] == {"ref": "2026Q1", "warnings": []}
    ids = [s["id"] for s in r["skeleton"]]
    assert ids[1] == "positive_moments"  # 季報第二節 = 正向時刻
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("report", {"scope": "quarter", "ref": "2026-Q2"})


async def test_quarter_slot_validations(client: Client) -> None:
    """槽缺/多 → E_MISSING_AXIS;超字數/負面詞 → rejected(不落庫)。"""
    await finalized_session(client)
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("report", {
            "scope": "quarter", "ref": "2026Q2",
            "slots": {"positive_moments": "好"}})
    r = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2",
        "slots": {**QUARTER_SLOTS, "growth": "長" * 301}}))
    assert r["rejected"] is True and r["violations"][0]["kind"] == "over_length"
    r2 = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2",
        "slots": {**QUARTER_SLOTS, "growth": "他還是一樣講不聽,但我有進步。"}}))
    assert r2["rejected"] is True
    assert any(x["kind"] == "forbidden_term" and x["term"] == "講不聽"
               for x in r2["violations"])


async def test_quarter_number_whitelist(client: Client) -> None:
    """數字白名單:slot 數字必 ∈ 聚合值 ∪ ref;自創統計拒收。"""
    await finalized_session(client)
    bad = {**QUARTER_SLOTS, "growth": "這季我們吵了 97 次,但都和好了。"}
    r = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": bad}))
    assert r["rejected"] is True
    assert any(x["kind"] == "number_not_in_aggregates" and x["term"] == "97"
               for x in r["violations"])
    ok = {**QUARTER_SLOTS, "growth": "這季共 1 件乒乓案收斂,我有跟著做。"}
    r2 = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": ok}))
    assert "report_id" in r2  # 聚合值(1)放行


async def test_quarter_raw_text_leak_rejected(client: Client) -> None:
    """防滲:匯總 slot 內含期內 facts 連續原文 → 拒收(隱私降階)。"""
    await finalized_session(client)
    leak = {**QUARTER_SLOTS,
            "positive_moments": "記得那次:妹妹拿走他的玩具車,他大叫並推了妹妹,後來和好。"}
    r = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": leak}))
    assert r["rejected"] is True
    assert any(x["kind"] == "raw_text_leak" for x in r["violations"])


async def test_quarter_safety_template_and_version(client: Client) -> None:
    """敏感節雙態:有紅旗 → 模板帶數;落庫 version 遞增。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他說他想死"})
    await client.call_tool("finalize", {
        "session_id": sid, "outcome": "partial", "draft": "我先陪著你。",
        "referral_ack": True})
    r = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": QUARTER_SLOTS}))
    assert "本季共 1 次高警訊,均已附轉介。" in r["body"]
    assert r["version"] == 1


# ── H 件:語意紅線三層 ──────────────────────────────────────────


async def test_semantic_tripwire_warns_but_archives(client: Client, db: MemoryDatabase) -> None:
    """第一層 tripwire:主詞+負面定性 → 警告不拒收;events 稽核。"""
    await finalized_session(client)
    slots = {**QUARTER_SLOTS, "growth": "他就是很懶,可是我有改變我的說法。"}
    r = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": slots}))
    assert "report_id" in r  # 不拒收
    assert r["semantic_warnings"][0]["term"] == "懶"
    evs = [e for e in db._events if e["kind"] == "report_semantic_warning"]
    assert len(evs) == 1 and evs[0]["payload"]["ref_key"] == "2026Q2"


async def test_semantic_negation_exempt(client: Client) -> None:
    """否定前綴豁免:「他不是故意的」不觸發。"""
    await finalized_session(client)
    slots = {**QUARTER_SLOTS, "growth": "我後來明白他不是故意的,我先改了我的開場白。"}
    r = data_of(await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": slots}))
    assert "report_id" in r and "semantic_warnings" not in r


async def test_semantic_replay_next_quarter(client: Client) -> None:
    """第二層回放:上季警示注入本季 phase1 的 prev_audit 固定節。"""
    await finalized_session(client)
    slots = {**QUARTER_SLOTS, "growth": "他就是很懶,可是我有改變我的說法。"}
    await client.call_tool("report", {"scope": "quarter", "ref": "2026Q2", "slots": slots})
    r = data_of(await client.call_tool("report", {"scope": "quarter", "ref": "2026Q3"}))
    assert r["prev_audit"]["ref"] == "2026Q2"
    assert r["prev_audit"]["warnings"][0]["term"] == "懶"
    fixed = {s["id"]: s for s in r["skeleton"] if s["type"] == "fixed"}
    assert "懶" in fixed["prev_audit"]["content"]  # 回放進固定節


# ── year ────────────────────────────────────────────────────────


async def test_year_missing_quarters_surface(client: Client) -> None:
    """年報:缺季照常出報,missing_quarters 與 recap 節標示。"""
    await finalized_session(client)
    await client.call_tool("report", {
        "scope": "quarter", "ref": "2026Q2", "slots": QUARTER_SLOTS})
    r = data_of(await client.call_tool("report", {"scope": "year", "ref": "2026"}))
    assert r["missing_quarters"] == ["2026Q1", "2026Q3", "2026Q4"]
    fixed = {s["id"]: s for s in r["skeleton"] if s["type"] == "fixed"}
    assert "2026Q2:已定稿 v1" in fixed["quarters_recap"]["content"]
    assert "2026Q1:缺(未產季報)" in fixed["quarters_recap"]["content"]
    year_slots = {
        "journey": "從每天的硬碰硬,到會先蹲下來聽他說;我們都長大了一點。",
        "letter": "謝謝你願意一直跟我說話。",
    }
    r2 = data_of(await client.call_tool("report", {
        "scope": "year", "ref": "2026", "slots": year_slots}))
    assert r2["version"] == 1 and "## 四季回顧" in r2["body"]
