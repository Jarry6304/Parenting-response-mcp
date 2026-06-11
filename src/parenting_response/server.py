"""FastMCP server:對外只暴露三個編排入口(spec v2.2 tool 介面契約)。

參數採寬鬆型別 + 體內以 pydantic 驗證 → 錯誤碼契約(E_MISSING_AXIS 等)由我方發出,
而非框架驗證訊息;守衛永遠先於 LLM。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .orchestrator import Orchestrator
from .schema import PRError


def build_server(orch: Orchestrator) -> FastMCP:
    mcp = FastMCP(name="parenting-response")

    @mcp.tool
    async def analyze_situation(
        mode: str | None = None,
        age_band: str | None = None,
        facts: str | None = None,
        emotion: str | None = None,
        emotion_intensity: str | None = None,
        safety_flag: bool = False,
        problem_category: str | None = None,
        confounders: list[str] | None = None,
        parent_goal: str | None = None,
        child_id: str = "C1",
        linked_plan_id: str | None = None,
    ) -> dict[str, Any]:
        """S2(內含 G0):分析情境,產出建議卡(round 0)。

        必填軸 = mode / age_band / facts / emotion / emotion_intensity,缺 → E_MISSING_AXIS。
        mode ∈ live|rehearsal;age_band ∈ 2-3|4-6|7-11|12+(0-2 範圍外);
        emotion_intensity ∈ 低|中|高;linked_plan_id = rehearsal record_id(promotion 鏈)。
        """
        params = {
            k: v
            for k, v in {
                "mode": mode, "age_band": age_band, "facts": facts, "emotion": emotion,
                "emotion_intensity": emotion_intensity, "safety_flag": safety_flag,
                "problem_category": problem_category, "confounders": confounders,
                "parent_goal": parent_goal, "child_id": child_id, "linked_plan_id": linked_plan_id,
            }.items()
            if v is not None
        }
        try:
            result = await orch.analyze(params)
        except PRError as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(mode="json")

    @mcp.tool
    async def next_round(
        session_id: str, child_reaction: str, reaction_note: str | None = None
    ) -> dict[str, Any]:
        """S3 乒乓:回報孩子反應,取得下一張卡。

        child_reaction ∈ 鬆動配合|否認堅持|情緒爆發|退縮害怕|反問試探|轉移打岔;
        reaction_note = 家長轉述自由文本(G0 複檢對象,建議提供)。
        """
        try:
            result = await orch.next_round(session_id, child_reaction, reaction_note)
        except PRError as exc:
            raise ToolError(str(exc)) from exc
        return result.model_dump(mode="json")

    @mcp.tool
    async def finalize_record(
        session_id: str,
        outcome: str,
        outcome_note: str | None = None,
        parent_self_note: str | None = None,
        followup: str | None = None,
    ) -> dict[str, Any]:
        """S4 收尾:聚合回填理論欄位(A3),落 L0 record,session 轉終態。

        outcome ∈ resolved|partial|unresolved|escalated_to_redflag。
        """
        try:
            return await orch.finalize(session_id, outcome, outcome_note, parent_self_note, followup)
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    _registered = (analyze_situation, next_round, finalize_record)  # 由 @mcp.tool 註冊
    del _registered
    return mcp


def main() -> None:
    """正式進入點:PG + anthropic;DATABASE_URL / ANTHROPIC_API_KEY 由環境提供。"""
    from .db import PgDatabase
    from .llm import AnthropicLLM

    dsn = os.environ["DATABASE_URL"]

    async def _run() -> None:
        db = PgDatabase(dsn)
        await db.open()
        await db.ensure_schema()
        orch = Orchestrator(db, AnthropicLLM())
        await build_server(orch).run_async()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
