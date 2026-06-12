"""report-core 載入器(v3.0 F/H 件):解析 references/report-core.md。

單一事實來源 = report-core.md(章節結構/槽位參數/guardian/驗證參數);
本模組只做解析與 fail-fast 完整性驗證,**零 LLM**。改骨架改文件,不改 code。
塊格式沿 cores/tags.md(```text fenced + `key: value`,塊名容點號)。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parents[2] / "references" / "report-core.md"

_BLOCK_RE = re.compile(r"```text\n(.*?)```", re.DOTALL)

REPORT_SCOPES: tuple[str, ...] = ("event", "quarter", "year")

# 每 scope 的必備節(缺一 fail-fast);safety 為敏感節,必有 template
_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "event": ("overview", "safety", "what_worked", "next_time", "quotes"),
    "quarter": ("stats", "positive_moments", "safety", "prev_audit", "growth", "next_quarter"),
    "year": ("stats", "quarters_recap", "journey", "safety", "letter"),
}

_GUARDIAN_BLOCK = "report.guardian"
_VALIDATION_BLOCK = "report.validation"
_VALIDATION_KEYS = ("negative_patterns", "number_whitelist_scopes", "leak_window",
                    "raw_quota_event")


def _parse_block(block: str) -> tuple[str, dict[str, str]] | None:
    name: str | None = None
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            head, sep, rest = line.partition(":")
            if sep and not rest.strip():
                name = head.strip()
            continue
        key, sep, value = line.strip().partition(":")
        if sep and name is not None and value.strip():
            fields[key.strip()] = value.strip()
    if name is None or not fields:
        return None
    return name, fields


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, str]]:
    text = _PATH.read_text(encoding="utf-8")
    blocks: dict[str, dict[str, str]] = {}
    for block in _BLOCK_RE.findall(text):
        parsed = _parse_block(block)
        if parsed is not None:
            name, fields = parsed
            blocks[name] = fields

    for scope, sections in _REQUIRED_SECTIONS.items():  # fail-fast:缺節即拒啟動
        for sec in sections:
            name = f"report.{scope}.{sec}"
            fields = blocks.get(name)
            if fields is None:
                raise RuntimeError(f"{_PATH} 缺報告區塊:{name}")
            if fields.get("type") not in ("fixed", "slot"):
                raise RuntimeError(f"{_PATH} 區塊 {name} type 須 fixed|slot")
            if not fields.get("title") or not fields.get("order", "").isdigit():
                raise RuntimeError(f"{_PATH} 區塊 {name} 缺 title/order")
            if fields["type"] == "slot" and not fields.get("max_chars", "").isdigit():
                raise RuntimeError(f"{_PATH} slot 區塊 {name} 缺 max_chars")
            if sec == "safety" and "|" not in fields.get("template", ""):
                raise RuntimeError(f"{_PATH} 敏感節 {name} 缺雙態 template(有警訊|無警訊)")
    if not blocks.get(_GUARDIAN_BLOCK):
        raise RuntimeError(f"{_PATH} 缺 guardian 指令塊")
    validation = blocks.get(_VALIDATION_BLOCK)
    if validation is None or any(not validation.get(k) for k in _VALIDATION_KEYS):
        raise RuntimeError(f"{_PATH} 缺 validation 參數塊或鍵不全:{_VALIDATION_KEYS}")
    return blocks


def sections(scope: str) -> list[dict[str, Any]]:
    """scope 的有序章節定義(id/title/type/max_chars/hint/template)。"""
    loaded = _load()
    out: list[dict[str, Any]] = []
    for sec in _REQUIRED_SECTIONS[scope]:
        f = loaded[f"report.{scope}.{sec}"]
        item: dict[str, Any] = {"id": sec, "title": f["title"], "type": f["type"],
                                "order": int(f["order"])}
        if f["type"] == "slot":
            item["max_chars"] = int(f["max_chars"])
            if f.get("hint"):
                item["hint"] = f["hint"]
        if f.get("template"):
            item["template"] = f["template"]
        out.append(item)
    out.sort(key=lambda x: int(x["order"]))
    return out


def guardian() -> list[str]:
    """host 生成 slots 前的自查指令(H 件第三層,phase1 隨骨架回傳)。"""
    g = _load()[_GUARDIAN_BLOCK]
    return [g[k] for k in sorted(g)]


def validation() -> dict[str, Any]:
    """驗證參數:負面清單 regex / 數字白名單範圍 / 防滲滑窗 / event raw_quota。"""
    v = _load()[_VALIDATION_BLOCK]
    return {
        "negative_re": re.compile(v["negative_patterns"]),
        "number_whitelist_scopes": tuple(v["number_whitelist_scopes"].split("|")),
        "leak_window": int(v["leak_window"]),
        "raw_quota_event": int(v["raw_quota_event"]),
    }
