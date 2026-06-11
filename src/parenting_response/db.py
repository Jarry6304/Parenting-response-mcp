"""PG 持久層 + 不變量(FSM 第二道防線)。

不變量(spec v3.0 資料模型,承 v2.2「雙保險」):
  rounds PK (session_id, round_no)        → 重複輪次寫入必失敗
  round_no 由 server 取 max(round_no)+1   → client 無法指定輪次
  records UNIQUE(session_id)              → 一 session 至多一 record
  status 以 UPDATE ... WHERE status='open' 條件式轉移 → 併發雙 finalize 恰一成功

v3.0 差異:sessions 多 stage(FSM 細分);① 先建 session、② 才補軸,
故 age_band / emotion_intensity 可為 NULL;rounds 無卡(card 可 NULL);
records 多 draft / claimed_sources(schema_version=2,見 record-schema.md)。

MemoryDatabase 以同語意實作,供驗收測試 hermetic 執行;
PG 真不變量由 DDL + PgDatabase 承載(TEST_DATABASE_URL 可跑同一套測試)。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol


class UniqueViolation(Exception):
    pass


SESSION_COLUMNS: tuple[str, ...] = (
    "session_id", "child_id", "mode", "status", "stage", "age_band", "facts", "emotion",
    "emotion_intensity", "safety_flag", "severity", "is_positive_log",
    "problem_category", "confounders", "parent_goal", "goal_aligned", "linked_plan_id",
)

RECORD_COLUMNS: tuple[str, ...] = (
    "record_id", "session_id", "schema_version", "status", "linked_plan_id",
    "dreikurs_purpose", "maslow_need", "erikson_stage", "piaget_stage", "dev_normative",
    "claimed_sources", "draft",
    "outcome", "outcome_note", "parent_self_note", "followup", "tools_used", "posture",
)

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    child_id          TEXT NOT NULL,
    mode              TEXT NOT NULL,
    status            TEXT NOT NULL,
    stage             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    age_band          TEXT,
    facts             TEXT NOT NULL,
    emotion           TEXT NOT NULL,
    emotion_intensity TEXT,
    safety_flag       BOOLEAN DEFAULT false,
    severity          TEXT,
    is_positive_log   BOOLEAN DEFAULT false,
    problem_category  TEXT,
    confounders       JSONB,
    parent_goal       TEXT,
    goal_aligned      BOOLEAN,
    linked_plan_id    TEXT
);

CREATE TABLE IF NOT EXISTS rounds (
    session_id      TEXT REFERENCES sessions(session_id),
    round_no        INT NOT NULL,
    child_reaction  TEXT,
    reaction_note   TEXT,
    card            JSONB,
    core_outputs    JSONB NOT NULL,
    synthesis_trace JSONB NOT NULL,
    degraded        BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, round_no)
);

CREATE TABLE IF NOT EXISTS records (
    record_id        TEXT PRIMARY KEY,
    session_id       TEXT UNIQUE REFERENCES sessions(session_id),
    schema_version   INT NOT NULL DEFAULT 2,
    status           TEXT NOT NULL,
    linked_plan_id   TEXT,
    dreikurs_purpose TEXT,
    maslow_need      JSONB,
    erikson_stage    TEXT,
    piaget_stage     TEXT,
    dev_normative    BOOLEAN,
    claimed_sources  JSONB,
    draft            TEXT,
    outcome          TEXT NOT NULL,
    outcome_note     TEXT,
    parent_self_note TEXT,
    followup         TEXT,
    tools_used       JSONB,
    posture          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# v2.2 → v3.0 既有資料庫升級(冪等;migration 0002 與 ensure_schema 共用,單一來源)。
# 0001 動態 import 本檔 DDL,全新庫在 0001 即得 v3 形狀,本塊必須可 no-op。
DDL_MIGRATE = """
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE sessions ALTER COLUMN age_band DROP NOT NULL;
ALTER TABLE sessions ALTER COLUMN emotion_intensity DROP NOT NULL;
ALTER TABLE rounds ALTER COLUMN card DROP NOT NULL;
ALTER TABLE records ADD COLUMN IF NOT EXISTS claimed_sources JSONB;
ALTER TABLE records ADD COLUMN IF NOT EXISTS draft TEXT;
ALTER TABLE records ALTER COLUMN schema_version SET DEFAULT 2;
UPDATE sessions SET stage = CASE status WHEN 'open' THEN 'ready' ELSE status END
WHERE stage IS NULL;
"""


class Database(Protocol):
    async def create_session(self, row: dict[str, Any]) -> None: ...
    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    async def update_session(self, session_id: str, fields: dict[str, Any]) -> None: ...
    async def insert_round(
        self, session_id: str, *, child_reaction: str | None, reaction_note: str | None,
        card: dict[str, Any] | None, core_outputs: dict[str, Any], synthesis_trace: dict[str, Any],
        degraded: bool,
    ) -> int: ...
    async def get_rounds(self, session_id: str) -> list[dict[str, Any]]: ...
    async def get_record(self, record_id: str) -> dict[str, Any] | None: ...
    async def get_record_by_session(self, session_id: str) -> dict[str, Any] | None: ...
    async def count_records_with_prefix(self, prefix: str) -> int: ...
    async def finalize_tx(
        self, session_id: str, *, terminal_status: str,
        session_updates: dict[str, Any], record_row: dict[str, Any],
    ) -> bool: ...


class MemoryDatabase:
    """同不變量語意的記憶體實作(測試用)。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._rounds: dict[str, list[dict[str, Any]]] = {}
        self._records: dict[str, dict[str, Any]] = {}
        self._records_by_session: dict[str, str] = {}

    async def create_session(self, row: dict[str, Any]) -> None:
        async with self._lock:
            sid = row["session_id"]
            if sid in self._sessions:
                raise UniqueViolation(f"session {sid} 已存在")
            self._sessions[sid] = dict(row)
            self._rounds[sid] = []

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._sessions.get(session_id)
        return dict(row) if row else None

    async def update_session(self, session_id: str, fields: dict[str, Any]) -> None:
        async with self._lock:
            safe = {k: v for k, v in fields.items() if k in SESSION_COLUMNS and k != "session_id"}
            self._sessions[session_id].update(safe)  # 與 PgDatabase 同白名單語意

    async def insert_round(
        self, session_id: str, *, child_reaction: str | None, reaction_note: str | None,
        card: dict[str, Any] | None, core_outputs: dict[str, Any], synthesis_trace: dict[str, Any],
        degraded: bool,
    ) -> int:
        async with self._lock:
            rounds = self._rounds[session_id]
            round_no = (rounds[-1]["round_no"] + 1) if rounds else 0  # server 取 max+1
            rounds.append({
                "session_id": session_id, "round_no": round_no,
                "child_reaction": child_reaction, "reaction_note": reaction_note,
                "card": card, "core_outputs": core_outputs,
                "synthesis_trace": synthesis_trace, "degraded": degraded,
            })
            return round_no

    async def get_rounds(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rounds.get(session_id, [])]

    async def get_record(self, record_id: str) -> dict[str, Any] | None:
        row = self._records.get(record_id)
        return dict(row) if row else None

    async def get_record_by_session(self, session_id: str) -> dict[str, Any] | None:
        rid = self._records_by_session.get(session_id)
        return dict(self._records[rid]) if rid else None

    async def count_records_with_prefix(self, prefix: str) -> int:
        return sum(1 for rid in self._records if rid.startswith(prefix))

    async def finalize_tx(
        self, session_id: str, *, terminal_status: str,
        session_updates: dict[str, Any], record_row: dict[str, Any],
    ) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session["status"] != "open":
                return False  # 條件式轉移:非 open 即敗,恰一成功
            rid = record_row["record_id"]
            if rid in self._records:
                raise UniqueViolation(f"record_id {rid} 已存在")
            if session_id in self._records_by_session:
                raise UniqueViolation(f"session {session_id} 已有 record")
            session["status"] = terminal_status
            session.update(session_updates)
            self._records[rid] = dict(record_row)
            self._records_by_session[session_id] = rid
            return True


class PgDatabase:
    """psycopg3(async)實作;不變量由 PG schema 承載。"""

    def __init__(self, dsn: str) -> None:
        from psycopg_pool import AsyncConnectionPool

        self._pool = AsyncConnectionPool(dsn, open=False, kwargs={"autocommit": True})

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def ensure_schema(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(DDL)
            await conn.execute(DDL_MIGRATE)  # 既有 v2.2 庫直接開機也補齊 v3 欄位

    @staticmethod
    def _jsonb(value: Any) -> Any:
        from psycopg.types.json import Jsonb

        return Jsonb(value) if value is not None else None

    async def create_session(self, row: dict[str, Any]) -> None:
        from psycopg import sql

        stmt = sql.SQL("INSERT INTO sessions ({cols}) VALUES ({ph})").format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in SESSION_COLUMNS),
            ph=sql.SQL(", ").join(sql.Placeholder() for _ in SESSION_COLUMNS),
        )
        values: list[Any] = [row.get(c) for c in SESSION_COLUMNS]
        values[SESSION_COLUMNS.index("confounders")] = self._jsonb(row.get("confounders"))
        async with self._pool.connection() as conn:
            await conn.execute(stmt, values)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM sessions WHERE session_id = %s", (session_id,))
            return await self._fetchone_dict(cur)

    async def update_session(self, session_id: str, fields: dict[str, Any]) -> None:
        from psycopg import sql

        safe = {k: v for k, v in fields.items() if k in SESSION_COLUMNS and k != "session_id"}
        if not safe:
            return
        stmt = sql.SQL("UPDATE sessions SET {sets} WHERE session_id = {ph}").format(
            sets=sql.SQL(", ").join(
                sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in safe
            ),
            ph=sql.Placeholder(),
        )
        async with self._pool.connection() as conn:
            await conn.execute(stmt, (*safe.values(), session_id))

    async def insert_round(
        self, session_id: str, *, child_reaction: str | None, reaction_note: str | None,
        card: dict[str, Any] | None, core_outputs: dict[str, Any], synthesis_trace: dict[str, Any],
        degraded: bool,
    ) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO rounds (session_id, round_no, child_reaction, reaction_note,
                                    card, core_outputs, synthesis_trace, degraded)
                SELECT %s, COALESCE(MAX(round_no) + 1, 0), %s, %s, %s, %s, %s, %s
                FROM rounds WHERE session_id = %s
                RETURNING round_no
                """,
                (session_id, child_reaction, reaction_note, self._jsonb(card),
                 self._jsonb(core_outputs), self._jsonb(synthesis_trace), degraded, session_id),
            )
            row = await cur.fetchone()
            assert row is not None
            return int(row[0])

    async def get_rounds(self, session_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM rounds WHERE session_id = %s ORDER BY round_no", (session_id,)
            )
            return await self._fetchall_dicts(cur)

    async def get_record(self, record_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM records WHERE record_id = %s", (record_id,))
            return await self._fetchone_dict(cur)

    async def get_record_by_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM records WHERE session_id = %s", (session_id,))
            return await self._fetchone_dict(cur)

    async def count_records_with_prefix(self, prefix: str) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM records WHERE record_id LIKE %s", (prefix + "%",)
            )
            row = await cur.fetchone()
            assert row is not None
            return int(row[0])

    async def finalize_tx(
        self, session_id: str, *, terminal_status: str,
        session_updates: dict[str, Any], record_row: dict[str, Any],
    ) -> bool:
        import psycopg
        from psycopg import sql

        safe = {k: v for k, v in session_updates.items() if k in SESSION_COLUMNS and k != "session_id"}
        set_parts = [sql.SQL("status = {}").format(sql.Placeholder())]
        set_parts.extend(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in safe
        )
        update_stmt = sql.SQL(
            "UPDATE sessions SET {sets} WHERE session_id = {ph} AND status = 'open'"
        ).format(sets=sql.SQL(", ").join(set_parts), ph=sql.Placeholder())
        insert_stmt = sql.SQL("INSERT INTO records ({cols}) VALUES ({ph})").format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in RECORD_COLUMNS),
            ph=sql.SQL(", ").join(sql.Placeholder() for _ in RECORD_COLUMNS),
        )
        values: list[Any] = [record_row.get(c) for c in RECORD_COLUMNS]
        for jcol in ("maslow_need", "tools_used", "claimed_sources"):
            values[RECORD_COLUMNS.index(jcol)] = self._jsonb(record_row.get(jcol))

        async with self._pool.connection() as conn:
            await conn.set_autocommit(False)
            try:
                async with conn.transaction():
                    cur = await conn.execute(update_stmt, (terminal_status, *safe.values(), session_id))
                    if cur.rowcount == 0:
                        return False
                    try:
                        await conn.execute(insert_stmt, values)
                    except psycopg.errors.UniqueViolation as exc:
                        raise UniqueViolation(str(exc)) from exc
                return True
            finally:
                await conn.set_autocommit(True)

    @staticmethod
    async def _fetchone_dict(cur: Any) -> dict[str, Any] | None:
        row = await cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))

    @staticmethod
    async def _fetchall_dicts(cur: Any) -> list[dict[str, Any]]:
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
