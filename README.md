# parenting-response MCP

台灣家庭育兒回應系統的 **Thin MCP server(v3.0):零 LLM 呼叫、零 API key**。server 以純 code 強制 6-tool 呼叫順序與安全閘;**6 回應核心**以靜態 TAG 交由 host(Claude)耦合生成,**2 探詢核心(Maslow/Satir)**前移約束探詢做診斷;L0 紀錄落 PostgreSQL(自由文本信封加密)。

> **賣點誠實:** 這是「多學派引導 + 安全閘 + 紀錄/報告」,**非**「code 強制獨立判讀」——隔離保證的是輸入素材(TAG 集)乾淨,不是 per-lens 推論。
>
> **v3.0 核心轉向:G0 由閘降為訊號**——輸入端永不停案(求助的人不該被掛電話),強制力集中輸出匣:③ 換安全約束集(3 風險向 × 4 年齡)、④ 須 `referral_ack`、紅旗 record 永久排除 promotion。

## Tool 介面(FSM:`① → ② → ③ ×n → ④ → ⑤ → report`,違序一律 `E_INVALID_STATE`)

| Tool | 必填 | server(純 code) |
|---|---|---|
| ① `constraints` | `facts / emotion / mode`(mode 缺 → 入口 ask-gate;`resume` 接舊案) | G0 短路 = **訊號**(旗標+轉介+safety_mode,照常建案);回 8 校紅線聯集 ∪ 禁用詞 pattern + Maslow/Satir 探點 |
| ② `prerequisites` | `age_band / emotion_intensity`(retro 另須 `parent_action`) | 正向紀錄缺 `script_decision` → ask-gate;`parent_action` 過 G0(source=②) |
| ③ `core_tags` | `session_id`(round>0 須 `child_reaction` 六類) | 6 回應核心 TAG + Erikson/Piaget 查表 + `converged`;**redflag_active → 安全約束集換軌**(無一般管教 TAG);retro ×1 回六校覆盤鏡頭;上輪收斂 → 收束 ask-gate;第 5 輪起 `suggest_pause` |
| ④ `finalize` | `session_id / outcome / draft`(紅旗在案另須 `referral_ack=true`) | 自由文本 G0 複檢 + 禁用詞 `pattern_check`;過 → `record_id`(`record.redflag` 落錨)+ `next: archive` |
| ⑤ `archive` | `session_id / chunk_no / turns` | 原始逐字稿歸檔:工具標記防滲(整 chunk 拒收)、content_hash 冪等、G0 掃 parent 發言(record 不回改) |
| `report` | `scope ∈ event\|quarter\|year / ref`(+`slots` = phase2) | phase1 九維聚合+骨架+guardian;phase2 五道驗證(字數/負面清單/數字白名單/原文防滲)→ 確定性組裝落庫;語意 tripwire 警告不拒收、下季回放 |

- 終態 `finalized` / `expired`(TTL 棄案);`redflag_stopped` 自本輪改版退役(legacy 列保留)。
- G0 訊號單調:`redflag_active`/`severity`/`redflag_vector`(首見)只升不降不覆寫;①②③④⑤ 全入口稽核落 `events`。
- 多照顧者(爸/媽):由 OAuth sub 經 `CAREGIVER_MAP` 映射,**不收輸入參數**;報告僅自照計數,比較句進語意警示。

## 快速開始(本機)

```bash
uv venv --python 3.12 && uv sync
uv run pytest -q     # 134 條驗收(in-memory,免 PG、免任何 API key)
uv run pyright       # strict(src),0 errors
```

執行(只需 PostgreSQL,**不需任何 LLM API key**):

```bash
export DATABASE_URL=postgresql://user:pass@localhost/parenting_response
uv run alembic upgrade head    # 0001→0008(或交由啟動時 ensure_schema)
uv run parenting-response-mcp  # streamable-HTTP,預設 127.0.0.1:8000(local 模式)
```

## 部署(Cloud Run + Neon + AuthKit;見 `docs/deploy-runbook.md`)

**env 總表**:

| env | 模式 | 說明 |
|---|---|---|
| `DATABASE_URL` | 必 | PostgreSQL 連線(Neon pooled) |
| `AUTH_MODE` | 必(雲) | `local`(預設;**只准 loopback**,違者拒啟動)\| `authkit` |
| `AUTHKIT_DOMAIN` / `BASE_URL` | authkit 必 | WorkOS AuthKit 網域 / server 公開 URL |
| `ALLOWED_SUBJECTS` | authkit 必 | 放行 sub 清單(逗號分隔);其餘 401 + `auth_denied` 稽核 |
| `CAREGIVER_MAP` | authkit 必 | JSON `{sub: 爸\|媽}`;未映射 sub 建案即拒 |
| `ENVELOPE_KEYS` / `ENVELOPE_ACTIVE_KEY_ID` | 雲必 | 信封加密金鑰圈(JSON `{kid: b64-32B}`)/ 現用 kid;未設 = 明文直通(僅限本機) |
| `HOST` / `PORT` | 選 | 預設 `127.0.0.1:8000`;容器 `0.0.0.0` + `$PORT` |
| `SESSION_TTL_DAYS` | 選 | 棄案 TTL(預設 30;≤0 停用) |

退役:`MCP_BEARER_TOKEN`(v3.0 靜態 bearer 閘 → AuthKit OAuth)。

Claude custom connector:URL 填 `https://<host>/mcp`,AuthKit 登入(DCR)。
**部署 = repo checkout / 容器 COPY 全量**(`references/` 是 runtime 輸入,不隨 wheel 打包)。
週備份:`.github/workflows/backup.yml`(pg_dump→zstd→age→私有 repo);還原演練見 runbook §6。

## 文件地圖

| 要查 | 看 |
|---|---|
| 總規格(LOCKED):FSM、tool 契約、安全邊界、驗收 | `parenting-response-mcp-spec-v3.0.md`(含 2026-06 Amendment A–K;衝突處以 Amendment 節為準) |
| 學派 TAG(6 回應+2 探詢+覆盤 6+safety 7;runtime 即讀) | `references/cores/tags.md` |
| 報告骨架/槽位/guardian/驗證參數 | `references/report-core.md` |
| L0 欄位語意、受控詞表、schema_version 分流、events 契約 | `references/record-schema.md` |
| 紅旗/禁用詞詞源(F1–F8 / P01–P50) | `references/tw-parenting-antipatterns.md` |
| 部署/備份/還原/金鑰輪替 | `docs/deploy-runbook.md` |
| 歷史(v2.2 fat server) | 標 `superseded` 各檔 |

## 專案結構

```text
src/parenting_response/
├── server.py        # FastMCP,6 tools + AUTH_MODE 分流(main)
├── orchestrator.py  # FSM 守衛 → G0 訊號 → TAG/safety 卡/覆盤 → 後檢 → 落庫 → 報告
├── cores/           # tags.md 解析器(8 校+覆盤 6+safety 7,fail-fast)
├── report_core.py   # report-core.md 解析器(骨架/guardian/驗證參數)
├── report.py        # 九維聚合 + 確定性組裝(期界錨臺北)
├── auth.py          # AuthKit OAuth + sub allowlist(I 件)
├── crypto.py        # 信封加密 AES-256-GCM(J 件;多鑰共存)
├── redflag.py       # G0 兩級 + 風險向
├── schema.py        # 受控詞表 + 錯誤碼 + TZ_TAIPEI
├── wordlists.py     # antipatterns 的 code 投影 + 語意紅線 + 工具標記防滲
└── db.py            # psycopg3 + 不變量 + 透明加解密;Memory 同語意(測試)
migrations/          # Alembic 0001–0008(皆冪等;0007 就地加密需金鑰)
tests/               # 134 條驗收(零 LLM)
Dockerfile           # Cloud Run 映像(uv slim + references/)
.github/workflows/backup.yml  # 週備份
```

已知邊界:connector 端到端與 Cloud Run 冷啟待真環境驗收(runbook §4);
sub 拒絕回 401 非 403(fastmcp 卡點限制,稽核等價);fastmcp 3.x 升級為獨立決策。
