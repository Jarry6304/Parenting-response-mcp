"""cores 載入器(v3.2):解析 references/cores/tags.md 的學派 TAG 與 safety 約束集。

單一事實來源 = tags.md(spec v3.2 / cores-tags 契約);本模組只做解析與
完整性驗證,**零 LLM、零網路**。改 TAG 改文件,不改 code。

格式(每塊一個 ```text fenced 區塊,塊名容點號):
  回應核心(6):<school>: { 理念, 套用, 示範, 紅線 }
  探詢核心(2):<school>: { 探詢, 探點, 示範問, 紅線 }
  safety(7,G 件):safety.base.{child|parent|third} / safety.delta.{age_band}
    —— 每塊必含 source 鍵(來源錨定)+ 至少一內容鍵;缺一 fail-fast。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..schema import AGE_BANDS, INQUIRY_CORES, RESPONSE_CORES

_TAGS_PATH = Path(__file__).resolve().parents[3] / "references" / "cores" / "tags.md"

_BLOCK_RE = re.compile(r"```text\n(.*?)```", re.DOTALL)

RESPONSE_TAG_KEYS: tuple[str, ...] = ("理念", "套用", "示範", "紅線")
INQUIRY_TAG_KEYS: tuple[str, ...] = ("探詢", "探點", "示範問", "紅線")

# v3.2 G 件:3 風險向底座 × 4 年齡 delta = 7 塊全顯式,不允許靜默 fallback
SAFETY_VECTORS: tuple[str, ...] = ("child", "parent", "third")
SAFETY_BLOCKS: tuple[str, ...] = (
    *(f"safety.base.{v}" for v in SAFETY_VECTORS),
    *(f"safety.delta.{b}" for b in AGE_BANDS),
)


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

    # v3.2 G 件:safety 7 塊 fail-fast——12+ 的 delta 是最關鍵的一塊,
    # fallback 等於允許它被遺忘,故缺塊/缺 source 一律拒啟動(「無補充」須顯式)。
    for block in SAFETY_BLOCKS:
        fields = tags.get(block)
        if fields is None:
            raise RuntimeError(f"{_TAGS_PATH} 缺 safety 區塊:{block}")
        if not fields.get("source"):
            raise RuntimeError(f"{_TAGS_PATH} safety 區塊 {block} 缺來源錨定鍵:source")
        if not any(k != "source" and v for k, v in fields.items()):
            raise RuntimeError(f"{_TAGS_PATH} safety 區塊 {block} 無內容鍵")
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


def safety_cards(vector: str, age_band: str | None) -> dict[str, Any]:
    """safety_mode 組卡(spec v3.2 G 件):base.{風險向} (+ delta.{age_band} 僅當 vector=child)。

    parent / third 風險向不疊 delta——內容對象非孩子,語域調整無著力點。
    """
    loaded = _load()
    card: dict[str, Any] = {
        "vector": vector,
        "base": dict(loaded[f"safety.base.{vector}"]),
    }
    if vector == "child" and age_band in AGE_BANDS:
        card["delta"] = dict(loaded[f"safety.delta.{age_band}"])
    return card
