# CHANGELOG

版本斷代總表(細節:spec 各版 frontmatter 的 `amended` 欄 + git log)。
版號規約:spec 採 amend 制——架構不變的行為變更寫回現版,不開新號。

## v3.0(2026-06-12 Amendment:G0 訊號化與能力擴充 A–K)

**核心轉向:G0 由閘降為訊號**——輸入永不停案(`redflag_stopped` 退役),
強制力集中輸出匣(③ 安全約束集換軌 / ④ `referral_ack` / `record.redflag`
排除 promotion)。工具 4 → 6 個。134 條驗收。

- **A** G0 閘→訊號:旗標/severity/風險向單調寫入,FSM 照常推進(遷移 0004,records schema_version 2→3)
- **B** retro 事後覆盤 mode:② 必填 `parent_action`、③×1 回六校覆盤鏡頭、converged=NULL
- **C** 入口分流 ask-gate(live/retro/resume + open 案清單)+ resume 續期(`updated_at` 錨)
- **D** 收束 ask-gate(讀上輪 `synthesis_trace.converged`)+ 第 5 輪 `suggest_pause`
- **E** ⑤ `archive` 逐字稿歸檔:工具標記防滲、content_hash 冪等、G0 僅掃 parent(遷移 0005)
- **F** `report` 兩段式(event/quarter/year):九維聚合 + 五道驗證 + 確定性組裝(遷移 0006)
- **G** safety 分齡安全約束集:3 風險向 × 4 年齡 delta,tags.md 7 塊 fail-fast
- **H** 語意紅線三層:tripwire 警告不拒收 → events 稽核 → 下季回放;guardian 前置
- **I** WorkOS AuthKit OAuth + sub allowlist(401+`auth_denied`);local 非 loopback 拒啟動;靜態 bearer 退役
- **J** 信封加密 AES-256-GCM(多鑰輪替;遷移 0007 就地加密)+ Dockerfile + 週備份(pg_dump→zstd→age→私有 repo)
- **K** 多照顧者:sub→caregiver 映射(不收輸入)、報告自照計數、比較句 tripwire(遷移 0008)

## v3.0(2026-06-11 defect-fixes v1.0–v1.1,#1–#11)

stopped record 排除 promotion / ④ G0 複檢 / ④ 須 ≥1 輪 ③ / 高張力 note 閘 /
converged 錨點 / 棄案 TTL=expired / events 稽核證據鏈 / 預設綁 127.0.0.1 /
record_id 臺北日 / F2·F5 人身錨定。63 條驗收。

## v3.0(2026-06-11 初版)

v2.2 fat → **thin server:零 LLM、零 API key**。6 回應核心靜態 TAG 由 host
耦合,2 探詢核心(Maslow/Satir)前移 ①;4-tool FSM code 強制;正向紀錄
硬閘短鏈;L0 落 PostgreSQL(遷移 0001–0003)。

## v2.2(superseded)

fat server:自打 Anthropic API,10 核心隔離並行 + 合成層(resonance)。
詳見 `parenting-response-mcp-spec-v2.2.md` 與標 superseded 各檔。
