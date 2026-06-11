---
spec: parenting-response / cores
version: 0.1
status: superseded（v3.0 起學派 TAG 單一事實來源 = tags.md;僅供歷史參照）
superseded_by: references/cores/tags.md
date: 2026-06-11
implements: parenting-response-mcp-spec-v2.2.md（核心呼叫契約 / 模型策略 / 嚴格隔離面）
consumers: src/cores/*（呼叫封裝）, synthesis.py, postcheck.py, orchestrator.py
---

# cores — 十核心共用契約

> 每個核心 = 一個理論鏡頭、一次獨立 API 呼叫。本檔定共用契約(輸入/輸出/隔離/模型),各核心檔只寫自己的理論與 prompt,不重述。

## 角色與配置總表

| core | 檔 | 角色 | model_default |
|---|---|---|---|
| 正向教養 | `pd.md` | 産招 | sonnet |
| Dreikurs | `dreikurs.md` | 産招 | haiku |
| Gottman | `gottman.md` | 産招 | sonnet |
| NVC | `nvc.md` | 産招 | sonnet |
| Rogers | `rogers.md` | 産招 | sonnet |
| Adler | `adler.md` | 觀點 | sonnet |
| Maslow | `maslow.md` | 約束 | haiku |
| Satir | `satir.md` | 約束 | sonnet |
| Erikson | `erikson.md` | 約束 | haiku |
| Piaget | `piaget.md` | 約束 | haiku |

**去家族化(resonance v3)**:合成不分族、不折算、不加權——家族標籤無消費端,本目錄不含任何家族/譜系後設資訊;十核心在合成版面中**等格式、等地位、順序洗牌**(契約見 `resonance-c-light.md` v3)。

模型對齊 v2.2 模型策略:細膩語感(Satir/Adler + 産招話術四核)→ sonnet;判別型(Dreikurs 目的分類、Maslow/Erikson/Piaget 約束分析)→ haiku 預設,config 可升。

## 輸入契約(嚴格隔離,縫補裁決)

所有核心吃**同一份結構化情境**,不含:其他核心輸出、任何候選、歷輪卡文、linked_plan 摘要(後兩者僅合成可見)。現實事件(家長實際說了什麼、孩子怎麼回)一律經家長轉述 `reaction_note` 進入。

```json
{
  "mode": "live | rehearsal",
  "age_band": "2-3 | 4-6 | 7-11 | 12+",
  "facts": "<S1 蒐集的客觀事實>",
  "emotion": "<家長主情緒>",
  "emotion_intensity": "低 | 中 | 高",
  "safety_flag": false,
  "problem_category": "<受控詞表 | null>",
  "confounders": ["F4"],
  "parent_goal": "<家長目標 | null>",
  "round_no": 0,
  "history": [
    { "round_no": 1, "child_reaction": "否認堅持", "reaction_note": "<轉述 | null>" }
  ]
}
```

- round 0:`history = []`。
- next_round 的點火子集由 `pingpong.md` 決定;核心不知道自己屬於哪個子集——對每次呼叫而言,世界只有這份情境。

## 輸出通則

- **嚴格 JSON**:無 markdown 圍欄、無前後綴文字;欄位缺漏 = 核心失敗(retry → unavailable)。
- 全 zh-TW;`utterance` 用台灣家庭口語,孩子聽的話符合 age_band 語言水位。

| 角色 | 輸出 schema |
|---|---|
| 産招 | `{ "candidate": { "posture": "<8值>", "utterance": "<1–3 句,家長可直接照說>" }, "analysis": "<2–4 句>", "confidence": 0.0–1.0 }`(dreikurs 另加 `purpose`) |
| 觀點 | `{ "analysis": "<含私人邏輯假說 / 歸屬策略 / 課題切分>" }` |
| 約束 | `{ "analysis": "<2–4 句>", "constraints": [<0–3 條>], <核心特定欄位> }` |

- `posture` 受控 8 值(定義見 `record-schema.md`):同理接住/情緒教練/溫和設限/給選擇/自然後果/共同解題/修復關係/退場降溫。
- `confidence` = **本鏡頭對此情境的適配度**,不是話術自評。resonance v3 下它**不進合成版面**(顯示即加權誘因,且跨核心自評不可比),由 code 排版時剝除,僅落 `rounds.core_outputs` 供 L1 審計(自評適配 vs 實際取用率對照);仍要求不適配時誠實低分(≤0.4)——審計失真即無意義。
- **核心特定欄位 = A3 聚合與 pingpong 的資料來源,欄位名即 de facto 契約**:`dreikurs.purpose`、`maslow.unmet_needs`、`erikson.stage_observed/within_norm`、`piaget.stage_observed/within_norm`、`satir.child_stance/parent_stance`、`gottman.emotion_processed`。改名 = 破壞 L0 聚合/converged 判準,須過 record-schema 版本管理。

## constraint 物件(約束核心)

```json
{ "type": "<核心固定值>",
  "rule": "<situation-grounded,「不得…」格式,逐字扣 facts/history>",
  "checkable_by": "pattern | guardian",
  "forbidden_terms": ["<僅 pattern 型必填,併入當輪 postcheck 詞表>"] }
```

0–3 條;**禁空泛通則**(「要有同理心」不是約束;「不得以沒收生日禮物作後果——該禮物是他唯一的安撫物」才是)。

## 反模式禁投影(産招)

`utterance` 不得含 F1–F8 任何反模式句式:恐嚇威脅/羞辱貶低標籤/比較貶抑/情感勒索/全稱否定翻舊帳/賄賂交換/情緒否定敷衍/體罰肢體威嚇(全表 `tw-parenting-antipatterns.md`)。**也不得以引用反例方式出現**(卡片不引反例句規約)——postcheck pattern 對卡全文檢,引用照樣攔。

## 載入方式

各核心檔「system prompt」節全文 = anthropic API 的 `system` 參數;`user` message = 上述情境 JSON 字串。每核心一次獨立呼叫(`asyncio.gather` 單波並行),無共享 context——這就是隔離的實作面。

全部核心原始輸出由 orchestrator 全量落 `rounds.core_outputs`(隔離審計 + A3 聚合來源);進合成的只有 v3 並列版面投影——`{ core, analysis, candidate }`,無 confidence、無任何權重欄。
