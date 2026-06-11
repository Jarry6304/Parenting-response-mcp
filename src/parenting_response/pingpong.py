"""S3 反應路由 + converged 判準(references/pingpong.md 的 code 投影)。

設計不變量:每輪約束核心點火 ≥ 2(否則 A5 必然降級)。
converged = C1 ∧ C2 ∧ C3;僅為建議收尾訊號,非 FSM 轉移。
"""

from __future__ import annotations

from typing import Any

from .schema import CONSTRAINT_CORES, Constraint

# 反應 → 點火子集(pingpong.md 路由表)
ROUTES: dict[str, tuple[str, ...]] = {
    "鬆動配合": ("pd", "satir", "maslow", "erikson"),
    "否認堅持": ("dreikurs", "pd", "adler", "maslow", "erikson"),
    "情緒爆發": ("gottman", "rogers", "nvc", "maslow", "satir"),
    "退縮害怕": ("rogers", "gottman", "adler", "maslow", "satir", "erikson"),
    "反問試探": ("pd", "dreikurs", "adler", "piaget", "erikson"),
    "轉移打岔": ("dreikurs", "nvc", "satir", "piaget"),
}

_HIGH_TENSION = ("退縮害怕", "情緒爆發")

for _reaction, _cores in ROUTES.items():
    assert sum(1 for c in _cores if c in CONSTRAINT_CORES) >= 2, _reaction


def ignition_set(reaction: str, prev_reaction: str | None) -> tuple[list[str], bool]:
    """回傳(點火子集, 是否 R+ 輪)。R+:前輪高張力 → 鬆動輪加點 Rogers。"""
    cores = list(ROUTES[reaction])
    r_plus = reaction == "鬆動配合" and prev_reaction in _HIGH_TENSION
    if r_plus and "rogers" not in cores:
        cores.append("rogers")
    return cores, r_plus


def compute_converged(
    *,
    reaction: str,
    r_plus: bool,
    round_outputs: dict[str, dict[str, Any] | None],
    new_constraints: list[Constraint],
    known_types: set[str],
    warning_hit: bool,
) -> bool:
    # C1:本輪 = 鬆動配合(必要非充分)
    if reaction != "鬆動配合":
        return False

    # C2:非討好鑑別。Satir 缺席 → 不可判 → 保守 false(D3)。
    satir = round_outputs.get("satir")
    if not satir or satir.get("child_stance") == "討好":
        return False
    gottman = round_outputs.get("gottman")
    if gottman is not None and gottman.get("emotion_processed") is False:
        return False
    if r_plus:
        # R+ 輪:Satir 與 Rogers 雙鏡頭皆無討好/恐懼訊號才過。
        # Rogers 無結構化欄位,以 analysis 文字訊號保守判(pingpong.md;rogers prompt 要求明寫)。
        rogers = round_outputs.get("rogers")
        if not rogers:
            return False
        analysis = str(rogers.get("analysis", ""))
        if "恐懼" in analysis or "討好" in analysis:
            return False

    # C3:無新增高張力訊號(警訊級零命中;新約束無新 type)。
    if warning_hit:
        return False
    return all(c.type in known_types for c in new_constraints)
