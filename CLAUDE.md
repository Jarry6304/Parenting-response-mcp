# CLAUDE.md

台灣家庭育兒回應 MCP server。文件與訊息一律 zh-TW。

## 指令

```bash
uv sync                # 安裝(Python 3.12+;.venv)
uv run pytest -q       # 31 條驗收測試(in-memory,免 PG / API key)
uv run pyright         # strict,範圍 = src/(必須 0 errors)
uv run alembic upgrade head   # 需 DATABASE_URL
```

## 事實來源的階層(改東西前先看這裡)

1. **`parenting-response-mcp-spec-v2.2.md` 是總規格**;`references/resonance-c-light.md`(v3)是合成契約。行為與規格衝突 = bug。
2. **十核心 prompt 的單一事實來源 = `references/cores/<id>.md` 的「## system prompt」節**,runtime 由 `src/parenting_response/cores/__init__.py` 解析載入。改 prompt 改文件,不改 code。
3. **`src/parenting_response/wordlists.py` 是 `references/tw-parenting-antipatterns.md` 的 code 投影**:改詞表先改文件,再同步 code。
4. 核心輸出欄位名(`purpose`/`unmet_needs`/`stage_observed`/`within_norm`/`child_stance`/`emotion_processed`)是 L0 聚合與 converged 的 de facto 契約,改名須過 `references/record-schema.md` 的版本管理。

## 不可破壞的不變量

- FSM:`analyze → next_round* → finalize`,守衛先於一切 LLM(測試斷言違序 LLM 計數 = 0)。
- 終態寫入一律走 `db.finalize_tx`(條件式 `WHERE status='open'` + records UNIQUE);不要繞過。
- 核心輸入 = 結構化情境 only:無其他核心輸出、無卡文、無 linked_plan(嚴格隔離)。
- 合成版面與 `SynthesisTrace` 不得含 family / confidence / 權重欄(`extra="forbid"` + assert,防回歸)。
- 降級路徑(後檢上限、約束核心 < K=2)出降級安全卡,不出正常卡。

## 測試約定

- `tests/conftest.py`:`FakeLLM` 以 tag 路由(`core:<id>` / `synthesis` / `guardian`)並計數;`MemoryDatabase` 與 PG 同不變量語意;server 經 fastmcp in-memory `Client` 直打。
- 新增行為 → 對應 spec 驗收條目加測試;G0/詞表類測試注意 canned 文本別誤踩詞表。

## 依賴注意

- fastmcp pin `<3`(spec 釘 2.x 線;3.x 升級是獨立決策,勿順手升)。
- `uv.lock` 進版控;模型字串集中在 `src/parenting_response/llm.py`。
