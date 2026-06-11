"""L0 落庫:record 欄位(schema v2)/ record_id 序號 / promotion / converged / severity
(spec v3.0 驗收 11 + 資料模型不變量)。"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import constraints_args, data_of, open_session, prereq_args, ready_session
from parenting_response.db import MemoryDatabase


async def finalize_clean(client: Client, sid: str, **over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "session_id": sid, "outcome": "resolved",
        "draft": "我看到你很努力,我們一起想辦法。", "claimed_sources": ["pd", "adler"],
    }
    args.update(over)
    return data_of(await client.call_tool("finalize", args))


async def test_record_fields_v3(client: Client, db: MemoryDatabase) -> None:
    """records schema_version=2:新欄落地、無源欄恆 NULL、maslow_need 固定排序。"""
    sid = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid})
    r = await finalize_clean(client, sid, maslow_need=["尊重", "安全"], outcome_note="有效")
    rec = await db.get_record(r["record_id"])
    assert rec is not None
    assert rec["schema_version"] == 2
    assert rec["status"] == "done"
    assert rec["session_id"] == sid
    assert rec["draft"] == "我看到你很努力,我們一起想辦法。"
    assert rec["claimed_sources"] == ["pd", "adler"]
    assert rec["maslow_need"] == ["安全", "尊重"]  # MASLOW_ORDER 固定排序
    assert rec["erikson_stage"] == "主動對罪惡感" and rec["piaget_stage"] == "前運思期"
    assert rec["outcome"] == "resolved" and rec["outcome_note"] == "有效"
    # v3 無判讀來源欄恆 NULL(record-schema v2)
    assert rec["dreikurs_purpose"] is None and rec["posture"] is None
    assert rec["dev_normative"] is None and rec["tools_used"] is None


async def test_record_id_daily_sequence(client: Client) -> None:
    """record_id = YYYYMMDD-NN 當日序號遞增。"""
    ids: list[str] = []
    for _ in range(2):
        sid = await ready_session(client)
        await client.call_tool("core_tags", {"session_id": sid})
        ids.append((await finalize_clean(client, sid))["record_id"])
    assert all(re.fullmatch(r"\d{8}-\d{2,}", i) for i in ids)
    assert int(ids[1].split("-")[1]) == int(ids[0].split("-")[1]) + 1


async def test_promotion_chain_done_from_plan(client: Client, db: MemoryDatabase) -> None:
    """rehearsal → planned;live + linked_plan_id → done_from_plan(A2 升遷鏈)。"""
    sid = await open_session(client, mode="rehearsal")
    await client.call_tool("prerequisites", prereq_args(sid))
    await client.call_tool("core_tags", {"session_id": sid})
    plan = await finalize_clean(client, sid, outcome="partial")
    rec = await db.get_record(plan["record_id"])
    assert rec is not None and rec["status"] == "planned"

    r = data_of(await client.call_tool("constraints", constraints_args(
        linked_plan_id=plan["record_id"])))
    sid2 = r["session_id"]
    await client.call_tool("prerequisites", prereq_args(sid2))
    await client.call_tool("core_tags", {"session_id": sid2})
    done = await finalize_clean(client, sid2)
    rec2 = await db.get_record(done["record_id"])
    assert rec2 is not None and rec2["status"] == "done_from_plan"
    assert rec2["linked_plan_id"] == plan["record_id"]


async def test_redflag_record_excluded_from_promotion(client: Client, db: MemoryDatabase) -> None:
    """#1:rehearsal 紅旗自動收案 → record.status=stopped,① 引用一律 E_INVALID_LINK。"""
    sid = await open_session(client, mode="rehearsal")
    await client.call_tool("prerequisites", prereq_args(sid))
    await client.call_tool("core_tags", {"session_id": sid})
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他撞牆說想消失"}))
    assert r["redflag"]["hit"] is True
    rec = await db.get_record_by_session(sid)
    assert rec is not None
    assert rec["status"] == "stopped" and rec["outcome"] == "escalated_to_redflag"
    with pytest.raises(ToolError, match="E_INVALID_LINK"):
        await client.call_tool("constraints", constraints_args(linked_plan_id=rec["record_id"]))


async def test_legacy_planned_escalated_record_blocked(client: Client, db: MemoryDatabase) -> None:
    """#1 縱深:v1 遺留列(status=planned ∧ outcome=escalated)由 outcome 防線擋。"""
    db._records["LEGACY-01"] = {"record_id": "LEGACY-01", "status": "planned",
                                "outcome": "escalated_to_redflag"}
    with pytest.raises(ToolError, match="E_INVALID_LINK"):
        await client.call_tool("constraints", constraints_args(linked_plan_id="LEGACY-01"))


async def _react(client: Client, sid: str, reaction: str, note: str | None = None) -> bool:
    r = data_of(await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": reaction, "reaction_note": note}))
    converged = r["converged"]
    assert isinstance(converged, bool)
    return converged


async def test_converged_rules(client: Client) -> None:
    """驗收11:converged 為 code 規則(D3 投影),非 host 自報。"""
    # round 0 恆 False;低張力脈絡下單輪鬆動配合即收斂
    sid = await ready_session(client)
    r0 = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    assert r0["converged"] is False
    assert await _react(client, sid, "鬆動配合") is True

    # 高張力(情緒爆發)後第一個鬆動 = False(討好式順從防線);連續第二輪 = True
    sid2 = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid2})
    assert await _react(client, sid2, "情緒爆發", "大哭摔積木") is False
    assert await _react(client, sid2, "鬆動配合") is False
    assert await _react(client, sid2, "鬆動配合") is True

    # 退縮害怕同屬高張力
    sid3 = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid3})
    assert await _react(client, sid3, "退縮害怕", "低頭不說話一直發抖") is False
    assert await _react(client, sid3, "鬆動配合") is False

    # 警訊詞阻斷收斂(配合但語境危險 ≠ 收斂)
    sid4 = await ready_session(client)
    await client.call_tool("core_tags", {"session_id": sid4})
    assert await _react(client, sid4, "鬆動配合", "他配合了,但我剛才罵他欠揍") is False


async def test_severity_monotonic_raises(client: Client, db: MemoryDatabase) -> None:
    """severity 單調只升不降:② intensity=高 → 中;③ 警訊 → 高。"""
    sid = await ready_session(client, emotion_intensity="高")
    assert db._sessions[sid]["severity"] == "中"
    await client.call_tool("core_tags", {"session_id": sid})
    await client.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持", "reaction_note": "我說再吵就罰跪"})
    assert db._sessions[sid]["severity"] == "高"
