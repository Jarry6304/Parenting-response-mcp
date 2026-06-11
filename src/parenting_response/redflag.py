"""G0 紅旗:① 預篩 + ③ 複檢 + ④ 自由文本(兩級詞表,縫補裁決)。

先於一切 LLM 呼叫;檢具名欄位文本。命中攜帶欄位/詞組/前後文節錄
(defect-fixes #8 證據鏈:reason 進 record、全量進 events)。
"""

from __future__ import annotations

from collections.abc import Iterable

from .schema import Redflag
from .wordlists import REFERRAL_TEXT, find_shortcircuit, find_warnings

# (欄位名, 文本) 對;欄位名進 reason 與稽核 payload
LabeledTexts = Iterable[tuple[str, str | None]]


def _excerpt(text: str, phrase: str, margin: int = 12) -> str:
    """命中詞前後文節錄(稽核用;誤觸與真危機事後可區辨)。"""
    i = text.find(phrase)
    start = max(0, i - margin)
    end = min(len(text), i + len(phrase) + margin)
    return f"{'…' if start > 0 else ''}{text[start:end]}{'…' if end < len(text) else ''}"


def check_shortcircuit(fields: LabeledTexts) -> Redflag | None:
    """短路級:任一欄位命中 → 停案(①③)或轉介必達(④);攜帶證據鏈。"""
    for field, text in fields:
        if not text:
            continue
        phrase = find_shortcircuit(text)
        if phrase is not None:
            return Redflag(
                hit=True, reason=f"G0 短路級詞組命中({field}):「{phrase}」",
                referral=REFERRAL_TEXT,
                field=field, phrase=phrase, excerpt=_excerpt(text, phrase),
            )
    return None


def check_warning(fields: LabeledTexts) -> list[tuple[str, str]]:
    """警訊級:不停案;回 (欄位, 詞組) 命中列——severity 升「高」+ events 稽核。"""
    hits: list[tuple[str, str]] = []
    for field, text in fields:
        if text:
            hits.extend((field, p) for p in find_warnings(text))
    return hits
