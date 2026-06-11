"""輸出端 pattern 錨定(defect-fixes #11):誤殺回歸 + 真陽性不退。

F2 人身錨定、F5 負面接續錨定——合法的同理轉述/條件句/誇獎不得被攔,
真 F2/F5 句式照攔(詞表寧緊勿鬆只適用於無多義的侮辱詞)。
"""

from __future__ import annotations

import pytest

from parenting_response.wordlists import find_output_violations

LEGITIMATE = [
    "你就是很想再玩一下,對嗎?",            # 同理心轉述(舊 F2 裸詞「你就是」誤殺)
    "如果計時器沒用,我們就換一個方法。",    # 條件句「沒用」指方法(舊 F2 裸詞誤殺)
    "你每次都會自己把玩具收好,好棒!",      # 正向誇獎(舊 F5 裸詞「每次都」誤殺)
    "我們週末來做廢物利用的勞作。",          # 「廢物利用」固定詞
    "我看到你很生氣,我們先深呼吸。",        # 一般合法草稿
]

TRUE_POSITIVES = [
    "你就是不聽話。",
    "你就是這種人。",
    "你真的很沒用。",
    "你這個沒用的東西!",
    "你每次都這樣!",
    "每次都是你惹妹妹。",
    "說過幾百遍了,你永遠學不會。",
]


@pytest.mark.parametrize("draft", LEGITIMATE)
def test_legitimate_drafts_pass(draft: str) -> None:
    assert find_output_violations(draft) == []


@pytest.mark.parametrize("draft", TRUE_POSITIVES)
def test_abusive_drafts_still_hit(draft: str) -> None:
    assert find_output_violations(draft) != []
