"""G0 兩級詞組 + 輸出端 pattern 禁用詞。

詞源(單一事實來源):references/tw-parenting-antipatterns.md。
本檔為其 code 投影;修詞表先修文件再同步此處。
變體擴充原則:F2 人身錨定、F3/F5 搭配結構錨定,不攔多義裸詞;
高特異性侮辱詞才裸詞直攔(見文件「在地化備註」,defect-fixes #11)。
"""

from __future__ import annotations

import re

# ── G0 短路級(v3.2 A 件:命中 → 訊號,不停案;轉介必達 + safety_mode) ──
# 風險向(spec v3.2 G 件):命中組自然攜帶 child / parent / third,
# 決定 ③ safety_mode 組卡用哪張底座卡;詞面無法消歧主語(如「打到瘀青」
# 可能家長自陳),取語意最可能向,known limitation 文件如實陳述。

G0_SHORTCIRCUIT_BY_VECTOR: dict[str, tuple[str, ...]] = {
    # 孩子自身風險:自傷/自殺意念 + 傷人傷物升級(主體是孩子)
    "child": (
        "不想活", "想死", "想消失", "自殘", "割手", "割腕",
        "持械", "掐脖", "虐待動物",
    ),
    # 第三方/目睹:虐待/疏忽跡象 + 性相關(通報義務向)
    "third": (
        "打到瘀青", "打到受傷", "燙傷", "整天沒吃", "反鎖", "單獨留置", "深夜趕出",
        "不當觸碰", "摸下體",
    ),
    # 家長端風險:失控/自傷
    "parent": (
        "快忍不住打", "已經失手", "怕自己傷害", "活不下去",
    ),
}

G0_SHORTCIRCUIT_PHRASES: tuple[str, ...] = tuple(
    p for phrases in G0_SHORTCIRCUIT_BY_VECTOR.values() for p in phrases
)

_VECTOR_BY_PHRASE: dict[str, str] = {
    p: v for v, phrases in G0_SHORTCIRCUIT_BY_VECTOR.items() for p in phrases
}


def vector_of(phrase: str) -> str:
    """短路詞組 → 風險向(child|parent|third);組卡的唯一判斷來源。"""
    return _VECTOR_BY_PHRASE[phrase]

# ── G0 警訊級(不停案;severity 升「高」,A3 推導吃) ────────────────

G0_WARNING_PHRASES: tuple[str, ...] = (
    # 遺棄威脅既說(P03/P04/P25)
    "丟在這裡", "把你丟掉", "不帶你回家", "孤兒院", "給別人養", "我不要你了", "不是我的小孩",
    # 體罰工具與肢體威嚇既說/既發生(P46–P50)
    "衣架", "棍子拿來", "愛的小手", "手伸出來", "揍你", "打到你乖", "欠揍", "罰跪", "罰站到",
)

REFERRAL_TEXT = (
    "這個情況超出本系統的安全範圍,請尋求專業協助:"
    "兒童青少年心智科或心理諮商;台灣 113 保護專線;若有立即危險請撥 110/119。"
)

# ── 輸出端 pattern 禁用詞(僅 F2/F3/F5 語言投影;檢卡全文) ────────

OUTPUT_PATTERN_F2 = (
    r"你就是(?:笨|壞|懶|蠢|皮|故意|欠揍|欠罵|不乖|不聽話|不受教|不會想|沒救|沒用|沒出息"
    r"|這種人|講不聽|說不聽|教不會|學不乖|愛哭|愛搗蛋|死性不改)"
    r"|(?:你|妳)(?:真的?|好|很|這麼|那麼|就是|根本){0,3}沒用|沒用的東西"
    r"|豬腦|豬頭|沒長腦|羞羞臉|丟不丟臉|廢物(?!利用)|像什麼樣子|哭什麼哭|撿角|沒出息|死小孩|死囝仔|夭壽"
)
OUTPUT_PATTERN_F3 = r"你看(哥哥|姊姊|弟弟|妹妹)|人家.{0,6}都(可以|會|行)|別人家的?(小孩|孩子)|跟你(爸|媽)一(個樣|樣)|全班就你|同學都|都比你(乖|懂事|好|強)"
OUTPUT_PATTERN_F5 = (
    r"每次都(?:這樣|那樣|是你|不|沒|忘|亂|搞|惹|哭|鬧|拖|氣)"
    r"|從來(不|沒)|又來了|又開始了|早就跟你說|上次(也是|就)|講(過)?幾?(百|十|多少)遍|永遠(學|教)不會"
)

OUTPUT_PATTERN: re.Pattern[str] = re.compile(
    "|".join((OUTPUT_PATTERN_F2, OUTPUT_PATTERN_F3, OUTPUT_PATTERN_F5))
)


def find_shortcircuit(text: str) -> str | None:
    """回傳第一個命中的短路級詞組;G0 是 code 詞組層,不做語意消歧(設計,非缺陷)。"""
    for phrase in G0_SHORTCIRCUIT_PHRASES:
        if phrase in text:
            return phrase
    return None


def find_warnings(text: str) -> list[str]:
    return [p for p in G0_WARNING_PHRASES if p in text]


def find_output_violations(text: str, extra_terms: list[str] | None = None) -> list[str]:
    """固定詞表(F2/F3/F5)∪ 當輪 pattern 型 constraints 的 forbidden_terms。"""
    hits: list[str] = [m.group(0) for m in OUTPUT_PATTERN.finditer(text)]
    for term in extra_terms or []:
        if term and term in text:
            hits.append(term)
    return hits
