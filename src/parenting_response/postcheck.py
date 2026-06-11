"""後檢:code pattern + guardian LLM(spec v2.2 硬 fence 下游閘)。

1. pattern:固定詞表(F2/F3/F5 投影)∪ 當輪 pattern 型 constraints 的 forbidden_terms。
2. guardian:Haiku(同 vendor 不同 model string),逐條驗 constraints 語意項。
違者退回重生(retry ≤ N);上限 → 降級安全卡。
"""

from __future__ import annotations

import json
from typing import Any, cast

from .cores import parse_json_loose
from .llm import MODEL_HAIKU, LLMClient
from .schema import Card, Constraint
from .wordlists import find_output_violations

GUARDIAN_SYSTEM = """你是後檢守門員。輸入是一張育兒建議卡與一組約束;逐條檢查卡的全文是否違反任何約束(語意層面:不踩需求底線、不損自我、不超齡)。

只判違反與否,不評卡的好壞、不改寫、不建議。
嚴格輸出 JSON(無任何其他文字):
{ "violations": [ { "rule": "被違反的約束原文", "where": "卡中違反處的簡述" } ] }
無違反時 violations 為空陣列。"""


def pattern_check(card: Card, constraints: list[Constraint]) -> list[str]:
    extra = [t for c in constraints if c.checkable_by == "pattern" for t in c.forbidden_terms]
    return find_output_violations(card.full_text(), extra)


async def guardian_check(card: Card, constraints: list[Constraint], llm: LLMClient) -> list[dict[str, Any]]:
    if not constraints:
        return []
    payload = json.dumps(
        {
            "constraints": [c.model_dump() for c in constraints],
            "card": card.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    raw = await llm.complete(model=MODEL_HAIKU, system=GUARDIAN_SYSTEM, user=payload, tag="guardian")
    data = parse_json_loose(raw)
    violations = data.get("violations")
    if not isinstance(violations, list):
        return []
    out: list[dict[str, Any]] = []
    for v in cast(list[Any], violations):
        if isinstance(v, dict):
            out.append(cast(dict[str, Any], v))
    return out
