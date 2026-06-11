"""G0 紅旗:analyze 預篩 + next_round 複檢(兩級詞表,縫補裁決)。

先於一切 LLM 呼叫;檢 facts / emotion / reaction_note 文本。
"""

from __future__ import annotations

from .schema import Redflag
from .wordlists import REFERRAL_TEXT, find_shortcircuit, find_warnings


def check_shortcircuit(*texts: str | None) -> Redflag | None:
    """短路級:任一文本命中 → 停案 + 轉介。"""
    for text in texts:
        if not text:
            continue
        phrase = find_shortcircuit(text)
        if phrase is not None:
            return Redflag(hit=True, reason=f"G0 短路級詞組命中:「{phrase}」", referral=REFERRAL_TEXT)
    return None


def check_warning(*texts: str | None) -> list[str]:
    """警訊級:不停案;命中 → severity 升「高」(record-schema 推導規則)。"""
    hits: list[str] = []
    for text in texts:
        if text:
            hits.extend(find_warnings(text))
    return hits
