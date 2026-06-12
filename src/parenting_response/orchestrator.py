"""編排器(v3.2):FSM 守衛 → G0 訊號 → 回傳靜態 TAG / safety 卡 → 後檢 → 落庫。**全程零 LLM。**

不變量(可斷言:無 LLM client 物件):
  FSM stage:constrained → {ready|short_pending} → finalized(終態另有 TTL 之 expired)
  違 stage 呼叫一律 E_INVALID_STATE,零成本
  records UNIQUE(session_id);status 條件式轉移 WHERE status='open'

v3.2 A 件:G0 由閘降為訊號——輸入命中**不擋、不停案、FSM 照常推進**;
強制力集中輸出匣:③ 換 safety 約束集、④ 須 referral_ack、record.redflag 排除 promotion。
redflag_stopped 自 v3.2 移除(legacy 列保留,查詢視同 closed)。
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

from .cores import inquiry_probes, red_line_union, response_tags, safety_cards
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
    REFERRAL_TEXT,
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

# record_id 的「當日」= 臺北日,與部署主機時區無關(record-schema);
# 台灣自 1980 無夏令時,固定 +8 免 tzdata 依賴
_TZ_TAIPEI = _dt.timezone(_dt.timedelta(hours=8))


class Orchestrator:
    def __init__(self, db: Database, *, session_ttl_days: int = 30) -> None:
        self.db = db
        self.session_ttl_days = session_ttl_days  # ≤0 = 停用棄案清掃
        # 注意:無 self.llm —— v3 零推論,刻意不收 LLM client

    # ── ① constraints(約束探詢,內含 G0) ─────────────────────────

    async def constraints(
        self, *, facts: str | None, emotion: str | None, mode: str | None,
        child_id: str, linked_plan_id: str | None,
    ) -> dict[str, Any]:
        if not facts or not emotion or mode not in MODES:
            raise PRError(E_MISSING_AXIS, "① 必要:facts / emotion / mode(live|rehearsal)")

        # 棄案 TTL(lazy 清掃):host 斷線遺留的 open 案逾期轉吸收態 expired,
        # 不產 record;severity 留在 sessions 供 L0 追蹤。錨定最後活動而非建案時間。
        if self.session_ttl_days > 0:
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=self.session_ttl_days)
            await self.db.expire_stale_sessions(cutoff)

        # linked_plan 守衛(承 v2.2 A2 + v3.2 A 件):須指向存在且 status=planned 的
        # record;紅旗案不可引用——redflag=true 為 v3.2 主錨,status/outcome 為 legacy
        # 縱深防禦(雙保險,兼擋 v1 遺留之 planned+escalated 列)。
        if linked_plan_id is not None:
            rec = await self.db.get_record(linked_plan_id)
            if (rec is None or rec.get("status") != "planned"
                    or rec.get("outcome") == "escalated_to_redflag"
                    or rec.get("redflag") is True):
                raise PRError(E_INVALID_LINK,
                              f"linked_plan_id={linked_plan_id} 不存在、非 planned 或為紅旗案")

        session_id = uuid.uuid4().hex
        labeled = (("facts", facts), ("emotion", emotion))

        # G0(v3.2 A 件:訊號,不停案)——短路命中照常建案,旗標+severity=高,
        # FSM 照常推進;強制力由輸出匣承接(③ safety 卡、④ referral_ack)。
        rf = check_shortcircuit(labeled)
        warning_hits = check_warning(labeled)
        await self.db.create_session(self._row(
            session_id, child_id, mode, facts, emotion,
            stage="constrained", status="open",
            severity="高" if (rf is not None or warning_hits) else "低",
            linked_plan_id=linked_plan_id,
            redflag_active=rf is not None,
            redflag_vector=rf.vector if rf is not None else None,
        ))
        if rf is not None or warning_hits:
            await self._log_g0(session_id, "①", rf=rf, warnings=warning_hits)
        result: dict[str, Any] = {
            "session_id": session_id,
            "constraints": self._constraint_set(),     # 8 校紅線聯集 ∪ 禁用詞 pattern
            "inquiry_probes": self._inquiry_probes(),  # Maslow/Satir 探點(引導 S1)
            "next": "prerequisites",
        }
        if rf is not None:  # 轉介必達 + safety_mode 標記(內容換軌在 ③)
            result["redflag"] = rf.model_dump()
            result["referral"] = rf.referral
            result["safety_mode"] = True
        return result

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

        rf: Redflag | None = None
        warning_hit = False
        if round_no == 0:
            if child_reaction is not None:
                raise PRError(E_INVALID_STATE, "round 0 不收 child_reaction(spec:round 0 = NULL)")
        else:  # 乒乓輪需 reaction
            if child_reaction not in CHILD_REACTIONS:
                raise PRError(E_INVALID_STATE, f"child_reaction 須 ∈ 六類:{child_reaction}")
            # 高張力輪強制轉述(硬閘,與 ② script_decision 同型):紅旗複檢的風險
            # 集中在高張力輪,G0 有效性不可繫於 host 自律;非高張力無轉述 → 跳過複檢(已知軟點)。
            if child_reaction in _HIGH_TENSION_REACTIONS and not reaction_note:
                return {"requires": "reaction_note",
                        "ask": "孩子有情緒爆發/退縮反應,請轉述他實際說了什麼或做了什麼(G0 複檢需要)"}
            labeled = (("reaction_note", reaction_note),)
            rf = check_shortcircuit(labeled)  # G0 複檢(None-safe;高張力輪必有轉述)
            warning_hits = check_warning(labeled)
            warning_hit = bool(warning_hits)
            if rf is not None:
                # v3.2 A 件:命中 → 訊號(旗標+severity 單調升),照常推進本輪,不收案
                await self.db.update_session(session_id, self._redflag_updates(s, rf))
                s = {**s, "redflag_active": True,
                     "redflag_vector": s.get("redflag_vector") or rf.vector}
            elif warning_hit and SEVERITY_ORDER[str(s.get("severity") or "低")] < SEVERITY_ORDER["高"]:
                await self.db.update_session(session_id, {"severity": "高"})  # 單調只升不降
            if rf is not None or warning_hits:
                await self._log_g0(session_id, "③", rf=rf, warnings=warning_hits,
                                   round_no=round_no)

        primary: tuple[str, ...] = RESPONSE_CORES  # round 0:6 核心全 primary
        if round_no > 0 and child_reaction is not None:
            primary = REACTION_PRIMARY[child_reaction]

        safety_mode = bool(s.get("redflag_active"))
        prior_reactions: list[str | None] = [r.get("child_reaction") for r in rounds]
        # safety_mode 下不出收斂訊號——D3 是管教乒乓的規則,危機陪伴不適用
        converged = (False if safety_mode
                     else self._converged(child_reaction, round_no, prior_reactions, warning_hit))

        band = str(s["age_band"])
        stages = {"erikson": ERIKSON_BY_BAND[band],  # 確定性查表,不經 LLM(與風險無關,照回)
                  "piaget": PIAGET_BY_BAND[band]}

        await self.db.insert_round(
            session_id, child_reaction=child_reaction, reaction_note=reaction_note,
            card=None, core_outputs={"primary": list(primary)},
            synthesis_trace={"converged": converged}, degraded=False,
        )
        result: dict[str, Any]
        if safety_mode:
            # v3.2 安全約束集換軌:不出一般管教 TAG——家長當下最需要的是
            # 「現在該說什麼」(陪伴/傾聽/降溫+轉介),內容換軌、不斷供。
            vector = str(s.get("redflag_vector") or "child")  # 理論不可達之防禦:取最保守向
            result = {"safety_mode": True,
                      "safety_tags": safety_cards(vector, band),
                      "dev_stages": stages, "converged": converged,
                      "next": "core_tags | finalize"}
        else:
            result = {"response_tags": self._response_tags(primary), "dev_stages": stages,
                      "converged": converged, "next": "core_tags | finalize"}
        if rf is not None:  # 本輪命中:轉介必達
            result["redflag"] = rf.model_dump()
            result["referral"] = rf.referral
        return result

    # ── ④ finalize(終態;一般 / short) ──────────────────────────

    async def finalize(
        self, *, session_id: str, outcome: str, draft: str | None,
        claimed_sources: list[str] | None, maslow_need: list[str] | None,
        outcome_note: str | None, parent_self_note: str | None, followup: str | None,
        referral_ack: bool | None = None,
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

        # G0 複檢(④ 四個自由文本;承「每個入口都是檢查點」)。短路命中不拒收——
        # ④ 紅旗主體多為家長自陳而非進行中乒乓,鎖案無助益;旗標+severity 落庫、
        # 轉介必達,不因後續拒收而無聲。
        labeled = (("draft", draft), ("outcome_note", outcome_note),
                   ("parent_self_note", parent_self_note), ("followup", followup))
        rf = check_shortcircuit(labeled)
        warning_hits = check_warning(labeled)
        warnings = [p for _, p in warning_hits]  # 回傳形狀維持詞組列(回溯相容)
        if rf is not None:
            await self.db.update_session(session_id, self._redflag_updates(s, rf))
        elif warning_hits:
            await self.db.update_session(
                session_id, {"severity": self._raise(s.get("severity"), "高")})
        if rf is not None or warning_hits:
            await self._log_g0(session_id, "④", rf=rf, warnings=warning_hits)

        # v3.2 A 件落庫前置:旗標在案(含本次 ④ 才命中者)→ 轉介必須已向家長送達,
        # host 以 referral_ack=true 確認;缺則 E_MISSING_AXIS(訊號已落,不丟)。
        redflag_now = bool(s.get("redflag_active")) or rf is not None
        if redflag_now and referral_ack is not True:
            raise PRError(
                E_MISSING_AXIS,
                f"紅旗訊號在案:④ 須帶 referral_ack=true(請先向家長送達轉介:{REFERRAL_TEXT})",
            )

        short = s["stage"] == "short_pending"
        if short:
            if draft is not None:
                raise PRError(E_INVALID_STATE, "short 模式不接受 draft(只記事,不產劇本)")
        else:
            if s["stage"] != "ready":
                raise PRError(E_INVALID_STATE, f"stage={s['stage']} 不可 finalize")
            rounds = await self.db.get_rounds(session_id)
            if not rounds:  # FSM:core_tags → finalize;不取 TAG 不得交稿
                raise PRError(E_INVALID_STATE, "一般模式須先 ③ core_tags 至少一輪(round 0 起手)")
            if draft is None:
                raise PRError(E_INVALID_STATE, "一般模式須交 draft(host 草稿過後檢才落庫)")
            violations = self._pattern_check(draft)  # 禁用詞 code 後檢
            if violations:
                # 拒收稽核(defect-fixes #7):重試軌跡可考——host 踩了哪些詞、是否屢試
                await self.db.log_event(session_id, "finalize_rejected", {
                    "violations": violations, "outcome": outcome,
                    "redflag_hit": rf is not None,
                })
                rejected: dict[str, Any] = {"rejected": True, "violations": violations,
                                            "hint": "draft 含禁用詞,請重生後重交(不落庫)"}
                if rf is not None:  # G0 訊號不因拒收而丟失
                    rejected["redflag"] = rf.model_dump()
                    rejected["referral"] = rf.referral
                return rejected

        record = await self._build_record(s, outcome, draft, claimed_sources, maslow_need,
                                          outcome_note, parent_self_note, followup,
                                          redflag=redflag_now)
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

    async def _log_g0(
        self, session_id: str, source: str, *, rf: Redflag | None,
        warnings: list[tuple[str, str]], round_no: int | None = None,
    ) -> None:
        """G0 稽核落庫(defect-fixes #7/#8):欄位/詞組/節錄與轉介送達,事後可重建。

        「曾接觸紅旗之案」= events.kind=g0_shortcircuit ∪ outcome=escalated_to_redflag
        (④ 命中不拒收的列 record 外觀正常,證據只在 events)。
        """
        base: dict[str, Any] = {"source": source}
        if round_no is not None:
            base["round_no"] = round_no
        if rf is not None:
            await self.db.log_event(session_id, "g0_shortcircuit", {
                **base, "field": rf.field, "phrase": rf.phrase, "excerpt": rf.excerpt,
                "vector": rf.vector,         # 風險向(v3.2 G 件:組卡緣由可重建)
                "referral_delivered": True,  # 命中路徑回傳必含 referral(by construction)
            })
        if warnings:
            await self.db.log_event(session_id, "g0_warning", {
                **base, "hits": [{"field": f, "phrase": p} for f, p in warnings],
            })

    def _redflag_updates(self, s: dict[str, Any], rf: Redflag) -> dict[str, Any]:
        """短路命中之 session 訊號更新(v3.2 A 件):旗標升、severity 升、
        風險向首見寫入後不覆寫——三者皆單調,後續任何操作不得降。"""
        updates: dict[str, Any] = {
            "redflag_active": True,
            "severity": self._raise(s.get("severity"), "高"),
        }
        if not s.get("redflag_vector"):
            updates["redflag_vector"] = rf.vector
        return updates

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
        prefix = _dt.datetime.now(_TZ_TAIPEI).strftime("%Y%m%d")
        n = await self.db.count_records_with_prefix(prefix) + 1
        return f"{prefix}-{n:02d}"

    # ── 落庫組裝 ──────────────────────────────────────────────────

    async def _build_record(
        self, s: dict[str, Any], outcome: str, draft: str | None,
        claimed_sources: list[str] | None, maslow_need: list[str] | None,
        outcome_note: str | None, parent_self_note: str | None, followup: str | None,
        *, redflag: bool = False,
    ) -> dict[str, Any]:
        band = s.get("age_band")
        linked = s.get("linked_plan_id")
        if outcome == "escalated_to_redflag":
            status = "stopped"  # legacy 受控詞(host 可自交);v3.2 promotion 排除主錨 = redflag
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
            "schema_version": 3,
            "status": status,
            "linked_plan_id": linked,
            "dreikurs_purpose": None,  # v3 無判讀來源,恆 NULL(record-schema v3)
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
            "redflag": redflag,        # v3.2 A 件:promotion 排除錨(不可變)
            "parent_action": s.get("parent_action"),  # v3.2 B 件:retro 當時實際處理
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
        child_reaction: str | None, round_no: int,
        prior_reactions: list[str | None], warning_hit: bool,
    ) -> bool:
        """D3 投影(零 LLM;單一來源 = spec v3.0「converged 判定表」):
        鬆動配合 ∧ 無警訊 ∧ 自最近一次高張力反應後已有 ≥1 輪鬆動配合。

        高張力(情緒爆發/退縮害怕)與鬆動之間夾其他反應**不重置**防線——
        討好式順從常見軌跡「爆發→嘴硬→順從」不得洗白;無高張力史 → 首個鬆動
        即 True;round 0 恆 False。
        """
        if round_no == 0 or child_reaction != "鬆動配合" or warning_hit:
            return False
        eased = 0
        for prev in reversed(prior_reactions):  # 反向掃描至最近一次高張力
            if prev == "鬆動配合":
                eased += 1
            elif str(prev or "") in _HIGH_TENSION_REACTIONS:
                return eased >= 1
        return True  # 無高張力史

    # ── 推導與工具 ────────────────────────────────────────────────

    @staticmethod
    def _raise(cur: Any, to: str) -> str:
        cur_s = str(cur or "低")
        return to if SEVERITY_ORDER[to] > SEVERITY_ORDER.get(cur_s, 0) else cur_s

    @staticmethod
    def _row(session_id: str, child_id: str, mode: str, facts: str, emotion: str,
             *, stage: str, status: str, severity: str, linked_plan_id: str | None,
             redflag_active: bool = False, redflag_vector: str | None = None) -> dict[str, Any]:
        return {"session_id": session_id, "child_id": child_id, "mode": mode,
                "stage": stage, "status": status, "facts": facts, "emotion": emotion,
                "severity": severity, "linked_plan_id": linked_plan_id,
                "redflag_active": redflag_active, "redflag_vector": redflag_vector}
