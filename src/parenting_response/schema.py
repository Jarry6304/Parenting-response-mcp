"""受控詞表 + constraint + pydantic models + 錯誤碼(spec v2.2 / record-schema.md / resonance v3)。

卡欄位 zh ↔ code 對照:判讀=reading、姿態=posture、起手話術=opening_utterances、
觀察點=watchpoints、界線=boundary、紅線=redline、來源摘要=source_summary。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── 錯誤碼(spec v2.2 錯誤處理節) ──────────────────────────────────

E_MISSING_AXIS = "E_MISSING_AXIS"
E_INVALID_STATE = "E_INVALID_STATE"
E_INVALID_REACTION = "E_INVALID_REACTION"
E_INVALID_LINK = "E_INVALID_LINK"
# spec 錯誤處理表「産招全失敗 → 回錯誤不出卡」,未配碼;本實作以此碼承載。
E_CORES_UNAVAILABLE = "E_CORES_UNAVAILABLE"


class PRError(Exception):
    """攜帶錯誤碼的領域錯誤;server 層轉 ToolError。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# ── 受控詞表(record-schema.md 鎖定值域) ──────────────────────────

Mode = Literal["live", "rehearsal"]
AgeBand = Literal["2-3", "4-6", "7-11", "12+"]  # 0-2 刻意範圍外(C3)
EmotionIntensity = Literal["低", "中", "高"]
Severity = Literal["低", "中", "高"]
SessionStatus = Literal["open", "finalized", "redflag_stopped"]
RecordStatus = Literal["planned", "done", "done_from_plan"]

ChildReaction = Literal["鬆動配合", "否認堅持", "情緒爆發", "退縮害怕", "反問試探", "轉移打岔"]
CHILD_REACTIONS: tuple[str, ...] = ("鬆動配合", "否認堅持", "情緒爆發", "退縮害怕", "反問試探", "轉移打岔")

Outcome = Literal["resolved", "partial", "unresolved", "escalated_to_redflag"]
OUTCOMES: tuple[str, ...] = ("resolved", "partial", "unresolved", "escalated_to_redflag")

Posture = Literal["同理接住", "情緒教練", "溫和設限", "給選擇", "自然後果", "共同解題", "修復關係", "退場降溫"]

ProblemCategory = Literal[
    "作息睡眠", "飲食", "3C使用", "課業學習", "手足衝突", "同儕學校", "情緒行為",
    "公共場合", "生活自理", "安全行為", "頂嘴禮貌", "誠實", "正向紀錄", "其他",
]

Confounder = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]

ConstraintType = Literal["需求不踩底", "不損自我", "不超齡-心理社會", "不超齡-認知"]

CoreId = Literal["pd", "dreikurs", "gottman", "nvc", "rogers", "adler", "maslow", "satir", "erikson", "piaget"]
PRODUCER_CORES: tuple[str, ...] = ("pd", "dreikurs", "gottman", "nvc", "rogers")
PERSPECTIVE_CORES: tuple[str, ...] = ("adler",)
CONSTRAINT_CORES: tuple[str, ...] = ("maslow", "satir", "erikson", "piaget")
ALL_CORES: tuple[str, ...] = PRODUCER_CORES + PERSPECTIVE_CORES + CONSTRAINT_CORES

DreikursPurpose = Literal["關注", "權力", "報復", "自暴自棄", "不明"]
MaslowNeed = Literal["生理", "安全", "愛與歸屬", "尊重"]
MASLOW_ORDER: tuple[str, ...] = ("生理", "安全", "愛與歸屬", "尊重")
EriksonStage = Literal["自主對羞愧懷疑", "主動對罪惡感", "勤奮對自卑", "認同對角色混淆"]
PiagetStage = Literal["前運思期", "具體運思期", "形式運思期"]
SatirStance = Literal["討好", "指責", "超理智", "打岔", "一致", "不明"]

# age_band ↔ 發展階段預設映射(record-schema.md;聚合缺席時回填)
ERIKSON_BY_BAND: dict[str, str] = {
    "2-3": "自主對羞愧懷疑", "4-6": "主動對罪惡感", "7-11": "勤奮對自卑", "12+": "認同對角色混淆",
}
PIAGET_BY_BAND: dict[str, str] = {
    "2-3": "前運思期", "4-6": "前運思期", "7-11": "具體運思期", "12+": "形式運思期",
}

SEVERITY_ORDER: dict[str, int] = {"低": 0, "中": 1, "高": 2}


# ── tool 輸入(必填軸驗證 = E_MISSING_AXIS 的 code 代理) ──────────

class SituationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    age_band: AgeBand
    facts: str = Field(min_length=1)
    emotion: str = Field(min_length=1)
    emotion_intensity: EmotionIntensity
    safety_flag: bool = False
    problem_category: ProblemCategory | None = None
    confounders: list[Confounder] | None = None
    parent_goal: str | None = None
    child_id: str = "C1"
    linked_plan_id: str | None = None


# ── constraint 物件(cores/README 契約) ───────────────────────────

class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ConstraintType
    rule: str = Field(min_length=1)
    checkable_by: Literal["pattern", "guardian"]
    forbidden_terms: list[str] = Field(default_factory=list[str])

    @model_validator(mode="after")
    def _pattern_needs_terms(self) -> "Constraint":
        if self.checkable_by == "pattern" and not self.forbidden_terms:
            raise ValueError("pattern 型 constraint 必須附 forbidden_terms")
        return self


# ── 核心輸出契約(references/cores/*.md;欄位名即 de facto 契約) ──

class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posture: Posture
    utterance: str = Field(min_length=1)


class ProducerOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    candidate: Candidate
    analysis: str
    confidence: float = Field(ge=0.0, le=1.0)


class DreikursOutput(ProducerOutput):
    purpose: DreikursPurpose


class GottmanOutput(ProducerOutput):
    emotion_processed: bool | None = None  # pingpong C2 的 code 判讀來源


class AdlerOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    analysis: str


class ConstraintCoreOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    analysis: str
    constraints: list[Constraint] = Field(default_factory=list[Constraint])


class MaslowOutput(ConstraintCoreOutput):
    unmet_needs: list[MaslowNeed] = Field(default_factory=list[MaslowNeed])


class SatirOutput(ConstraintCoreOutput):
    child_stance: SatirStance
    parent_stance: SatirStance


class EriksonOutput(ConstraintCoreOutput):
    stage_observed: EriksonStage
    within_norm: bool


class PiagetOutput(ConstraintCoreOutput):
    stage_observed: PiagetStage
    within_norm: bool


CORE_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "pd": ProducerOutput,
    "dreikurs": DreikursOutput,
    "gottman": GottmanOutput,
    "nvc": ProducerOutput,
    "rogers": ProducerOutput,
    "adler": AdlerOutput,
    "maslow": MaslowOutput,
    "satir": SatirOutput,
    "erikson": EriksonOutput,
    "piaget": PiagetOutput,
}


# ── 卡(v2 建議卡 + v3 來源摘要) ─────────────────────────────────

class OpeningUtterance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    source: CoreId  # v3:每句標來源核心


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading: str            # 判讀
    posture: Posture        # 姿態(SYN 生成,可跨核心織,仍落受控 8 值)
    opening_utterances: list[OpeningUtterance]  # 起手話術(降級卡可空,不硬出)
    watchpoints: str        # 觀察點(含分歧分支)
    boundary: str           # 界線
    redline: str            # 紅線
    source_summary: str     # 來源摘要(v3:取用了誰、放下了誰+理由)

    def full_text(self) -> str:
        """供 postcheck pattern 檢的卡全文。"""
        parts = [self.reading, *(u.text for u in self.opening_utterances),
                 self.watchpoints, self.boundary, self.redline, self.source_summary]
        return "\n".join(parts)


# ── synthesis_trace(resonance v3 瘦身版;extra=forbid 即防回歸閘) ──

class UtteranceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utterance: str
    core: CoreId


class SetAside(BaseModel):
    model_config = ConfigDict(extra="forbid")
    core: CoreId
    reason: str = Field(min_length=1)  # 驗收:set_aside 各項含一句理由


class Divergence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tension: str
    surfaced_in: str


class SynthesisTrace(BaseModel):
    """trace 不得含 family / confidence / 權重欄位——extra=forbid 使 schema 直接拒收(防回歸)。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = 3
    inputs_seen: list[CoreId]
    unavailable: list[CoreId] = Field(default_factory=list[CoreId])
    presentation_order: list[CoreId]  # 洗牌結果,審位置效應
    utterance_sources: list[UtteranceSource] = Field(default_factory=list[UtteranceSource])
    set_aside: list[SetAside] = Field(default_factory=list[SetAside])
    divergences_surfaced: list[Divergence] = Field(default_factory=list[Divergence])


# ── tool 回傳 ─────────────────────────────────────────────────────

class Redflag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hit: bool
    reason: str
    referral: str


class AnalyzeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    card: Card | None
    synthesis_trace: SynthesisTrace | None
    redflag: Redflag | None
    degraded: bool = False

    @model_validator(mode="after")
    def _redflag_invariant(self) -> "AnalyzeResult":
        # 不變量(v2.2):redflag.hit=true ⟺ card/trace = None
        hit = self.redflag is not None and self.redflag.hit
        if hit and (self.card is not None or self.synthesis_trace is not None):
            raise ValueError("redflag hit 時 card/trace 必須為 None")
        if not hit and self.card is None:
            raise ValueError("非 redflag 時必須有 card")
        return self


class RoundResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card: Card | None
    synthesis_trace: SynthesisTrace | None
    converged: bool = False
    redflag: Redflag | None
    degraded: bool = False


def constraint_key(c: Constraint) -> tuple[str, str]:
    """constraints 跨輪聯集的去重鍵(pingpong.md:同 type 同 rule 去重)。"""
    return (c.type, c.rule)


def parse_constraints(core_outputs: dict[str, dict[str, Any] | None]) -> list[Constraint]:
    """自核心原始輸出收集 constraints(僅約束核心會有)。"""
    out: list[Constraint] = []
    for cid in CONSTRAINT_CORES:
        data = core_outputs.get(cid)
        if not data:
            continue
        for raw in data.get("constraints", []):
            out.append(Constraint.model_validate(raw))
    return out
