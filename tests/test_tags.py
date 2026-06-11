"""tags.md 載入 / ① 探點+紅線聯集 / ③ 反應映射 / 發展查表(spec v3.0 驗收 3・7・9)。"""

from __future__ import annotations

from fastmcp import Client

from conftest import constraints_args, data_of, ready_session
from parenting_response.cores import (
    INQUIRY_TAG_KEYS,
    RESPONSE_TAG_KEYS,
    load_tags,
    red_line_union,
)
from parenting_response.schema import INQUIRY_CORES, RESPONSE_CORES

# spec v3.0「反應二級強調」表(測試端字面複寫,守 code 投影不漂移)
SPEC_PRIMARY: dict[str, set[str]] = {
    "鬆動配合": {"pd", "adler"},
    "否認堅持": {"dreikurs", "adler", "pd"},
    "情緒爆發": {"gottman", "rogers"},
    "退縮害怕": {"rogers", "nvc"},
    "反問試探": {"nvc", "pd"},
    "轉移打岔": {"gottman", "pd"},
}

# record-schema.md 確定性映射表(字面複寫)
EXPECTED_STAGES: dict[str, tuple[str, str]] = {
    "2-3": ("自主對羞愧懷疑", "前運思期"),
    "4-6": ("主動對罪惡感", "前運思期"),
    "7-11": ("勤奮對自卑", "具體運思期"),
    "12+": ("認同對角色混淆", "形式運思期"),
}


def test_tags_loader_completeness() -> None:
    """tags.md 載入:8 校齊、欄位齊、值非空(fail-fast 驗證)。"""
    tags = load_tags()
    assert set(tags) == set(RESPONSE_CORES) | set(INQUIRY_CORES)
    for school in RESPONSE_CORES:
        for key in RESPONSE_TAG_KEYS:
            assert tags[school][key], f"{school}.{key} 空"
    for school in INQUIRY_CORES:
        for key in INQUIRY_TAG_KEYS:
            assert tags[school][key], f"{school}.{key} 空"


def test_red_line_union_covers_8_schools() -> None:
    union = red_line_union()
    assert {r["school"] for r in union} == set(RESPONSE_CORES) | set(INQUIRY_CORES)
    assert all(r["rule"] for r in union)


async def test_constraints_returns_probes_and_redlines(client: Client) -> None:
    """驗收3:任一情境,① 回傳含 Maslow/Satir 探點(引導 S1)+ 約束集。"""
    r = data_of(await client.call_tool("constraints", constraints_args()))
    probes = r["inquiry_probes"]
    assert set(probes) == {"maslow", "satir"}
    for school in ("maslow", "satir"):
        assert probes[school]["探詢"] and probes[school]["探點"]
        assert probes[school]["示範問"] and probes[school]["紅線"]
    cs = r["constraints"]
    assert {x["school"] for x in cs["red_lines"]} == set(RESPONSE_CORES) | set(INQUIRY_CORES)
    assert len(cs["forbidden_patterns"]) == 3 and all(cs["forbidden_patterns"])
    assert r["next"] == "prerequisites"


async def test_round0_all_six_primary(client: Client) -> None:
    """round 0 無 reaction:6 回應核心全 primary;探詢核心不進耦合。"""
    sid = await ready_session(client)
    r = data_of(await client.call_tool("core_tags", {"session_id": sid}))
    tags = r["response_tags"]
    assert [t["school"] for t in tags] == list(RESPONSE_CORES)
    assert all(t["role"] == "primary" for t in tags)
    for t in tags:
        assert set(t["tag"]) == set(RESPONSE_TAG_KEYS)
        assert all(t["tag"].values())
    assert {t["school"] for t in tags}.isdisjoint(INQUIRY_CORES)
    assert r["next"] == "core_tags | finalize"


async def test_reaction_primary_mapping_deterministic(client: Client) -> None:
    """驗收7(全六類):③ 依 child_reaction 確定性標 primary/support,不經 LLM。"""
    for reaction, expected in SPEC_PRIMARY.items():
        sid = await ready_session(client)
        await client.call_tool("core_tags", {"session_id": sid})
        # 高張力輪強制轉述(#4);乾淨文本避開詞表
        note = "大哭把積木掃到地上" if reaction in {"情緒爆發", "退縮害怕"} else None
        r = data_of(await client.call_tool("core_tags", {
            "session_id": sid, "child_reaction": reaction, "reaction_note": note}))
        tags = r["response_tags"]
        assert {t["school"] for t in tags} == set(RESPONSE_CORES), reaction  # 6 核心都回
        got_primary = {t["school"] for t in tags if t["role"] == "primary"}
        assert got_primary == expected, reaction
        assert {t["school"] for t in tags if t["role"] == "support"} == set(RESPONSE_CORES) - expected
        assert all(t["role"] == "primary" for t in tags[: len(expected)])  # primary 在前


async def test_dev_stage_lookup_per_band(client: Client) -> None:
    """驗收9:任一 age_band,Erikson/Piaget 與映射表一致(不經 LLM)。"""
    for band, (erikson, piaget) in EXPECTED_STAGES.items():
        sid = await ready_session(client, age_band=band)
        r = data_of(await client.call_tool("core_tags", {"session_id": sid}))
        assert r["dev_stages"] == {"erikson": erikson, "piaget": piaget}, band
