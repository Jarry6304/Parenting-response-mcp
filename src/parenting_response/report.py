"""報告聚合與組裝(v3.0 F 件):純函數,吃 db raw rows,**零 LLM**。

聚合值是數字白名單的唯一來源(host 在 slot 內只能用這裡出現的數字);
fixed 節由本模組確定性組裝(無時間戳——同輸入必同 body,逐位元可重現)。
期界一律臺北時區(季/年的「當期」= 家庭的日曆,不是 UTC 容器的)。
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections import Counter
from typing import Any

from .schema import TZ_TAIPEI

QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
YEAR_RE = re.compile(r"^\d{4}$")

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def period_bounds(scope: str, ref: str) -> tuple[_dt.datetime, _dt.datetime]:
    """quarter/year ref → [start, end) UTC 界(臺北日曆界轉換)。"""
    if scope == "quarter":
        m = QUARTER_RE.fullmatch(ref)
        assert m is not None
        year, q = int(m.group(1)), int(m.group(2))
        start = _dt.datetime(year, 3 * (q - 1) + 1, 1, tzinfo=TZ_TAIPEI)
        end = (_dt.datetime(year + 1, 1, 1, tzinfo=TZ_TAIPEI) if q == 4
               else _dt.datetime(year, 3 * q + 1, 1, tzinfo=TZ_TAIPEI))
    else:  # year
        y = int(ref)
        start = _dt.datetime(y, 1, 1, tzinfo=TZ_TAIPEI)
        end = _dt.datetime(y + 1, 1, 1, tzinfo=TZ_TAIPEI)
    return start.astimezone(_dt.timezone.utc), end.astimezone(_dt.timezone.utc)


# ── 聚合(9 維度;quarter/year 同函數,期界不同) ─────────────────


def aggregate_period(
    sessions: list[dict[str, Any]],
    records: list[dict[str, Any]],
    rounds_by_session: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    def _conv(r: dict[str, Any]) -> bool:
        trace: dict[str, Any] = r.get("synthesis_trace") or {}
        return trace.get("converged") is True

    pingpong = {sid for sid, rs in rounds_by_session.items() if len(rs) > 1}
    converged = {sid for sid, rs in rounds_by_session.items() if any(_conv(r) for r in rs)}
    n_rounds = [len(rs) for rs in rounds_by_session.values() if rs]
    return {
        "sessions_total": len(sessions),
        "records_total": len(records),
        "outcome_dist": dict(Counter(str(r["outcome"]) for r in records)),
        "mode_dist": dict(Counter(str(s["mode"]) for s in sessions)),
        # K 件:各照顧者「自照」案量(中性計數;報告不產對比節,比較句進 tripwire)
        "caregiver_dist": dict(Counter(str(s.get("caregiver") or "爸") for s in sessions)),
        "severity_dist": dict(Counter(str(s.get("severity") or "低") for s in sessions)),
        "redflag_count": sum(1 for s in sessions if s.get("redflag_active")),
        "positive_log_count": sum(1 for s in sessions if s.get("is_positive_log")),
        "converged_count": len(converged & pingpong),
        "pingpong_count": len(pingpong),
        "promotion_done": sum(1 for r in records if str(r["status"]) == "done_from_plan"),
        "planned_count": sum(1 for r in records if str(r["status"]) == "planned"),
        "rounds_avg": round(sum(n_rounds) / len(n_rounds), 1) if n_rounds else 0,
    }


def aggregate_event(
    session: dict[str, Any], record: dict[str, Any], rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    reactions = [str(r["child_reaction"]) for r in rounds
                 if r.get("child_reaction") is not None]
    last_trace: dict[str, Any] = (rounds[-1].get("synthesis_trace") or {}) if rounds else {}
    return {
        "mode": session["mode"],
        "problem_category": session.get("problem_category"),
        "age_band": session.get("age_band"),
        "rounds_count": len(rounds),
        "reactions": reactions,
        "outcome": record["outcome"],
        "converged_final": last_trace.get("converged") is True,
        "redflag": bool(record.get("redflag")),
        "redflag_hits": 0,  # orchestrator 以 events 數覆寫(g0_shortcircuit 次數)
        "severity": session.get("severity"),
    }


# ── fixed 節組裝(確定性;無時間戳) ──────────────────────────────


def fill_safety_template(template: str, n: int) -> str:
    """敏感節雙態模板:「有警訊句|無警訊句」——n>0 帶數,n=0 用無警訊句式。"""
    with_hits, _, without = template.partition("|")
    return with_hits.replace("{n}", str(n)) if n > 0 else without


def render_event_overview(agg: dict[str, Any]) -> str:
    lines = [
        f"模式:{agg['mode']}",
        f"問題類別:{agg['problem_category'] or '未分類'}",
        f"年齡段:{agg['age_band']}",
        f"乒乓輪數:{agg['rounds_count']}(反應:{'→'.join(agg['reactions']) or '無'})",
        f"結果:{agg['outcome']}",
        f"收斂:{'是' if agg['converged_final'] else '否'}",
    ]
    return "\n".join(lines)


def render_period_stats(agg: dict[str, Any], label: str) -> str:
    def dist(d: dict[str, int]) -> str:
        return "、".join(f"{k} {v}" for k, v in sorted(d.items())) or "無"

    lines = [
        f"{label}案量:{agg['sessions_total']}(完成 {agg['records_total']})",
        f"結果分布:{dist(agg['outcome_dist'])}",
        f"模式分布:{dist(agg['mode_dist'])}",
        f"照顧紀錄:{dist(agg['caregiver_dist'])}",
        f"正向紀錄:{agg['positive_log_count']}",
        f"乒乓案 {agg['pingpong_count']} 件,其中收斂 {agg['converged_count']} 件"
        f"(平均 {agg['rounds_avg']} 輪)",
        f"預演→實戰:{agg['promotion_done']} 件(計畫 {agg['planned_count']} 件)",
    ]
    return "\n".join(lines)


def render_prev_audit(warnings: list[dict[str, str]] | None) -> str:
    if not warnings:
        return "上期無語意警示。"
    lines = [f"- 「{w['clause']}」(觸發詞:{w['term']})" for w in warnings]
    return "上期報告語意警示回放(寫下季 slot 前先回看):\n" + "\n".join(lines)


def render_quarters_recap(
    quarter_refs: list[str], found: dict[str, dict[str, Any]],
) -> str:
    lines: list[str] = []
    for ref in quarter_refs:
        row = found.get(ref)
        lines.append(f"- {ref}:{'已定稿 v' + str(row['version']) if row else '缺(未產季報)'}")
    return "\n".join(lines)


def assemble_body(scope: str, ref: str, ordered_sections: list[dict[str, Any]],
                  contents: dict[str, str]) -> str:
    """確定性組裝:章節序 + 標題 + 內容;**不含時間戳**(同輸入逐位元相同)。"""
    title = {"event": "事件卡", "quarter": "季報", "year": "年報"}[scope]
    parts = [f"# {title}({ref})"]
    for sec in ordered_sections:
        parts.append(f"## {sec['title']}\n\n{contents[str(sec['id'])]}")
    return "\n\n".join(parts) + "\n"


# ── slot 驗證素材 ────────────────────────────────────────────────


def numbers_in(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def whitelist_numbers(aggregates: dict[str, Any], ref: str) -> set[str]:
    """數字白名單 = 聚合值全集 ∪ ref 數字 ∪ 0(「無」的數字形)。"""
    found: set[str] = {"0"}
    found |= numbers_in(ref)

    def walk(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            found.add(str(v))
            if isinstance(v, float) and v.is_integer():
                found.add(str(int(v)))
        elif isinstance(v, dict):
            for x in v.values():  # type: ignore[union-attr]
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:  # type: ignore[union-attr]
                walk(x)

    walk(aggregates)
    return found


def leak_windows(texts: list[str], window: int) -> set[str]:
    """scope 內自由文本的連續 n 字滑窗集(防滲比對基)。"""
    out: set[str] = set()
    for t in texts:
        compact = re.sub(r"\s", "", t)
        for i in range(len(compact) - window + 1):
            out.add(compact[i:i + window])
    return out


def find_leak(slot_text: str, windows: set[str], window: int) -> str | None:
    compact = re.sub(r"\s", "", slot_text)
    for i in range(len(compact) - window + 1):
        seg = compact[i:i + window]
        if seg in windows:
            return seg
    return None


def meta_json(aggregates: dict[str, Any], slots: dict[str, str],
              warnings: list[dict[str, str]]) -> str:
    return json.dumps({"aggregates": aggregates, "slots": slots,
                       "semantic_warnings": warnings}, ensure_ascii=False, sort_keys=True)
