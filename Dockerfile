# parenting-response-mcp(v3.2)— Cloud Run 部署映像
# references/ 必須隨映像(tags.md / report-core.md 是 runtime 輸入,不打 wheel)。
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# 先鎖依賴層(快取友善),再 COPY 原始碼
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src/ src/
COPY references/ references/
COPY migrations/ migrations/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# Cloud Run 注入 $PORT;對外綁定 0.0.0.0 須 AUTH_MODE=authkit(server 端 fail-fast 防呆)
ENV HOST=0.0.0.0
ENV AUTH_MODE=authkit
CMD ["uv", "run", "--no-sync", "parenting-response-mcp"]
