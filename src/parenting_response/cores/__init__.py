"""十核心:registry + prompt 載入 + 隔離呼叫封裝。

隔離保證點(spec v2.2 + cores/README):
- 每核心一次獨立 API 呼叫,輸入只有結構化情境 JSON;
- 不含其他核心輸出、不含候選、不含歷輪卡文、不含 linked_plan(嚴格隔離,縫補裁決)。
prompt 單一事實來源 = references/cores/<id>.md 的「## system prompt」節。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..llm import MODEL_HAIKU, MODEL_SONNET, LLMClient
from ..schema import ALL_CORES, CORE_OUTPUT_MODELS

_REFERENCES_CORES = Path(__file__).resolve().parents[3] / "references" / "cores"

_PROMPT_RE = re.compile(r"## system prompt\s*```text\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class CoreSpec:
    core_id: str
    role: str  # producer | perspective | constraint
    model: str
    output_model: type[BaseModel]


REGISTRY: dict[str, CoreSpec] = {
    "pd": CoreSpec("pd", "producer", MODEL_SONNET, CORE_OUTPUT_MODELS["pd"]),
    "dreikurs": CoreSpec("dreikurs", "producer", MODEL_HAIKU, CORE_OUTPUT_MODELS["dreikurs"]),
    "gottman": CoreSpec("gottman", "producer", MODEL_SONNET, CORE_OUTPUT_MODELS["gottman"]),
    "nvc": CoreSpec("nvc", "producer", MODEL_SONNET, CORE_OUTPUT_MODELS["nvc"]),
    "rogers": CoreSpec("rogers", "producer", MODEL_SONNET, CORE_OUTPUT_MODELS["rogers"]),
    "adler": CoreSpec("adler", "perspective", MODEL_SONNET, CORE_OUTPUT_MODELS["adler"]),
    "maslow": CoreSpec("maslow", "constraint", MODEL_HAIKU, CORE_OUTPUT_MODELS["maslow"]),
    "satir": CoreSpec("satir", "constraint", MODEL_SONNET, CORE_OUTPUT_MODELS["satir"]),
    "erikson": CoreSpec("erikson", "constraint", MODEL_HAIKU, CORE_OUTPUT_MODELS["erikson"]),
    "piaget": CoreSpec("piaget", "constraint", MODEL_HAIKU, CORE_OUTPUT_MODELS["piaget"]),
}
assert tuple(REGISTRY) == ALL_CORES


@lru_cache(maxsize=None)
def load_prompt(core_id: str) -> str:
    path = _REFERENCES_CORES / f"{core_id}.md"
    match = _PROMPT_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError(f"{path} 缺「## system prompt」節")
    return match.group(1).strip()


def parse_json_loose(raw: str) -> dict[str, Any]:
    """容忍模型多包一層 fence/前後綴;取第一個 { 到最後一個 }。"""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("輸出不含 JSON 物件")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("輸出 JSON 非物件")
    return cast(dict[str, Any], data)


async def call_core(
    core_id: str, situation_payload: str, llm: LLMClient, *, retries: int = 1
) -> dict[str, Any] | None:
    """單核心隔離呼叫;失敗 retry,仍失敗回 None(unavailable)。"""
    spec = REGISTRY[core_id]
    system = load_prompt(core_id)
    for _ in range(retries + 1):
        try:
            raw = await llm.complete(
                model=spec.model, system=system, user=situation_payload, tag=f"core:{core_id}"
            )
            return spec.output_model.model_validate(parse_json_loose(raw)).model_dump()
        except Exception:
            continue
    return None


async def fan_out(
    core_ids: list[str], situation_payload: str, llm: LLMClient
) -> dict[str, dict[str, Any] | None]:
    """單波並行(asyncio.gather);全核心吃同一份情境,互不參照。"""
    results = await asyncio.gather(
        *(call_core(cid, situation_payload, llm) for cid in core_ids)
    )
    return dict(zip(core_ids, results))
