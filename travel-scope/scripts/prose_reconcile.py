# -*- coding: utf-8 -*-
"""MT-D2 第 6 步：固定术语表 + 数字/日期/币种/URL/实体名/目的地的「不漂移」对账。

登记面 references/prose-glossary.json；本文件是唯一实现。合同里从 MT-C 就写着这一层
（`no_new_facts.enforced_by` 点名的就是 prose_reconcile.py + prose-glossary.json），
MT-C 那一轮先把「必须有这一层」登记下来，是为了不让 MT-E 把语义对账当成可选项。
现在 MT-D2 把它补齐：翻译表在 MT-E 生成之前，先把尺子立起来并且量过实测语料。

三条设计决定（都是被实测逼出来的，不是审美）：
  · 只查**结构事实**（数字、日期、币种码、URL 主机、登记的实体名与目的地名），
    不判断「翻得好不好」——语义反义/漏译是 MT-F 第二遍人工复核的活，本模块不冒充它。
  · 实体名与目的地名**从既有登记面读**（display_names.read_pairs 与 dataset.destinations），
    不在术语表里再抄一份人名地名表；术语表只收「跨条必须一致」的固定措辞与单位/币种映射。
  · 数字不许换算、金额不许折算、单位不许改口径：本项目交付的是读者要照着花钱的行程，
    「110-180 元」翻成「$15-25」看着更顺，但那是把汇率当成事实来源，而汇率合同另有出处。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
GLOSSARY_PATH = ROOT / "references" / "prose-glossary.json"
CJK = re.compile(r"[\u4e00-\u9fff]")

CHECK_VOCABULARY = ("number", "date", "currency", "url", "entity", "destination",
                    "term", "unit_system", "proper_name_variant")
FINDING_CODES = {
    "number": "fact_drift_number",
    "date": "fact_drift_date",
    "currency": "fact_drift_currency",
    "url": "fact_drift_url",
    "entity": "fact_drift_entity",
    "destination": "fact_drift_destination",
    "term": "fact_drift_term",
    "unit_system": "fact_drift_unit_system",
    "proper_name_variant": "fact_drift_proper_name_variant",
}
# 结构面自己的码：不属于 MT-C 的表门（那边只登记本模块读得到的字段），
# 由 scripts/test_v422_prose_glossary.py 与本文件双向闭合。
STRUCTURAL_CODES = ("glossary_not_object", "glossary_missing_field", "glossary_entry_incomplete",
                    "glossary_term_duplicate", "glossary_check_unregistered",
                    "glossary_english_contains_cjk", "glossary_term_match_unknown",
                    "glossary_not_after_shape", "glossary_proper_name_shape_unknown",
                    "glossary_proper_name_param_unregistered", "glossary_allowed_pair_incomplete",
                    "glossary_allowed_pair_duplicate", "glossary_allowed_pair_not_a_conflict")
# MT-F4（业主 2026-11-02 第 2 条授权 #119）：**不用 `\\b`**。中文也算 `\\w`，
# `\\b` 在『炖锅Cioppino』这种写法处根本不成立，用它会整批漏检——这条是 MT-F3 第一版自己踩的。
PROPER_NAME_TOKEN = re.compile(r"(?<![A-Za-z])([A-Z][A-Za-z]{4,})(?![A-Za-z])")
ALLOWED_PAIR_FIELDS = ("cn_text", "en_text", "cn_token", "en_token")
PROPER_NAME_PARAMS = ("min_token_length", "shared_prefix_length", "max_levenshtein")


def glossary() -> dict:
    doc = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("glossary_not_object：术语表面不是对象")
    for field in doc["required_top_level_fields"]:
        if field not in doc:
            raise ValueError("glossary_missing_field：登记面缺 %s" % field)
    return doc


def term_table(doc: dict | None = None) -> dict:
    """固定措辞表：cn → 必须出现的英文形式。逐条必须带 source，否则不算登记（只是愿望）。"""
    doc = doc or glossary()
    out: dict[str, dict] = {}
    for entry in doc["terms"]:
        for field in doc["term_required_fields"]:
            if str(entry.get(field) or "").strip() == "":
                raise ValueError("glossary_entry_incomplete：%r 缺 %s" % (entry.get("cn"), field))
        cn = str(entry["cn"])
        if cn in out:
            raise ValueError("glossary_term_duplicate：%r 登记了两次（两行不同英文＝没人知道哪条作准）" % cn)
        boundary = list(entry.get("not_after") or [])
        if boundary and entry.get("match") != "before_number":
            raise ValueError("glossary_not_after_shape：%r 声明了 not_after，但它的 match=%r "
                             "不是按位置判的模式——那这条边界就不会被任何规则读到"
                             % (cn, entry.get("match")))
        if any(len(str(ch)) != 1 for ch in boundary):
            raise ValueError("glossary_not_after_shape：%r 的 not_after 必须是**单字**列表，"
                             "多字条目会被当成字符集合里的一个不存在的元素，静默失效" % cn)
        if CJK.search(entry["en"]):
            raise ValueError("glossary_english_contains_cjk：%r 的固定英文里还有汉字" % cn)
        out[cn] = entry
    return out


def currency_map(doc: dict | None = None) -> dict:
    doc = doc or glossary()
    return {str(item["cn"]): str(item["en"]) for item in doc["currency_map"]}


def month_names(doc: dict | None = None) -> dict:
    doc = doc or glossary()
    return {int(item["cn"]): str(item["en"]) for item in doc["month_names"]}


# --------------------------------------------------------------------------------------------
# 事实抽取。每个抽取器只认**自己登记过的形状**，认不出来就当没这条事实——
# 「宁可漏检也不瞎猜」和「不许把没登记的列当成散文」是同一条纪律。
# --------------------------------------------------------------------------------------------
NUMBER = re.compile(r"\d+(?:[.,]\d+)?(?:\s*[-–~至]\s*\d+(?:[.,]\d+)?)?")
YEAR = re.compile(r"(?:1[89]|20)\d{2}")
MONTH_DAY = re.compile(r"(\d{1,2})\s*月(?:(\d{1,2})\s*日)?")
URL = re.compile(r"(?:https?://)?(?:[A-Za-z0-9_-]+\.)+(?:com|cn|org|net|io|co|jp|hk|tw|gov|edu)"
                 r"(?:/[^\s，。;；)）\"']*)?")
CURRENCY_TOKENS = ("元", "人民币", "美元", "美金", "比索", "日元", "欧元", "英镑")


def numbers_in(text: str) -> list[str]:
    """数字串，但**先挖掉日期写法**。

    「2月为旱季」里的 2 归日期检查管（要 February 或 Month 2），不该再被数字检查要一遍——
    否则「February is the dry season」这种正确译文会被判漂移。两类检查各管各的事实，
    重叠就会造出假阳性，而假阳性最终会让业主把整条门当噪音关掉。
    """
    stripped = MONTH_DAY.sub(" ", str(text or ""))
    return [item.replace(" ", "") for item in NUMBER.findall(stripped)]


def years_in(text: str) -> list[str]:
    return [match.group(0) for match in YEAR.finditer(str(text or ""))]


def months_in(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2) or "") for m in MONTH_DAY.finditer(str(text or ""))]


def currencies_in(text: str) -> list[str]:
    """只认**金额表达式里的**币种：数字与币种词相邻（两侧各允许 4 字）才算。

    合同要防的是「110-180 元被折算成 $25」，不是散文里单独提了一种钱——那种句子没有可对照的
    数字，硬要求 ISO 码只会把尺子变成噪音机：实测第一版就因此误报 2 条
    （登记在 prose-glossary.json::measured_2026_11_01）。

    **长令牌先占位并把那几个字遮掉**：`美元` 里的 `元` 不是第二笔钱。第 1 版按
    CURRENCY_TOKENS 逐个全文扫，同一金额上的 元 会撞进 美元 内部 ⇒ 「10-15美元/人」
    既要写 USD 又要写 CNY。实测面（prose-glossary.json::currency_token_overlap_measured）：
    两地 legacy 835 条**零**命中这种重叠，MT-E0 取数面上正好 5 条 CA 价格行，且这 5 条
    遮掉长令牌后再找 元 就没有了 ⇒ 那 5 条是纯子串假阳性，不是真的两种钱。
    """
    body = str(text or "")
    masked = list(body)
    out: list[str] = []
    for token in sorted(CURRENCY_TOKENS, key=len, reverse=True):
        start = 0
        while True:
            position = body.find(token, start)
            if position < 0:
                break
            start = position + len(token)
            if any(masked[index] == "\u0000" for index in range(position, position + len(token))):
                continue          # 这几个字已经属于更长的币种词，不再当第二笔钱
            window = "".join(masked[max(0, position - 4): position + len(token) + 4])
            if NUMBER.search(window):
                out.append(token)
                for index in range(position, position + len(token)):
                    masked[index] = "\u0000"
                break
    return out


def term_applies(text: str, term: str, mode: str, not_after=()) -> bool:
    """术语的命中判定也有闭集：单字措辞（约）当子串会撞「预约／条约／盟约」，必须按语境算。

    这一条是量真实语料量出来的，不是设想出来的：第一版 substring 匹配在 PH 旧表上报了 4 条假阳性。
    新模式必须先登记（term_match_modes），否则这里抛——**闭集是登记面管着的**。

    `before_number` 还要过**词边界**：'约' 紧跟数字、但前一个字在登记的 `not_after` 里时，
    这个词是「预约」不是「大约」。那批字来自两地语料的实测分布（约 后面跟数字的 13 处全在句首；
    词内部的 约 前面只出现过 蜜／配／预／》／人／盟 这 6 个），不是随手列的偏旁表。
    """
    body = str(text or "")
    if mode == "substring":
        return term in body
    if mode == "before_number":
        for match in re.finditer(re.escape(term) + r"\s*\d", body):
            previous = body[match.start() - 1:match.start()]
            if previous and previous in set(not_after):
                continue
            return True
        return False
    raise ValueError("glossary_term_match_unknown：措辞 %r 的 match=%r 不在登记闭集 %s"
                     % (term, mode, ["substring", "before_number"]))


def levenshtein(a: str, b: str, cap: int) -> int:
    """带上限的编辑距离：长度差先超过上限就直接返回上限+1，不浪费整表计算。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    previous = list(range(len(b) + 1))
    for index, ca in enumerate(a, start=1):
        current = [index]
        for column, cb in enumerate(b, start=1):
            current.append(min(previous[column] + 1, current[column - 1] + 1,
                               previous[column - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _is_name_variant(first: str, second: str, spec: dict) -> bool:
    """两个拉丁专名算不算「近似冲突」：完全相同不算，前缀不同也不算（那是两个名字）。"""
    a, b = str(first), str(second)
    if a.lower() == b.lower():
        return False
    prefix = int(spec["shared_prefix_length"])
    if a[:prefix].lower() != b[:prefix].lower():
        return False
    return 1 <= levenshtein(a.lower(), b.lower(), int(spec["max_levenshtein"])) \
        <= int(spec["max_levenshtein"])


def proper_name_rule(doc: dict | None = None) -> dict:
    """读 `proper_name_variants` 那一格，参数与豁免只有这一份出处，且当场自证形状。

    三颗牙，都是为了让「配置驱动」不变成「配置写错了也没人知道」：
      · `token_shape` 必须逐字等于实现里编译好的那份正则——两边各写一遍迟早分叉；
      · 三个参数必须是正整数：0 或负数会让检查悄悄变成「全放过」或「全拦住」，
        而一条会静默失效的门比没有门更坏（业主会以为它在）；
      · 每条豁免**自己必须就是一对冲突**：登记一条本来不冲突的豁免＝死豁免，
        它会让下一个读者以为「这类已经处理过」，实际那条永远不会被拦。
    """
    doc = doc or glossary()
    spec = doc["proper_name_variants"]
    if str(spec.get("token_shape")) != PROPER_NAME_TOKEN.pattern:
        raise ValueError("glossary_proper_name_shape_unknown：登记面 token_shape=%r 与实现那份 %r 不同 "
                         "⇒ 两份正则，一条漏一条误" % (spec.get("token_shape"), PROPER_NAME_TOKEN.pattern))
    for name in PROPER_NAME_PARAMS:
        value = spec.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("glossary_proper_name_param_unregistered：%s=%r 不是正整数 ⇒ "
                             "这条检查会静默变成噪音机或空气" % (name, value))
    allowed: dict[tuple, dict] = {}
    for entry in spec.get("allowed_pairs") or []:
        missing = [field for field in ALLOWED_PAIR_FIELDS if str(entry.get(field) or "") == ""]
        if missing:
            raise ValueError("glossary_allowed_pair_incomplete：豁免条目缺 %s ⇒ 半条豁免等于没豁免，"
                             "还更容易被读成『这一类都放行了』" % "/".join(missing))
        if not _is_name_variant(entry["cn_token"], entry["en_token"], spec):
            raise ValueError("glossary_allowed_pair_not_a_conflict：%r↔%r 按本规则根本不算冲突 ⇒ "
                             "死豁免，删掉它或承认规则写错了" % (entry["cn_token"], entry["en_token"]))
        key = (entry["cn_text"], entry["en_text"],
               entry["cn_token"].lower(), entry["en_token"].lower())
        if key in allowed:
            raise ValueError("glossary_allowed_pair_duplicate：同一对原文的同一冲突登记了两次豁免")
        allowed[key] = entry
    return {"spec": spec, "allowed": allowed}


def proper_name_conflicts(cn: str, en: str, rule: dict) -> list:
    """同一语义对内部的中英拉丁专名冲突。只报形状，**不改中文也不改英文**。"""
    spec = rule["spec"]
    minimum = int(spec["min_token_length"])

    def tokens(text: str) -> list:
        out: list[str] = []
        for match in PROPER_NAME_TOKEN.finditer(str(text or "")):
            token = match.group(1)
            if len(token) >= minimum and token not in out:
                out.append(token)
        return out

    hits = []
    for first in tokens(cn):
        for second in tokens(en):
            if not _is_name_variant(first, second, spec):
                continue
            if (str(cn), str(en), first.lower(), second.lower()) in rule["allowed"]:
                continue          # 逐对精确豁免：四项全等才算，差一个字节都不算
            hits.append({"cn_token": first, "en_token": second,
                         "distance": levenshtein(first.lower(), second.lower(),
                                                 int(spec["max_levenshtein"]))})
    return hits


def urls_in(text: str) -> list[str]:
    return [m.group(0) for m in URL.finditer(str(text or ""))]


def url_host(text: str) -> str:
    """主机名（含端口前的部分）：路径可以因渲染而异，域名换了就是把读者带去别处。"""
    cleaned = re.sub(r"^https?://", "", str(text or ""))
    return cleaned.split("/")[0].lower()


def entity_face(dataset: dict) -> dict:
    """实体名唯一出处：tier1 显示名登记对（display_names.read_pairs），本模块不自建名字表。"""
    import display_names
    pairs, _conflicts = display_names.read_pairs(dataset)
    return {str(cn): str(info["english"]) for cn, info in pairs.items()}


def destination_face(dataset: dict) -> dict:
    """目的地名的出处是载荷自己的 destinations（[中文名, 英文名, …]）；不另抄一份城市表。"""
    out: dict[str, str] = {}
    for row in dataset.get("destinations") or []:
        if isinstance(row, dict):
            cn, en = str(row.get("0") or row.get("cn") or "").strip(), str(row.get("1") or "").strip()
        else:
            cn = str(row[0]).strip() if row else ""
            en = str(row[1]).strip() if len(row) > 1 else ""
        if cn and CJK.search(cn) and en and not CJK.search(en):
            out[cn] = en
    return out


# --------------------------------------------------------------------------------------------
# 对账
# --------------------------------------------------------------------------------------------
def _missing(expected: list, haystack: str, normalise=lambda v: v) -> list:
    text = normalise(haystack)
    return [item for item in expected if normalise(item) not in text]


def dataset_faces(dataset: dict | None) -> dict | None:
    """实体名与目的地名各读一次。

    逐条对账都去 `display_names.read_pairs` 一遍会把 819 条对账变成 819 次全表扫描——
    不是怕慢，是怕两次扫描之间数据变了却没人发现。一次取面、多次用面，面与结论同源。
    """
    if dataset is None:
        return None
    return {"entity": entity_face(dataset), "destination": destination_face(dataset)}


def reconcile_pair(cn: str, en: str, *, dataset: dict | None = None,
                   doc: dict | None = None, faces: dict | None = None) -> list[dict]:
    """一条 (中文原文, 英文译文) 的结构事实对账；返回 findings（空表＝没漂移）。

    数字：原文里每个数字串都必须在译文里出现（原样，不许换算/取整/区间改端点）。
    日期：年份逐位对齐；`N月` 必须变成同一月份的英文月名或同号数字，`N日` 必须留号。
    币种：原文出现 `元/美元/…` 时，译文必须用登记的币种码（元→CNY 这条是实测载荷里的写法），
          且金额数字仍要在——这防的是「顺手折算成当地货币」。
    URL：主机名必须一致；原文有链接而译文没有＝链接丢了。
    实体名／目的地：只查**登记面上有英文名**的那些；查不到的名字不猜，交给 MT-F 人工复核。
    专名形状：同一对内部中文格与英文格的拉丁专名近似却不相同 ⇒ 发码（MT-F4／#119）；
              只报形状不改任何一侧，豁免按具体 pair 逐条登记。
    """
    doc = doc or glossary()
    text_en = str(en or "")
    findings: list[dict] = []
    checks_enabled = set(doc["checks"])
    for check in CHECK_VOCABULARY:
        if check not in checks_enabled:
            raise ValueError("glossary_check_unregistered：实现要查 %s，登记面没开" % check)

    lost = _missing(numbers_in(cn), text_en)
    if lost:
        findings.append({"code": FINDING_CODES["number"],
                         "detail": "原文数字 %s 在译文里找不到（不许换算/取整/改区间端点）"
                                   % ",".join(sorted(set(lost))[:6])})

    years_lost = _missing(years_in(cn), text_en)
    if years_lost:
        findings.append({"code": FINDING_CODES["date"],
                         "detail": "年份 %s 没出现在译文里" % ",".join(sorted(set(years_lost)))})
    names = month_names(doc)
    for number, day in months_in(cn):
        month = int(number)
        token = str(names.get(month, ""))
        if token and token.lower() not in text_en.lower() and number not in text_en:
            findings.append({"code": FINDING_CODES["date"],
                             "detail": "%s月 既没写成 %s 也没留下数字 %s" % (number, token, number)})
        if day and day not in text_en:
            findings.append({"code": FINDING_CODES["date"],
                             "detail": "%s日 的日号 %s 没进译文" % (number, day)})

    currencies = currencies_in(cn)
    if currencies:
        mapping = currency_map(doc)
        required = [mapping[token] for token in currencies if token in mapping]
        absent = [code for code in required if code not in text_en]
        if absent:
            findings.append({"code": FINDING_CODES["currency"],
                             "detail": "原文币种 %s ⇒ 必须写登记的 %s（译文里没有＝折算或漏写）"
                                       % ("/".join(currencies), "/".join(absent))})

    for link in urls_in(cn):
        host = url_host(link)
        if host not in text_en.lower():
            findings.append({"code": FINDING_CODES["url"],
                             "detail": "链接主机 %s 没进译文（原文链接 %s）" % (host, link[:60])})

    faces = faces if faces is not None else dataset_faces(dataset)
    if faces is not None:
        for cn_name, en_name in sorted(faces["entity"].items()):
            if cn_name and cn_name in cn and en_name not in text_en:
                findings.append({"code": FINDING_CODES["entity"],
                                 "detail": "登记的实体名 %r 在该格里，译文却没出现其登记英文名 %r"
                                           % (cn_name, en_name)})
        for cn_name, en_name in sorted(faces["destination"].items()):
            if cn_name and cn_name in cn and en_name not in text_en:
                findings.append({"code": FINDING_CODES["destination"],
                                 "detail": "目的地 %r 出现在原文里，译文未保留登记名 %r"
                                           % (cn_name, en_name)})
    for spec in doc["unit_system_switches"]:
        if str(spec["cn"]) in cn:
            alien = [token for token in spec["alien"] if token.lower() in text_en.lower()]
            if alien:
                findings.append({"code": FINDING_CODES["unit_system"],
                                 "detail": "原文用 %r（公制），译文出现 %s＝换了制式（登记的公制写法是 %r）"
                                           % (spec["cn"], "/".join(alien), spec["metric_en"])})

    for term, entry in sorted(term_table(doc).items()):
        if term_applies(cn, term, entry["match"], entry.get("not_after") or ()) \
                and entry["en"] not in text_en:
            findings.append({"code": FINDING_CODES["term"],
                             "detail": "固定措辞 %r 在该格里，译文没写登记的 %r（%s）"
                                       % (term, entry["en"], entry["category"])})

    if "proper_name_variant" in checks_enabled:
        # MT-F4（#119）：只查同一语义对**内部**的中英专名形状对不上。
        # 它证明的是「两面对不上」，不是「谁作准」——所以细节里不许替业主下结论。
        rule = proper_name_rule(doc)
        for hit in proper_name_conflicts(cn, text_en, rule):
            findings.append({"code": FINDING_CODES["proper_name_variant"],
                             "detail": "同一语义对里中文格写 %r、英文格写 %r（编辑距离 %d）⇒ 中英两面对不上；"
                                       "谁作准要按来源裁，若错在中文原格，只改英文不算结案；"
                                       "豁免只能按这一个具体 pair 逐条登记，不许立宽规则"
                                       % (hit["cn_token"], hit["en_token"], hit["distance"])})
    return findings


def checker(dataset: dict | None = None, doc: dict | None = None):
    """一次性把登记面与实体/目的地面读好，返回一个逐条对账的闭包。

    validate_table 会对每条 entry 调一次：不缓存就是「每条都重读一遍 JSON、重扫一遍载荷」，
    500 条表就是 500 次同样的磁盘解析——贵不是重点，**重点是两次读之间文件可能变了**，
    那样同一张表的两条 entry 就各自按不同版本的登记面判过。一次读、多次用，才是同一把尺子。
    """
    doc = doc or glossary()
    faces = dataset_faces(dataset)
    return lambda cn, en: reconcile_pair(cn, en, dataset=dataset, doc=doc, faces=faces)


def measure_pairs(pairs: list[tuple[str, str]], *, dataset: dict | None = None,
                  doc: dict | None = None) -> dict:
    """成批对账 + 逐码计数。`clean` 是分母减掉有条目的对数，不是「抽了几条看看」。"""
    doc = doc or glossary()
    faces = dataset_faces(dataset)
    counts: dict[str, int] = {}
    offenders: dict[str, list] = {}
    flagged = 0
    for cn, en in pairs:
        items = reconcile_pair(cn, en, dataset=dataset, doc=doc, faces=faces)
        if items:
            flagged += 1
        for item in items:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
            offenders.setdefault(item["code"], [])
            if len(offenders[item["code"]]) < 10:
                offenders[item["code"]].append({"cn": cn[:70], "en": en[:70],
                                                "detail": item["detail"][:160]})
    return {"pairs": len(pairs), "flagged_pairs": flagged, "clean_pairs": len(pairs) - flagged,
            "code_counts": dict(sorted(counts.items())), "samples_by_code": offenders,
            "denominator_note": "flagged_pairs 按**对**计，一条对可以同时撞多个码；"
                                "code_counts 按码计，两个数不可互推。"}


def legacy_candidate_pairs(dataset: dict) -> list:
    """legacy 候选对：旧表里「中文键 + 非空且键含汉字」的那批，按键排序。

    选择口径只有这一份——`--from-legacy-map` 与 .temp 的实测工具都调它。各写一份筛选就会
    出现两个分母（本项目反复为此返工）。排序是为了让逐码计数可复现，不靠 dict 插入顺序。
    """
    return [(cn, str(en)) for cn, en in sorted((dataset.get("en_text_replacements") or {}).items())
            if isinstance(en, str) and en.strip() and CJK.search(str(cn))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prose no-drift reconciliation (MT-D2 step 6)")
    parser.add_argument("--dataset", default="", help="run dataset.json：读实体名与目的地名")
    parser.add_argument("--table", default="", help="翻译表（MT-E 产物）：逐条 entry 对账")
    parser.add_argument("--from-legacy-map", action="store_true",
                        help="量 run 载荷里 legacy 候选英文（旧表 cn→en 对）的漂移——"
                             "这不是验收旧表，是给「旧英文能不能直接当本轮来源」一条实测答案")
    parser.add_argument("--report", default="", help="把对账结果写到这个 JSON 文件")
    args = parser.parse_args()
    if not args.dataset:
        parser.error("--dataset 必须给：实体名与目的地名只有载荷里那一份")
    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    doc = glossary()
    if args.table:
        table = json.loads(Path(args.table).read_text(encoding="utf-8"))
        entries = table.get("entries") if isinstance(table, dict) else None
        if not isinstance(entries, dict):
            raise SystemExit("--table 里没有 entries 对象（MT-C 之后表必须逐条记录）")
        pairs = [(str((item or {}).get("cn") or ""), str((item or {}).get("en") or ""))
                 for item in entries.values()]
        source = "translation_table"
    elif args.from_legacy_map:
        pairs = legacy_candidate_pairs(dataset)
        source = "legacy_en_text_replacements"
    else:
        parser.error("--table 或 --from-legacy-map 至少给一个")
    report = measure_pairs(pairs, dataset=dataset, doc=doc)
    report.update({"source": source, "dataset": str(dataset_path),
                   "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest().upper(),
                   "glossary_sha256": hashlib.sha256(GLOSSARY_PATH.read_bytes()).hexdigest().upper(),
                   "checks": list(doc["checks"])})
    if args.report:
        Path(args.report).write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n")
                                      .encode("utf-8"))
    print(json.dumps({key: report[key] for key in
                      ("source", "pairs", "flagged_pairs", "clean_pairs", "code_counts",
                       "denominator_note")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
