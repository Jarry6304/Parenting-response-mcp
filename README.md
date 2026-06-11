# parenting-response MCP

台灣家庭育兒回應系統的 Fat MCP server——10 個理論核心單波全平行、完全隔離,C-輕合成(不分族、隔離並列、溯源生成),硬 fence(FSM 守衛 / G0 兩級紅旗 / 後檢)全 code 強制,L0 紀錄落 PostgreSQL。

- 規格:`parenting-response-mcp-spec-v2.2.md`
- 合成契約:`references/resonance-c-light.md`(v3)
- 詞表/路由/L0 語意:`references/`(cores prompt 即 runtime 載入的單一事實來源)

## 開發

```bash
uv venv --python 3.12
uv sync                 # 安裝依賴(含 dev)
uv run pytest -q        # 20+ 條驗收測試(in-memory,不需 PG / API key)
uv run pyright          # strict 型別檢查
```

## 執行

```bash
export DATABASE_URL=postgresql://user:pass@localhost/parenting_response
export ANTHROPIC_API_KEY=sk-ant-...
uv run alembic upgrade head        # 或由 server 啟動時 ensure_schema
uv run parenting-response-mcp      # stdio transport
```

Claude Desktop 設定範例:

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

## 結構

```text
src/parenting_response/
├── server.py          # FastMCP,3 tools(analyze_situation / next_round / finalize_record)
├── orchestrator.py    # FSM 守衛 → G0 → 單波 fan-out → 合成 → 後檢 → 聚合回填
├── cores/             # registry + prompt 載入(references/cores/*.md)+ 隔離呼叫
├── synthesis.py       # C-輕 v3:並列排版(洗牌)+ 生成 + 溯源驗證
├── postcheck.py       # pattern + guardian
├── pingpong.py        # S3 點火路由 + converged(D3)
├── redflag.py         # G0 兩級(短路/警訊)
├── schema.py          # 受控詞表 + pydantic models + 錯誤碼
├── wordlists.py       # tw-parenting-antipatterns 的 code 投影
└── db.py              # PG(psycopg3)+ 不變量;Memory 同語意(測試)
migrations/            # Alembic
tests/                 # 驗收條件(spec v2.2 + resonance v3)
```
