---
spec: parenting-response / report-core
version: 3.2
status: LOCKED
date: 2026-06-12
implements: parenting-response-mcp-spec-v3.2.md(F 件 report 體系 + H 件語意紅線三層)
consumers: report_core 載入器, orchestrator.report(phase1 骨架/guardian、phase2 驗證組裝)
---

# report-core(v3.2)— 三種報告的骨架、槽位與紅線

> 報告 = **code 聚合(fixed)+ host 敘事(slot)** 的確定性組裝。fixed 節由
> server 以聚合值組裝,host 不可交;slot 節由 host 依 guardian 指令生成、
> 受字數/數字白名單/負面清單/防滲驗證。本檔為章節結構與驗證參數的單一事實來源:
> 改骨架改本檔,不改 code。塊格式沿 cores/tags.md(`key: value`,塊名容點號)。

## 章節定義格式

每節一個 fenced 塊:`report.<scope>.<section_id>:`。鍵:
- `title`:節標題(組裝時輸出)
- `type`:`fixed`(code 組裝)| `slot`(host 填)
- `order`:節序(整數,組裝排序鍵)
- `max_chars`:slot 字數上限(僅 slot)
- `hint`:slot 生成提示(phase1 隨骨架回傳;僅 slot)
- `template`:fixed 敏感節的句式模板(僅 safety 節;`{n}` 代入聚合值)

---

## event(單案事件卡;④⑤ 之後)

```text
report.event.overview:
  title: 案況
  type: fixed
  order: 1
```

```text
report.event.safety:
  title: 安全
  type: fixed
  order: 2
  template: 本案共 {n} 次高警訊,均已附轉介。|本案無安全警訊。
```

```text
report.event.what_worked:
  title: 這次有效的
  type: slot
  order: 3
  max_chars: 150
  hint: 描述這次哪個回應方式有效(行為與效果,不評價孩子人格)。
```

```text
report.event.next_time:
  title: 下次想試的
  type: slot
  order: 4
  max_chars: 150
  hint: 一個具體的下次調整(可引用 ③ 的 TAG 視角)。
```

```text
report.event.quotes:
  title: 對話片段
  type: slot
  order: 5
  max_chars: 200
  hint: 可引逐字稿原文,上限 2 段(raw_quota);只選能說明轉折的片段。
```

## quarter(季報;family-share 等級)

```text
report.quarter.stats:
  title: 本季概況
  type: fixed
  order: 1
```

```text
report.quarter.positive_moments:
  title: 正向時刻
  type: slot
  order: 2
  max_chars: 300
  hint: 本季最值得記住的 2-3 個正向片刻(描述場景,不比較、不評分)。
```

```text
report.quarter.safety:
  title: 安全
  type: fixed
  order: 3
  template: 本季共 {n} 次高警訊,均已附轉介。|本季無安全警訊。
```

```text
report.quarter.prev_audit:
  title: 上期語意稽核
  type: fixed
  order: 4
```

```text
report.quarter.growth:
  title: 成長與調整
  type: slot
  order: 5
  max_chars: 300
  hint: 家長自己的調整(以「我」開頭的句子優先;孩子的變化描述行為不貼標籤)。
```

```text
report.quarter.next_quarter:
  title: 下季想練習的
  type: slot
  order: 6
  max_chars: 200
  hint: 一到兩個練習目標,具體可做。
```

## year(年報)

```text
report.year.stats:
  title: 全年概況
  type: fixed
  order: 1
```

```text
report.year.quarters_recap:
  title: 四季回顧
  type: fixed
  order: 2
```

```text
report.year.journey:
  title: 這一年
  type: slot
  order: 3
  max_chars: 500
  hint: 一年的歷程敘事:從哪裡出發、走到哪裡(寫關係的變化,不寫成績單)。
```

```text
report.year.safety:
  title: 安全
  type: fixed
  order: 4
  template: 本年共 {n} 次高警訊,均已附轉介。|本年無安全警訊。
```

```text
report.year.letter:
  title: 想說的話
  type: slot
  order: 5
  max_chars: 400
  hint: 給孩子或未來自己的一段話。
```

---

## guardian(host 生成 slots 前的自查指令;phase1 隨骨架回傳)

```text
report.guardian:
  g1: 孩子是有困難的人,不是困難本身——檢查每一句:行為可以被描述,人格不可被定性。
  g2: 數字只用 server 給的聚合值,不自創統計、不寫「大概」「好幾次」之類的模糊量詞。
  g3: 安全與警訊只在 fixed 節呈現,slot 內不重述警訊細節、不引用危機對話原文。
  g4: 季報/年報是可分享文件:不抄錄 facts/轉述原文(單案細節留在 event 卡)。
  g5: 比較只跟孩子自己比(上季的他 vs 這季的他),不與手足、同齡、別家比較。
```

## 驗證參數

```text
report.validation:
  negative_patterns: 講不聽|帶不動|管不了|沒救|無可救藥|問題兒童|屢勸不聽
  number_whitelist_scopes: quarter|year
  leak_window: 12
  raw_quota_event: 2
```

- `negative_patterns`:slot 負面定性清單(正則 alternation;命中 → 拒收)。
  輸出禁用詞 pattern(F2/F3/F5)同步套用於所有 slot(單一來源 = wordlists.py)。
- `number_whitelist_scopes`:數字白名單僅驗匯總級(event 單案敘事免驗——
  引用原文常含數字,單案無統計可造)。
- `leak_window`:quarter/year 防滲滑窗字數——slot 含 scope 內任一自由文本
  (facts/reaction_note/records 文本/逐字稿)之連續 12 字 → 拒收(隱私降階:
  匯總報告不得內含單案原文)。
- `raw_quota_event`:event quotes 槽的逐字稿引用段數上限(host 自律 + 字數上限承載;
  code 不逐段驗——已知軟點,文件如實陳述)。

## 語意紅線三層(H 件;單一事實來源 = wordlists.py 之 SEMANTIC_*)

1. **tripwire(警告不拒收)**:slot 子句同時含「主詞(孩子/兒子/女兒/他/她)+
   負面定性詞」且無否定前綴 → 回傳 `semantic_warnings` + events 稽核。
2. **下期回放**:季報 phase1 注入上一季定稿的 semantic_warnings 至
   `prev_audit` 固定節——警告不會無聲消失,下季回看。
3. **guardian 前置**:上方 g1–g5 在 phase1 隨骨架回傳,host 生成前自查。
