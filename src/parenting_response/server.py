"""FastMCP server (v3.0):對 host 只暴露 4 個編排入口。

v3.0 = thin server:**零 LLM 呼叫、零 ANTHROPIC_API_KEY**。
所有「不得違反」由 orchestrator 以 code 斷言(FSM 守衛、G0、後檢);
host(Claude)負責 S1 探詢、6 回應核心 TAG 的耦合生成、對 user 講話。

對外傳輸:streamable-HTTP(custom connector 用)。bearer 閘見 main()。
"""

from __future__ import annotations

import os
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider, StaticTokenVerifier

from .orchestrator import Orchestrator
from .schema import PRError


def build_server(orch: Orchestrator, *, auth: AuthProvider | None = None) -> FastMCP:
    mcp = FastMCP(name="parenting-response", auth=auth)

    @mcp.tool
    async def constraints(
        facts: str | None = None,
        emotion: str | None = None,
        mode: str | None = None,
        child_id: str = "C1",
        linked_plan_id: str | None = None,
    ) -> dict[str, Any]:
        """① 約束探詢(內含 G0)。

        必要:`facts / emotion / mode`(mode ∈ live|rehearsal)。
        過 → 回 {session_id, 禁用詞+紅線約束集, Maslow/Satir 探點}(引導 S1);
        G0 短路命中 → session=redflag_stopped,回轉介,鎖 ②③④。
        """
        try:
            return await orch.constraints(
                facts=facts, emotion=emotion, mode=mode,
                child_id=child_id, linked_plan_id=linked_plan_id,
            )
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def prerequisites(
        session_id: str,
        age_band: str | None = None,
        emotion_intensity: str | None = None,
        problem_category: str | None = None,
        script_decision: str | None = None,
    ) -> dict[str, Any]:
        """② 必備條件(+ 正向紀錄硬閘)。

        驗 `age_band ∈ 2-3|4-6|7-11|12+`、`emotion_intensity ∈ 低|中|高`。
        正向紀錄且缺 `script_decision ∈ skip|generate` → 回 ask-gate(不解鎖);
        skip → 走 short ④;generate / 一般 → 解鎖 ③。
        """
        try:
            return await orch.prerequisites(
                session_id=session_id, age_band=age_band,
                emotion_intensity=emotion_intensity,
                problem_category=problem_category, script_decision=script_decision,
            )
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def core_tags(
        session_id: str,
        child_reaction: str | None = None,
        reaction_note: str | None = None,
    ) -> dict[str, Any]:
        """③ 各核心條件(乒乓,可 ×n)。

        回 6 回應核心 TAG(標 primary/support,依 child_reaction 確定性映射)
        + Erikson/Piaget 查表 stage + converged(code 規則,非 host 自報)。
        round 0 = NULL 反應;round>0 對 reaction_note 複檢 G0,命中 → redflag_stopped。
        child_reaction ∈ 鬆動配合|否認堅持|情緒爆發|退縮害怕|反問試探|轉移打岔。
        """
        try:
            return await orch.core_tags(
                session_id=session_id, child_reaction=child_reaction,
                reaction_note=reaction_note,
            )
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def finalize(
        session_id: str,
        outcome: str,
        draft: str | None = None,
        claimed_sources: list[str] | None = None,
        maslow_need: list[str] | None = None,
        outcome_note: str | None = None,
        parent_self_note: str | None = None,
        followup: str | None = None,
    ) -> dict[str, Any]:
        """④ 總結分析(終態)。

        一般模式(stage=ready):須交 draft → 禁用詞 pattern_check,過則落 record;
        含禁用詞 → 拒落庫,回違規詞要求重生。
        short 模式(stage=short_pending):不接受 draft,只記事、不跑 pattern_check。
        outcome ∈ resolved|partial|unresolved|escalated_to_redflag;
        claimed_sources ⊆ 6 回應核心(軟溯源);maslow_need ⊆ 生理|安全|愛與歸屬|尊重
        (① 探點命中之 host 回報)。
        """
        try:
            return await orch.finalize(
                session_id=session_id, outcome=outcome, draft=draft,
                claimed_sources=claimed_sources, maslow_need=maslow_need,
                outcome_note=outcome_note, parent_self_note=parent_self_note,
                followup=followup,
            )
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    _registered = (constraints, prerequisites, core_tags, finalize)  # @mcp.tool 註冊
    del _registered
    return mcp


def main() -> None:
    """進入點:thin server,**無 LLM client**。只需 DATABASE_URL。

    傳輸 = streamable-HTTP(custom connector 用)。
    MCP_BEARER_TOKEN 設了則啟用 bearer 閘(靜態 token 驗證)。
    """
    import asyncio

    from .db import PgDatabase

    dsn = os.environ["DATABASE_URL"]
    # secure-by-default:預設只綁 loopback;對外暴露須顯式 HOST=…(records 含兒少個資)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    token = os.environ.get("MCP_BEARER_TOKEN")
    ttl_days = int(os.environ.get("SESSION_TTL_DAYS", "30"))  # ≤0 = 停用棄案清掃
    auth = StaticTokenVerifier(tokens={token: {"client_id": "mcp-host"}}) if token else None
    if auth is None and host not in ("127.0.0.1", "localhost", "::1"):
        print("警告:HOST 綁非 loopback 且未設 MCP_BEARER_TOKEN——同網段任何人可讀寫"
              "兒少個資紀錄;對外暴露前請設 token 或以反向代理加閘。", file=sys.stderr)

    async def _run() -> None:
        db = PgDatabase(dsn)
        await db.open()
        await db.ensure_schema()
        orch = Orchestrator(db, session_ttl_days=ttl_days)  # 注意:不傳 llm —— v3 零推論
        server = build_server(orch, auth=auth)
        await server.run_async(transport="streamable-http", host=host, port=port)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
