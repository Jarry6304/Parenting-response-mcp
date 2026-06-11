"""編排器:FSM 守衛 → G0 → 單波 fan-out → 合成(v3)→ 後檢 → 落庫 → 聚合回填。

全部「不得違反」在此以 code 斷言;LLM 呼叫永遠在守衛之後(可斷言:違序 LLM 計數 = 0)。
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import uuid
from typing import Any

from . import pingpong
from .cores import fan_out
from .db import Database, UniqueViolation
from .llm import LLMClient
from .redflag import check_shortcircuit, check_warning
from .schema import (
    ALL_CORES,
    CHILD_REACTIONS,
    CONSTRAINT_CORES,
    E_CORES_UNAVAILABLE,
    E_INVALID_LINK,
    E_INVALID_REACTION,
    E_INVALID_STATE,
    E_MISSING_AXIS,
    ERIKSON_BY_BAND,
    MASLOW_ORDER,
    OUTCOMES,
    PIAGET_BY_BAND,
    PRODUCER_CORES,
    SEVERITY_ORDER,
    AnalyzeResult,
    Card,
    Constraint,
    PRError,
    RoundResult,
    SituationInput,
    SynthesisTrace,
    constraint_key,
    parse_constraints,
)
from .postcheck import guardian_check, pattern_check
from .synthesis import (
    SourceVerificationError,
    build_degraded_card,
    dump_card,
    dump_trace,
    make_trace,
    situation_summary_line,
    synthesize_once,
    verify_sources,
)

_SEVERITY_RISK_CONFOUNDERS = {"F1", "F4", "F8"}


class Orchestrator:
    def __init__(
        self,
        db: Database,
        llm: LLMClient,
        *,
        rng: random.Random | None = None,
        retry_n: int = 2,
        k_min: int = 2,
    ) -> None:
        self.db = db
        self.llm = llm
        self.rng = rng or random.Random()
        self.retry_n = retry_n
        self.k_min = k_min

    # ── [2] analyze_situation(S2,內含 G0) ─────────────────────────

    async def analyze(self, raw: dict[str, Any]) -> AnalyzeResult:
        # FSM 守衛:必填軸驗證(E_MISSING_AXIS 的 code 代理),先於一切 LLM。
        try:
            s = SituationInput.model_validate(raw)
        except Exception as exc:
            raise PRError(E_MISSING_AXIS, f"必填軸缺漏或值域外:{exc}") from exc

        # 守衛:linked_plan_id 須指向存在且 status=planned 的 record(A2)。
        if s.linked_plan_id is not None:
            rec = await self.db.get_record(s.linked_plan_id)
            if rec is None or rec.get("status") != "planned":
                raise PRError(E_INVALID_LINK, f"linked_plan_id={s.linked_plan_id} 不存在或非 planned")

        session_id = uuid.uuid4().hex

        # G0 短路級預篩(零核心呼叫;A1:sessions 一列、rounds 零列)。
        rf = check_shortcircuit(s.facts, s.emotion)
        if rf is not None:
            await self.db.create_session(self._session_row(session_id, s, status="redflag_stopped", severity="高"))
            return AnalyzeResult(session_id=session_id, card=None, synthesis_trace=None, redflag=rf)

        warnings = check_warning(s.facts, s.emotion)

        situation = self._situation_dict(s.model_dump(), round_no=0, history=[])
        payload = self._payload(situation)

        # 單波 fan-out:全 10 核心隔離並行。
        outputs = await fan_out(list(ALL_CORES), payload, self.llm)

        if not any(outputs.get(p) for p in PRODUCER_CORES):
            raise PRError(E_CORES_UNAVAILABLE, "産招核心全數失敗,不出卡")

        constraints = parse_constraints(outputs)
        card, trace, degraded = await self._pipeline(
            situation=situation, called=list(ALL_CORES), outputs=outputs, constraints=constraints
        )

        severity = self._severity(s, warning_hit=bool(warnings), constraint_count=len(constraints))
        await self.db.create_session(self._session_row(session_id, s, status="open", severity=severity))
        await self.db.insert_round(
            session_id, child_reaction=None, reaction_note=None,
            card=dump_card(card), core_outputs=outputs, synthesis_trace=dump_trace(trace),
            degraded=degraded,
        )
        return AnalyzeResult(
            session_id=session_id, card=card, synthesis_trace=trace, redflag=None, degraded=degraded
        )

    # ── [3] next_round(S3 乒乓) ──────────────────────────────────

    async def next_round(
        self, session_id: str, child_reaction: str, reaction_note: str | None = None
    ) -> RoundResult:
        # FSM 守衛(先於一切 LLM):session 存在 ∧ open ∧ round 0 存在。
        session = await self.db.get_session(session_id)
        if session is None or session["status"] != "open":
            raise PRError(E_INVALID_STATE, f"session {session_id} 不存在或非 open")
        rounds = await self.db.get_rounds(session_id)
        if not rounds:
            raise PRError(E_INVALID_STATE, "round 0 不存在")
        if child_reaction not in CHILD_REACTIONS:
            raise PRError(E_INVALID_REACTION, f"child_reaction 須 ∈ 六類,收到:{child_reaction}")

        # G0 複檢(對 reaction_note;空則對 child_reaction 字面——六類受控值必不命中)。
        rf = check_shortcircuit(reaction_note if reaction_note else child_reaction)
        if rf is not None:
            record = await self._build_record(
                session, rounds, outcome="escalated_to_redflag",
                outcome_note=rf.reason, parent_self_note=None, followup=None,
            )
            ok = await self._finalize_with_id_retry(
                session_id, terminal_status="redflag_stopped",
                session_updates={
                    "severity": "高",
                    "goal_aligned": self._goal_aligned(session.get("parent_goal"), "escalated_to_redflag"),
                },
                record=record,
            )
            if not ok:
                raise PRError(E_INVALID_STATE, "session 已非 open(並發轉移)")
            return RoundResult(card=None, synthesis_trace=None, converged=False, redflag=rf)

        warnings = check_warning(reaction_note)
        if warnings and SEVERITY_ORDER[str(session.get("severity") or "低")] < SEVERITY_ORDER["高"]:
            await self.db.update_session(session_id, {"severity": "高"})  # 單調只升不降

        prev_reaction = rounds[-1].get("child_reaction")
        cores, r_plus = pingpong.ignition_set(child_reaction, prev_reaction)

        next_no = int(rounds[-1]["round_no"]) + 1
        history = [
            {"round_no": r["round_no"], "child_reaction": r["child_reaction"], "reaction_note": r.get("reaction_note")}
            for r in rounds
            if r["round_no"] > 0
        ]
        history.append({"round_no": next_no, "child_reaction": child_reaction, "reaction_note": reaction_note})

        situation = self._situation_dict(session, round_no=next_no, history=history)
        payload = self._payload(situation)
        outputs = await fan_out(cores, payload, self.llm)

        if not any(outputs.get(p) for p in PRODUCER_CORES if p in cores):
            raise PRError(E_CORES_UNAVAILABLE, "本輪産招核心全數失敗,不出卡")

        # 約束跨輪沿用:歷輪 ∪ 本輪,(type, rule) 去重(pingpong.md)。
        prev_constraints: list[Constraint] = []
        for r in rounds:
            prev_constraints.extend(parse_constraints(r["core_outputs"]))
        new_constraints = parse_constraints(outputs)
        known_types = {c.type for c in prev_constraints}
        merged: dict[tuple[str, str], Constraint] = {constraint_key(c): c for c in prev_constraints}
        for c in new_constraints:
            merged.setdefault(constraint_key(c), c)
        accumulated = list(merged.values())

        card, trace, degraded = await self._pipeline(
            situation=situation, called=cores, outputs=outputs, constraints=accumulated
        )

        converged = False
        if not degraded:
            converged = pingpong.compute_converged(
                reaction=child_reaction, r_plus=r_plus, round_outputs=outputs,
                new_constraints=new_constraints, known_types=known_types,
                warning_hit=bool(warnings),
            )

        await self.db.insert_round(
            session_id, child_reaction=child_reaction, reaction_note=reaction_note,
            card=dump_card(card), core_outputs=outputs, synthesis_trace=dump_trace(trace),
            degraded=degraded,
        )
        return RoundResult(
            card=card, synthesis_trace=trace, converged=converged, redflag=None, degraded=degraded
        )

    # ── [4] finalize_record(S4;不進 LLM 管線) ──────────────────

    async def finalize(
        self,
        session_id: str,
        outcome: str,
        outcome_note: str | None = None,
        parent_self_note: str | None = None,
        followup: str | None = None,
    ) -> dict[str, str]:
        session = await self.db.get_session(session_id)
        if session is None or session["status"] != "open":
            raise PRError(E_INVALID_STATE, f"session {session_id} 不存在或非 open")
        rounds = await self.db.get_rounds(session_id)
        if not rounds:
            raise PRError(E_INVALID_STATE, "round 0 不存在")
        if outcome not in OUTCOMES:
            raise PRError(E_INVALID_STATE, f"outcome 不在受控詞表:{outcome}")

        record = await self._build_record(
            session, rounds, outcome=outcome, outcome_note=outcome_note,
            parent_self_note=parent_self_note, followup=followup,
        )
        ok = await self._finalize_with_id_retry(
            session_id, terminal_status="finalized",
            session_updates={"goal_aligned": self._goal_aligned(session.get("parent_goal"), outcome)},
            record=record,
        )
        if not ok:
            raise PRError(E_INVALID_STATE, "session 已非 open(併發 finalize 恰一成功)")
        return {"record_id": record["record_id"]}

    # ── 合成 + 後檢管線(retry ≤ N;A5 降級) ─────────────────────

    async def _pipeline(
        self,
        *,
        situation: dict[str, Any],
        called: list[str],
        outputs: dict[str, dict[str, Any] | None],
        constraints: list[Constraint],
    ) -> tuple[Card, SynthesisTrace, bool]:
        summary = situation_summary_line(situation)
        inputs_seen = [c for c in called if outputs.get(c)]
        k_available = sum(1 for c in called if c in CONSTRAINT_CORES and outputs.get(c))
        presentation_order: list[str] = []

        if k_available < self.k_min:
            # A5:約束核心可用 < K → 合成完直接降級,正常卡不出。
            try:
                _card, _sa, _dv, presentation_order = await synthesize_once(
                    situation_summary=summary, core_outputs=outputs,
                    constraints=constraints, llm=self.llm, rng=self.rng,
                )
            except Exception:
                presentation_order = []
            return self._degraded(called, outputs, constraints, presentation_order)

        for _ in range(self.retry_n + 1):
            try:
                card, set_aside, divergences, order = await synthesize_once(
                    situation_summary=summary, core_outputs=outputs,
                    constraints=constraints, llm=self.llm, rng=self.rng,
                )
                presentation_order = order
                verify_sources(card, inputs_seen)  # 溯源驗證:code,零 LLM 成本
            except SourceVerificationError:
                continue  # 退回重生
            except Exception:
                continue
            if pattern_check(card, constraints):
                continue  # 禁用詞 → 重生
            if await guardian_check(card, constraints, self.llm):
                continue  # 語意違約束 → 重生
            trace = make_trace(
                called=called, core_outputs=outputs, presentation_order=presentation_order,
                card=card, set_aside=set_aside, divergences=divergences,
            )
            return card, trace, False

        return self._degraded(called, outputs, constraints, presentation_order)

    def _degraded(
        self,
        called: list[str],
        outputs: dict[str, dict[str, Any] | None],
        constraints: list[Constraint],
        presentation_order: list[str],
    ) -> tuple[Card, SynthesisTrace, bool]:
        card = build_degraded_card(constraints)
        trace = make_trace(
            called=called, core_outputs=outputs, presentation_order=presentation_order,
            card=card, set_aside=[], divergences=[],
        )
        return card, trace, True

    # ── A3 聚合回填(record-schema.md 規則) ──────────────────────

    async def _build_record(
        self,
        session: dict[str, Any],
        rounds: list[dict[str, Any]],
        *,
        outcome: str,
        outcome_note: str | None,
        parent_self_note: str | None,
        followup: str | None,
    ) -> dict[str, Any]:
        purpose: str | None = None
        maslow_seen = False
        needs: set[str] = set()
        erikson_stage: str | None = None
        erikson_norm: bool | None = None
        piaget_stage: str | None = None
        piaget_norm: bool | None = None
        tools: set[str] = set()
        posture: str | None = None

        for r in rounds:
            co: dict[str, Any] = r["core_outputs"]
            if co.get("dreikurs"):
                purpose = co["dreikurs"].get("purpose")  # 判讀類取最後
            if co.get("maslow"):
                maslow_seen = True
                needs |= set(co["maslow"].get("unmet_needs", []))
            if co.get("erikson"):
                erikson_stage = co["erikson"].get("stage_observed")
                erikson_norm = co["erikson"].get("within_norm")
            if co.get("piaget"):
                piaget_stage = co["piaget"].get("stage_observed")
                piaget_norm = co["piaget"].get("within_norm")
            for src in r["synthesis_trace"].get("utterance_sources", []):
                tools.add(src["core"])  # 溯源即貢獻(resonance v3)
            if not r.get("degraded"):
                posture = r["card"].get("posture")  # 最後一張非降級卡

        if purpose == "不明":
            purpose = None
        band = str(session["age_band"])
        dev_normative: bool | None
        if erikson_norm is None and piaget_norm is None:
            dev_normative = None
        elif erikson_norm is None:
            dev_normative = piaget_norm
        elif piaget_norm is None:
            dev_normative = erikson_norm
        else:
            dev_normative = erikson_norm and piaget_norm

        mode = str(session["mode"])
        linked = session.get("linked_plan_id")
        if mode == "rehearsal":
            status = "planned"
        elif linked:
            status = "done_from_plan"
        else:
            status = "done"

        return {
            "record_id": await self._next_record_id(),
            "session_id": session["session_id"],
            "schema_version": 1,
            "status": status,
            "linked_plan_id": linked,
            "dreikurs_purpose": purpose,
            "maslow_need": [n for n in MASLOW_ORDER if n in needs] if maslow_seen else None,
            "erikson_stage": erikson_stage or ERIKSON_BY_BAND[band],
            "piaget_stage": piaget_stage or PIAGET_BY_BAND[band],
            "dev_normative": dev_normative,
            "outcome": outcome,
            "outcome_note": outcome_note,
            "parent_self_note": parent_self_note,
            "followup": followup,
            "tools_used": [c for c in ALL_CORES if c in tools],
            "posture": posture,
        }

    async def _finalize_with_id_retry(
        self,
        session_id: str,
        *,
        terminal_status: str,
        session_updates: dict[str, Any],
        record: dict[str, Any],
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

    # ── 推導與工具 ────────────────────────────────────────────────

    @staticmethod
    def _goal_aligned(parent_goal: Any, outcome: str) -> bool | None:
        if not parent_goal:
            return None
        if outcome == "resolved":
            return True
        if outcome == "partial":
            return None  # 不可判,不臆測
        return False

    @staticmethod
    def _severity(s: SituationInput, *, warning_hit: bool, constraint_count: int) -> str:
        if s.safety_flag or warning_hit:
            return "高"
        if (
            s.emotion_intensity == "高"
            or (set(s.confounders or []) & _SEVERITY_RISK_CONFOUNDERS)
            or constraint_count >= 4
        ):
            return "中"
        return "低"

    @staticmethod
    def _session_row(session_id: str, s: SituationInput, *, status: str, severity: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "child_id": s.child_id,
            "mode": s.mode,
            "status": status,
            "age_band": s.age_band,
            "facts": s.facts,
            "emotion": s.emotion,
            "emotion_intensity": s.emotion_intensity,
            "safety_flag": s.safety_flag,
            "severity": severity,
            "is_positive_log": s.problem_category == "正向紀錄",
            "problem_category": s.problem_category,
            "confounders": list(s.confounders) if s.confounders else None,
            "parent_goal": s.parent_goal,
            "goal_aligned": None,
            "linked_plan_id": s.linked_plan_id,
        }

    @staticmethod
    def _situation_dict(
        source: dict[str, Any], *, round_no: int, history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """核心輸入情境(cores/README 輸入契約;嚴格隔離:無 linked_plan、無卡文)。"""
        return {
            "mode": source["mode"],
            "age_band": source["age_band"],
            "facts": source["facts"],
            "emotion": source["emotion"],
            "emotion_intensity": source["emotion_intensity"],
            "safety_flag": bool(source.get("safety_flag")),
            "problem_category": source.get("problem_category"),
            "confounders": source.get("confounders"),
            "parent_goal": source.get("parent_goal"),
            "round_no": round_no,
            "history": history,
        }

    @staticmethod
    def _payload(situation: dict[str, Any]) -> str:
        payload = json.dumps(situation, ensure_ascii=False)
        assert "linked_plan" not in payload  # 嚴格隔離可斷言(縫補裁決)
        return payload
