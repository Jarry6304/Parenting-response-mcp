"""v3.2 A 件(G0 閘→訊號)+ G 件(safety 分齡內容)驗收。

A:輸入永不停案(redflag_stopped 不再產生)、訊號單調、promotion 排除;
G:3 風險向 × 4 年齡 delta 組卡、7 塊 fail-fast、source 錨定。
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import parenting_response.cores as cores
from conftest import constraints_args, data_of, prereq_args, ready_session
from parenting_response.cores import safety_cards
from parenting_response.db import MemoryDatabase
from parenting_response.schema import AGE_BANDS


async def test_no_redflag_stopped_terminal_anywhere(client: Client, db: MemoryDatabase) -> None:
    """A 核心:①③④ 全入口短路命中,session 一律照常推進——
    v3.2 起無任何路徑產生 redflag_stopped 終態。"""
    # ① 命中
    r1 = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    # ③ 命中
    sid2 = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid2})
    await client.call_tool("core_tags", {
        "session_id": sid2, "child_reaction": "情緒爆發", "reaction_note": "他撞牆說想消失"})
    # ④ 命中(收案)
    await client.call_tool("finalize", {
        "session_id": sid2, "outcome": "partial", "draft": "我先陪著你。",
        "referral_ack": True})
    statuses = {s["status"] for s in db._sessions.values()}
    assert "redflag_stopped" not in statuses
    assert db._sessions[r1["session_id"]]["status"] == "open"
    assert db._sessions[sid2]["status"] == "finalized"


async def test_vector_parent_no_age_delta(client: Client, db: MemoryDatabase) -> None:
    """G:家長失控組 → vector=parent;safety 卡 = base.parent,不疊年齡 delta
    (內容對象是家長,語域調整無著力點)。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他一直鬧,我快忍不住打下去了", emotion="自責")))
    sid = r["session_id"]
    assert db._sessions[sid]["redflag_vector"] == "parent"
    await client.call_tool("prerequisites", prereq_args(sid))
    r3 = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    assert r3["safety_mode"] is True
    card = r3["safety_tags"]
    assert card["vector"] == "parent"
    assert "1925" in str(card["base"])  # 安心專線(家長端轉介)
    assert "delta" not in card


async def test_vector_third_from_recheck(client: Client, db: MemoryDatabase) -> None:
    """G:③ 複檢命中第三方組(虐待跡象)→ vector=third,卡換 base.third。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "退縮害怕",
        "reaction_note": "他說安親班老師把他打到瘀青"}))
    assert db._sessions[sid]["redflag_vector"] == "third"
    card = r["safety_tags"]
    assert card["vector"] == "third"
    assert "113" in str(card["base"]) and "53" in str(card["base"])  # 通報義務錨定
    assert "delta" not in card


async def test_vector_first_seen_not_overwritten(client: Client, db: MemoryDatabase) -> None:
    """G:風險向首見寫入後不覆寫——後續命中他向詞組,卡仍依首見向。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    assert db._sessions[sid]["redflag_vector"] == "child"
    await client.call_tool("prerequisites", prereq_args(sid))
    await client.call_tool("core_tags", {"session_id": sid})
    r3 = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發",
        "reaction_note": "我也快忍不住打他了"}))  # parent 組詞
    assert db._sessions[sid]["redflag_vector"] == "child"  # 首見不覆寫
    assert r3["safety_tags"]["vector"] == "child"


async def test_child_vector_carries_age_delta(client: Client) -> None:
    """G:child 向疊年齡 delta——12+ 直接問(實證);2-3 不用抽象詞彙。"""
    for band, marker in (("12+", "直接問"), ("2-3", "抽象詞彙")):
        sid = await ready_session(client, age_band=band)
        await client.call_tool("core_tags", {"session_id": sid})
        r = data_of(await client.call_tool("core_tags", {
            "session_id": sid, "child_reaction": "情緒爆發",
            "reaction_note": "他說他想死"}))
        card = r["safety_tags"]
        assert card["vector"] == "child"
        assert marker in str(card["delta"]), band
        assert card["delta"]["source"], band


def test_safety_cards_pure_lookup() -> None:
    """G:組卡為確定性查表——child×4 bands 都有 delta;parent/third 永無。"""
    for band in AGE_BANDS:
        card = safety_cards("child", band)
        assert card["base"]["source"] and card["delta"]["source"], band
    for vector in ("parent", "third"):
        card = safety_cards(vector, "4-6")
        assert card["base"]["source"]
        assert "delta" not in card


def test_missing_safety_block_fails_fast(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G:7 塊缺一 → 啟動即 fail-fast(12+ 的 delta 不允許被遺忘)。"""
    import pathlib

    content = cores._TAGS_PATH.read_text(encoding="utf-8")
    broken = content.replace("safety.delta.12+:", "safety.delta.removed:")
    p = pathlib.Path(str(tmp_path)) / "tags.md"
    p.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(cores, "_TAGS_PATH", p)
    cores._load.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=r"safety\.delta\.12\+"):
            cores._load()
    finally:
        cores._load.cache_clear()  # 清掉壞結果,其他測試重讀原檔


def test_safety_block_missing_source_fails_fast(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G:safety 塊缺 source 錨定 → fail-fast(內容不可無出處)。"""
    import pathlib

    content = cores._TAGS_PATH.read_text(encoding="utf-8")
    broken = content.replace(
        "  source: 衛福部自殺防治守門人「1問2應3轉介」;全國自殺防治中心守門人宣導素材。",
        "")
    p = pathlib.Path(str(tmp_path)) / "tags.md"
    p.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(cores, "_TAGS_PATH", p)
    cores._load.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="source"):
            cores._load()
    finally:
        cores._load.cache_clear()


async def test_warning_does_not_flag(client: Client, db: MemoryDatabase) -> None:
    """A:警訊級照舊只升 severity,不立旗——③ 仍回一般管教 TAG。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他不收玩具,我吼了他說要把你丟掉", emotion="後悔")))
    sid = r["session_id"]
    s = db._sessions[sid]
    assert s["severity"] == "高" and s["redflag_active"] is False
    assert "safety_mode" not in r
    await client.call_tool("prerequisites", prereq_args(sid))
    r3 = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    assert "response_tags" in r3 and "safety_tags" not in r3


async def test_converged_false_under_safety_mode(client: Client) -> None:
    """A:safety_mode 下 converged 恆 false——危機陪伴不適用管教收斂訊號。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他說他想死"})
    for _ in range(2):  # 連續鬆動配合,一般規則早該 true
        r = data_of(await client.call_tool("core_tags", {
            "session_id": sid, "child_reaction": "鬆動配合"}))
        assert r["converged"] is False
    assert r["safety_mode"] is True


async def test_redflag_session_severity_monotonic(client: Client, db: MemoryDatabase) -> None:
    """A:旗標與 severity 單調——後續乾淨輪不降旗、不降級。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    await client.call_tool("prerequisites", prereq_args(sid, emotion_intensity="低"))
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "鬆動配合", "reaction_note": "他平靜下來了"})
    s = db._sessions[sid]
    assert s["redflag_active"] is True and s["severity"] == "高"


async def test_escalated_outcome_maps_legacy_stopped(client: Client, db: MemoryDatabase) -> None:
    """A:host 仍可交 outcome=escalated_to_redflag(受控詞保留)→
    record.status=stopped(legacy 映射)且 redflag=true,promotion 雙保險。"""
    r = data_of(await client.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕", mode="rehearsal")))
    sid = r["session_id"]
    await client.call_tool("prerequisites", prereq_args(sid))
    await client.call_tool("core_tags", {"session_id": sid})
    r2 = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "escalated_to_redflag",
        "draft": "我先陪著你,我在這裡。", "referral_ack": True}))
    rec = await db.get_record(r2["record_id"])
    assert rec is not None
    assert rec["status"] == "stopped" and rec["redflag"] is True
    with pytest.raises(ToolError, match="E_INVALID_LINK"):
        await client.call_tool("constraints", constraints_args(linked_plan_id=rec["record_id"]))


async def test_finalize_clean_session_no_ack_needed(client: Client) -> None:
    """A:無旗標案 ④ 不需 referral_ack(形狀 = {record_id, next})。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想辦法。"}))
    assert set(r) == {"record_id", "next"}
