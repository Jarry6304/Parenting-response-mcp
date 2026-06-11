"""C-輕 合成(resonance-c-light v3):code 排版(隔離並列+洗牌)→ LLM 生成 → code 溯源驗證。

中心原則:不分族、不加權——版面不含 family / confidence / 任何權重欄位(可斷言);
隨機但有源頭——每句話術必可溯源(code 驗證,零 LLM 成本)。
"""

from __future__ import annotations

import json
import random
from typing import Any

from .llm import MODEL_SONNET, LLMClient
from .schema import (
    CONSTRAINT_CORES,
    PERSPECTIVE_CORES,
    PRODUCER_CORES,
    Card,
    Constraint,
    Divergence,
    SetAside,
    SynthesisTrace,
    UtteranceSource,
)
from .cores import parse_json_loose

DISPLAY: dict[str, str] = {
    "pd": "PD", "dreikurs": "Dreikurs", "gottman": "Gottman", "nvc": "NVC",
    "rogers": "Rogers", "adler": "Adler", "maslow": "Maslow", "satir": "Satir",
    "erikson": "Erikson", "piaget": "Piaget",
}

SYNTH_SYSTEM = """你是育兒建議卡的合成器,服務台灣家長。你會收到:情境摘要、約束(必須全部遵守,後檢將逐條驗)、以及多個理論核心的隔離並列輸出(順序隨機,彼此等地位)。

沒有計票規則、沒有權重公式:由你依「情境貼合 + 約束相容」自行取捨——可織多核心、可只取一源、可自行措辭。

輸出結構規則(硬性):
1. 全部約束逐條遵守;違者會被退回重生。
2. 起手話術 2–3 句,每句必須標來源核心代號(取「可用來源代號」清單中的值);自行措辭處標最近源頭。
3. 方向分歧不壓平:在觀察點攤開張力,寫「看哪個反應 → 各自下一步」。
4. 放下的方向在 set_aside 各記一句理由(供審計,非辯護)。
5. 卡片不引用反例句:只寫可以說的話,不得以「不要說○○」形式出現任何負面句式。
6. 話術不得含恐嚇、羞辱標籤、比較、情感勒索、全稱否定(每次都/從來不)、賄賂交換、情緒否定、體罰暗示。

嚴格輸出 JSON(無任何其他文字):
{
  "card": {
    "reading": "判讀(2-4 句)",
    "posture": "同理接住|情緒教練|溫和設限|給選擇|自然後果|共同解題|修復關係|退場降溫 之一",
    "opening_utterances": [ { "text": "句子", "source": "核心代號" } ],
    "watchpoints": "觀察點:含分歧分支(看哪個反應 → 各自下一步)",
    "boundary": "界線",
    "redline": "紅線(何時停手/求助)",
    "source_summary": "來源摘要:取用了誰、放下了誰+一句理由"
  },
  "set_aside": [ { "core": "核心代號", "reason": "一句理由" } ],
  "divergences_surfaced": [ { "tension": "張力描述", "surfaced_in": "觀察點" } ]
}"""


class SourceVerificationError(Exception):
    """溯源驗證失敗 → 退回重生(本驗證零 LLM 成本)。"""


def build_layout(
    *,
    situation_summary: str,
    constraint_outputs: dict[str, dict[str, Any] | None],
    parallel_outputs: dict[str, dict[str, Any] | None],
    order: list[str],
) -> str:
    """隔離並列版面:每核心等格式區塊、順序已洗牌;無 family、無 confidence、無權重欄。"""
    lines: list[str] = [f"【情境】{situation_summary}", "", "【約束(後檢將逐條驗,事前遵守)】"]
    for cid in CONSTRAINT_CORES:
        data = constraint_outputs.get(cid)
        if not data:
            lines.append(f"  {DISPLAY[cid]} : (本輪不可用)")
            continue
        rules = "; ".join(c["rule"] for c in data.get("constraints", [])) or "(無附加約束)"
        lines.append(f"  {DISPLAY[cid]} : {rules}")
        lines.append(f"    analysis: {data['analysis']}")
    lines.append("")
    lines.append("【核心輸出(隔離並列,順序隨機)】")
    for cid in order:
        data = parallel_outputs[cid]
        assert data is not None
        block = f"  [{DISPLAY[cid]}] analysis: {data['analysis']}"
        candidate = data.get("candidate")
        if candidate:
            block += f"\n    candidate({candidate['posture']}): {candidate['utterance']}"
        lines.append(block)
    lines.append("")
    lines.append("可用來源代號: " + ", ".join(sorted(set(order) | {c for c, v in constraint_outputs.items() if v})))
    layout = "\n".join(lines)
    # 不加權的 code 保證點(resonance v3 驗收:可斷言)
    assert "confidence" not in layout and "family" not in layout
    return layout


def shuffle_order(parallel_ids: list[str], rng: random.Random) -> list[str]:
    order = list(parallel_ids)
    rng.shuffle(order)
    return order


def verify_sources(card: Card, inputs_seen: list[str]) -> None:
    """code 溯源驗證:每句有來源 ∈ inputs_seen;失敗 → 重生(零 LLM)。"""
    allowed = set(inputs_seen)
    for u in card.opening_utterances:
        if u.source not in allowed:
            raise SourceVerificationError(f"來源 {u.source} ∉ inputs_seen")
    if not card.opening_utterances:
        raise SourceVerificationError("起手話術為空(非降級卡必須 ≥1 句)")


async def synthesize_once(
    *,
    situation_summary: str,
    core_outputs: dict[str, dict[str, Any] | None],
    constraints: list[Constraint],
    llm: LLMClient,
    rng: random.Random,
) -> tuple[Card, list[SetAside], list[Divergence], list[str]]:
    """一次合成呼叫;回 (card, set_aside, divergences, presentation_order)。"""
    parallel_ids = [c for c in (*PRODUCER_CORES, *PERSPECTIVE_CORES) if core_outputs.get(c)]
    constraint_outputs = {c: core_outputs.get(c) for c in CONSTRAINT_CORES}
    order = shuffle_order(parallel_ids, rng)
    layout = build_layout(
        situation_summary=situation_summary,
        constraint_outputs=constraint_outputs,
        parallel_outputs={c: core_outputs[c] for c in order},
        order=order,
    )
    extra_rules = "\n".join(f"- {c.rule}" for c in constraints)
    user = layout + ("\n\n【累積約束清單(逐條遵守)】\n" + extra_rules if extra_rules else "")
    raw = await llm.complete(model=MODEL_SONNET, system=SYNTH_SYSTEM, user=user, tag="synthesis")
    data = parse_json_loose(raw)
    card = Card.model_validate(data["card"])
    set_aside = [SetAside.model_validate(x) for x in data.get("set_aside", [])]
    divergences = [Divergence.model_validate(x) for x in data.get("divergences_surfaced", [])]
    return card, set_aside, divergences, order


def make_trace(
    *,
    called: list[str],
    core_outputs: dict[str, dict[str, Any] | None],
    presentation_order: list[str],
    card: Card,
    set_aside: list[SetAside],
    divergences: list[Divergence],
) -> SynthesisTrace:
    inputs_seen = [c for c in called if core_outputs.get(c)]
    unavailable = [c for c in called if not core_outputs.get(c)]
    return SynthesisTrace(
        inputs_seen=inputs_seen,  # type: ignore[arg-type]
        unavailable=unavailable,  # type: ignore[arg-type]
        presentation_order=presentation_order,  # type: ignore[arg-type]
        utterance_sources=[
            UtteranceSource(utterance=u.text, core=u.source) for u in card.opening_utterances
        ],
        set_aside=set_aside,
        divergences_surfaced=divergences,
    )


def build_degraded_card(constraints: list[Constraint]) -> Card:
    """降級安全卡(A5 / 後檢上限):約束摘要 + 安全提醒,不硬出話術。"""
    rules = ";".join(c.rule for c in constraints) or "(本輪無可用約束)"
    return Card(
        reading="本輪未能產出通過後檢的正常卡,以下為降級安全內容(degraded)。",
        posture="同理接住",
        opening_utterances=[],
        watchpoints="約束摘要:" + rules,
        boundary="暫不採取新的管教動作;先陪伴、先安頓彼此情緒。",
        redline="若出現自傷、傷人或您快失控的情況,先確保安全並尋求協助(113 / 110)。",
        source_summary="降級安全卡:後檢未通過或約束核心不足。",
    )


def dump_card(card: Card) -> dict[str, Any]:
    return card.model_dump(mode="json")


def dump_trace(trace: SynthesisTrace) -> dict[str, Any]:
    return trace.model_dump(mode="json")


def situation_summary_line(s: dict[str, Any], parent_goal_label: str = "家長目的") -> str:
    parts = [
        f"mode={s['mode']}", f"{s['age_band']} 歲帶",
        f"類別={s.get('problem_category') or '未標'}",
        f"情緒={s['emotion']}/{s['emotion_intensity']}(事實,非權重)",
    ]
    if s.get("confounders"):
        parts.append("confounders=" + ",".join(s["confounders"]))
    line = "｜".join(parts) + f"\n        事實:{s['facts']}"
    if s.get("parent_goal"):
        line += f"\n        {parent_goal_label}:{s['parent_goal']}"
    return line


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=None)
