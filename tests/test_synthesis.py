"""resonance v3 驗收:版面不加權、洗牌、溯源強制、trace 防回歸。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parenting_response.schema import SynthesisTrace

from conftest import analyze_args, data_of


async def test_layout_has_no_family_or_confidence(client, fake_llm):
    await client.call_tool("analyze_situation", analyze_args())
    synth_user = fake_llm.calls_for("synthesis")[0]["user"]
    assert "family" not in synth_user
    assert "confidence" not in synth_user
    assert "信心" not in synth_user


async def test_presentation_order_shuffles_and_lands_in_trace(client):
    orders: set[tuple[str, ...]] = set()
    for _ in range(6):
        res = data_of(await client.call_tool("analyze_situation", analyze_args()))
        order = res["synthesis_trace"]["presentation_order"]
        assert sorted(order) == sorted(set(order))  # 無重複
        orders.add(tuple(order))
    assert len(orders) > 1  # 洗牌生效(非恆定)


async def test_source_verification_forces_regen_without_llm_check(client, fake_llm, db):
    # 轉移打岔輪點火子集無 gottman;合成硬標 gottman → 溯源驗證退回重生 → 上限降級。
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    sid = res["session_id"]
    bad = {
        "card": {
            "reading": "判讀", "posture": "同理接住",
            "opening_utterances": [{"text": "句子", "source": "gottman"}],
            "watchpoints": "看", "boundary": "界", "redline": "紅", "source_summary": "摘",
        },
        "set_aside": [], "divergences_surfaced": [],
    }
    fake_llm.handlers["synthesis"] = bad
    g_before = fake_llm.count("guardian")
    s_before = fake_llm.count("synthesis")
    rr = data_of(
        await client.call_tool(
            "next_round",
            {"session_id": sid, "child_reaction": "轉移打岔", "reaction_note": "他扮鬼臉跑走"},
        )
    )
    assert rr["degraded"] is True
    assert fake_llm.count("synthesis") - s_before == 3  # retry_n=2 → 3 次重生
    assert fake_llm.count("guardian") == g_before  # 溯源驗證 = code,零 LLM 成本


async def test_set_aside_and_divergence_in_trace(client, fake_llm):
    def synth(_system: str, user: str) -> str:
        import json

        ids = []
        for line in user.splitlines():
            if line.startswith("可用來源代號"):
                ids = [t.strip() for t in line.split(":", 1)[1].split(",")]
        src = "pd" if "pd" in ids else ids[0]
        return json.dumps({
            "card": {
                "reading": "判讀", "posture": "溫和設限",
                "opening_utterances": [{"text": "我們先一起深呼吸。", "source": src}],
                "watchpoints": "鬆動 → 一起想辦法;堅持 → 先談情緒(分歧攤開)",
                "boundary": "界", "redline": "紅", "source_summary": "取 PD;放下 NVC",
            },
            "set_aside": [{"core": "nvc", "reason": "情緒高,觀察句延後"}],
            "divergences_surfaced": [{"tension": "先情緒 vs 先講規則", "surfaced_in": "觀察點"}],
        }, ensure_ascii=False)

    fake_llm.handlers["synthesis"] = synth
    res = data_of(await client.call_tool("analyze_situation", analyze_args()))
    trace = res["synthesis_trace"]
    assert trace["set_aside"] == [{"core": "nvc", "reason": "情緒高,觀察句延後"}]
    assert trace["divergences_surfaced"][0]["surfaced_in"] == "觀察點"
    assert trace["utterance_sources"][0]["core"] == "pd"


def test_trace_schema_rejects_family_and_confidence():
    base = {
        "inputs_seen": ["pd"], "presentation_order": ["pd"],
        "utterance_sources": [], "set_aside": [], "divergences_surfaced": [],
    }
    SynthesisTrace.model_validate(base)  # 合法
    with pytest.raises(ValidationError):
        SynthesisTrace.model_validate({**base, "family_agreement": {"adler": 2}})
    with pytest.raises(ValidationError):
        SynthesisTrace.model_validate({**base, "confidence": 0.9})


def test_set_aside_requires_reason():
    from parenting_response.schema import SetAside

    with pytest.raises(ValidationError):
        SetAside.model_validate({"core": "nvc", "reason": ""})
