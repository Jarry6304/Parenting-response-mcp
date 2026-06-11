"""驗收測試共用件:FakeLLM(可路由、可計數)+ MemoryDatabase + in-memory MCP client。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable

import pytest
from fastmcp import Client

from parenting_response.db import MemoryDatabase
from parenting_response.orchestrator import Orchestrator
from parenting_response.schema import PRODUCER_CORES
from parenting_response.server import build_server

# 每核心 canned 輸出;analysis 帶獨特標記字串,供隔離斷言用。
CORE_CANNED: dict[str, dict[str, Any]] = {
    "pd": {
        "candidate": {"posture": "溫和設限", "utterance": "車車先放這裡,我們等等一起想辦法。"},
        "analysis": "PD-分析-標記-甲", "confidence": 0.8,
    },
    "dreikurs": {
        "purpose": "權力",
        "candidate": {"posture": "給選擇", "utterance": "你想先收車車,還是先去洗手?"},
        "analysis": "DK-分析-標記-乙", "confidence": 0.7,
    },
    "gottman": {
        "emotion_processed": True,
        "candidate": {"posture": "情緒教練", "utterance": "你看起來好生氣,因為車被拿走了,對嗎?"},
        "analysis": "GM-分析-標記-丙", "confidence": 0.9,
    },
    "nvc": {
        "candidate": {"posture": "同理接住", "utterance": "我看到妹妹拿了你的車。"},
        "analysis": "NV-分析-標記-丁", "confidence": 0.6,
    },
    "rogers": {
        "candidate": {"posture": "同理接住", "utterance": "你好希望車車趕快回來。"},
        "analysis": "RG-分析-標記-戊", "confidence": 0.5,
    },
    "adler": {"analysis": "AD-分析-標記-己:私人邏輯=用搶宣示掌控"},
    "maslow": {
        "analysis": "MS-分析-標記-庚", "unmet_needs": ["安全"],
        "constraints": [{
            "type": "需求不踩底", "rule": "不得以取消點心作為後果",
            "checkable_by": "pattern", "forbidden_terms": ["不准吃"],
        }],
    },
    "satir": {
        "analysis": "ST-分析-標記-辛", "child_stance": "一致", "parent_stance": "指責",
        "constraints": [{
            "type": "不損自我", "rule": "不得人格定性,談行為不談人", "checkable_by": "guardian",
        }],
    },
    "erikson": {
        "analysis": "EK-分析-標記-壬", "stage_observed": "主動對罪惡感",
        "within_norm": True, "constraints": [],
    },
    "piaget": {
        "analysis": "PG-分析-標記-癸", "stage_observed": "前運思期",
        "within_norm": True, "constraints": [],
    },
}

ANALYSIS_MARKERS = [str(v["analysis"]) for v in CORE_CANNED.values()]

SYNTH_MARK = "(合成)"


def default_synthesis(_system: str, user: str) -> str:
    """讀版面的「可用來源代號」行,從可用産招挑來源——模擬守規矩的合成。"""
    ids: list[str] = []
    for line in user.splitlines():
        if line.startswith("可用來源代號"):
            ids = [t.strip() for t in line.split(":", 1)[1].split(",")]
    producers = [p for p in PRODUCER_CORES if p in ids]
    utterances = [{"text": f"{SYNTH_MARK}我先蹲下來,陪你一起深呼吸。", "source": producers[0]}]
    if len(producers) > 1:
        utterances.append({"text": f"{SYNTH_MARK}等一下我們一起想辦法。", "source": producers[1]})
    card = {
        "reading": "孩子的東西被拿走,正在用行動守住物權;先接情緒再談規則。",
        "posture": "溫和設限",
        "opening_utterances": utterances,
        "watchpoints": "看孩子反應:鬆動 → 一起想辦法;堅持 → 先陪伴稍後再談。",
        "boundary": "可以生氣,不可以動手。",
        "redline": "若出現傷人或自傷行為,先確保安全並暫停對話。",
        "source_summary": "取用前兩個可用産招;其餘本輪先放下。",
    }
    return json.dumps({"card": card, "set_aside": [], "divergences_surfaced": []}, ensure_ascii=False)


Handler = str | dict[str, Any] | Callable[[str, str], str] | Exception | type[Exception]


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.handlers: dict[str, Handler] = {}

    def count(self, prefix: str = "") -> int:
        return sum(1 for c in self.calls if c["tag"].startswith(prefix))

    def calls_for(self, prefix: str) -> list[dict[str, str]]:
        return [c for c in self.calls if c["tag"].startswith(prefix)]

    async def complete(self, *, model: str, system: str, user: str, tag: str) -> str:
        self.calls.append({"tag": tag, "model": model, "system": system, "user": user})
        handler = self.handlers.get(tag)
        if handler is None:
            if tag.startswith("core:"):
                handler = CORE_CANNED[tag.removeprefix("core:")]
            elif tag == "synthesis":
                handler = default_synthesis
            elif tag == "guardian":
                handler = '{"violations": []}'
            else:  # pragma: no cover
                raise AssertionError(f"未知 tag:{tag}")
        if isinstance(handler, type) and issubclass(handler, Exception):
            raise handler(tag)
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(system, user)
        if isinstance(handler, dict):
            return json.dumps(handler, ensure_ascii=False)
        return handler


def analyze_args(**over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "mode": "live",
        "age_band": "4-6",
        "facts": "妹妹拿走他的玩具車,他大叫並推了妹妹",
        "emotion": "生氣",
        "emotion_intensity": "高",
        "problem_category": "手足衝突",
        "parent_goal": "讓他用說的不動手",
    }
    args.update(over)
    return args


def data_of(result: Any) -> dict[str, Any]:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    return json.loads(result.content[0].text)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def db() -> MemoryDatabase:
    return MemoryDatabase()


@pytest.fixture
def orch(db: MemoryDatabase, fake_llm: FakeLLM) -> Orchestrator:
    return Orchestrator(db, fake_llm)


@pytest.fixture
async def client(orch: Orchestrator) -> AsyncIterator[Client]:
    async with Client(build_server(orch)) as c:
        yield c
