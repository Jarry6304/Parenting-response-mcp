# CLAUDE.md

台灣家庭育兒回應 MCP server(v3.0 thin:**零 LLM 呼叫、零 API key**)。文件與訊息一律 zh-TW。

## 指令

```bash
uv sync                # 安裝(Python 3.12+;.venv)
uv run pytest -q       # 32 條驗收(in-memory,免 PG、免 API key)
uv run pyright         # strict,範圍 = src/(必須 0 errors)
uv run alembic upgrade head   # 需 DATABASE_URL(0002 冪等,既有庫可直升)
```

## 事實來源的階層(改東西前先看這裡)

1. **`parenting-response-mcp-spec-v3.0.md` 是總規格(LOCKED)**;行為與規格衝突 = bug。標 `superseded` 各檔(含 v2.2)僅供歷史參照。
2. **學派 TAG 單一事實來源 = `references/cores/tags.md`**,runtime 由 `cores/__init__.py` 解析(8 校完整性 fail-fast)。改 TAG 改文件,不改 code。
3. **`wordlists.py` 是 `references/tw-parenting-antipatterns.md` 的 code 投影**:先改文件,再同步 code。
4. records 欄位語意與 `schema_version`(現 = 2)歸 `references/record-schema.md` 版本管理:變更必 bump 並同步 Alembic 遷移。
5. `REACTION_PRIMARY` 與 converged 規則的單一來源 = spec v3.0;orchestrator 內為 code 投影,改映射先改 spec。

## 不可破壞的不變量

- **零 LLM**:server 端無 LLM client 物件(測試斷言);耦合生成是 host 的事。**禁止引入 anthropic / 任何 LLM SDK**。
- FSM stage 守衛:`① constraints → ② prerequisites → ③ core_tags* → ④ finalize`,違序一律 `E_INVALID_STATE`;吸收態三個:終態 `finalized`/`redflag_stopped` + 棄案 `expired`(僅 ① TTL 懶清掃產生,錨定最後活動;無 record、severity 留存)。
- G0 先於一切:① 短路 → 轉介鎖死;③ 複檢(高張力輪強制 `reaction_note`,缺則 ask-gate;其餘輪有轉述才檢),命中 → 自動收案 `escalated_to_redflag`(record `status=stopped`,不進 promotion 鏈);④ 四個自由文本複檢(短路不拒收:轉介必達 + severity↑);警訊級 → severity 升「高」(單調只升)。
- 正向紀錄硬閘:缺 `script_decision` 不解鎖;skip 走 short ④(`draft=NULL`,不跑 `pattern_check`);一般 ④ 須先 ③ 至少一輪、必有 draft 且過禁用詞檢才落庫。
- 終態寫入一律走 `db.finalize_tx`(條件式 `WHERE status='open'` + records UNIQUE);不要繞過。
- ① 約束集 = 8 校紅線聯集 ∪ wordlists 禁用詞 pattern;探詢核心(maslow/satir)只進 ①,不進 ③ 耦合。
- `converged` 為 code 規則(D3 投影,單一來源 = spec v3.0 判定表):鬆動配合 ∧ 無警訊 ∧ 自最近一次高張力後已有 ≥1 輪鬆動配合(夾其他反應不重置防線)。

## 測試與依賴

- `tests/conftest.py`:`MemoryDatabase`(db.py,與 PG 同不變量語意)+ fastmcp in-memory `Client` 直打;**無 FakeLLM**。新增行為 → 對應 spec 驗收條目加測試;canned 文本別誤踩詞表(兩級詞組 + F2/F3/F5 pattern)。
- fastmcp pin `<3`(3.x 升級是獨立決策,勿順手升);bearer 閘用 `fastmcp.server.auth.StaticTokenVerifier`;`uv.lock` 進版控。
- `references/` 不隨 wheel 打包:部署 = repo checkout + `uv run`(tags.md 是 ① 的 runtime 輸入)。
