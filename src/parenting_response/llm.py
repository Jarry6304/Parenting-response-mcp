"""LLM 呼叫封裝:可注入(測試 mock 並斷言呼叫計數),正式走 anthropic SDK。

tag 慣例:core:<id> / synthesis / guardian —— 測試據此路由與計數。
模型策略見 spec v2.2:細膩語感 → Sonnet;判別型與 guardian → Haiku(同 vendor 不同 model string)。
"""

from __future__ import annotations

from typing import Protocol

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"


class LLMClient(Protocol):
    async def complete(self, *, model: str, system: str, user: str, tag: str) -> str: ...


class AnthropicLLM:
    """正式實作;測試不用(注入 FakeLLM)。"""

    def __init__(self, api_key: str | None = None, max_tokens: int = 2000) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()
        self._max_tokens = max_tokens

    async def complete(self, *, model: str, system: str, user: str, tag: str) -> str:
        resp = await self._client.messages.create(
            model=model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
