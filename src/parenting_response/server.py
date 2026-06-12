"""FastMCP server (v3.0):對 host 暴露 6 個編排入口(①-⑤ + report)。

thin server:**零 LLM 呼叫、零 ANTHROPIC_API_KEY**。
所有「不得違反」由 orchestrator 以 code 斷言(FSM 守衛、G0 訊號、後檢);
host(Claude)負責 S1 探詢、TAG 耦合生成、slot 敘事、對 user 講話。

對外傳輸:streamable-HTTP(custom connector 用)。
驗證:AUTH_MODE=local(預設,只准 loopback)| authkit(OAuth,見 auth.py)。
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider

from .auth import build_auth, validate_binding
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
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """① 約束探詢(內含 G0 訊號)+ 入口分流。

        mode 缺 → 回入口 ask-gate{options: live|retro|resume, open_sessions}(不建案);
        mode=resume + session_id → 接手 open 舊案,回三軸與輪摘要(不建新案);
        mode ∈ live|rehearsal|retro → 必要 `facts / emotion`(retro=事後覆盤),
        過 → 回 {session_id, 禁用詞+紅線約束集, Maslow/Satir 探點}(引導 S1);
        G0 短路命中(v3.0 訊號,不停案)→ 照常建案,另回 {redflag, referral,
        safety_mode=true}——轉介請立即向家長送達,後續 ③ 將換安全約束集。
        """
        try:
            return await orch.constraints(
                facts=facts, emotion=emotion, mode=mode,
                child_id=child_id, linked_plan_id=linked_plan_id,
                session_id=session_id,
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
        parent_action: str | None = None,
    ) -> dict[str, Any]:
        """② 必備條件(+ 正向紀錄硬閘)。

        驗 `age_band ∈ 2-3|4-6|7-11|12+`、`emotion_intensity ∈ 低|中|高`。
        retro 模式必填 `parent_action`(當時你實際怎麼處理;進 G0 複檢)。
        正向紀錄且缺 `script_decision ∈ skip|generate` → 回 ask-gate(不解鎖);
        skip → 走 short ④;generate / 一般 → 解鎖 ③。
        """
        try:
            return await orch.prerequisites(
                session_id=session_id, age_band=age_band,
                emotion_intensity=emotion_intensity,
                problem_category=problem_category, script_decision=script_decision,
                parent_action=parent_action,
            )
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def core_tags(
        session_id: str,
        child_reaction: str | None = None,
        reaction_note: str | None = None,
        parent_decision: str | None = None,
    ) -> dict[str, Any]:
        """③ 各核心條件(乒乓,可 ×n)。

        回 6 回應核心 TAG(標 primary/support,依 child_reaction 確定性映射)
        + Erikson/Piaget 查表 stage + converged(code 規則,非 host 自報)。
        round 0 = NULL 反應;round>0 對 reaction_note 複檢 G0——命中為訊號
        (v3.0:不停案,照常記輪),該輪起回傳換 safety_tags 安全約束集
        (陪伴/傾聽/降溫+轉介),不出一般管教 TAG。
        上輪已收斂(live)→ 回收束 ask-gate:家長要繼續須帶
        parent_decision="continue",要收尾改呼 finalize。第 5 輪起附 suggest_pause。
        child_reaction ∈ 鬆動配合|否認堅持|情緒爆發|退縮害怕|反問試探|轉移打岔。
        """
        try:
            return await orch.core_tags(
                session_id=session_id, child_reaction=child_reaction,
                reaction_note=reaction_note, parent_decision=parent_decision,
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
        referral_ack: bool | None = None,
    ) -> dict[str, Any]:
        """④ 總結分析(終態)。

        一般模式(stage=ready):須交 draft → 禁用詞 pattern_check,過則落 record;
        含禁用詞 → 拒落庫,回違規詞要求重生。
        short 模式(stage=short_pending):不接受 draft,只記事、不跑 pattern_check。
        紅旗訊號在案(v3.0):須帶 referral_ack=true(轉介已向家長送達),
        否則 E_MISSING_AXIS;落庫之 record.redflag=true,不進 promotion 鏈。
        outcome ∈ resolved|partial|unresolved|escalated_to_redflag;
        claimed_sources ⊆ 6 回應核心(軟溯源);maslow_need ⊆ 生理|安全|愛與歸屬|尊重
        (① 探點命中之 host 回報)。
        """
        try:
            return await orch.finalize(
                session_id=session_id, outcome=outcome, draft=draft,
                claimed_sources=claimed_sources, maslow_need=maslow_need,
                outcome_note=outcome_note, parent_self_note=parent_self_note,
                followup=followup, referral_ack=referral_ack,
            )
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def archive(
        session_id: str,
        chunk_no: int,
        turns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """⑤ 原始逐字稿歸檔(v3.0;④ 之後的收尾鏈,終態案可補錄)。

        turns = [{role: parent|assistant, content: 對話原文}, …](依序)。
        含工具協議標記 → 整 chunk 拒收回明細;同內容重送冪等(duplicate);
        parent 發言過 G0 複檢——命中補升訊號(record 不回改)。
        成功 → next: report(event)。
        """
        try:
            return await orch.archive(session_id=session_id, chunk_no=chunk_no, turns=turns)
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def report(
        scope: str,
        ref: str,
        slots: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """報告(v3.0;兩段式)。scope ∈ event|quarter|year;
        ref = session_id|YYYYQn|YYYY。

        phase1(slots 缺):回 {aggregates(九維聚合), skeleton(章節骨架:
        fixed 已組裝 / slot 待填+字數上限+hint), guardian(生成前自查)}。
        phase2(slots 給):五道驗證(槽齊備/字數/負面清單/數字白名單/
        原文防滲)→ 確定性組裝 → 落庫 version+1 回 body;
        語意警示(主詞+負面定性)warning 不拒收,稽核並於下季回放。
        """
        try:
            return await orch.report(scope=scope, ref=ref, slots=slots)
        except PRError as exc:
            raise ToolError(str(exc)) from exc

    _registered = (constraints, prerequisites, core_tags, finalize, archive, report)
    del _registered
    return mcp


def main() -> None:
    """進入點:thin server,**無 LLM client**。只需 DATABASE_URL(+authkit 三要素)。

    傳輸 = streamable-HTTP(custom connector 用)。
    AUTH_MODE=local(預設):無閘,**非 loopback 一律拒啟動**(fail-fast);
    AUTH_MODE=authkit:WorkOS AuthKit OAuth + ALLOWED_SUBJECTS allowlist
    (v3.0 I 件;v3.0 的靜態 bearer 閘已退役)。
    """
    import asyncio

    from .crypto import Envelope
    from .db import PgDatabase

    dsn = os.environ["DATABASE_URL"]
    envelope = Envelope.from_env()  # 未設 ENVELOPE_KEYS → 明文直通(local dev)
    # secure-by-default:預設只綁 loopback;對外(Cloud Run)= authkit 模式 + HOST=0.0.0.0
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    mode = os.environ.get("AUTH_MODE", "local")
    ttl_days = int(os.environ.get("SESSION_TTL_DAYS", "30"))  # ≤0 = 停用棄案清掃
    validate_binding(mode, host)  # local + 非 loopback → 拒啟動(個資面)

    import json

    caregiver_map: dict[str, str] = json.loads(os.environ.get("CAREGIVER_MAP", "{}"))

    async def _run() -> None:
        db = PgDatabase(dsn, envelope=envelope)
        await db.open()
        await db.ensure_schema()
        auth = build_auth(
            mode=mode,
            authkit_domain=os.environ.get("AUTHKIT_DOMAIN"),
            base_url=os.environ.get("BASE_URL"),
            allowed_subjects=[s.strip() for s in
                              os.environ.get("ALLOWED_SUBJECTS", "").split(",") if s.strip()],
            db=db,
        )
        orch = Orchestrator(db, session_ttl_days=ttl_days,
                            caregiver_map=caregiver_map)  # 注意:不傳 llm —— v3 零推論
        server = build_server(orch, auth=auth)
        await server.run_async(transport="streamable-http", host=host, port=port)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
