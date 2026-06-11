# parenting-response MCP

台灣家庭育兒回應系統的 **Thin MCP server(v3.0):零 LLM 呼叫、零 API key**。對 host(Claude)只暴露 4 個工具,server 端以純 code 強制呼叫順序與安全閘;**6 回應核心**以靜態 TAG 交由 host 一次耦合生成,**2 探詢核心(Maslow/Satir)**前移到約束探詢做診斷;L0 紀錄落 PostgreSQL 供長期分析。

> **賣點誠實:** v3.0 是「多學派引導 + 安全閘」,**非**「code 強制獨立判讀」——隔離保證的是輸入素材(TAG 集)乾淨,不是 per-lens 推論。對外與 demo 一律據此描述(spec v3.0「邊界」節)。

三個設計信念:

1. **凡「不得違反」的,不交給 LLM 自律**——呼叫順序是狀態機、紅旗是詞組比對、草稿過不了禁用詞檢就不落庫,全是 code 閘 + DB 不變量。
2. **server 不付推論費**——真隔離需 MCP sampling(Claude client 不支援),v3.0 以靜態 TAG + 反應二級強調換取零 key、零推論成本。
3. **人在迴圈**——系統給引導與收斂訊號;說不說、收不收案,永遠是家長決定。

## 架構

```mermaid
flowchart LR
    H[host Claude<br/>S1 探詢 / 耦合生成 / 對 user 講話] -->|4 tools・FSM 序| S[MCP server<br/>純 code・零 LLM]
    S --> T1{① 約束探詢<br/>G0 + 紅線 + Maslow/Satir 探點}
    T1 -->|短路命中| STOP[redflag_stopped<br/>轉介 113/110]
    T1 -->|過| T2[② 必備條件<br/>必填軸 + 正向紀錄硬閘]
    T2 --> T3[③ 各核心條件<br/>6 回應核心 TAG + 反應二級強調]
    T3 -.host 耦合.-> H
    T3 --> T4[④ 總結分析<br/>host 交草稿 → 禁用詞 code → 落庫]
    T4 --> DB[(sessions / rounds / records)]
```

## Tool 介面(FSM:`① constraints → ② prerequisites → ③ core_tags ×n → ④ finalize`,違序 `E_INVALID_STATE`)

| Tool | 階段 | 必填 | 回傳重點 |
|---|---|---|---|
| `constraints` | ① 約束探詢(內含 G0) | `facts / emotion / mode` | 8 校紅線聯集 ∪ 禁用詞 pattern + **Maslow/Satir 探點**(引導 S1) |
| `prerequisites` | ② 必備條件 | `age_band / emotion_intensity`(`problem_category?` / `script_decision?`) | 正向紀錄缺 `script_decision` → ask-gate 不解鎖 |
| `core_tags` | ③ 乒乓 ×n | `session_id`(round>0 須 `child_reaction`,round 0 = NULL) | 6 回應核心 TAG(primary/support)+ Erikson/Piaget 查表 + `converged` |
| `finalize` | ④ 終態 | `session_id / outcome / draft`(short 模式禁 draft) | 禁用詞 `pattern_check` 過 → `record_id`;違規 → 拒落庫回違規詞 |

- `age_band ∈ 2-3|4-6|7-11|12+`(0-2 刻意範圍外);`child_reaction ∈ 鬆動配合|否認堅持|情緒爆發|退縮害怕|反問試探|轉移打岔`。
- **正向紀錄硬閘**:`problem_category=正向紀錄` 時 ② 必問 `script_decision ∈ skip|generate`;skip → short ④(只記事,`draft=NULL`、不跑 pattern_check)。
- **反應二級強調**:③ 依 `child_reaction` 確定性映射 primary(如 情緒爆發 → gottman, rogers),host 以 primary 領銜耦合;round 0 六核心全 primary。
- 兩終態(`finalized` / `redflag_stopped`)為吸收態;違序呼叫一律明確錯誤、**零 server 成本**。
- promotion:rehearsal 收案得 `record_id` → live 以 `linked_plan_id` 引用,record 自動 `done_from_plan`。
- ④ 可附 `claimed_sources`(⊆ 6 回應核心,軟溯源)與 `maslow_need`(⊆ 缺損四層,① 探點命中之回報)。

## 安全邊界

- **G0 兩級**(code):短路級(自傷/虐待/失控訊號)→ 停案 + 轉介(113/110);警訊級 → 不停案,severity 升「高」。① 對 facts/emotion、③ 每輪對 reaction 複檢;複檢命中自動收案(`escalated_to_redflag`)。
- **後檢**(④,code):host 草稿對固定禁用詞表(羞辱標籤/比較/全稱翻舊帳的語言投影,F2/F3/F5)`pattern_check`;命中拒落庫、回違規詞要求重生。
- **紅線約束集**(①,code):8 校(6 回應 + 2 探詢)紅線聯集 ∪ `wordlists.py` 禁用詞 pattern,開場即交給 host。
- `converged` 為 code 規則(非 host 自報),內建 D3 鑑別:**討好式順從 ≠ 收斂**——高張力反應(情緒爆發/退縮害怕)後的第一個「鬆動配合」不算,需連續兩輪。
- 軟保證(host 配合,僅誘因不偵測):溯源真實性、「是否真問家長」、「只過後檢才到 user」——`record_id`/`converged` 藏在 ④ 後作為誘因。

## Host(Claude)端責任

Server 只管守序與安全;對話與生成由 host 承擔——① 拿探點後做 S1 探詢(先排除 Maslow 缺損、探 Satir 冰山);② 問齊必填軸(正向紀錄須真的問家長要不要劇本);③ 拿 TAG 後以 primary 領銜耦合生成、對 user 講話;④ 把實際用的草稿交回後檢,並標註 `claimed_sources`。

## 快速開始

```bash
uv venv --python 3.12 && uv sync
uv run pytest -q          # 32 條驗收(in-memory,免 PG、免任何 API key)
uv run pyright            # strict(src),0 errors
```

執行(只需 PostgreSQL,**不需任何 LLM API key**):

```bash
export DATABASE_URL=postgresql://user:pass@localhost/parenting_response
export MCP_BEARER_TOKEN=change-me        # 選填:設了即啟用 bearer 閘
uv run alembic upgrade head              # 既有資料庫升級(或交由啟動時 ensure_schema)
uv run parenting-response-mcp            # streamable-HTTP,預設 0.0.0.0:8000
```

Claude custom connector(remote MCP):URL 填 `https://<host>:<port>/mcp`,有設 `MCP_BEARER_TOKEN` 則以 bearer token 連線。

> 部署 = **repo checkout + `uv run`**:學派 TAG 與詞表的事實來源在 `references/`,不隨 wheel 打包;勿以純 wheel 安裝部署。

## 文件地圖(漸進載入)

| 要查 | 看 |
|---|---|
| 總規格:FSM、tool 契約、安全邊界、驗收 | `parenting-response-mcp-spec-v3.0.md` |
| 學派 TAG(6 回應 + 2 探詢;runtime 即讀此處) | `references/cores/tags.md` |
| L0 欄位語意、受控詞表、schema_version 分流 | `references/record-schema.md` |
| 紅旗/禁用詞詞源(F1–F8 / P01–P50) | `references/tw-parenting-antipatterns.md` |
| 歷史(v2.2 fat server:合成/乒乓/十核心 prompt) | `parenting-response-mcp-spec-v2.2.md` 與 `references/` 內標 `superseded` 各檔 |

## 專案結構

```text
src/parenting_response/
├── server.py          # FastMCP,4 tools + bearer 閘(main)
├── orchestrator.py    # FSM stage 守衛 → G0 → TAG/查表/converged → 後檢 → 落庫
├── cores/             # tags.md 解析器(8 校完整性 fail-fast)
├── redflag.py         # G0 兩級
├── schema.py          # 受控詞表 + 錯誤碼(+ Redflag)
├── wordlists.py       # antipatterns 的 code 投影
└── db.py              # psycopg3 + 不變量;Memory 同語意(測試)
migrations/            # Alembic(0001 初始 / 0002 v3 冪等升級)
tests/                 # 驗收條件測試(零 LLM)
```

## 狀態與已知邊界

- spec v3.0 LOCKED(架構與三項待議全數定案);v2.2 標 superseded 保留為歷史。
- 驗收測試跑在同語意 MemoryDatabase;**真 PG 不變量與 0002 遷移尚待真 PG 整合驗證**;bearer 閘屬手動/整合驗證項(in-memory client 不經 HTTP)。
- 未來:L1–L4 聚合(`query_records` / `periodic_report`)、SQLite 本地後端(Protocol 已留口)、fastmcp 3.x 升級評估(獨立決策)。
