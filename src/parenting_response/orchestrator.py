"""編排器(v3.0):FSM 守衛 → G0 → 回傳靜態 TAG → 後檢 → 落庫。**全程零 LLM。**

不變量(可斷言:無 LLM client 物件):
  FSM stage:constrained → {ready|short_pending} → {finalized|redflag_stopped}
  違 stage 呼叫一律 E_INVALID_STATE,零成本
  records UNIQUE(session_id);status 條件式轉移 WHERE status='open'

v2.2 fat(自打 API 產招)→ v3.0 thin(回傳 TAG,host 耦合)。
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

from .cores import inquiry_probes, red_line_union, response_tags
from .db import Database, UniqueViolation
from .redflag import check_shortcircuit, check_warning
from .schema import (
    AGE_BANDS,
    CHILD_REACTIONS,
    E_INVALID_LINK,
    E_INVALID_STATE,
    E_MISSING_AXIS,
    ERIKSON_BY_BAND,
    INTENSITIES,
    MASLOW_ORDER,
    MODES,
    OUTCOMES,
    PIAGET_BY_BAND,
    POSITIVE_LOG,
    PROBLEM_CATEGORIES,
    RESPONSE_CORES,
    SCRIPT_DECISIONS,
    SEVERITY_ORDER,
    PRError,
    Redflag,
)
from .wordlists import (
    OUTPUT_PATTERN_F2,
    OUTPUT_PATTERN_F3,
    OUTPUT_PATTERN_F5,
    find_output_violations,
)

# 反應二級強調(單一來源 = spec v3.0「反應二級強調」表;此處為 code 投影,僅含 6 回應核心)
REACTION_PRIMARY: dict[str, tuple[str, ...]] = {
    "鬆動配合": ("pd", "adler"),
    "否認堅持": ("dreikurs", "adler", "pd"),
    "情緒爆發": ("gottman", "rogers"),
    "退縮害怕": ("rogers", "nvc"),
    "反問試探": ("nvc", "pd"),
    "轉移打岔": ("gottman", "pd"),
}

# D3 投影:高張力反應後的第一個「鬆動配合」不算收斂(討好式順從防線)
_HIGH_TENSION_REACTIONS = {"情緒爆發", "退縮害怕"}


class Orchestrator:
    def __init__(self, db: Database) -> None:
        self.db = db
        # 注意:無 self.llm —— v3 零推論,刻意不收 LLM client

    # ── ① constraints(約束探詢,內含 G0) ─────────────────────────

    async def constraints(
        self, *, facts: str | None, emotion: str | None, mode: str | None,
        child_id: str, linked_plan_id: str | None,
    ) -> dict[str, Any]:
        if not facts or not emotion or mode not in MODES:
            raise PRError(E_MISSING_AXIS, "① 必要:facts / emotion / mode(live|rehearsal)")

        # linked_plan 守衛(承 v2.2 A2):須指向存在且 status=planned 的 record;
        # outcome 驗證為縱深防禦,兼擋 v1 遺留之 planned+escalated 列(紅旗案不可引用)。
        if linked_plan_id is not None:
            rec = await self.db.get_record(linked_plan_id)
            if (rec is None or rec.get("status") != "planned"
                    or rec.get("outcome") == "escalated_to_redflag"):
                raise PRError(E_INVALID_LINK,
                              f"linked_plan_id={linked_plan_id} 不存在、非 planned 或為紅旗案")

        session_id = uuid.uuid4().hex

        rf = check_shortcircuit(facts, emotion)  # G0 短路,code,零成本
        if rf is not None:
            await self.db.create_session(self._row(
                session_id, child_id, mode, facts, emotion,
                stage="redflag_stopped", status="redflag_stopped",
                severity="高", linked_plan_id=linked_plan_id,
            ))
            return {"session_id": session_id, "redflag": rf.model_dump(),
                    "referral": rf.referral, "card": None}

        warning = check_warning(facts, emotion)
        await self.db.create_session(self._row(
            session_id, child_id, mode, facts, emotion,
            stage="constrained", status="open",
            severity="高" if warning else "低", linked_plan_id=linked_plan_id,
        ))
        return {
            "session_id": session_id,
            "constraints": self._constraint_set(),     # 8 校紅線聯集 ∪ 禁用詞 pattern
            "inquiry_probes": self._inquiry_probes(),  # Maslow/Satir 探點(引導 S1)
            "next": "prerequisites",
        }

    # ── ② prerequisites(必填軸 + 正向紀錄硬閘) ───────────────────

    async def prerequisites(
        self, *, session_id: str, age_band: str | None,
        emotion_intensity: str | None, problem_category: str | None,
        script_decision: str | None,
    ) -> dict[str, Any]:
        s = await self._require_stage(session_id, "constrained")

        if age_band not in AGE_BANDS or emotion_intensity not in INTENSITIES:
            raise PRError(E_MISSING_AXIS, "② 必填:age_band(2-3|4-6|7-11|12+)/ emotion_intensity(低|中|高)")
        if problem_category is not None and problem_category not in PROBLEM_CATEGORIES:
            raise PRError(E_MISSING_AXIS, f"problem_category 不在受控詞表:{problem_category}")

        # 正向紀錄硬閘:缺 script_decision → ask-gate,不解鎖任何後續
        if problem_category == POSITIVE_LOG and script_decision not in SCRIPT_DECISIONS:
            return {"requires": "script_decision",
                    "ask": "這是正向紀錄,需要幫你產生回應劇本嗎?(skip=只記事 / generate=產劇本)"}

        updates: dict[str, Any] = {
            "age_band": age_band, "emotion_intensity": emotion_intensity,
            "problem_category": problem_category,
            "is_positive_log": problem_category == POSITIVE_LOG,
        }
        if emotion_intensity == "高":
            updates["severity"] = self._raise(s.get("severity"), "中")

        if problem_category == POSITIVE_LOG and script_decision == "skip":
            updates["stage"] = "short_pending"
            await self.db.update_session(session_id, updates)
            return {"next": "finalize", "mode": "short"}

        updates["stage"] = "ready"
        await self.db.update_session(session_id, updates)
        return {"next": "core_tags"}

    # ── ③ core_tags(乒乓,可 ×n) ─────────────────────────────────

    async def core_tags(
        self, *, session_id: str, child_reaction: str | None, reaction_note: str | None,
    ) -> dict[str, Any]:
        s = await self._require_stage(session_id, "ready")
        rounds = await self.db.get_rounds(session_id)
        round_no = len(rounds)

        warning_hit = False
        if round_no == 0:
            if child_reaction is not None:
                raise PRError(E_INVALID_STATE, "round 0 不收 child_reaction(spec:round 0 = NULL)")
        else:  # 乒乓輪需 reaction
            if child_reaction not in CHILD_REACTIONS:
                raise PRError(E_INVALID_STATE, f"child_reaction 須 ∈ 六類:{child_reaction}")
            rf = check_shortcircuit(reaction_note if reaction_note else child_reaction)  # G0 複檢
            if rf is not None:
                await self._escalate(session_id, s, rf)
                return {"redflag": rf.model_dump(), "referral": rf.referral, "card": None}
            warning_hit = bool(check_warning(reaction_note))
            if warning_hit and SEVERITY_ORDER[str(s.get("severity") or "低")] < SEVERITY_ORDER["高"]:
                await self.db.update_session(session_id, {"severity": "高"})  # 單調只升不降

        primary: tuple[str, ...] = RESPONSE_CORES  # round 0:6 核心全 primary
        if round_no > 0 and child_reaction is not None:
            primary = REACTION_PRIMARY[child_reaction]

        prev_reaction = rounds[-1].get("child_reaction") if rounds else None
        converged = self._converged(child_reaction, round_no, prev_reaction, warning_hit)

        band = str(s["age_band"])
        stages = {"erikson": ERIKSON_BY_BAND[band],  # 確定性查表,不經 LLM
                  "piaget": PIAGET_BY_BAND[band]}

        await self.db.insert_round(
            session_id, child_reaction=child_reaction, reaction_note=reaction_note,
            card=None, core_outputs={"primary": list(primary)},
            synthesis_trace={}, degraded=False,
        )
        return {"response_tags": self._response_tags(primary), "dev_stages": stages,
                "converged": converged, "next": "core_tags | finalize"}

    # ── ④ finalize(終態;一般 / short) ──────────────────────────

    async def finalize(
        self, *, session_id: str, outcome: str, draft: str | None,
        claimed_sources: list[str] | None, maslow_need: list[str] | None,
        outcome_note: str | None, parent_self_note: str | None, followup: str | None,
    ) -> dict[str, Any]:
        s = await self.db.get_session(session_id)
        if s is None or s["status"] != "open":
            raise PRError(E_INVALID_STATE, f"session {session_id} 不存在或非 open")
        if outcome not in OUTCOMES:
            raise PRError(E_INVALID_STATE, f"outcome 不在受控詞表:{outcome}")
        if claimed_sources is not None:
            unknown = [c for c in claimed_sources if c not in RESPONSE_CORES]
            if unknown:
                raise PRError(E_INVALID_STATE, f"claimed_sources 須 ⊆ 6 回應核心:{unknown}")
        if maslow_need is not None:
            unknown = [n for n in maslow_need if n not in MASLOW_ORDER]
            if unknown:
                raise PRError(E_INVALID_STATE, f"maslow_need 須 ⊆ 缺損四層:{unknown}")

        # G0 複檢(④ 四個自由文本;承「每個入口都是檢查點」)。短路命中不拒收、
        # 不改走 redflag_stopped——④ 紅旗主體多為家長自陳而非進行中乒乓,鎖案無助益;
        # 轉介必達 + severity 標記供 L0 追蹤。命中即落 severity,不因後續拒收而無聲。
        rf = check_shortcircuit(draft, outcome_note, parent_self_note, followup)
        warnings = check_warning(draft, outcome_note, parent_self_note, followup)
        if rf is not None or warnings:
            await self.db.update_session(
                session_id, {"severity": self._raise(s.get("severity"), "高")})

        short = s["stage"] == "short_pending"
        if short:
            if draft is not None:
                raise PRError(E_INVALID_STATE, "short 模式不接受 draft(只記事,不產劇本)")
        else:
            if s["stage"] != "ready":
                raise PRError(E_INVALID_STATE, f"stage={s['stage']} 不可 finalize")
            if draft is None:
                raise PRError(E_INVALID_STATE, "一般模式須交 draft(host 草稿過後檢才落庫)")
            violations = self._pattern_check(draft)  # 禁用詞 code 後檢
            if violations:
                rejected: dict[str, Any] = {"rejected": True, "violations": violations,
                                            "hint": "draft 含禁用詞,請重生後重交(不落庫)"}
                if rf is not None:  # G0 訊號不因拒收而丟失
                    rejected["redflag"] = rf.model_dump()
                    rejected["referral"] = rf.referral
                return rejected

        record = await self._build_record(s, outcome, draft, claimed_sources, maslow_need,
                                          outcome_note, parent_self_note, followup)
        ok = await self._finalize_with_id_retry(
            session_id, terminal_status="finalized",
            session_updates={"stage": "finalized"}, record=record,
        )
        if not ok:
            raise PRError(E_INVALID_STATE, "session 已非 open(併發 finalize 恰一成功)")
        result: dict[str, Any] = {"record_id": record["record_id"]}
        if rf is not None:
            result["redflag"] = rf.model_dump()
            result["referral"] = rf.referral
        elif warnings:
            result["warnings"] = warnings
        return result

    # ── 共用守衛 / 終態 ───────────────────────────────────────────

    async def _require_stage(self, session_id: str, stage: str) -> dict[str, Any]:
        s = await self.db.get_session(session_id)
        if s is None or s["status"] != "open" or s["stage"] != stage:
            raise PRError(E_INVALID_STATE,
                          f"session {session_id} 須在 stage={stage}(實際:{s and s.get('stage')})")
        return s

    async def _escalate(self, session_id: str, s: dict[str, Any], rf: Redflag) -> None:
        record = await self._build_record(
            s, "escalated_to_redflag", None, None, None, rf.reason, None, None,
        )
        ok = await self._finalize_with_id_retry(
            session_id, terminal_status="redflag_stopped",
            session_updates={"severity": "高", "stage": "redflag_stopped"}, record=record,
        )
        if not ok:
            raise PRError(E_INVALID_STATE, "session 已非 open(並發轉移)")

    async def _finalize_with_id_retry(
        self, session_id: str, *, terminal_status: str,
        session_updates: dict[str, Any], record: dict[str, Any],
    ) -> bool:
        # record_id 撞號(同日序號競態)→ 重取重試;UNIQUE(session_id) 由條件式轉移保證不觸發。
        for bump in range(3):
            if bump:
                record["record_id"] = await self._next_record_id()
            try:
                return await self.db.finalize_tx(
                    session_id, terminal_status=terminal_status,
                    session_updates=session_updates, record_row=record,
                )
            except UniqueViolation:
                continue
        raise PRError(E_INVALID_STATE, "record_id 連續撞號,放棄")

    async def _next_record_id(self) -> str:
        prefix = _dt.date.today().strftime("%Y%m%d")
        n = await self.db.count_records_with_prefix(prefix) + 1
        return f"{prefix}-{n:02d}"

    # ── 落庫組裝 ──────────────────────────────────────────────────

    async def _build_record(
        self, s: dict[str, Any], outcome: str, draft: str | None,
        claimed_sources: list[str] | None, maslow_need: list[str] | None,
        outcome_note: str | None, parent_self_note: str | None, followup: str | None,
    ) -> dict[str, Any]:
        band = s.get("age_band")
        linked = s.get("linked_plan_id")
        if outcome == "escalated_to_redflag":
            status = "stopped"  # 紅旗案非可執行計畫,不進任何 promotion 推導
        elif str(s["mode"]) == "rehearsal":
            status = "planned"
        elif linked:
            status = "done_from_plan"
        else:
            status = "done"
        needs: set[str] = set(maslow_need) if maslow_need else set()
        return {
            "record_id": await self._next_record_id(),
            "session_id": s["session_id"],
            "schema_version": 2,
            "status": status,
            "linked_plan_id": linked,
            "dreikurs_purpose": None,  # v3 無判讀來源,恆 NULL(record-schema v2)
            "maslow_need": [n for n in MASLOW_ORDER if n in needs] or None,  # ① 探點命中,host 自報
            "erikson_stage": ERIKSON_BY_BAND[str(band)] if band else None,  # 查表
            "piaget_stage": PIAGET_BY_BAND[str(band)] if band else None,    # 查表
            "dev_normative": None,     # v3 無判讀來源,恆 NULL
            "claimed_sources": claimed_sources,  # host 自報,不可驗(軟溯源)
            "draft": draft,
            "outcome": outcome,
            "outcome_note": outcome_note,
            "parent_self_note": parent_self_note,
            "followup": followup,
            "tools_used": None,        # v2 遺產欄;v3 改記 claimed_sources
            "posture": None,           # v3 無判讀來源,恆 NULL
        }

    # ── 靜態素材(tags.md / wordlists 的 code 出口) ────────────────

    @staticmethod
    def _constraint_set() -> dict[str, Any]:
        """① 約束集 = 8 校紅線聯集 ∪ wordlists 禁用詞 pattern(F2/F3/F5)。"""
        red_lines: list[dict[str, str]] = red_line_union()
        return {
            "red_lines": red_lines,
            "forbidden_patterns": [OUTPUT_PATTERN_F2, OUTPUT_PATTERN_F3, OUTPUT_PATTERN_F5],
        }

    @staticmethod
    def _inquiry_probes() -> dict[str, dict[str, str]]:
        """① 探詢核心(maslow/satir)探點;引導 S1 診斷,不進回應耦合。"""
        return inquiry_probes()

    @staticmethod
    def _response_tags(primary: tuple[str, ...]) -> list[dict[str, Any]]:
        """6 回應核心 TAG,標 primary/support;primary 在前(host 以 primary 領銜耦合)。"""
        tags = response_tags()
        ordered = [*(c for c in RESPONSE_CORES if c in primary),
                   *(c for c in RESPONSE_CORES if c not in primary)]
        return [{"school": c, "role": "primary" if c in primary else "support", "tag": tags[c]}
                for c in ordered]

    @staticmethod
    def _pattern_check(draft: str) -> list[str]:
        """④ 後檢:wordlists 固定禁用詞(F2/F3/F5 投影);命中即拒落庫。"""
        return find_output_violations(draft)

    @staticmethod
    def _converged(
        child_reaction: str | None, round_no: int, prev_reaction: Any, warning_hit: bool,
    ) -> bool:
        """D3 投影(零 LLM):鬆動配合 ∧ 無警訊 ∧ 前一輪非高張力。

        高張力(情緒爆發/退縮害怕)後的第一個鬆動配合 → False(討好式順從防線),
        連續第二輪鬆動配合 → True;round 0 恆 False。
        """
        if round_no == 0 or child_reaction != "鬆動配合" or warning_hit:
            return False
        return str(prev_reaction or "") not in _HIGH_TENSION_REACTIONS

    # ── 推導與工具 ────────────────────────────────────────────────

    @staticmethod
    def _raise(cur: Any, to: str) -> str:
        cur_s = str(cur or "低")
        return to if SEVERITY_ORDER[to] > SEVERITY_ORDER.get(cur_s, 0) else cur_s

    @staticmethod
    def _row(session_id: str, child_id: str, mode: str, facts: str, emotion: str,
             *, stage: str, status: str, severity: str, linked_plan_id: str | None) -> dict[str, Any]:
        return {"session_id": session_id, "child_id": child_id, "mode": mode,
                "stage": stage, "status": status, "facts": facts, "emotion": emotion,
                "severity": severity, "linked_plan_id": linked_plan_id}
