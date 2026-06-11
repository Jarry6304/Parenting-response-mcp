"""L0 / promotion 驗收:A3 server 端聚合、受控詞表、promotion 鏈。"""

from __future__ import annotations

import re

from parenting_response.schema import MASLOW_ORDER, OUTCOMES

from conftest import analyze_args, data_of


async def test_promotion_chain_done_from_plan(client, db):
    plan = data_of(
        await client.call_tool("analyze_situation", analyze_args(mode="rehearsal"))
    )
    fin = data_of(
        await client.call_tool(
            "finalize_record", {"session_id": plan["session_id"], "outcome": "resolved"}
        )
    )
    plan_record = await db.get_record(fin["record_id"])
    assert plan_record is not None and plan_record["status"] == "planned"

    live = data_of(
        await client.call_tool(
            "analyze_situation", analyze_args(mode="live", linked_plan_id=fin["record_id"])
        )
    )
    fin2 = data_of(
        await client.call_tool(
            "finalize_record", {"session_id": live["session_id"], "outcome": "resolved"}
        )
    )
    record = await db.get_record(fin2["record_id"])
    assert record is not None
    assert record["status"] == "done_from_plan"          # A2
    assert record["linked_plan_id"] == fin["record_id"]  # 鏈結在 record 層


async def test_a3_aggregation_is_server_side(client, db):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    sid = res["session_id"]
    fin = data_of(
        await client.call_tool(
            "finalize_record",
            {"session_id": sid, "outcome": "partial", "outcome_note": "有進展"},
        )
    )
    record = await db.get_record(fin["record_id"])
    assert record is not None
    # 理論欄位全由 server 自 rounds 聚合,client 僅傳 outcome 系欄位。
    assert record["dreikurs_purpose"] == "權力"
    assert record["maslow_need"] == ["安全"]
    assert record["erikson_stage"] == "主動對罪惡感"
    assert record["piaget_stage"] == "前運思期"
    assert record["dev_normative"] is True
    assert record["tools_used"] == ["pd", "dreikurs"]  # 溯源即貢獻(utterance_sources 聯集)
    assert record["posture"] == "溫和設限"
    assert re.fullmatch(r"\d{8}-\d{2,}", record["record_id"])
    session = await db.get_session(sid)
    assert session is not None
    assert session["goal_aligned"] is None  # partial → 不可判,不臆測


async def test_record_vocab_locked(client, db):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    fin = data_of(
        await client.call_tool(
            "finalize_record", {"session_id": res["session_id"], "outcome": "resolved"}
        )
    )
    record = await db.get_record(fin["record_id"])
    assert record is not None
    assert record["outcome"] in OUTCOMES
    assert record["status"] in ("planned", "done", "done_from_plan")
    assert record["dreikurs_purpose"] in ("關注", "權力", "報復", "自暴自棄", None)
    assert all(n in MASLOW_ORDER for n in record["maslow_need"] or [])
    session = await db.get_session(res["session_id"])
    assert session is not None and session["goal_aligned"] is True  # resolved → true


async def test_rounds_carry_card_outputs_trace(client, db):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    sid = res["session_id"]
    await client.call_tool(
        "next_round",
        {"session_id": sid, "child_reaction": "鬆動配合", "reaction_note": "他放下車說好"},
    )
    rounds = await db.get_rounds(sid)
    assert [r["round_no"] for r in rounds] == [0, 1]  # round_no server 端嚴格遞增
    for r in rounds:
        assert r["card"] and r["core_outputs"] and r["synthesis_trace"]
    assert rounds[0]["child_reaction"] is None
    assert rounds[1]["child_reaction"] == "鬆動配合"
    assert rounds[1]["reaction_note"] == "他放下車說好"


async def test_converged_with_d3_guard(client, fake_llm):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    sid = res["session_id"]
    rr = data_of(
        await client.call_tool(
            "next_round",
            {"session_id": sid, "child_reaction": "鬆動配合", "reaction_note": "他放下車說好"},
        )
    )
    assert rr["converged"] is True  # satir=一致、無警訊、無新約束型

    # D3:Satir 判討好 → 不收斂。
    discount = dict(
        analysis="ST-討好樣態", child_stance="討好", parent_stance="指責", constraints=[]
    )
    fake_llm.handlers["core:satir"] = discount
    res2 = data_of(await client.call_tool("analyze_situation", analyze_args()))
    rr2 = data_of(
        await client.call_tool(
            "next_round",
            {"session_id": res2["session_id"], "child_reaction": "鬆動配合",
             "reaction_note": "他馬上說對不起我乖"},
        )
    )
    assert rr2["converged"] is False
