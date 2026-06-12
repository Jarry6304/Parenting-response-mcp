"""受控詞表 + 錯誤碼 + 共用模型(spec v3.0 / record-schema.md)。

v3.0 零 LLM:核心輸出契約、卡、合成 trace 模型全數移除;
本檔是 ②③④ 驗證與 records 落庫的受控詞表單一 code 來源。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# ── 錯誤碼(spec v3.0:違序 / 缺軸 / 連結) ────────────────────────

E_MISSING_AXIS = "E_MISSING_AXIS"
E_INVALID_STATE = "E_INVALID_STATE"
E_INVALID_LINK = "E_INVALID_LINK"


class PRError(Exception):
    """攜帶錯誤碼的領域錯誤;server 層轉 ToolError。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# ── 受控詞表(record-schema.md 鎖定值域) ──────────────────────────

Mode = Literal["live", "rehearsal"]
MODES: tuple[str, ...] = ("live", "rehearsal", "retro")  # retro = 事後覆盤(v3.2 B 件)

AgeBand = Literal["2-3", "4-6", "7-11", "12+"]  # 0-2 刻意範圍外(C3)
AGE_BANDS: tuple[str, ...] = ("2-3", "4-6", "7-11", "12+")

EmotionIntensity = Literal["低", "中", "高"]
INTENSITIES: tuple[str, ...] = ("低", "中", "高")

Severity = Literal["低", "中", "高"]
SEVERITY_ORDER: dict[str, int] = {"低": 0, "中": 1, "高": 2}

# v3.2 A 件:終態 = finalized / expired;redflag_stopped 僅 legacy 列保留(查詢視同 closed),
# 新寫入路徑不再產生——G0 由閘降為訊號(sessions.redflag_active)。
SessionStatus = Literal["open", "finalized", "expired", "redflag_stopped"]
# FSM stage(spec v3.2):① constrained → ② {ready|short_pending} → 終態(expired 僅由 TTL 清掃產生)
SessionStage = Literal["constrained", "ready", "short_pending", "finalized", "expired", "redflag_stopped"]
RecordStatus = Literal["planned", "done", "done_from_plan", "stopped"]  # stopped = legacy 紅旗案;v3.2 排除鏈改錨 record.redflag

ChildReaction = Literal["鬆動配合", "否認堅持", "情緒爆發", "退縮害怕", "反問試探", "轉移打岔"]
CHILD_REACTIONS: tuple[str, ...] = ("鬆動配合", "否認堅持", "情緒爆發", "退縮害怕", "反問試探", "轉移打岔")

Outcome = Literal["resolved", "partial", "unresolved", "escalated_to_redflag"]
OUTCOMES: tuple[str, ...] = ("resolved", "partial", "unresolved", "escalated_to_redflag")

ScriptDecision = Literal["skip", "generate"]
SCRIPT_DECISIONS: tuple[str, ...] = ("skip", "generate")
POSITIVE_LOG = "正向紀錄"  # 正向紀錄硬閘的觸發類別

PROBLEM_CATEGORIES: tuple[str, ...] = (
    "作息睡眠", "飲食", "3C使用", "課業學習", "手足衝突", "同儕學校", "情緒行為",
    "公共場合", "生活自理", "安全行為", "頂嘴禮貌", "誠實", "正向紀錄", "其他",
)

MaslowNeed = Literal["生理", "安全", "愛與歸屬", "尊重"]
MASLOW_ORDER: tuple[str, ...] = ("生理", "安全", "愛與歸屬", "尊重")

# ── 學派分群(spec v3.0:回應核心進 ③ 耦合;探詢核心屬 ① 約束探詢) ──

RESPONSE_CORES: tuple[str, ...] = ("pd", "adler", "dreikurs", "gottman", "rogers", "nvc")
INQUIRY_CORES: tuple[str, ...] = ("maslow", "satir")

# age_band ↔ 發展階段確定性查表(record-schema.md;v3.0 唯一來源,不經 LLM)
ERIKSON_BY_BAND: dict[str, str] = {
    "2-3": "自主對羞愧懷疑", "4-6": "主動對罪惡感", "7-11": "勤奮對自卑", "12+": "認同對角色混淆",
}
PIAGET_BY_BAND: dict[str, str] = {
    "2-3": "前運思期", "4-6": "前運思期", "7-11": "具體運思期", "12+": "形式運思期",
}


# ── tool 回傳共用模型 ─────────────────────────────────────────────

class Redflag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hit: bool
    reason: str
    referral: str
    # 證據鏈(defect-fixes #8):命中欄位 / 詞組 / 前後文節錄(events 同步落庫,可重建緣由)
    field: str | None = None
    phrase: str | None = None
    excerpt: str | None = None
    # v3.2 G 件:命中組攜帶的風險向(child|parent|third)→ ③ safety_mode 組卡
    vector: str | None = None
