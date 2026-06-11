# CLAUDE.md

台灣家庭育兒回應 MCP server(v3.0 thin:**零 LLM 呼叫、零 API key**)。文件與訊息一律 zh-TW。

## 指令

```bash
uv sync                # 安裝(Python 3.12+;.venv)
uv run pytest -q       # 32 條驗收測試(in-memory,免 PG、免任何 API key)
uv run pyright         # strict,範圍 = src/(必須 0 errors)
uv run alembic upgrade head   # 需 DATABASE_URL(0002 冪等,既有庫可直升)
```

## 事實來源的階層(改東西前先看這裡)

1. **`parenting-response-mcp-spec-v3.0.md` 是總規格(LOCKED)**。行為與規格衝突 = bug。v2.2 與 `references/` 內標 `superseded` 各檔僅供歷史參照,勿當現行契約。
2. **學派 TAG 的單一事實來源 = `references/cores/tags.md`**(6 回應核心 `理念/套用/示範/紅線`;2 探詢核心 `探詢/探點/示範問/紅線`),runtime 由 `src/parenting_response/cores/__init__.py` 解析載入(8 校完整性 fail-fast)。改 TAG 改文件,不改 code。
3. **`src/parenting_response/wordlists.py` 是 `references/tw-parenting-antipatterns.md` 的 code 投影**:改詞表先改文件,再同步 code。
4. records 欄位語意與 `schema_version`(現 = 2)歸 `references/record-schema.md` 版本管理:任何欄位語意/值域變更必須 bump 並同步 Alembic 遷移。
5. 反應二級強調表(`REACTION_PRIMARY`)與 converged 規則的單一來源 = spec v3.0;`orchestrator.py` 內為 code 投影,改映射先改 spec。

## 不可破壞的不變量

- **零 LLM**:server 端無 LLM client 物件(測試斷言 `Orchestrator.__init__` 無 llm 參數、無 `parenting_response.llm` 模組);耦合生成是 host 的事。
- FSM stage 守衛:`① constraints → ② prerequisites → ③ core_tags* → ④ finalize`,違序一律 `E_INVALID_STATE`、零成本;兩終態(`finalized`/`redflag_stopped`)為吸收態。
- G0 先於一切:① 對 facts/emotion 短路,③ 每輪對 reaction 複檢;短路 → 轉介鎖死,複檢命中 → 自動收案 `escalated_to_redflag`。
- 正向紀錄硬閘:缺 `script_decision` 不解鎖任何後續;skip 走 short ④(`draft=NULL`,不跑 `pattern_check`);一般 ④ 必有 draft 且過禁用詞檢才落庫。
- 終態寫入一律走 `db.finalize_tx`(條件式 `WHERE status='open'` + records UNIQUE);不要繞過。
- ① 約束集 = 8 校紅線聯集 ∪ wordlists 禁用詞 pattern;探詢核心(maslow/satir)只進 ①,不進 ③ 耦合。
- `converged` 為 code 規則(D3 投影):鬆動配合 ∧ 無警訊 ∧ 前一輪非高張力(情緒爆發/退縮害怕後需連續兩輪)。

## 測試約定

- `tests/conftest.py`:`MemoryDatabase`(`db.py`,與 PG 同不變量語意)+ fastmcp in-memory `Client` 直打;**無 FakeLLM**(零 LLM 後不存在)。
- 新增行為 → 對應 spec v3.0 驗收條目加測試;G0/詞表類測試注意 canned 文本別誤踩詞表(兩級詞組 + F2/F3/F5 pattern)。

## 依賴注意

- fastmcp pin `<3`(spec 釘 2.x 線;3.x 升級是獨立決策,勿順手升);bearer 閘用 `fastmcp.server.auth.StaticTokenVerifier`。
- `uv.lock` 進版控;**禁止引入 anthropic / 任何 LLM SDK 依賴**(零 key 是 v3.0 賣點)。
- `references/` 不隨 wheel 打包:部署 = repo checkout + `uv run`(tags.md 是 ① 的 runtime 輸入)。
