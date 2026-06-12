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
import datetime as _dt
import json
from typing import Any, Protocol


class UniqueViolation(Exception):
    pass


SESSION_COLUMNS: tuple[str, ...] = (
    "session_id", "child_id", "mode", "status", "stage", "age_band", "facts", "emotion",
    "emotion_intensity", "safety_flag", "severity", "is_positive_log",
    "problem_category", "confounders", "parent_goal", "goal_aligned", "linked_plan_id",
    # v3.2:A 件 G0 訊號(旗標+風險向)/ B 件 retro 暫存 / C 件 TTL 續期錨
    "redflag_active", "redflag_vector", "parent_action", "updated_at",
)

RECORD_COLUMNS: tuple[str, ...] = (
    "record_id", "session_id", "schema_version", "status", "linked_plan_id",
    "dreikurs_purpose", "maslow_need", "erikson_stage", "piaget_stage", "dev_normative",
    "claimed_sources", "draft",
    "outcome", "outcome_note", "parent_self_note", "followup", "tools_used", "posture",
    # v3.2(schema_version=3):A 件 promotion 排除錨 / B 件 retro 當時實際處理
    "redflag", "parent_action",
)

# 稽核事件(append-only;defect-fixes #7/#8):G0 命中(兩級)與 ④ pattern 拒收
# 一律落庫——severity 與拒收皆可重建緣由;0003 遷移與 ensure_schema 共用,單一來源。
DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    event_id   BIGSERIAL PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id),
    kind       TEXT NOT NULL,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_session_idx ON events (session_id);
"""

# 原始逐字稿(v3.2 E 件;append-only side-table,不動 records schema_version):
# turns 存 JSON 文字(TEXT 而非 JSONB——0007 就地加密就緒);
# UNIQUE(session_id, content_hash) 承載冪等(同 chunk 重送不重複落)。
# 0005 遷移與 ensure_schema 共用,單一來源。
DDL_TRANSCRIPTS = """
CREATE TABLE IF NOT EXISTS raw_transcripts (
    transcript_id BIGSERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    chunk_no      INT NOT NULL,
    content_hash  TEXT NOT NULL,
    turns         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, content_hash)
);
CREATE INDEX IF NOT EXISTS raw_transcripts_session_idx ON raw_transcripts (session_id);
"""

# 報告定稿(v3.2 F 件;同 ref 多版,version 遞增,最新版為「定稿」):
# body 為確定性組裝全文(TEXT,0007 加密就緒);meta 存聚合快照/slots/語意警示
# (季報回放讀上一季 meta.semantic_warnings)。0006 遷移與 ensure_schema 共用。
DDL_REPORTS = """
CREATE TABLE IF NOT EXISTS reports (
    report_id  BIGSERIAL PRIMARY KEY,
    scope      TEXT NOT NULL,
    ref_key    TEXT NOT NULL,
    version    INT NOT NULL,
    body       TEXT NOT NULL,
    meta       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope, ref_key, version)
);
"""

# v3.2 0006:報告級/auth 事件無 session 錨(payload 帶 ref_key/sub)→
# events.session_id 放寬可空;reports 表見 DDL_REPORTS。
DDL_MIGRATE_0006 = """
ALTER TABLE events ALTER COLUMN session_id DROP NOT NULL;
"""

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    child_id          TEXT NOT NULL,
    mode              TEXT NOT NULL,
    status            TEXT NOT NULL,
    stage             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
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
    linked_plan_id    TEXT,
    redflag_active    BOOLEAN NOT NULL DEFAULT false,
    redflag_vector    TEXT,
    parent_action     TEXT
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
    schema_version   INT NOT NULL DEFAULT 3,
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
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    redflag          BOOLEAN NOT NULL DEFAULT false,
    parent_action    TEXT
);
""" + DDL_EVENTS + DDL_TRANSCRIPTS + DDL_REPORTS

# v2.2 → v3.0 既有資料庫升級(冪等;migration 0002 與 ensure_schema 共用,單一來源)。
# 0001 動態 import 本檔 DDL,全新庫在 0001 即得 v3 形狀,本塊必須可 no-op。
DDL_MIGRATE = """
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE sessions ALTER COLUMN age_band DROP NOT NULL;
ALTER TABLE sessions ALTER COLUMN emotion_intensity DROP NOT NULL;
ALTER TABLE rounds ALTER COLUMN card DROP NOT NULL;
ALTER TABLE records ADD COLUMN IF NOT EXISTS claimed_sources JSONB;
ALTER TABLE records ADD COLUMN IF NOT EXISTS draft TEXT;
UPDATE sessions SET stage = CASE status WHEN 'open' THEN 'ready' ELSE status END
WHERE stage IS NULL;
"""

# v3.0 → v3.2 升級(冪等;migration 0004 與 ensure_schema 共用,單一來源):
# A 件 G0 訊號欄 + B 件 parent_action + C 件 updated_at(回填=created_at,TTL 續期錨);
# records schema_version 2→3(record-schema.md 版本管理)。
# legacy redflag_stopped 列不回填——歷史終態,查詢視同 closed。
DDL_MIGRATE_0004 = """
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS redflag_active BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS redflag_vector TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS parent_action TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE sessions ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE sessions ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE records ADD COLUMN IF NOT EXISTS redflag BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE records ADD COLUMN IF NOT EXISTS parent_action TEXT;
ALTER TABLE records ALTER COLUMN schema_version SET DEFAULT 3;
"""


class Database(Protocol):
    async def create_session(self, row: dict[str, Any]) -> None: ...
    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    async def list_open_sessions(self, child_id: str) -> list[dict[str, Any]]: ...
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
    async def expire_stale_sessions(self, cutoff: _dt.datetime) -> int: ...
    async def log_event(self, session_id: str | None, kind: str, payload: dict[str, Any]) -> None: ...
    async def get_events(self, session_id: str) -> list[dict[str, Any]]: ...
    async def insert_transcript(
        self, session_id: str, *, chunk_no: int, content_hash: str, turns_json: str,
    ) -> int | None: ...
    async def get_transcripts(self, session_id: str) -> list[dict[str, Any]]: ...
    async def list_sessions_between(
        self, start: _dt.datetime, end: _dt.datetime,
    ) -> list[dict[str, Any]]: ...
    async def list_records_between(
        self, start: _dt.datetime, end: _dt.datetime,
    ) -> list[dict[str, Any]]: ...
    async def list_rounds_for_sessions(
        self, session_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]: ...
    async def get_report_latest(self, scope: str, ref_key: str) -> dict[str, Any] | None: ...
    async def insert_report(
        self, scope: str, ref_key: str, *, body: str, meta_json: str,
    ) -> dict[str, Any]: ...
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
        self._events: list[dict[str, Any]] = []
        self._transcripts: dict[str, list[dict[str, Any]]] = {}
        self._reports: list[dict[str, Any]] = []

    async def create_session(self, row: dict[str, Any]) -> None:
        async with self._lock:
            sid = row["session_id"]
            if sid in self._sessions:
                raise UniqueViolation(f"session {sid} 已存在")
            stored = dict(row)
            now = _dt.datetime.now(_dt.timezone.utc)
            stored.setdefault("created_at", now)  # PG: DEFAULT now()
            stored.setdefault("updated_at", now)  # PG: DEFAULT now()(C 件 TTL 續期錨)
            self._sessions[sid] = stored
            self._rounds[sid] = []

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._sessions.get(session_id)
        return dict(row) if row else None

    async def list_open_sessions(self, child_id: str) -> list[dict[str, Any]]:
        # 入口 ask-gate 的「續上次」清單(v3.2 C 件);最近活動在前
        rows = [dict(s) for s in self._sessions.values()
                if s["child_id"] == child_id and s["status"] == "open"]
        rows.sort(key=lambda r: r.get("updated_at") or r["created_at"], reverse=True)
        return rows

    async def update_session(self, session_id: str, fields: dict[str, Any]) -> None:
        async with self._lock:
            safe = {k: v for k, v in fields.items() if k in SESSION_COLUMNS and k != "session_id"}
            if not safe:
                return
            safe.setdefault("updated_at", _dt.datetime.now(_dt.timezone.utc))  # 活動即續期
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
                "created_at": _dt.datetime.now(_dt.timezone.utc),  # PG: DEFAULT now()
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

    async def expire_stale_sessions(self, cutoff: _dt.datetime) -> int:
        # 棄案 TTL 錨定「最後活動」:近期有輪或近期被 touch(resume / ②③④,
        # v3.2 C 件 updated_at)→ 不棄;乒乓本就跨日。
        async with self._lock:
            n = 0
            for sid, s in self._sessions.items():
                if s["status"] != "open" or s["created_at"] >= cutoff:
                    continue
                if (s.get("updated_at") or s["created_at"]) >= cutoff:
                    continue
                if any(r["created_at"] >= cutoff for r in self._rounds.get(sid, [])):
                    continue
                s["status"] = "expired"
                s["stage"] = "expired"
                n += 1
            return n

    async def log_event(self, session_id: str | None, kind: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._events.append({
                "event_id": len(self._events) + 1, "session_id": session_id,
                "kind": kind, "payload": dict(payload),
                "created_at": _dt.datetime.now(_dt.timezone.utc),
            })

    async def get_events(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self._events if e["session_id"] == session_id]

    async def list_sessions_between(
        self, start: _dt.datetime, end: _dt.datetime,
    ) -> list[dict[str, Any]]:
        return [dict(s) for s in self._sessions.values()
                if start <= s["created_at"] < end]

    async def list_records_between(
        self, start: _dt.datetime, end: _dt.datetime,
    ) -> list[dict[str, Any]]:
        return [dict(r) for r in self._records.values()
                if start <= r["created_at"] < end]

    async def list_rounds_for_sessions(
        self, session_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        return {sid: [dict(r) for r in self._rounds.get(sid, [])] for sid in session_ids}

    async def get_report_latest(self, scope: str, ref_key: str) -> dict[str, Any] | None:
        rows = [r for r in self._reports if r["scope"] == scope and r["ref_key"] == ref_key]
        return dict(max(rows, key=lambda r: r["version"])) if rows else None

    async def insert_report(
        self, scope: str, ref_key: str, *, body: str, meta_json: str,
    ) -> dict[str, Any]:
        async with self._lock:
            prev = [r["version"] for r in self._reports
                    if r["scope"] == scope and r["ref_key"] == ref_key]
            row = {
                "report_id": len(self._reports) + 1, "scope": scope, "ref_key": ref_key,
                "version": (max(prev) + 1) if prev else 1,
                "body": body, "meta": meta_json,
                "created_at": _dt.datetime.now(_dt.timezone.utc),
            }
            self._reports.append(row)
            return dict(row)

    async def insert_transcript(
        self, session_id: str, *, chunk_no: int, content_hash: str, turns_json: str,
    ) -> int | None:
        async with self._lock:
            rows = self._transcripts.setdefault(session_id, [])
            if any(r["content_hash"] == content_hash for r in rows):
                return None  # UNIQUE(session_id, content_hash):重送冪等
            tid = sum(len(v) for v in self._transcripts.values())
            rows.append({
                "transcript_id": tid, "session_id": session_id, "chunk_no": chunk_no,
                "content_hash": content_hash, "turns": turns_json,
                "created_at": _dt.datetime.now(_dt.timezone.utc),
            })
            return tid

    async def get_transcripts(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._transcripts.get(session_id, [])]

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
            stored = dict(record_row)
            stored.setdefault("created_at", _dt.datetime.now(_dt.timezone.utc))  # PG: DEFAULT now()
            self._records[rid] = stored
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
            await conn.execute(DDL_MIGRATE)       # 既有 v2.2 庫直接開機也補齊 v3.0 欄位
            await conn.execute(DDL_MIGRATE_0004)  # 既有 v3.0 庫補齊 v3.2 欄位(冪等)
            await conn.execute(DDL_MIGRATE_0006)  # events.session_id 放寬可空(冪等)

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

    async def list_open_sessions(self, child_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM sessions WHERE child_id = %s AND status = 'open'
                ORDER BY COALESCE(updated_at, created_at) DESC
                """,
                (child_id,),
            )
            return await self._fetchall_dicts(cur)

    async def update_session(self, session_id: str, fields: dict[str, Any]) -> None:
        from psycopg import sql

        safe = {k: v for k, v in fields.items() if k in SESSION_COLUMNS and k != "session_id"}
        if not safe:
            return
        safe.setdefault("updated_at", _dt.datetime.now(_dt.timezone.utc))  # 活動即續期
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

    async def expire_stale_sessions(self, cutoff: _dt.datetime) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE sessions s SET status = 'expired', stage = 'expired'
                WHERE s.status = 'open' AND s.created_at < %s
                  AND COALESCE(s.updated_at, s.created_at) < %s
                  AND NOT EXISTS (SELECT 1 FROM rounds r
                                  WHERE r.session_id = s.session_id AND r.created_at >= %s)
                """,
                (cutoff, cutoff, cutoff),
            )
            return cur.rowcount

    async def log_event(self, session_id: str | None, kind: str, payload: dict[str, Any]) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO events (session_id, kind, payload) VALUES (%s, %s, %s)",
                (session_id, kind, self._jsonb(payload)),
            )

    async def get_events(self, session_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM events WHERE session_id = %s ORDER BY event_id", (session_id,)
            )
            return await self._fetchall_dicts(cur)

    async def insert_transcript(
        self, session_id: str, *, chunk_no: int, content_hash: str, turns_json: str,
    ) -> int | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO raw_transcripts (session_id, chunk_no, content_hash, turns)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id, content_hash) DO NOTHING
                RETURNING transcript_id
                """,
                (session_id, chunk_no, content_hash, turns_json),
            )
            row = await cur.fetchone()
            return int(row[0]) if row is not None else None  # None = 重送冪等

    async def get_transcripts(self, session_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM raw_transcripts WHERE session_id = %s ORDER BY transcript_id",
                (session_id,),
            )
            return await self._fetchall_dicts(cur)

    async def list_sessions_between(
        self, start: _dt.datetime, end: _dt.datetime,
    ) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM sessions WHERE created_at >= %s AND created_at < %s",
                (start, end),
            )
            return await self._fetchall_dicts(cur)

    async def list_records_between(
        self, start: _dt.datetime, end: _dt.datetime,
    ) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM records WHERE created_at >= %s AND created_at < %s",
                (start, end),
            )
            return await self._fetchall_dicts(cur)

    async def list_rounds_for_sessions(
        self, session_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not session_ids:
            return {}
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM rounds WHERE session_id = ANY(%s) ORDER BY session_id, round_no",
                (session_ids,),
            )
            rows = await self._fetchall_dicts(cur)
        out: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
        for r in rows:
            out[str(r["session_id"])].append(r)
        return out

    async def get_report_latest(self, scope: str, ref_key: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM reports WHERE scope = %s AND ref_key = %s
                ORDER BY version DESC LIMIT 1
                """,
                (scope, ref_key),
            )
            return await self._fetchone_dict(cur)

    async def insert_report(
        self, scope: str, ref_key: str, *, body: str, meta_json: str,
    ) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO reports (scope, ref_key, version, body, meta)
                SELECT %s, %s, COALESCE(MAX(version), 0) + 1, %s, %s
                FROM reports WHERE scope = %s AND ref_key = %s
                RETURNING report_id, scope, ref_key, version, body, meta, created_at
                """,
                (scope, ref_key, body, meta_json, scope, ref_key),
            )
            row = await self._fetchone_dict(cur)
            assert row is not None
            return row

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
