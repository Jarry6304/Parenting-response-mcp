"""驗證閘(v3.2 I 件):AuthKit OAuth(WorkOS)+ sub allowlist。

零密碼自管:JWT 驗章/效期/audience 由 fastmcp AuthKitProvider(JWKS)承載;
本模組只加一層 **sub allowlist**——AuthKit 帳號 ≠ 本系統使用者,
家庭系統只放行明列的兩個 sub。

形狀註記:allowlist 攔截以 verify_token 回 None 落地(HTTP 401)。spec 偏好
403(已認證未授權),但 fastmcp 的 ASGI middleware 掛在 auth 之前拿不到已驗
sub,401 + events `auth_denied` 留痕為實作取捨——稽核面等價(deploy-runbook
如實陳述此偏離)。

local 模式(AUTH_MODE=local,預設):無閘,**只准綁 loopback**,
非 loopback 一律拒啟動(records 含兒少個資;v3.0 的 stderr 警告升級為 fail-fast)。
"""

from __future__ import annotations

from typing import Any

from fastmcp.server.auth import AuthProvider, TokenVerifier
from fastmcp.server.auth.auth import AccessToken

from .db import Database

AUTH_MODES = ("local", "authkit")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class ConfigError(SystemExit):
    """啟動組態錯誤:fail-fast,不帶半開狀態上線。"""

    def __init__(self, message: str) -> None:
        super().__init__(f"組態錯誤:{message}")


def validate_binding(mode: str, host: str) -> None:
    """綁定防呆:local 模式非 loopback 即拒啟動(個資面不可裸奔)。"""
    if mode not in AUTH_MODES:
        raise ConfigError(f"AUTH_MODE 須 ∈ {'|'.join(AUTH_MODES)}:{mode}")
    if mode == "local" and host not in _LOOPBACK_HOSTS:
        raise ConfigError(
            f"AUTH_MODE=local 只准綁 loopback(HOST={host});"
            "對外部署請設 AUTH_MODE=authkit(+ AUTHKIT_DOMAIN/BASE_URL/ALLOWED_SUBJECTS)")


class AllowlistVerifier(TokenVerifier):
    """JWT 驗過(inner)後再驗 sub ∈ allowlist;拒絕一律 events `auth_denied` 留痕。"""

    def __init__(self, inner: TokenVerifier, allowed: frozenset[str], db: Database) -> None:
        super().__init__(base_url=inner.base_url, required_scopes=inner.required_scopes)
        self._inner = inner
        self._allowed = allowed
        self._db = db

    async def verify_token(self, token: str) -> AccessToken | None:
        tok = await self._inner.verify_token(token)
        if tok is None:
            return None  # 簽章/效期不過:fastmcp 既有 401,毋須留痕(網路噪音)
        sub = _sub_of(tok)
        if sub not in self._allowed:
            await self._db.log_event(None, "auth_denied", {
                "sub": sub, "reason": "sub 不在 ALLOWED_SUBJECTS"})
            return None
        return tok


def _sub_of(tok: AccessToken) -> str | None:
    if tok.subject:
        return str(tok.subject)
    claims: dict[str, Any] = tok.claims or {}
    sub = claims.get("sub")
    return str(sub) if sub is not None else None


def current_sub() -> str | None:
    """請求上下文的已驗 sub(無 auth / local 模式 → None)。"""
    from fastmcp.server.dependencies import get_access_token

    try:
        tok = get_access_token()
    except Exception:
        return None
    return _sub_of(tok) if tok is not None else None


def build_auth(
    *, mode: str, authkit_domain: str | None, base_url: str | None,
    allowed_subjects: list[str], db: Database,
) -> AuthProvider | None:
    """組 auth provider:local → None;authkit → AuthKitProvider + allowlist。

    authkit 三要素缺一拒啟動——ALLOWED_SUBJECTS 尤其不可缺省,
    缺省語意會變成「任何 AuthKit 帳號可入」,對家庭系統即等於沒鎖。
    """
    if mode == "local":
        return None
    if not authkit_domain or not base_url:
        raise ConfigError("AUTH_MODE=authkit 須設 AUTHKIT_DOMAIN 與 BASE_URL")
    if not allowed_subjects:
        raise ConfigError("AUTH_MODE=authkit 須設 ALLOWED_SUBJECTS(逗號分隔 sub 清單)")

    from fastmcp.server.auth.providers.jwt import JWTVerifier
    from fastmcp.server.auth.providers.workos import AuthKitProvider

    domain = authkit_domain.rstrip("/")
    inner = JWTVerifier(jwks_uri=f"{domain}/oauth2/jwks", issuer=domain, algorithm="RS256")
    wrapped = AllowlistVerifier(inner, frozenset(allowed_subjects), db)
    return AuthKitProvider(authkit_domain=domain, base_url=base_url, token_verifier=wrapped)
