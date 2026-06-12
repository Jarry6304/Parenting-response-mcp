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

# ── 語意紅線(v3.2 H 件):報告 slot 的「主詞+負面定性」tripwire ──
# 第一層:警告不拒收——子句同時含孩子主詞與評價詞、且無否定前綴 → 記
# semantic_warnings(events 稽核 + 下期季報回放)。詞表從嚴列「人格定性」詞,
# 不含行為描述詞(「打人」是行為,「壞」是定性)。

SEMANTIC_SUBJECT_RE = re.compile(r"孩子|兒子|女兒|哥哥|弟弟|姊姊|妹妹|他|她")
SEMANTIC_EVAL_TERMS: tuple[str, ...] = (
    "懶", "笨", "壞", "故意", "難搞", "難帶", "講不聽", "不受教", "沒救",
    "白目", "欠管", "皮在癢", "屢勸不聽", "無可救藥", "問題兒童",
)
SEMANTIC_NEG_PREFIX_RE = re.compile(r"不是|並非|沒有|不再|不會|很少")
_CLAUSE_SPLIT_RE = re.compile(r"[,。;!?\n,;!?]")


def semantic_warnings(text: str) -> list[dict[str, str]]:
    """語意 tripwire:回 [{clause, term}](空 = 乾淨)。子句粒度判定,
    否定前綴(「他不是故意的」)豁免。"""
    hits: list[dict[str, str]] = []
    for clause in _CLAUSE_SPLIT_RE.split(text):
        if not clause.strip() or not SEMANTIC_SUBJECT_RE.search(clause):
            continue
        if SEMANTIC_NEG_PREFIX_RE.search(clause):
            continue
        for term in SEMANTIC_EVAL_TERMS:
            if term in clause:
                hits.append({"clause": clause.strip(), "term": term})
                break
    return hits


# ── ⑤ archive 防滲(v3.2 E 件):工具協議標記不得混入逐字稿 ──────
# 錨定「協議標記」而非語意:逐字稿是家長與 host 的對話原文,任何
# function-call / tool-use 結構出現即代表 host 把工具軌道誤倒進來(或偽造),
# 整 chunk 拒收。樣式涵蓋 XML 形(<function…>)與 JSON 形("tool_calls":)。
_TOOL_MARKUP_RE = re.compile(
    r"</?(?:antml:)?(?:function|invoke|parameter|tool_use|tool_result|function_calls|function_results)\b[^>]*>"
    r"|\"(?:tool_calls|function_call|tool_use_id|tool_result)\"\s*:"
    r"|```json\s*\{",
)


def find_tool_markup(text: str) -> list[str]:
    """逐字稿工具標記掃描:回命中樣式列(空 = 乾淨)。"""
    return [m.group(0) for m in _TOOL_MARKUP_RE.finditer(text)]


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
