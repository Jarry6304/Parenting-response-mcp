"""cores 載入器(v3.0):解析 references/cores/tags.md 的學派 TAG。

單一事實來源 = tags.md(spec v3.0 / cores-tags 契約);本模組只做解析與
完整性驗證,**零 LLM、零網路**。改 TAG 改文件,不改 code。

格式(每校一個 ```text fenced 區塊):
  回應核心(6):<school>: { 理念, 套用, 示範, 紅線 }
  探詢核心(2):<school>: { 探詢, 探點, 示範問, 紅線 }
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..schema import INQUIRY_CORES, RESPONSE_CORES

_TAGS_PATH = Path(__file__).resolve().parents[3] / "references" / "cores" / "tags.md"

_BLOCK_RE = re.compile(r"```text\n(.*?)```", re.DOTALL)

RESPONSE_TAG_KEYS: tuple[str, ...] = ("理念", "套用", "示範", "紅線")
INQUIRY_TAG_KEYS: tuple[str, ...] = ("探詢", "探點", "示範問", "紅線")


def _parse_block(block: str) -> tuple[str, dict[str, str]] | None:
    """單一 fenced 區塊:第 0 欄 `<school>:` 開塊,其後縮排 `key: value`。

    非學派區塊(如文件中的格式範本)解析不出欄位 → 回 None 略過。
    """
    school: str | None = None
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            head, sep, rest = line.partition(":")
            if sep and not rest.strip():
                school = head.strip()
            continue
        key, sep, value = line.strip().partition(":")
        if sep and school is not None and value.strip():
            fields[key.strip()] = value.strip()
    if school is None or not fields:
        return None
    return school, fields


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, str]]:
    text = _TAGS_PATH.read_text(encoding="utf-8")
    tags: dict[str, dict[str, str]] = {}
    for block in _BLOCK_RE.findall(text):
        parsed = _parse_block(block)
        if parsed is not None:
            school, fields = parsed
            tags[school] = fields

    expected: list[tuple[str, tuple[str, ...]]] = [
        *((s, RESPONSE_TAG_KEYS) for s in RESPONSE_CORES),
        *((s, INQUIRY_TAG_KEYS) for s in INQUIRY_CORES),
    ]
    for school, keys in expected:  # fail-fast:缺校 / 缺欄即啟動失敗
        fields = tags.get(school)
        if fields is None:
            raise RuntimeError(f"{_TAGS_PATH} 缺學派區塊:{school}")
        for key in keys:
            if not fields.get(key):
                raise RuntimeError(f"{_TAGS_PATH} 學派 {school} 缺欄位或值為空:{key}")
    return tags


def load_tags() -> dict[str, dict[str, str]]:
    """全 8 校 TAG;回 copy(快取本體視為凍結)。"""
    return {school: dict(fields) for school, fields in _load().items()}


def response_tags() -> dict[str, dict[str, str]]:
    """6 回應核心 TAG(③ 耦合素材)。"""
    loaded = _load()
    return {s: dict(loaded[s]) for s in RESPONSE_CORES}


def inquiry_probes() -> dict[str, dict[str, str]]:
    """2 探詢核心探點(① 引導 S1 診斷,不進耦合)。"""
    loaded = _load()
    return {s: dict(loaded[s]) for s in INQUIRY_CORES}


def red_line_union() -> list[dict[str, str]]:
    """8 校(6 回應 + 2 探詢)紅線聯集,① 約束集成分。"""
    loaded = _load()
    return [{"school": s, "rule": loaded[s]["紅線"]} for s in (*RESPONSE_CORES, *INQUIRY_CORES)]
