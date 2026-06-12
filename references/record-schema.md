---
spec: parenting-response / record-schema
version: 0.3
status: DRAFT（schema_version 3 隨 spec v3.0 落地;v2/v1 節保留供讀舊列）
date: 2026-06-12
implements: parenting-response-mcp-spec-v3.0.md(2026-06 G0 訊號化 amend;records v3 + side-tables);歷史:amend 前 v3.0(records v2)、v2.2(records v1 / A3)
consumers: orchestrator.py(④ 落庫 / ⑤ 歸檔 / report / events 稽核), schema.py(受控詞表), db.py, migrations/0002–0008, report.py(聚合)
---

# record-schema — L0 欄位語意、受控詞表、聚合/落庫規則

> L0 紀錄是 L1–L4 與報告聚合的唯一資料源:欄位語意一旦寫入就是長期契約。本檔鎖定**受控詞表的值域**與**records 欄位的落庫規則**;讀取端依 `schema_version` 分流(v3 = 現行;v2/v1 = 歷史列,規則保留於後)。

## schema_version 3(v3.0,現行)

v3.0 G0 訊號化 + retro:在 v2 基礎上新增——

| 欄位 | v3 來源 |
|---|---|
| records.`redflag`(新增) | bool;④ 落庫時 = `session.redflag_active ∨ ④ 短路命中`。**promotion 排除主錨**:`redflag=true` 之 record 被 ① `linked_plan_id` 引用一律 `E_INVALID_LINK`(status/outcome 檢查降為 legacy 雙保險)。落庫後不可變;⑤ 歸檔再命中**不回改**(events 留痕) |
| records.`parent_action`(新增) | retro 模式 ② 所交「當時實際怎麼處理」(其他模式 NULL);覆盤的事實錨 |
| sessions.`redflag_active`(新增) | bool 單調只升:①②③④⑤ 任一入口短路命中 → true;不再停案(`redflag_stopped` 自本輪改版不再產生) |
| sessions.`redflag_vector`(新增) | `child` \| `parent` \| `third` \| NULL;命中組自然攜帶(`wordlists.G0_SHORTCIRCUIT_BY_VECTOR`),**首見寫入後不覆寫**;③ safety_mode 組卡的唯一判斷來源 |
| sessions.`parent_action`(新增) | retro ② 暫存(④ 投影至 record);G0 複檢面(source=`②`) |
| sessions.`updated_at`(新增) | 活動錨:任何 update 自動 touch、resume 顯式續期;TTL 懶清掃改錨 `max(updated_at, 最後輪)` |
| sessions.`caregiver`(新增) | `爸` \| `媽`(DEFAULT 爸);**由已驗 sub 經 CAREGIVER_MAP 映射,不收輸入參數**;local 模式恆「爸」 |

- ④ 落庫前置(A 件):`redflag_active ∨ 本次命中` 時須 `referral_ack=true`,否則 `E_MISSING_AXIS`(轉介必達的 code 強制;訊號先落,擋下不丟)。
- severity 推導追加:② `parent_action` 與 ⑤ parent turns 之 G0 命中(兩級皆)→ 高(單調不變)。
- side-tables(**不動 schema_version**,本檔追蹤契約):`raw_transcripts`(⑤,turns = canonical JSON、UNIQUE(session_id, content_hash) 冪等)與 `reports`(scope/ref_key/version 遞增,body 確定性組裝、meta 存聚合快照+slots+語意警示)。
- 信封加密(J 件):自由文本欄(sessions.facts/emotion/parent_action、rounds.reaction_note、records.draft/outcome_note/parent_self_note/followup/parent_action、raw_transcripts.turns、reports.body/meta)庫存 `enc:<key_id>:…` 密文,db 層透明解密——**讀取端語意不變**;events payload 設計上明文(證據鏈可考)。

## schema_version 2(v3.0 初版/amend 前,歷史)

v3.0 零 LLM:server 不再產生 per-situation 判讀,records 欄位來源全面改寫——

| 欄位 | v2 來源 |
|---|---|
| `draft`(新增) | host ④ 提交之草稿(short 模式 = NULL;一般模式必填且過 `pattern_check`) |
| `claimed_sources`(新增) | host ④ 自報「哪招來自哪學派」,⊆ 6 回應核心(軟溯源,**不可驗**) |
| `maslow_need` | host ④ 自報 **① Maslow 探點命中**結果,⊆ 缺損四層、`MASLOW_ORDER` 固定排序;NULL = 未回報 |
| `erikson_stage` / `piaget_stage` | `age_band` 確定性查表(下表;不經 LLM) |
| `dreikurs_purpose` / `posture` / `dev_normative` / `tools_used` | **恆 NULL**(零 LLM 無判讀來源;`tools_used` 由 `claimed_sources` 接替) |
| `outcome` / `outcome_note` / `parent_self_note` / `followup` | host ④ 提交(同 v1) |
| `status` / `linked_plan_id` | mode 與 promotion 鏈映射(同 v1,見「mode 與 record.status」) |

- **A3 聚合自 v2 起廢止**(rounds 不再有核心輸出可聚;後文 A3 節僅適用 v1 列)。
- sessions 推導:`severity` 單調只升不降——① 警訊級命中 → 高;② `emotion_intensity=高` → 中;③ 複檢警訊 → 高;④ 自由文本 G0(短路或警訊)→ 高(`safety_flag`/`confounders` 軸 v3 不收,該兩條件停用)。`goal_aligned` v3 不再推導(無 `parent_goal` 軸)→ NULL。`is_positive_log` 同 v1。
- sessions 新增 `stage`(`constrained|ready|short_pending|finalized|redflag_stopped|expired`),FSM 細分守衛用;`age_band`/`emotion_intensity` 改可 NULL(① 先建 session、② 才補軸)。
- L1–L4 讀取端:`schema_version=2` 列照本節;`=1` 列照後文 v1 規則。

## 受控詞表(鎖定值域)

| 欄位 | 值域 | 語意備註 |
|---|---|---|
| sessions.mode | `live` \| `rehearsal` \| `retro` | live = 現場;rehearsal = 預演;retro = 事後覆盤(v3.0 B 件:② 必填 parent_action、③×1 回覆盤鏡頭、converged=NULL) |
| sessions.caregiver | `爸` \| `媽` | v3.0 K 件;由已驗 sub 映射,不收輸入 |
| sessions.redflag_vector | `child` \| `parent` \| `third` \| NULL | v3.0 G 件;首見不覆寫 |
| sessions.status | `open` \| `finalized` \| `expired` \|(legacy:`redflag_stopped`) | `expired` = TTL 棄案(自最後活動——含 updated_at——逾 `SESSION_TTL_DAYS` 由 ① 懶清掃轉入;無 record,severity 留存);`redflag_stopped` 僅 amend 前歷史列,本輪改版起不再產生,查詢視同 closed |
| sessions.age_band | `2-3` \| `4-6` \| `7-11` \| `12+` | 0-2 刻意範圍外(C3),pydantic 層擋 |
| sessions.emotion | 自由文本(必填) | 家長當下主情緒,建議單一情緒短語;非受控(B1 只要求 NOT NULL) |
| sessions.emotion_intensity | `低` \| `中` \| `高` | 家長主觀自評;S1 問法由 client 負責 |
| sessions.severity | `低` \| `中` \| `高` | server 推導,規則見下節;**單調只升不降** |
| sessions.problem_category | 見「新定詞表」 | 受控;可空 |
| sessions.confounders | `F1`–`F8` 之子集 | 家族代碼,詞源 `tw-parenting-antipatterns.md`;可空 |
| rounds.child_reaction | `鬆動配合` \| `否認堅持` \| `情緒爆發` \| `退縮害怕` \| `反問試探` \| `轉移打岔` | round 0 = NULL;操作型定義見 `pingpong.md` |
| rounds.reaction_note | 自由文本(可空) | S3 家長轉述;G0 複檢對象 + 核心輸入的現實事件來源(縫補) |
| records.status | `planned` \| `done` \| `done_from_plan` \| `stopped` | 映射規則見下「mode 與 record.status」;`stopped` 自 defect-fixes(2026-06-11)加入 v2 值域,不另 bump(僅出現於 `outcome=escalated_to_redflag` 之列,讀取端本就特判該 outcome) |
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
| outcome=escalated_to_redflag(本輪改版起僅 host 自報;**優先於 mode**) | `stopped`(legacy 映射) | promotion 排除主錨 = `record.redflag`,本列為雙保險;amend 前歷史列另有 ③ 自動收案來源 |
| mode=rehearsal | `planned`(固定) | resolved=計畫可用 / partial=計畫待磨 / unresolved=未得計畫 |
| mode ∈ {live, retro} 且 session.linked_plan_id 為空 | `done` | retro 是實際發生過的處理,非計畫 |
| mode=live 且 session.linked_plan_id 非空 | `done_from_plan`,record.linked_plan_id ← session 值 | 字面語意(promotion 鏈,A2;引用源須 `redflag=false`) |

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

**is_positive_log** := `(problem_category = 正向紀錄)`。短管線一問已於 v3.0 定案(② `script_decision` 硬閘,skip → short ④;見「schema_version 2」節),本段其餘為 v1 歷史規則。

**goal_aligned** — finalize 時判:

```text
parent_goal IS NULL          → NULL（無從對照）
outcome = resolved           → true
outcome = partial            → NULL（不可判,不臆測）
outcome ∈ {unresolved, escalated_to_redflag} → false
```

## A3 理論欄位聚合回填(finalize / 自動 record 共用)

> **僅適用 schema_version=1 歷史列;v2 起廢止(見「schema_version 2」節)。**

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

## events(稽核事件,defect-fixes #7/#8;migrations/0003,0006 起 `session_id` 可空)

> append-only 證據鏈:G0 命中、拒收與報告稽核的「為什麼」落庫於此——`severity=高` 不再是無緣由孤值;「曾接觸紅旗之案」= `events.kind=g0_shortcircuit` 之 session 集合(v3.0 主錨)∪ `records.redflag=true`。本表非 records 欄位,**不動 `schema_version`**;payload 契約變更在本節追蹤。報告級/auth 事件 `session_id=NULL`,以 payload `ref_key`/`sub` 錨定;authkit 模式所有 payload 自動附 `sub`(誰觸發)。

| kind | 觸發 | payload |
|---|---|---|
| `g0_shortcircuit` | ①②③④⑤ 短路級命中(③ 另含 `round_no`) | `source`(①\|②\|③\|④\|⑤)、`field`、`phrase`、`excerpt`、`vector`(child\|parent\|third,v3.0)、`referral_delivered=true` |
| `g0_warning` | ①②③④⑤ 警訊級命中 | `source`、`hits: [{field, phrase}, …]`(③ 另含 `round_no`) |
| `finalize_rejected` | ④ pattern 拒收(不落 record) | `violations`、`outcome`(嘗試值)、`redflag_hit`(bool) |
| `archive_rejected` | ⑤ 工具協議標記命中(整 chunk 拒收) | `source=⑤`、`chunk_no`、`hits: [{turn, patterns}]` |
| `report_rejected` | report phase2 驗證未過(不落庫) | `scope`、`ref_key`、`violations: [{slot, kind, term…}]`(kind ∈ over_length \| forbidden_term \| number_not_in_aggregates \| raw_text_leak) |
| `report_semantic_warning` | 語意 tripwire(警告不拒收;H 件) | `scope`、`ref_key`、`warnings: [{slot, clause, term}]`(含 K 件照顧者比較句) |
| `report_audit` | 報告定稿落庫 | `scope`、`ref_key`、`version`、`semantic_warning_count` |
| `auth_denied` | JWT 過但 sub ∉ ALLOWED_SUBJECTS(I 件) | `sub`、`reason` |
| `caregiver_unmapped` | authkit sub 無 CAREGIVER_MAP 映射(K 件,不建案) | `sub` |

## record_id 與 schema_version

- `record_id` = `YYYYMMDD-NN`(server 產,當日序號從 01 起;超過 99 自然增寬)。「當日」= **臺北日**(UTC+8 固定偏移,台灣無夏令時),與部署主機時區無關(defect-fixes #10)——UTC 容器或多機共庫不再出現跨午夜前綴錯日。報告期界(季/年)同錨臺北(`schema.TZ_TAIPEI` 單一來源)。
- `schema_version` 現 = **3**(v3.0,migrations/0004)。**任何欄位語意或值域變更必須 bump**,並同步 Alembic 遷移;L1–L4 讀取端依版本分流解讀。side-tables(events/raw_transcripts/reports)為 append-only 契約,不動本版號,變更在各節追蹤。

## 待議

- ~~正向紀錄是否走短管線~~ → v3.0 定案:② 硬閘詢問 `script_decision`,skip 走 short ④(只記事)
- 終態後 record 補註(parent_self_note 事後追記)機制
