"""v3.0 J 件:信封加密——roundtrip / 直通 / 輪替 / db 透明層(庫存密文、API 回明文)/
G0 先於加密。全套件其餘測試維持明文直通(僅本檔開金鑰)。"""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any, AsyncIterator

import pytest
from fastmcp import Client

from conftest import constraints_args, data_of, prereq_args
from parenting_response.crypto import Envelope
from parenting_response.db import MemoryDatabase
from parenting_response.orchestrator import Orchestrator
from parenting_response.server import build_server


def _key_b64() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture
def env() -> Envelope:
    return Envelope({"k1": base64.b64decode(_key_b64())}, "k1")


@pytest.fixture
def encdb(env: Envelope) -> MemoryDatabase:
    return MemoryDatabase(envelope=env)


@pytest.fixture
async def encclient(encdb: MemoryDatabase) -> AsyncIterator[Client]:
    async with Client(build_server(Orchestrator(encdb))) as c:
        yield c


def test_roundtrip_and_format(env: Envelope) -> None:
    ct = env.encrypt("他說他不想活了")
    assert ct.startswith("enc:k1:") and "不想活" not in ct
    assert env.decrypt(ct) == "他說他不想活了"
    assert env.encrypt("x") != env.encrypt("x")  # 隨機 nonce:同文不同密


def test_plaintext_passthrough(env: Envelope, monkeypatch: pytest.MonkeyPatch) -> None:
    """未設 env → from_env None(直通);decrypt 對無前綴回原文(混存相容)。"""
    monkeypatch.delenv("ENVELOPE_KEYS", raising=False)
    assert Envelope.from_env() is None
    assert env.decrypt("歷史明文資料") == "歷史明文資料"


def test_from_env_and_key_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENVELOPE_KEYS 多鑰共存:active 加密、舊鑰仍可解;active 缺/不在 → 拒。"""
    k1, k2 = _key_b64(), _key_b64()
    monkeypatch.setenv("ENVELOPE_KEYS", json.dumps({"k1": k1, "k2": k2}))
    monkeypatch.setenv("ENVELOPE_ACTIVE_KEY_ID", "k1")
    old = Envelope.from_env()
    assert old is not None
    ct_old = old.encrypt("輪替前的資料")

    monkeypatch.setenv("ENVELOPE_ACTIVE_KEY_ID", "k2")  # 輪替:新寫走 k2
    new = Envelope.from_env()
    assert new is not None
    assert new.encrypt("新資料").startswith("enc:k2:")
    assert new.decrypt(ct_old) == "輪替前的資料"  # 舊密文仍可解

    monkeypatch.setenv("ENVELOPE_ACTIVE_KEY_ID", "ghost")
    with pytest.raises(ValueError, match="ghost"):
        Envelope.from_env()
    monkeypatch.delenv("ENVELOPE_ACTIVE_KEY_ID")
    with pytest.raises(ValueError, match="ENVELOPE_ACTIVE_KEY_ID"):
        Envelope.from_env()


def test_unknown_key_id_raises(env: Envelope) -> None:
    """密文 key_id 不在鑰圈 → raise(輪替時舊鑰不可先撤)。"""
    ct = env.encrypt("資料").replace("enc:k1:", "enc:k9:")
    with pytest.raises(ValueError, match="k9"):
        env.decrypt(ct)


async def test_db_stores_ciphertext_api_returns_plaintext(
    encclient: Client, encdb: MemoryDatabase,
) -> None:
    """庫存密文(直查內部 dict 斷言)、API 回明文(orchestrator 無感)。"""
    r = data_of(await encclient.call_tool("constraints", constraints_args()))
    sid = r["session_id"]
    raw = encdb._sessions[sid]
    assert raw["facts"].startswith("enc:k1:") and "玩具車" not in raw["facts"]
    assert raw["emotion"].startswith("enc:k1:")
    s = await encdb.get_session(sid)
    assert s is not None and "玩具車" in s["facts"]  # API 面解密

    await encclient.call_tool("prerequisites", prereq_args(sid))
    await encclient.call_tool("core_tags", {"session_id": sid})
    await encclient.call_tool("core_tags", {
        "session_id": sid, "child_reaction": "否認堅持", "reaction_note": "他說不要就是不要"})
    raw_round = encdb._rounds[sid][1]
    assert raw_round["reaction_note"].startswith("enc:k1:")
    rounds = await encdb.get_rounds(sid)
    assert rounds[1]["reaction_note"] == "他說不要就是不要"


async def test_g0_scans_before_encryption(
    encclient: Client, encdb: MemoryDatabase,
) -> None:
    """G0 在 orchestrator 層掃明文(加密前)——密文庫不影響安全訊號。"""
    r = data_of(await encclient.call_tool("constraints", constraints_args(
        facts="他說他不想活了", emotion="害怕")))
    sid = r["session_id"]
    assert r["redflag"]["hit"] is True  # 命中(掃的是明文)
    s_raw = encdb._sessions[sid]
    assert s_raw["facts"].startswith("enc:k1:")  # 落庫已是密文
    assert s_raw["redflag_active"] is True and s_raw["severity"] == "高"
    evs = await encdb.get_events(sid)
    assert evs[0]["payload"]["phrase"] == "不想活"  # 證據鏈仍可考(events 設計上明文)


async def test_record_transcript_report_encrypted(
    encclient: Client, encdb: MemoryDatabase,
) -> None:
    """record 自由文本欄 / 逐字稿 turns / 報告 body 落庫皆密文,讀出皆明文。"""
    r0 = data_of(await encclient.call_tool("constraints", constraints_args()))
    sid = r0["session_id"]
    await encclient.call_tool("prerequisites", prereq_args(sid))
    await encclient.call_tool("core_tags", {"session_id": sid})
    r1 = data_of(await encclient.call_tool("finalize", {
        "session_id": sid, "outcome": "resolved",
        "draft": "我看到你很生氣,我們先深呼吸。", "outcome_note": "他後來自己收了"}))
    rid = r1["record_id"]
    raw_rec = encdb._records[rid]
    assert raw_rec["draft"].startswith("enc:k1:")
    assert raw_rec["outcome_note"].startswith("enc:k1:")
    rec = await encdb.get_record(rid)
    assert rec is not None and rec["draft"] == "我看到你很生氣,我們先深呼吸。"

    await encclient.call_tool("archive", {
        "session_id": sid, "chunk_no": 0,
        "turns": [{"role": "parent", "content": "他剛把妹妹推倒了"}]})
    raw_t = encdb._transcripts[sid][0]
    assert raw_t["turns"].startswith("enc:k1:")
    ts = await encdb.get_transcripts(sid)
    assert "推倒" in ts[0]["turns"]

    slots = {
        "what_worked": "先反映情緒,他就願意聽了。",
        "next_time": "更早介入,先把空間分開。",
        "quotes": "「你很生氣對不對?」",
    }
    r2 = data_of(await encclient.call_tool("report", {
        "scope": "event", "ref": sid, "slots": slots}))
    raw_report = encdb._reports[0]
    assert raw_report["body"].startswith("enc:k1:")
    assert raw_report["meta"].startswith("enc:k1:")
    assert "## 這次有效的" in r2["body"]  # 回傳明文
    latest = await encdb.get_report_latest("event", sid)
    assert latest is not None and "先反映情緒" in latest["body"]


async def test_resume_and_entry_gate_decrypt(
    encclient: Client, encdb: MemoryDatabase,
) -> None:
    """入口清單 facts 截斷與 resume 回放都吃解密後明文(不漏密文)。"""
    r0 = data_of(await encclient.call_tool("constraints", constraints_args()))
    gate = data_of(await encclient.call_tool("constraints", {}))
    assert "玩具車" in gate["open_sessions"][0]["facts"]
    resumed = data_of(await encclient.call_tool("constraints", {
        "mode": "resume", "session_id": r0["session_id"]}))
    assert "玩具車" in resumed["facts"]
