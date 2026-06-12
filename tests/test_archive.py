"""v3.2 E 件:⑤ 原始逐字稿歸檔——防滲拒收、chunk 冪等、G0 補檢(parent only)、
收尾鏈 next 指引。"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import data_of, ready_session
from parenting_response.db import MemoryDatabase

CLEAN_TURNS = [
    {"role": "parent", "content": "他剛剛把妹妹推倒了,我很生氣"},
    {"role": "assistant", "content": "先深呼吸,我們一步一步來"},
    {"role": "parent", "content": "好,我先試著蹲下來跟他說"},
]


async def finalized_session(client: Client) -> str:
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved", "draft": "我們一起想辦法。"}))
    assert r["next"] == "archive"  # ④ 指向 ⑤(收尾鏈)
    return sid


async def test_archive_persists_and_chains_to_report(client: Client, db: MemoryDatabase) -> None:
    """歸檔落庫(canonical JSON)→ next=report(event);終態案可收。"""
    sid = await finalized_session(client)
    r = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 0, "turns": CLEAN_TURNS}))
    assert r["archived"] is True and r["next"] == "report(event)"
    rows = await db.get_transcripts(sid)
    assert len(rows) == 1 and rows[0]["chunk_no"] == 0
    assert json.loads(rows[0]["turns"]) == CLEAN_TURNS


async def test_archive_idempotent_on_same_chunk(client: Client, db: MemoryDatabase) -> None:
    """同內容重送 → duplicate,不重複落;不同 chunk 內容照收。"""
    sid = await finalized_session(client)
    await client.call_tool("archive", {"session_id": sid, "chunk_no": 0, "turns": CLEAN_TURNS})
    r = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 0, "turns": CLEAN_TURNS}))
    assert r["duplicate"] is True
    assert len(await db.get_transcripts(sid)) == 1
    r2 = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 1,
        "turns": [{"role": "parent", "content": "後來他自己把玩具收好了"}]}))
    assert r2["archived"] is True
    assert len(await db.get_transcripts(sid)) == 2


async def test_archive_rejects_tool_markup_whole_chunk(
    client: Client, db: MemoryDatabase
) -> None:
    """任一 turn 含工具協議標記 → 整 chunk 拒收回明細 + events 稽核(不落庫)。"""
    sid = await finalized_session(client)
    dirty = [
        {"role": "parent", "content": "他剛剛把妹妹推倒了"},
        {"role": "assistant", "content": '叫工具:{"tool_calls": [{"name": "x"}]}'},
    ]
    r = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 0, "turns": dirty}))
    assert r["rejected"] is True
    assert r["violations"][0]["turn"] == 1
    assert await db.get_transcripts(sid) == []
    evs = [e for e in await db.get_events(sid) if e["kind"] == "archive_rejected"]
    assert len(evs) == 1 and evs[0]["payload"]["source"] == "⑤"

    xml_dirty = [{"role": "parent", "content": "我說 <function>test</function> 之類"}]
    r2 = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 1, "turns": xml_dirty}))
    assert r2["rejected"] is True


async def test_archive_g0_scans_parent_turns_only(client: Client, db: MemoryDatabase) -> None:
    """G0 補檢只掃 parent 發言:命中 → 旗標+severity+events(source=⑤),
    既落 record 不回改;assistant 引述同詞 → 不掃。"""
    sid = await finalized_session(client)
    rec_before = await db.get_record_by_session(sid)
    assert rec_before is not None and rec_before["redflag"] is False
    r = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 0,
        "turns": [{"role": "parent", "content": "其實那時我已經失手打了他"}]}))
    assert r["archived"] is True and r["redflag"]["hit"] is True and "113" in r["referral"]
    s = db._sessions[sid]
    assert s["redflag_active"] is True and s["severity"] == "高"
    evs = [e for e in await db.get_events(sid) if e["kind"] == "g0_shortcircuit"]
    assert len(evs) == 1 and evs[0]["payload"]["source"] == "⑤"
    rec_after = await db.get_record_by_session(sid)
    assert rec_after is not None and rec_after["redflag"] is False  # record 不可變

    sid2 = await finalized_session(client)
    r2 = data_of(await client.call_tool("archive", {
        "session_id": sid2, "chunk_no": 0,
        "turns": [{"role": "assistant", "content": "若孩子說出「不想活」這類話請立即求助"}]}))
    assert r2["archived"] is True and "redflag" not in r2  # 系統話術不算自陳
    assert db._sessions[sid2]["redflag_active"] is False


async def test_archive_open_session_also_accepted(client: Client, db: MemoryDatabase) -> None:
    """open 案也可歸檔(中途斷線先存稿)。"""
    sid = await ready_session(client)
    r = data_of(await client.call_tool("archive", {
        "session_id": sid, "chunk_no": 0, "turns": CLEAN_TURNS}))
    assert r["archived"] is True
    assert db._sessions[sid]["status"] == "open"  # 不動 FSM


async def test_archive_validates_inputs(client: Client) -> None:
    """session 不存在 → E_INVALID_STATE;turns 空/role 亂寫 → E_MISSING_AXIS。"""
    with pytest.raises(ToolError, match="E_INVALID_STATE"):
        await client.call_tool("archive", {"session_id": "ghost", "chunk_no": 0,
                                           "turns": CLEAN_TURNS})
    sid = await finalized_session(client)
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("archive", {"session_id": sid, "chunk_no": 0, "turns": []})
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("archive", {
            "session_id": sid, "chunk_no": 0,
            "turns": [{"role": "user", "content": "嗨"}]})
    with pytest.raises(ToolError, match="E_MISSING_AXIS"):
        await client.call_tool("archive", {
            "session_id": sid, "chunk_no": 0, "turns": [{"role": "parent", "content": ""}]})
