# parenting-response MCP

台灣家庭育兒回應系統的 **Thin MCP server(v3.0):零 LLM 呼叫、零 API key**。server 以純 code 強制 4-tool 呼叫順序與安全閘;**6 回應核心**以靜態 TAG 交由 host(Claude)耦合生成,**2 探詢核心(Maslow/Satir)**前移約束探詢做診斷;L0 紀錄落 PostgreSQL。

> **賣點誠實:** v3.0 是「多學派引導 + 安全閘」,**非**「code 強制獨立判讀」——隔離保證的是輸入素材(TAG 集)乾淨,不是 per-lens 推論(spec v3.0「邊界」節)。

## Tool 介面(FSM:`① → ② → ③ ×n → ④`,違序一律 `E_INVALID_STATE`、零成本)

| Tool | 必填 | server(純 code) |
|---|---|---|
| ① `constraints` | `facts / emotion / mode` | G0 短路紅旗(→ 轉介 113/110 鎖死);回 8 校紅線聯集 ∪ 禁用詞 pattern + Maslow/Satir 探點(引導 S1) |
| ② `prerequisites` | `age_band / emotion_intensity` | 正向紀錄缺 `script_decision ∈ skip\|generate` → ask-gate 不解鎖;skip → short ④ |
| ③ `core_tags` | `session_id`(round>0 須 `child_reaction` 六類;round 0 = NULL) | 6 回應核心 TAG(primary/support 依反應確定性映射)+ Erikson/Piaget 查表 + `converged`;高張力輪強制轉述複檢 G0(其餘輪有轉述才複檢),命中自動收案 |
| ④ `finalize` | `session_id / outcome / draft`(short 模式禁 draft;一般模式須 ≥1 輪 ③) | 自由文本 G0 複檢(短路 → 轉介必達 + severity 高,案照收)+ 禁用詞 `pattern_check`:過 → `record_id`;違規 → 拒落庫回違規詞 |

- 終態 `finalized` / `redflag_stopped` 為吸收態;G0 警訊級不停案但 severity 升「高」(單調只升)。
- 棄案 TTL:open 案自最後活動逾 `SESSION_TTL_DAYS`(預設 30)天,下次 ① 懶清掃轉吸收態 `expired`(無 record;severity 留存供追蹤)。
- 稽核證據鏈:G0 命中(兩級)與 ④ 拒收一律落 `events`(欄位/詞組/節錄/轉介送達;kind 契約見 `references/record-schema.md`)。
- `converged` 為 code 規則(D3):討好式順從 ≠ 收斂——自最近一次高張力(情緒爆發/退縮害怕)後需 ≥1 輪鬆動配合才收斂,夾其他反應不重置(判定表見 spec v3.0)。
- promotion 鏈:rehearsal 收案得 `record_id` → live 以 `linked_plan_id` 引用 → 自動 `done_from_plan`;紅旗案 record(`status=stopped`)不可引用(`E_INVALID_LINK`)。
- ④ 可附 `claimed_sources`(⊆ 6 回應核心,軟溯源)與 `maslow_need`(⊆ 缺損四層,① 探點命中之回報);host 負責 S1 探詢、以 primary 領銜耦合、把實際草稿交回後檢。

## 快速開始

```bash
uv venv --python 3.12 && uv sync
uv run pytest -q     # 32 條驗收(in-memory,免 PG、免任何 API key)
uv run pyright       # strict(src),0 errors
```

執行(只需 PostgreSQL,**不需任何 LLM API key**):

```bash
export DATABASE_URL=postgresql://user:pass@localhost/parenting_response
export MCP_BEARER_TOKEN=change-me   # 選填:設了即啟用 bearer 閘
uv run alembic upgrade head         # 既有庫升級(或交由啟動時 ensure_schema)
uv run parenting-response-mcp       # streamable-HTTP,預設 0.0.0.0:8000
```

Claude custom connector:URL 填 `https://<host>:<port>/mcp`,有 token 則以 bearer 連線。
**部署 = repo checkout + `uv run`**(`references/` 是 runtime 輸入,不隨 wheel 打包)。

## 文件地圖

| 要查 | 看 |
|---|---|
| 總規格(LOCKED):FSM、tool 契約、安全邊界、驗收 | `parenting-response-mcp-spec-v3.0.md` |
| 學派 TAG(6 回應 + 2 探詢;runtime 即讀此處) | `references/cores/tags.md` |
| L0 欄位語意、受控詞表、schema_version 分流 | `references/record-schema.md` |
| 紅旗/禁用詞詞源(F1–F8 / P01–P50) | `references/tw-parenting-antipatterns.md` |
| 歷史(v2.2 fat server:合成/乒乓/十核心 prompt) | 標 `superseded` 各檔 |

## 專案結構

```text
src/parenting_response/
├── server.py        # FastMCP,4 tools + bearer 閘(main)
├── orchestrator.py  # FSM 守衛 → G0 → TAG/查表/converged → 後檢 → 落庫
├── cores/           # tags.md 解析器(8 校完整性 fail-fast)
├── redflag.py       # G0 兩級
├── schema.py        # 受控詞表 + 錯誤碼
├── wordlists.py     # antipatterns 的 code 投影
└── db.py            # psycopg3 + 不變量;Memory 同語意(測試)
migrations/          # Alembic(0001 初始 / 0002 v3 冪等升級)
tests/               # 32 條驗收(零 LLM)
```

已知邊界:真 PG 遷移與 bearer 閘待真環境整合驗證;未來 L1–L4 聚合、SQLite 後端、fastmcp 3.x 升級皆為獨立決策。
