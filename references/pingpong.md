---
spec: parenting-response / pingpong
version: 0.1
status: DRAFT（待審）
date: 2026-06-11
implements: parenting-response-mcp-spec-v2.2.md（next_round 管線 / converged / D3）
consumers: orchestrator.py（點火路由）, redflag.py（複檢順位）, client prompt（六類分類指引、converged 呈現）
---

# pingpong — S3 反應路由與 converged 判準

> `next_round` 的兩個下放決策都在這裡:**child_reaction → 點火哪些核心**(路由表),以及 **converged 怎麼判**(含 D3:討好式順從 ≠ 收斂)。前置順序不重述:FSM 守衛 → G0 複檢(對 `reaction_note`)→ 本檔路由 → 合成 → 後檢(v2.2)。

## 六類反應:操作型定義(client 分類指引)

| 反應 | 操作型定義(以可觀察行為界定) |
|---|---|
| 鬆動配合 | 情緒強度下降,出現配合行為或口頭同意(**含勉強、含不甘願**——是否為討好由 C2 判,client 不必前置過濾) |
| 否認堅持 | 否認事實或堅持原行為,情緒平穩到中等(「我沒有」「我就是要」) |
| 情緒爆發 | 哭鬧、尖叫、丟摔、肢體抗拒等強度升級 |
| 退縮害怕 | 沉默、躲避、低頭發抖、討饒、眼神迴避 |
| 反問試探 | 反問為什麼、討價還價、故意小幅越線觀察反應 |
| 轉移打岔 | 顧左右而言他、扮鬼臉、突然換話題、假裝沒聽到 |

**兩可時的安全傾斜**:同時像兩類,取「情緒較重」者。優先序:`情緒爆發 > 退縮害怕 > 否認堅持 > 反問試探 > 轉移打岔 > 鬆動配合`。寧可多點安撫系核心,不可漏。

**reaction_note**:家長轉述自由文本(孩子說/做了什麼、家長實際說了什麼)。三個用途——G0 複檢對象(先於路由)、核心輸入的現實事件來源(嚴格隔離下,卡文不進核心,「家長照卡說了什麼」只能經轉述進入)、L0 審計。client 應鼓勵家長給轉述,但可空。

## 點火路由表

> 設計不變量:**每輪約束核心點火數 ≥ 2**——否則 A5(可用 < K,K=2)必然觸發、輪輪降級。産招每輪 ≥ 1(産招全失敗 → 回錯誤,v2.2)。觀點(Adler)只在「行為目的/私人邏輯」是問題軸心時點火。

| child_reaction | 産招 | 觀點 | 約束(≥2) | rationale |
|---|---|---|---|---|
| 鬆動配合 | PD | — | Satir + Maslow + Erikson | 固化正向、收尾導向;**Satir 必點**(D3 討好鑑別);Erikson 確認是自主配合非屈從 |
| 否認堅持 | Dreikurs + PD | Adler | Maslow + Erikson | 高機率權力課題:Dreikurs 判目的、Adler 解私人邏輯;PD 出溫和堅定/給選擇 |
| 情緒爆發 | Gottman + Rogers + NVC | — | Maslow + Satir | 先接情緒不講理;Maslow 檢生理/安全底線(餓睏累),Satir 防家長指責姿態升級 |
| 退縮害怕 | Rogers + Gottman | Adler | Maslow + Satir + Erikson | 安全感優先;Erikson 檢羞愧/罪惡感風險;Adler 解「退縮在保護什麼」 |
| 反問試探 | PD + Dreikurs | Adler | Piaget + Erikson | 界線測試 vs 真求知:Piaget 判認知層次(反問是理解需求還是談判),Dreikurs 判目的 |
| 轉移打岔 | Dreikurs + NVC | — | Satir + Piaget | 打岔 = Satir 求生存姿態或 Dreikurs 關注目的;Piaget 檢認知負荷(聽不懂也會打岔) |

**加點規則 R+**:本輪 = 鬆動配合 且 前一輪 ∈ {退縮害怕, 情緒爆發} → 産招加點 Rogers。高張力直轉配合是恐懼驅動的典型樣態,需無條件接納鏡頭參與,且 C2 證據要求升高(見下)。

成本:每輪 4–6 核心 + 合成 1 + guardian 1(retry 上界 +2N 同 v2.2)。

## 約束的跨輪沿用與 K 語意

```text
constraints 檢查表（postcheck 用） = 本 session 歷輪 constraints 聯集（同 type 同 rule 去重）
  ── 情境未重置,先前約束不因輪次失效;本輪新產約束併入
A5 的 K 檢查對象 = 本輪「約束核心呼叫成功數」
  ── 路由表保證每輪點火 ≥ 2;成功數 < 2 → 降級安全卡（rounds.degraded=true）
  ── 歷輪累積的檢查表仍可用於後檢,但「本輪無新鮮約束視角」即不出正常卡——寧降級
```

## converged 判準(D3 內建)

converged 是**建議收尾訊號,不是 FSM 轉移**:`converged=true` 只代表 client 可向家長呈現「這輪看起來收住了,要不要 finalize」;收不收永遠由家長決定(human-in-loop)。

```text
converged = C1 ∧ C2 ∧ C3

C1 本輪 child_reaction = 鬆動配合          —— 必要但絕不充分
C2 非討好鑑別通過:
   - Satir 輸出 child_stance ≠ 討好  且  analysis 未標記壓抑順從/恐懼驅動訊號
   - Gottman 若本輪點火:emotion_processed ≠ false（結構化欄位,code 可判）
   - Satir 本輪缺席（呼叫失敗）→ C2 不可判 → converged=false（保守向）
   - R+ 觸發輪（前輪高張力）:Satir 與 Rogers 兩鏡頭皆無討好/恐懼訊號才過
C3 無新增高張力訊號:
   - 本輪 reaction_note 零命中 G0 警訊級詞組
   - 本輪新產 constraints 無新 type（同型重申不算升級）
```

### 反例明列(防天真綁定,D3)

| 樣態 | 判定 |
|---|---|
| 退縮害怕 →(下一輪)鬆動配合 | 恐懼驅動疑似:R+ 加點 Rogers,C2 雙鏡頭門檻 |
| 孩子說「好啦對不起」但眼神迴避、肢體僵硬(轉述可見) | Satir 應判討好 → C2 不過 |
| 家長自陳用了交換條件後孩子配合(confounders+F6) | C1–C3 照判;converged 可 true,但 client 應在 finalize 的 followup 建議「交換 → 常規」的後續 |
| 連續轉移打岔 ≥ 2 輪 | 認知負荷或迴避溢出:不可能 converged(C1 不成立),client 建議降溫暫停、改日再談或轉 rehearsal |

## 輪次上限(待議預設)

`round_no ≥ 5` 仍未 converged → client 主動建議:以 `partial` / `unresolved` 收案,或本次安全收尾、另開 rehearsal session 預演下一次。上限值待實測調整;server 不強制(FSM 無此轉移),純 client 呈現層建議。

## 與 promotion 的關係

linked_plan 摘要**僅合成可見**(嚴格隔離,縫補裁決):點火核心對「照哪份預演打」一無所知,計畫脈絡由合成在織卡時運用;家長實際執行了計畫中哪句,經 `reaction_note` 轉述自然進入核心情境——隔離面最小,資訊不漏。

## 待議

- 輪次上限值(暫 5)與「建議轉 rehearsal」的觸發條件
- C3 的「新 type」判準是否放寬為「新 rule 即升級」(現偏寬:同型重申不算)
- 六類是否足夠(「假裝配合再犯」是延時樣態,跨 session 才可見 → L1 課題,非本檔)
