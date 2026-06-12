# 部署手冊 v3.0 — WorkOS AuthKit + Cloud Run + Neon(零成本基線)

> 對象:本人(+太太一個帳號)。所有雲端操作不在 code 內,照本檔手動執行;
> code 端只認 env。**金鑰原則:ENVELOPE 私鑰與 age 私鑰永不進雲端控制台以外的地方,
> age 私鑰只存離線(印出來/隨身碟)。**

## 0. 總覽(誰負責什麼)

| 元件 | 角色 | 免費額度內用量 |
|---|---|---|
| WorkOS AuthKit | OAuth 登入(DCR + JWKS) | 1M MAU 免費,實際 2 人 |
| GCP Cloud Run | server 容器(scale-to-zero) | 家庭流量遠低於免費層 |
| GCP Secret Manager | DATABASE_URL / ENVELOPE_KEYS 等 | 6 個 secret 版本內免費 |
| Neon | PostgreSQL(serverless) | 0.5GB 免費層 |
| GitHub Actions + 私有 repo | 週備份(pg_dump→zstd→age) | 私有 repo 2000 分鐘/月內 |

預估月費:**$0**(設 GCP 預算告警 $1 守底線,見 §3.4)。

## 1. WorkOS AuthKit(一次性)

1. 註冊 workos.com → 建 Project → 左欄 **AuthKit** 啟用,記下
   `AUTHKIT_DOMAIN`(形如 `https://xxx.authkit.app`)。
2. **Applications → Configuration**:啟用 **Dynamic Client Registration**
   (Claude custom connector 需要 DCR 自註冊)。
3. **Resource Indicator**:填 server 公開 URL **原樣**(部署後的
   `https://<cloud-run-url>`,= env `BASE_URL`;先部署拿到 URL 再回填此欄)。
4. **關閉自助註冊**:Authentication → 關 Sign-up,改 Invite-only;
   邀請兩個 email(本人 + 太太)。
5. 兩人各登入一次 → **Users** 頁複製各自 `user_…` id =
   `ALLOWED_SUBJECTS` 與 `CAREGIVER_MAP` 的 sub。

## 2. Neon(一次性)

1. neon.tech 建 Project(區域選 **AWS us-west-2**,靠近 Cloud Run us-west1)。
2. 取 pooled connection string → `DATABASE_URL`
   (`postgresql://…-pooler.…/neondb?sslmode=require`)。
3. 建唯讀角色給備份(SQL Editor):
   ```sql
   CREATE ROLE backup_ro LOGIN PASSWORD '<強密碼>';
   GRANT CONNECT ON DATABASE neondb TO backup_ro;
   GRANT USAGE ON SCHEMA public TO backup_ro;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO backup_ro;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO backup_ro;
   ```
   其連線字串 = GitHub secret `NEON_DATABASE_URL`。

## 3. GCP Cloud Run(一次性)

### 3.1 金鑰生成(本機)

```bash
python3 - <<'EOF'
import base64, json, secrets
print(json.dumps({"k1": base64.b64encode(secrets.token_bytes(32)).decode()}))
EOF
# 輸出即 ENVELOPE_KEYS;ENVELOPE_ACTIVE_KEY_ID=k1
```

### 3.2 Secret Manager

```bash
gcloud services enable run.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com
printf '%s' "$DATABASE_URL"   | gcloud secrets create database-url   --data-file=-
printf '%s' "$ENVELOPE_KEYS"  | gcloud secrets create envelope-keys  --data-file=-
```

### 3.3 部署

```bash
gcloud artifacts repositories create prmcp --repository-format=docker --location=us-west1
gcloud builds submit --tag us-west1-docker.pkg.dev/$PROJECT/prmcp/server:v3.0
gcloud run deploy parenting-response \
  --image us-west1-docker.pkg.dev/$PROJECT/prmcp/server:v3.0 \
  --region us-west1 --min-instances 0 --max-instances 1 \
  --memory 512Mi --allow-unauthenticated \
  --set-secrets "DATABASE_URL=database-url:latest,ENVELOPE_KEYS=envelope-keys:latest" \
  --set-env-vars "AUTH_MODE=authkit,HOST=0.0.0.0,ENVELOPE_ACTIVE_KEY_ID=k1,\
AUTHKIT_DOMAIN=https://xxx.authkit.app,\
BASE_URL=https://<部署後回填>,\
ALLOWED_SUBJECTS=user_AAA,user_BBB,\
CAREGIVER_MAP={\"user_AAA\":\"爸\"\,\"user_BBB\":\"媽\"}"
```

- 首次部署拿到 URL 後:回填 `BASE_URL` env(`gcloud run services update … --update-env-vars`)
  與 WorkOS Resource Indicator(§1.3),再 redeploy 一次。
- `--allow-unauthenticated` 是 Cloud Run 層(HTTP 可達);應用層由 AuthKit JWT + allowlist 把關。
- 首次啟動 `ensure_schema` 自動建/補表;正式做法是先在本機對 Neon 跑
  `DATABASE_URL=… ENVELOPE_KEYS=… ENVELOPE_ACTIVE_KEY_ID=k1 uv run alembic upgrade head`。

### 3.4 預算告警

Billing → Budgets:金額 $1,門檻 50%/100% email——任何非預期計費第一時間知道。

## 4. Claude custom connector(本人 + 太太各一次)

1. claude.ai → Settings → Connectors → **Add custom connector**。
2. URL = `https://<cloud-run-url>/mcp`。
3. 跳 AuthKit 登入(DCR 自動註冊;太太用她的邀請帳號)→ 完成。
4. 驗收:對 Claude 說「孩子剛剛亂丟玩具,我很生氣」→ 應走 ①(或入口
   ask-gate);換太太帳號建一案 → Neon 查 `sessions.caregiver='媽'`。

### 401/拒絕行為註記

sub 不在 `ALLOWED_SUBJECTS` 時回 **401**(非 403):fastmcp 的 allowlist 卡點在
token 驗證層(ASGI middleware 在 auth 前拿不到 sub)。稽核面等價——每次拒絕
都落 `events.kind=auth_denied`(含 sub)。

## 5. 備份(GitHub,一次性設定)

1. 建**私有** repo:`<you>/parenting-backup`(空 repo + README 即可)。
2. 本機 `age-keygen -o age.key`:公鑰(`age1…`)進 secret;**私鑰離線保存,
   不進任何雲端**(沒有私鑰 = 備份永遠打不開)。
3. 本 repo Settings → Secrets and variables → Actions 加四個 secret:
   `NEON_DATABASE_URL`(§2.3 唯讀)、`AGE_PUBLIC_KEY`、
   `BACKUP_REPO`(`<you>/parenting-backup`)、
   `BACKUP_REPO_TOKEN`(fine-grained PAT:僅該 repo、僅 Contents read/write)。
4. Actions 頁手動跑一次 `weekly-backup` 驗證綠燈、備份 repo 出現
   `2026/backup-YYYYMMDD.sql.zst.age`。

## 6. 還原演練(每季一次;本輪已在開發環境驗證過全流程)

```bash
git clone git@github.com:<you>/parenting-backup.git && cd parenting-backup
age -d -i /path/to/age.key 2026/backup-YYYYMMDD.sql.zst.age | zstd -d > restore.sql
# 起拋棄式 PG(docker 或本機),灌入:
psql "$SCRATCH_DATABASE_URL" < restore.sql
# 驗:表列數 > 0、密文欄以 enc: 開頭、應用層帶 ENVELOPE_KEYS 可讀明文
ENVELOPE_KEYS=… ENVELOPE_ACTIVE_KEY_ID=k1 DATABASE_URL=$SCRATCH_DATABASE_URL \
  uv run python -c "import asyncio
from parenting_response.crypto import Envelope
from parenting_response.db import PgDatabase
import os
async def m():
    db = PgDatabase(os.environ['DATABASE_URL'], envelope=Envelope.from_env())
    await db.open(); print(len(await db.list_open_sessions('C1')), 'opens 可解密')
asyncio.run(m())"
# 完成後銷毀拋棄庫與 restore.sql
```

> 開發環境已演練(2026-06-12):alembic 0001→0008 全鏈、全流程寫入密文落庫、
> pg_dump→壓縮→age→還原 6 表列數與密文逐位元一致、還原庫金鑰可解。
> 雲上首次部署後請用真 Neon 備份再走一次本節。

## 7. 金鑰輪替(年度或外洩時)

1. 生成 k2 加入 `ENVELOPE_KEYS`(保留 k1!),`ENVELOPE_ACTIVE_KEY_ID=k2` → redeploy:
   新寫走 k2,舊列 k1 仍可解(多鑰共存)。
2. 如需全量換鑰:`alembic downgrade 0006`(舊鑰解密)→ 換 KEYS 只留 k2 →
   `alembic upgrade head`(新鑰加密)。或保持混存,等自然汰換。
3. **絕不先撤舊鑰**:庫裡仍有 `enc:k1:` 列時移除 k1 → 讀取直接 raise。

## 8. 月檢清單(5 分鐘)

- [ ] GCP Billing = $0(或在告警內)
- [ ] backup repo 本月有 4–5 個新檔
- [ ] Neon 用量 < 0.4GB(接近 0.5 考慮清 events 老列或升級)
- [ ] `events` 抽查:有無非預期 `auth_denied`(陌生 sub 嘗試)
