---
spec: parenting-response / record-schema
version: 0.1
status: DRAFT（待審）
date: 2026-06-11
implements: parenting-response-mcp-spec-v2.2.md（資料模型 / A3 聚合回填 / 推導欄位）
consumers: orchestrator.py（analyze 推導 + finalize 聚合）, schema.py（受控詞表）, db.py, 未來 L1–L4
---

# record-schema — L0 欄位語意、受控詞表、A3 聚合回填規則

> L0 紀錄是 L1–L4 的唯一資料源:欄位語意一旦寫入就是長期契約。本檔鎖定三件事——**受控詞表的值域**、**sessions 推導欄位的 code 規則**、**records 理論欄位的聚合回填規則(A3)**。表結構本身見 mcp spec v2.2 資料模型節,不重述。

## 受控詞表(鎖定值域)

| 欄位 | 值域 | 語意備註 |
|---|---|---|
| sessions.mode | `live` \| `rehearsal` | live = 現場處理;rehearsal = 預演 |
| sessions.status | `open` \| `finalized` \| `redflag_stopped` | FSM 狀態,見 v2.2 |
| sessions.age_band | `2-3` \| `4-6` \| `7-11` \| `12+` | 0-2 刻意範圍外(C3),pydantic 層擋 |
| sessions.emotion | 自由文本(必填) | 家長當下主情緒,建議單一情緒短語;非受控(B1 只要求 NOT NULL) |
| sessions.emotion_intensity | `低` \| `中` \| `高` | 家長主觀自評;S1 問法由 client 負責 |
| sessions.severity | `低` \| `中` \| `高` | server 推導,規則見下節;**單調只升不降** |
| sessions.problem_category | 見「新定詞表」 | 受控;可空 |
| sessions.confounders | `F1`–`F8` 之子集 | 家族代碼,詞源 `tw-parenting-antipatterns.md`;可空 |
| rounds.child_reaction | `鬆動配合` \| `否認堅持` \| `情緒爆發` \| `退縮害怕` \| `反問試探` \| `轉移打岔` | round 0 = NULL;操作型定義見 `pingpong.md` |
| rounds.reaction_note | 自由文本(可空) | S3 家長轉述;G0 複檢對象 + 核心輸入的現實事件來源(縫補) |
| records.status | `planned` \| `done` \| `done_from_plan` | 映射規則見下「mode 與 record.status」 |
| records.outcome | `resolved` \| `partial` \| `unresolved` \| `escalated_to_redflag` | rehearsal 模式語意見下 |
| records.dreikurs_purpose | `關注` \| `權力` \| `報復` \| `自暴自棄` \| NULL | NULL = 未判讀或核心回報「不明」 |
| records.maslow_need | JSONB 陣列 ⊆ `[生理, 安全, 愛與歸屬, 尊重]` | 「未滿足層」;自我實現不入 L0(兒少情境聚焦缺損層);NULL = 未判讀,`[]` = 判讀過皆滿足 |
| records.erikson_stage | `自主對羞愧懷疑` \| `主動對罪惡感` \| `勤奮對自卑` \| `認同對角色混淆` | 實際表現階段(可與齡不符) |
| records.piaget_stage | `前運思期` \| `具體運思期` \| `形式運思期` | 同上 |
| records.dev_normative | bool \| NULL | Erikson ∧ Piaget 齡內判讀,規則見 A3 |
| records.posture | 見「新定詞表」 \| NULL | 最終卡的應對姿態 |
| records.tools_used | JSONB 陣列 ⊆ 10 核心 id | `pd, dreikurs, gottman, nvc, rogers, adler, maslow, satir, erikson, piaget` |

### age_band ↔ 發展階段預設映射(聚合缺席時的回填值)

| age_band | erikson_stage | piaget_stage |
|---|---|---|
| 2-3 | 自主對羞愧懷疑 | 前運思期 |
| 4-6 | 主動對罪惡感 | 前運思期 |
| 7-11 | 勤奮對自卑 | 具體運思期 |
| 12+ | 認同對角色混淆 | 形式運思期 |

## 新定詞表(本檔首次定義——上游 spec-v2 不可得,本檔即 de facto 標準)

**problem_category(14 值)**:
`作息睡眠 | 飲食 | 3C使用 | 課業學習 | 手足衝突 | 同儕學校 | 情緒行為 | 公共場合 | 生活自理 | 安全行為 | 頂嘴禮貌 | 誠實 | 正向紀錄 | 其他`

**posture(8 值,産招核心 `candidate.posture` 共用詞表)**:

| 值 | 語意 | 主要供應核心 |
|---|---|---|
| 同理接住 | 先反映、確認、不矯正 | Rogers / NVC |
| 情緒教練 | 命名情緒 + 陪伴消化,後段才設限 | Gottman |
| 溫和設限 | 界線清楚 + 語氣溫和並行 | PD / Gottman |
| 給選擇 | 有限選擇(皆可接受)交還主導權 | PD |
| 自然後果 | 自然/邏輯後果(3R),非處罰 | Dreikurs / PD |
| 共同解題 | 邀請孩子一起想辦法 | PD / NVC |
| 修復關係 | 家長先行修復(道歉/重新連結) | PD / Gottman |
| 退場降溫 | 暫停現場,家長或雙方先降溫 | Rogers |

## mode 與 record.status 映射

| 條件 | record.status | outcome 語意 |
|---|---|---|
| mode=rehearsal | `planned`(固定) | resolved=計畫可用 / partial=計畫待磨 / unresolved=未得計畫 |
| mode=live 且 session.linked_plan_id 為空 | `done` | 字面語意 |
| mode=live 且 session.linked_plan_id 非空 | `done_from_plan`,record.linked_plan_id ← session 值 | 字面語意(promotion 鏈,A2) |

## sessions 推導欄位規則(server code,deterministic)

**severity** — analyze 時初判,後續輪可上修、不可下修:

```text
高: safety_flag=true
    ∨ 任一輪文本命中「警訊級」詞組（tw-parenting-antipatterns.md G0 節,非短路級）
    ∨ session 曾經 G0 複檢升級（escalated）
中: emotion_intensity=高
    ∨ confounders ∩ {F1, F4, F8} ≠ ∅
    ∨ 單輪 constraints 總數 ≥ 4
低: 其餘
```

**is_positive_log** := `(problem_category = 正向紀錄)`。正向紀錄 session 仍走完整管線(卡 = 強化建議);是否值得短管線 → 待議。

**goal_aligned** — finalize 時判:

```text
parent_goal IS NULL          → NULL（無從對照）
outcome = resolved           → true
outcome = partial            → NULL（不可判,不臆測）
outcome ∈ {unresolved, escalated_to_redflag} → false
```

## A3 理論欄位聚合回填(finalize / 自動 record 共用)

**來源**:各輪 `rounds.core_outputs`(各核心原始輸出,key = 核心 id)。resonance v3 將 `synthesis_trace` 瘦身為溯源審計後,核心輸出改以此專欄落庫——隔離審計與 A3 聚合共用一源。欄位名以 `references/cores/*.md` 各核心輸出契約為準(`purpose`、`unmet_needs`、`stage_observed`、`within_norm`、`child_stance` 等),即 de facto 契約。

**聚合通則**:判讀類取「最後一次出現」(乒乓後期資訊較多、判讀較準);累積類取聯集;核心整 session 缺席 → NULL 或預設映射,不臆測。

| records 欄位 | 規則 |
|---|---|
| dreikurs_purpose | 最後一輪含 dreikurs 輸出之 `purpose`;值=`不明` → NULL;整程缺席 → NULL |
| maslow_need | 全輪 maslow `unmet_needs` 聯集,按 `[生理, 安全, 愛與歸屬, 尊重]` 固定排序;整程缺席 → NULL |
| erikson_stage | 最後一輪 erikson `stage_observed`;整程缺席 → 依 age_band 預設映射 |
| piaget_stage | 最後一輪 piaget `stage_observed`;整程缺席 → 依 age_band 預設映射 |
| dev_normative | erikson `within_norm` ∧ piaget `within_norm`(各取最後值);任一 false → false;兩者皆缺席 → NULL;僅一方有值 → 取該方 |
| tools_used | 各輪 `synthesis_trace.utterance_sources[].core` 聯集(resonance v3:溯源即貢獻判定) |
| posture | 最後一張 `degraded=false` 卡之「姿態」欄(SYN 生成、可跨核心織,仍 ∈ 本檔 8 值;resonance v3);全程降級 → NULL |

L1–L4 的核心取用率統計同樣以 `synthesis_trace.utterance_sources` 為源——溯源即歸因(resonance v3);本檔不收任何理論家族受控詞表(v3 去家族化)。

**自動 record(next_round G0 複檢命中,v2.2)**:`outcome=escalated_to_redflag`(鎖定);`outcome_note` = server 填 G0 reason;理論欄位照上表以**既有 rounds** 聚合;`parent_self_note` / `followup` = NULL——終態後無補註管道,補註機制 → 待議。

**G0 在 analyze 即命中**:無 record(A1:sessions 一列、rounds 零列、records 零列)。`records UNIQUE(session_id)` 與此分流共同保證:一 session 至多一 record,且必有 round 0 才可能有 record。

## record_id 與 schema_version

- `record_id` = `YYYYMMDD-NN`(server 產,當日序號從 01 起;超過 99 自然增寬)。
- `schema_version` 現 = 1。**任何欄位語意或值域變更必須 bump**,並同步 Alembic 遷移;L1–L4 讀取端依版本分流解讀。

## 待議

- 正向紀錄是否走短管線(目前:全管線)
- 終態後 record 補註(parent_self_note 事後追記)機制
