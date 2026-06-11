"""硬 fence 驗收:G0 兩級、核心隔離、pattern/guardian 後檢、降級路徑。"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from parenting_response.wordlists import find_output_violations

from conftest import ANALYSIS_MARKERS, SYNTH_MARK, analyze_args, data_of


async def test_g0_analyze_shortcircuit(client, fake_llm, db):
    res = data_of(
        await client.call_tool(
            "analyze_situation", analyze_args(facts="他在房間大喊說他想死,不想上學")
        )
    )
    assert res["redflag"]["hit"] is True
    assert res["card"] is None and res["synthesis_trace"] is None  # A1
    assert "113" in res["redflag"]["referral"]
    assert fake_llm.count() == 0  # 零核心呼叫
    session = await db.get_session(res["session_id"])
    assert session is not None and session["status"] == "redflag_stopped"
    assert await db.get_rounds(res["session_id"]) == []  # rounds 零列


async def test_g0_next_round_recheck_auto_record(client, fake_llm, db):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    sid = res["session_id"]
    before = fake_llm.count()
    rr = data_of(
        await client.call_tool(
            "next_round",
            {"session_id": sid, "child_reaction": "情緒爆發", "reaction_note": "他邊哭邊說想死"},
        )
    )
    assert rr["redflag"]["hit"] is True and rr["card"] is None
    assert fake_llm.count() == before  # 複檢命中:零核心呼叫
    session = await db.get_session(sid)
    assert session is not None and session["status"] == "redflag_stopped"
    record = await db.get_record_by_session(sid)
    assert record is not None and record["outcome"] == "escalated_to_redflag"


async def test_core_isolation_inputs(client, fake_llm):
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    core_calls = fake_llm.calls_for("core:")
    assert len(core_calls) == 10  # 單波全 10 核心
    for call in core_calls:
        payload = call["user"]
        assert '"history": []' in payload
        assert "linked_plan" not in payload  # 嚴格隔離
        for marker in ANALYSIS_MARKERS:  # 不含任何其他核心輸出
            assert marker not in payload

    # 乒乓輪:歷輪卡文不得進核心(卡僅合成可見)。
    n_before = fake_llm.count("core:")
    await client.call_tool(
        "next_round",
        {"session_id": res["session_id"], "child_reaction": "否認堅持", "reaction_note": "他說我沒有"},
    )
    for call in fake_llm.calls_for("core:")[n_before:]:
        assert SYNTH_MARK not in call["user"]
        for marker in ANALYSIS_MARKERS:
            assert marker not in call["user"]


async def test_constraint_cores_not_in_parallel_blocks(client, fake_llm):
    await client.call_tool("analyze_situation", analyze_args())
    synth_user = fake_llm.calls_for("synthesis")[0]["user"]
    # 約束核心只進【約束】段;並列區塊(帶 [名稱] 標記)只有産招+觀點。
    for name in ("[Maslow]", "[Satir]", "[Erikson]", "[Piaget]"):
        assert name not in synth_user
    assert "[Adler]" in synth_user and "[PD]" in synth_user


def test_pattern_unit_blocks_forbidden_terms():
    assert find_output_violations("你每次都這樣") != []
    assert find_output_violations("人家小明都可以,你為什麼不行") != []
    assert find_output_violations("我看到你很努力收玩具") == []


async def test_pattern_violation_degrades(client, fake_llm, db):
    bad_card = {
        "card": {
            "reading": "判讀", "posture": "溫和設限",
            "opening_utterances": [{"text": "你每次都這樣亂丟", "source": "pd"}],
            "watchpoints": "看", "boundary": "界", "redline": "紅",
            "source_summary": "摘",
        },
        "set_aside": [], "divergences_surfaced": [],
    }
    fake_llm.handlers["synthesis"] = bad_card
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    assert res["degraded"] is True
    assert res["card"]["opening_utterances"] == []  # 降級卡不硬出話術
    rounds = await db.get_rounds(res["session_id"])
    assert rounds[0]["degraded"] is True


async def test_dynamic_forbidden_terms_from_constraints(client, fake_llm):
    bad_card = {
        "card": {
            "reading": "判讀", "posture": "溫和設限",
            "opening_utterances": [{"text": "再吵就不准吃點心", "source": "pd"}],
            "watchpoints": "看", "boundary": "界", "redline": "紅",
            "source_summary": "摘",
        },
        "set_aside": [], "divergences_surfaced": [],
    }
    fake_llm.handlers["synthesis"] = bad_card
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    assert res["degraded"] is True  # maslow constraint 的 forbidden_terms 併入詞表


async def test_emergent_violation_caught_by_guardian(client, fake_llm, db):
    # 候選各自乾淨,織出的卡違約束(語意)→ guardian 攔下 → 上限 → 降級。
    fake_llm.handlers["guardian"] = (
        '{"violations": [{"rule": "不得人格定性,談行為不談人", "where": "起手話術隱含定性"}]}'
    )
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    assert res["degraded"] is True
    assert fake_llm.count("guardian") >= 1
    rounds = await db.get_rounds(res["session_id"])
    assert rounds[0]["degraded"] is True


async def test_constraint_cores_below_k_degrades(client, fake_llm):
    for cid in ("maslow", "satir", "erikson"):
        fake_llm.handlers[f"core:{cid}"] = RuntimeError
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    assert res["degraded"] is True  # 可用約束核心 = 1 < K=2 → 正常卡不出(A5)
    assert fake_llm.count("guardian") == 0  # 合成完直接降級,不進後檢


async def test_all_producers_fail_returns_error(client, fake_llm, db):
    for cid in ("pd", "dreikurs", "gottman", "nvc", "rogers"):
        fake_llm.handlers[f"core:{cid}"] = RuntimeError
    with pytest.raises(ToolError, match="E_CORES_UNAVAILABLE"):
        await client.call_tool("analyze_situation", analyze_args())
    assert db._sessions == {}  # 不出卡也不留半套 session
