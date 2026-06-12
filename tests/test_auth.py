"""v3.2 I 件:AuthKit OAuth + sub allowlist + loopback fail-fast +
StaticTokenVerifier 退役。JWT 驗章/401 屬 fastmcp 內建不重測;
connector 端到端驗收列 deploy-runbook(部署後手動)。"""

from __future__ import annotations

import pytest
from fastmcp.server.auth.auth import AccessToken

from conftest import constraints_args, data_of
from fastmcp import Client
from parenting_response.auth import (
    AllowlistVerifier,
    build_auth,
    current_sub,
    validate_binding,
)
from parenting_response.db import MemoryDatabase


def test_local_mode_loopback_only() -> None:
    """local 模式非 loopback → 拒啟動(v3.0 警告升級為 fail-fast)。"""
    validate_binding("local", "127.0.0.1")
    validate_binding("local", "::1")
    validate_binding("authkit", "0.0.0.0")  # 對外 = authkit,放行
    with pytest.raises(SystemExit, match="loopback"):
        validate_binding("local", "0.0.0.0")
    with pytest.raises(SystemExit, match="AUTH_MODE"):
        validate_binding("亂寫", "127.0.0.1")


def test_build_auth_local_none_and_authkit_failfast(db: MemoryDatabase) -> None:
    """local → 無閘(None);authkit 三要素缺一 → 拒啟動(allowlist 缺省=沒鎖)。"""
    assert build_auth(mode="local", authkit_domain=None, base_url=None,
                      allowed_subjects=[], db=db) is None
    with pytest.raises(SystemExit, match="AUTHKIT_DOMAIN"):
        build_auth(mode="authkit", authkit_domain=None, base_url="https://x.example",
                   allowed_subjects=["u1"], db=db)
    with pytest.raises(SystemExit, match="ALLOWED_SUBJECTS"):
        build_auth(mode="authkit", authkit_domain="https://a.authkit.app",
                   base_url="https://x.example", allowed_subjects=[], db=db)
    auth = build_auth(mode="authkit", authkit_domain="https://a.authkit.app",
                      base_url="https://x.example", allowed_subjects=["u1"], db=db)
    assert auth is not None  # AuthKitProvider(內含 allowlist verifier)


class _FakeInner:
    """inner verifier 替身:固定回 sub=user_ok 的 AccessToken。"""

    base_url = None
    required_scopes: list[str] = []

    async def verify_token(self, token: str) -> AccessToken | None:
        if token == "bad":
            return None
        return AccessToken(token=token, client_id="c", scopes=[],
                           claims={"sub": "user_ok"})


async def test_allowlist_verifier_gates_and_audits(db: MemoryDatabase) -> None:
    """sub ∈ allowlist → 放行;∉ → 拒(None)+ events auth_denied 留痕;
    簽章不過(inner None)→ 拒但不留痕(網路噪音)。"""
    ok = AllowlistVerifier(_FakeInner(), frozenset({"user_ok"}), db)  # type: ignore[arg-type]
    tok = await ok.verify_token("t1")
    assert tok is not None and tok.claims is not None and tok.claims["sub"] == "user_ok"

    deny = AllowlistVerifier(_FakeInner(), frozenset({"someone_else"}), db)  # type: ignore[arg-type]
    assert await deny.verify_token("t2") is None
    denied = [e for e in db._events if e["kind"] == "auth_denied"]
    assert len(denied) == 1
    assert denied[0]["session_id"] is None
    assert denied[0]["payload"]["sub"] == "user_ok"

    assert await deny.verify_token("bad") is None
    assert len([e for e in db._events if e["kind"] == "auth_denied"]) == 1  # 不增


async def test_events_carry_sub_when_authed(
    db: MemoryDatabase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """authkit 請求上下文下,G0 稽核 events 自動附 sub(誰觸發可考)。"""
    from parenting_response.orchestrator import Orchestrator
    from parenting_response.server import build_server

    monkeypatch.setattr("parenting_response.orchestrator.current_sub", lambda: "user_dad")
    orch = Orchestrator(db, caregiver_map={"user_dad": "爸"})
    async with Client(build_server(orch)) as c:
        r = data_of(await c.call_tool("constraints", constraints_args(
            facts="他說他不想活了", emotion="害怕")))
    evs = await db.get_events(r["session_id"])
    assert evs[0]["kind"] == "g0_shortcircuit" and evs[0]["payload"]["sub"] == "user_dad"


def test_current_sub_none_outside_request() -> None:
    """無請求上下文(local/測試)→ None(events 不附 sub,形狀不變)。"""
    assert current_sub() is None


def test_static_token_verifier_retired() -> None:
    """v3.0 bearer 閘退役:server.py 不再引用 StaticTokenVerifier / MCP_BEARER_TOKEN。"""
    import inspect

    import parenting_response.server as server_mod

    src = inspect.getsource(server_mod)
    assert "StaticTokenVerifier" not in src
    assert "MCP_BEARER_TOKEN" not in src
