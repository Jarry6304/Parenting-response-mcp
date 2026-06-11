# parenting-response MCP

台灣家庭育兒回應系統的 Fat MCP server:**10 個理論核心單波全平行、完全隔離**,C-輕合成(**不分族、隔離並列、溯源生成**),硬 fence(FSM 守衛 / G0 兩級紅旗 / 後檢)**全部 code 強制**,L0 紀錄落 PostgreSQL 供長期分析(L1–L4)。

三個設計信念:

1. **凡「不得違反」的,不交給 LLM 自律**——呼叫順序是狀態機、紅旗是詞組比對、產出違約束出不了後檢,全是 code 閘 + DB 不變量。
2. **理論之間不投票、不加權**——十個鏡頭隔離並列(順序洗牌),合成自行取捨,但每句話術強制溯源。
3. **人在迴圈**——系統產卡與收斂建議;說不說、收不收案,永遠是家長決定。

## 架構

```mermaid
flowchart LR
    CC[chat-Claude / Claude Desktop<br/>S1 問軸、S3 轉述、呈現卡] -->|3 tools| G[FSM 守衛<br/>code]
    G --> RF{G0 兩級紅旗<br/>code}
    RF -->|短路| STOP[停案 + 轉介]
    RF -->|過| FAN[單波 fan-out<br/>10 核心隔離並行]
    FAN --> SYN[C-輕 合成 v3<br/>並列洗牌 → 生成 + 溯源]
    SYN --> CHK[後檢<br/>pattern + guardian]
    CHK -->|違 → 重生 ≤N| SYN
    CHK --> PG[(PostgreSQL<br/>sessions/rounds/records)]
```

## Tool 介面(FSM:`[2] analyze → [3] next_round ×n → [4] finalize`,無跳關無回頭)

| Tool | 階段 | 必填 | 主要錯誤碼 |
|---|---|---|---|
| `analyze_situation` | S2(內含 G0) | `mode / age_band / facts / emotion / emotion_intensity` | `E_MISSING_AXIS` / `E_INVALID_LINK` |
| `next_round` | S3 乒乓 | `session_id / child_reaction`(六類;`reaction_note` 轉述強烈建議) | `E_INVALID_STATE` / `E_INVALID_REACTION` |
| `finalize_record` | S4 收尾 | `session_id / outcome` | `E_INVALID_STATE` |

- `age_band ∈ 2-3|4-6|7-11|12+`(0-2 刻意範圍外);`child_reaction ∈ 鬆動配合|否認堅持|情緒爆發|退縮害怕|反問試探|轉移打岔`。
- 兩終態(`finalized` / `redflag_stopped`)為吸收態;違序呼叫一律明確錯誤、**零 LLM 成本**。
- promotion:rehearsal 收案得 `record_id` → live 以 `linked_plan_id` 引用,record 自動 `done_from_plan`。

## 安全邊界

- **G0 兩級**(輸入端,code):短路級(自傷/虐待/失控訊號)→ 停案 + 轉介(113/110);警訊級 → 不停案,severity 升「高」。`next_round` 對家長轉述複檢,命中自動收案。
- **後檢**(輸出端):固定禁用詞表(羞辱標籤/比較/全稱翻舊帳的語言投影)∪ 約束核心動態禁詞 + guardian 逐條驗語意約束;違者重生 ≤ N,上限或約束核心不足(K<2)→ **降級安全卡**,不硬出話術。
- **溯源強制**(v3):起手話術每句標來源核心,code 驗證,審計與 L1 歸因都靠它。
- converged 只是建議訊號,且內建 D3 鑑別:**討好式順從 ≠ 收斂**。

## Client(chat-Claude)端責任

Server 只管編排;對話由 client 承擔——S1 問齊必填軸再呼叫 `analyze`;S3 把孩子反應分類成六類 + 盡量附自由轉述(`reaction_note`,G0 複檢與核心的現實事件來源);呈現卡時 `converged=true` 可建議收尾,但 finalize 永遠等家長點頭。

## 快速開始

```bash
uv venv --python 3.12 && uv sync
uv run pytest -q          # 31 條驗收(in-memory,免 PG / API key)
uv run pyright            # strict(src),0 errors
```

執行(需 PostgreSQL 與 Anthropic API key):

```bash
export DATABASE_URL=postgresql://user:pass@localhost/parenting_response
export ANTHROPIC_API_KEY=sk-ant-...
uv run alembic upgrade head        # 或交由 server 啟動時 ensure_schema
uv run parenting-response-mcp      # stdio transport
```

Claude Desktop 設定:

```json
{
  "mcpServers": {
    "parenting-response": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Parenting-response-mcp", "parenting-response-mcp"],
      "env": { "DATABASE_URL": "...", "ANTHROPIC_API_KEY": "..." }
    }
  }
}
```

## 文件地圖(漸進載入)

| 要查 | 看 |
|---|---|
| 總規格:FSM、管線、資料模型、驗收 | `parenting-response-mcp-spec-v2.2.md` |
| 合成契約:隔離並列、溯源、trace schema | `references/resonance-c-light.md`(v3) |
| L0 欄位語意、受控詞表、A3 聚合規則 | `references/record-schema.md` |
| S3 路由、converged 判準(D3) | `references/pingpong.md` |
| 紅旗/禁用詞/confounders 詞源(F1–F8 / P01–P50) | `references/tw-parenting-antipatterns.md` |
| 十核心 prompt(runtime 即讀此處) | `references/cores/` |

## 專案結構

```text
src/parenting_response/
├── server.py          # FastMCP,3 tools
├── orchestrator.py    # FSM 守衛 → G0 → fan-out → 合成 → 後檢 → A3 聚合
├── cores/             # registry + prompt 載入(references/cores/*.md)+ 隔離呼叫
├── synthesis.py       # C-輕 v3:並列排版(洗牌)+ 生成 + 溯源驗證
├── postcheck.py       # pattern + guardian
├── pingpong.py        # 點火路由 + converged(D3)
├── redflag.py         # G0 兩級
├── schema.py          # 受控詞表 + pydantic models + 錯誤碼
├── wordlists.py       # antipatterns 的 code 投影
└── db.py              # psycopg3 + 不變量;Memory 同語意(測試)
migrations/            # Alembic
tests/                 # 驗收條件測試
```

## 狀態與已知邊界

- 規格 DRAFT 審閱中;**修正項、FSM、語言選型、合成 v3 已定**。
- 驗收測試跑在同語意 MemoryDatabase;**真 PG 不變量尚待真 PG 整合測試**。
- **P0 待驗**:真模型煙霧測試(十核心 JSON 服從率、guardian 同家族盲點)。
- 未來:L1–L4 聚合(`query_records` / `periodic_report`)、跨 vendor 異質底模、fastmcp 3.x 升級評估。
