# CLAUDE.md

台灣家庭育兒回應 MCP server(v3.0 thin:**零 LLM 呼叫、零 API key**)。文件與訊息一律 zh-TW。

## 指令

```bash
uv sync                # 安裝(Python 3.12+;.venv)
uv run pytest -q       # 134 條驗收(in-memory,免 PG、免 API key)
uv run pyright         # strict,範圍 = src/(必須 0 errors)
uv run alembic upgrade head   # 需 DATABASE_URL(0001–0008 冪等;0007 就地加密另需 ENVELOPE_KEYS)
```

## 事實來源的階層(改東西前先看這裡)

1. **`parenting-response-mcp-spec-v3.0.md` 是總規格(LOCKED)**;行為與規格衝突 = bug。2026-06 G0 訊號化等 A–K 變更已 amend 寫回該檔文末 Amendment 節(衝突處以該節為準,版號維持 3.0);標 `superseded` 各檔(含 v2.2)僅供歷史參照。
2. **學派 TAG/safety 卡/覆盤鏡頭單一事實來源 = `references/cores/tags.md`**(8 校 + 覆盤 6 塊 + safety 7 塊,fail-fast),runtime 由 `cores/__init__.py` 解析。改內容改文件,不改 code。
3. **報告骨架/guardian/驗證參數單一來源 = `references/report-core.md`**(三 scope 章節、槽字數、敏感節模板、負面清單、防滲滑窗),runtime 由 `report_core.py` 解析(fail-fast)。
4. **`wordlists.py` 是 `references/tw-parenting-antipatterns.md` 的 code 投影**:先改文件,再同步 code。G0 短路詞依風險向分組(`G0_SHORTCIRCUIT_BY_VECTOR`:child/parent/third),向決定 ③ safety 卡。
5. records 欄位語意與 `schema_version`(現 = **3**)歸 `references/record-schema.md` 版本管理:變更必 bump 並同步 Alembic;`events`/`raw_transcripts`/`reports` 為 append-only side-tables,不動版號,契約同歸該檔。
6. `REACTION_PRIMARY`/`converged`/收束 ask-gate/軟上限為 code 投影,單一來源 = spec;orchestrator 內改映射先改 spec。

## 不可破壞的不變量

- **零 LLM**:server 端無 LLM client 物件(測試斷言);耦合生成是 host 的事。**禁止引入 anthropic / 任何 LLM SDK**(目前唯一密碼學依賴 = cryptography)。
- **G0 = 訊號,不是閘(v3.0 核心)**:①②③④⑤ 全入口複檢,短路命中**永不停案**——旗標 `redflag_active`/`severity=高`/`redflag_vector`(首見)單調寫入,FSM 照常推進;`redflag_stopped` 終態已退役,**任何新路徑不得產生**。強制力只在輸出匣:③ redflag_active → 安全約束集換軌(無一般管教 TAG、converged 恆 false)、④ 須 `referral_ack=true` 否則 `E_MISSING_AXIS`(訊號先落再擋)、`record.redflag=true` 永久排除 promotion(`E_INVALID_LINK`)。
- FSM stage 守衛:`① constraints → ② prerequisites → ③ core_tags* → ④ finalize(→ ⑤ archive → report)`,違序一律 `E_INVALID_STATE`;吸收態:終態 `finalized` + 棄案 `expired`(① TTL 懶清掃,錨最後活動 = updated_at ∪ rounds;resume 即續期)。⑤/report 不動 FSM(任何 status 可歸檔;event 報告需已收案)。
- 入口分流(①):mode 缺 → ask-gate(live/retro/resume + open 案清單,**不建案**);resume 不建案不動 stage,輪摘要不回放 reaction_note。
- retro(②③④):② 必填 `parent_action`(進 G0,source=②);③ 限一輪,回六校覆盤鏡頭,converged=NULL;探詢核心(maslow/satir)不作覆盤視角。
- 正向紀錄硬閘:缺 `script_decision` 不解鎖;skip 走 short ④(`draft=NULL`,不跑 `pattern_check`);一般 ④ 須先 ③ 至少一輪、必有 draft 且過禁用詞檢才落庫。
- 終態寫入一律走 `db.finalize_tx`(條件式 `WHERE status='open'` + records UNIQUE);不要繞過。
- ⑤ archive:工具協議標記命中 → 整 chunk 拒收;content_hash(明文)冪等;G0 只掃 parent turns;**已落 record 不回改**。
- report:fixed 節 code 組裝(敏感節僅模板句式)、slot 五道驗證(齊備/字數/負面清單/數字白名單(匯總級)/12 字滑窗防滲);組裝確定性(**body 禁時間戳**,同輸入逐位元同);語意 tripwire(含照顧者比較句)警告不拒收 → events + 下季回放。期界/record_id 一律錨臺北(`schema.TZ_TAIPEI`)。
- auth(I 件):`AUTH_MODE=local` 非 loopback **拒啟動**;authkit 三要素缺一拒啟動;sub allowlist 拒絕 = 401 + `auth_denied` 稽核;events payload 自動附 sub。
- 加密(J 件):G0 在 orchestrator 層掃**明文**,db 層透明 enc/dec(Memory/Pg 同語意);密文 `enc:<key_id>:…` 多鑰共存;未設金鑰 = 直通;**庫裡有舊鑰密文前不得撤鑰**。
- caregiver(K 件):只由已驗 sub 經 `CAREGIVER_MAP` 映射(**不收輸入參數**);未映射 → `E_INVALID_STATE` + 稽核,不建案;報告僅自照計數,不產對比。
- ① 約束集 = 8 校紅線聯集 ∪ wordlists 禁用詞 pattern;探詢核心(maslow/satir)只進 ①,不進 ③ 耦合。
- `converged` 為 code 規則(D3 投影):鬆動配合 ∧ 無警訊 ∧ 自最近一次高張力後已有 ≥1 輪鬆動配合;**寫入時定格於 `rounds.synthesis_trace.converged`**,收束 ask-gate 讀上輪 trace 不重算(live 限定;帶 `parent_decision=continue` 放行)。

## 測試與依賴

- `tests/conftest.py`:`MemoryDatabase`(db.py,與 PG 同不變量語意)+ fastmcp in-memory `Client` 直打;**無 FakeLLM**。新增行為 → 對應 spec 驗收條目加測試;canned 文本別誤踩詞表(兩級詞組 + F2/F3/F5 pattern + 語意紅線 `SEMANTIC_EVAL_TERMS` + 比較句),報告測試另防 12 字滑窗誤滲(slot 別抄 facts 原文)。
- 加密測試僅 `test_crypto.py` 開金鑰 fixture,全套件其餘維持直通;斷言密文直查 `MemoryDatabase` 內部 dict。
- fastmcp pin `<3`(3.x 升級是獨立決策,勿順手升);auth 用 `AuthKitProvider` + 自訂 `AllowlistVerifier`(`auth.py`);`uv.lock` 進版控。
- `references/` 不隨 wheel 打包:部署 = repo checkout / Docker COPY 全量 + `uv run`(tags.md / report-core.md 是 runtime 輸入)。
- 部署/備份/還原/金鑰輪替操作 → `docs/deploy-runbook.md`(雲端設定不進 code,只認 env)。
