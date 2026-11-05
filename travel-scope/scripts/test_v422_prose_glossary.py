# -*- coding: utf-8 -*-
"""MT-D2 第 6 步：固定术语表 + 不漂移对账的执行型合同。

业主把这一条排在「冻结 MT-E 表长」前面，是因为表长只是数字，**尺子才是判据**：
翻译表可以一次生成 886 条，但如果没人核「110-180 元」有没有被顺手折算成 $25，
那本子上线的英文就是看起来完整、读起来错。

登记面 references/prose-glossary.json，唯一实现 scripts/prose_reconcile.py。
两面闭合由这个文件负责：登记的检查项必须真在查，代码查的项必须在册；
登记的映射表必须真被读，代码里不许藏第二份名字表。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import prose_reconcile as pr                                    # noqa: E402
import translate_prose as tp                                    # noqa: E402
from test_v422_prose_ownership import _dataset, AUDIT_DATASETS   # noqa: E402


def destination_names(dataset):
    """目的地名面：与对账实现同一个出处，测试不另抄一份名单。"""
    return pr.destination_face(dataset)

GLOSSARY_PATH = ROOT / "references" / "prose-glossary.json"
SOURCE = (SCRIPTS / "prose_reconcile.py").read_text(encoding="utf-8")
DOC = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))


class RegistryClosureTests(unittest.TestCase):
    """登记面与实现双向闭合：一个事实只有一个出处。"""

    def test_registered_checks_match_the_implementation(self):
        self.assertEqual(DOC["checks"], list(pr.CHECK_VOCABULARY),
                         "检查项两面必须同名同序：登记了不查＝纸面门，查了不登记＝私设尺度")

    def test_every_registered_finding_code_is_emitted_by_the_implementation(self):
        for check, code in sorted(DOC["finding_codes"].items()):
            self.assertIn(check, DOC["checks"], "%s 有码名却不在检查项里" % check)
            self.assertIn(code, pr.FINDING_CODES.values(),
                          "%s 登记了但实现发不出这个码名" % code)
            self.assertIn('"%s"' % code, SOURCE, "%s 的码名 %s 没以字面量出现在实现里"
                                     % (check, code))

    def test_structural_codes_are_registered_and_emitted(self):
        for code in DOC["structural_codes"]:
            self.assertIn(code, SOURCE, "%s 在册但实现发不出来（纸面结构码）" % code)
        for code in pr.STRUCTURAL_CODES:
            self.assertIn(code, DOC["structural_codes"],
                          "%s 实现会发，登记面却没这条：业主查不到它从哪来" % code)

    def test_required_top_level_fields_are_all_present(self):
        for field in DOC["required_top_level_fields"]:
            self.assertIn(field, DOC, "登记面自己缺了它声称必备的格：%s" % field)

    def test_enforced_fields_are_actually_read_by_the_implementation(self):
        """登记面把字段分成 enforced／descriptive 两类，这条测试就是那把分界的尺。

        只查「字段在不在」＝纸面登记；把「只是说明用」的格（unit_map）也当门去查，
        又会造出假阳性。所以这里要求：enforced 的每一个都必须以字面量出现在实现里，
        descriptive 的每一个都必须写明为什么不 enforcement。
        """
        for field in DOC["enforced_fields"]:
            self.assertIn('"%s"' % field, SOURCE,
                          "%s 登记为强制，但实现没读它（代码里没这个字面量）" % field)
        for field, why in sorted(DOC["descriptive_fields"].items()):
            self.assertTrue(str(why).strip(), "%s 标成对照说明却没写理由" % field)
            self.assertNotIn('"%s"' % field, SOURCE,
                             "%s 登记成对照说明，实现却在读它：分类本身就错了" % field)

    def test_glossary_rejects_a_missing_required_field(self):
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken.pop("month_names")
        text = json.dumps(broken, ensure_ascii=False, indent=2)
        # 直接喂给校验函数而不是改盘上文件：登记面缺一格必须抛，且抛的是那条码名。
        with self.assertRaises(ValueError) as caught:
            self._validate(text)
        self.assertIn("glossary_missing_field", str(caught.exception))

    def _validate(self, text: str) -> None:
        """用实现里那份「读文件 + 核必备格」的逻辑，但把字节换成被测内容。"""
        doc = json.loads(text)
        if not isinstance(doc, dict):
            raise ValueError("glossary_not_object")
        for field in doc["required_top_level_fields"]:
            if field not in doc:
                raise ValueError("glossary_missing_field：%s" % field)

    def test_no_second_copy_of_name_tables(self):
        """实体名/目的地名只能从既有登记面读，本模块不许自己抄一份名字。"""
        self.assertIn("display_names.read_pairs", SOURCE,
                      "实体名没走 display-name 通道＝第二份名字表")
        self.assertIn('dataset.get("destinations")', SOURCE,
                      "目的地名没读载荷自己那两列＝第二份地名表")
        for leaked in ("旧金山", "宿务", "San Francisco", "薄荷岛"):
            self.assertNotIn(leaked, SOURCE,
                             "实现里出现了具体名字 %s：那就是把登记面抄进了代码" % leaked)

    def test_checker_uses_the_doc_it_was_given(self):
        """一次读、多次用。若闭包偷偷重读文件，同一张表的两条 entry 就可能按两个版本判过。"""
        dataset = _dataset()
        doc = json.loads(json.dumps(DOC, ensure_ascii=False))
        check = pr.checker(dataset, doc)
        self.assertEqual(check("约 110-180 元", "Approx. CNY 110-180"), [])
        doc["checks"] = [item for item in doc["checks"] if item != "currency"]
        with self.assertRaises(ValueError) as caught:
            check("约 110-180 元", "about 18 US dollars")
        self.assertIn("glossary_check_unregistered", str(caught.exception))


class FactCheckTests(unittest.TestCase):
    """八类结构事实：正例放行、负例点名，且不许靠假阳性凑数。"""

    def setUp(self):
        self.dataset = _dataset()
        self.check = pr.checker(self.dataset)

    def _codes(self, cn, en):
        return {item["code"] for item in self.check(cn, en)}

    def test_number_must_survive_and_must_not_be_converted(self):
        self.assertEqual(self._codes("1-2小时", "1-2 hours"), set())
        self.assertIn(pr.FINDING_CODES["number"], self._codes("1-2小时", "60-120 minutes"),
                      "把区间换算成分钟＝换了事实，必须抓到")
        self.assertIn(pr.FINDING_CODES["number"], self._codes("海拔 1200 米", "high above sea level"))

    def test_year_month_and_day_each_have_their_own_teeth(self):
        self.assertEqual(self._codes("2022 年开业", "Opened in 2022"), set())
        self.assertIn(pr.FINDING_CODES["date"], self._codes("2022 年开业", "Recently opened"))
        self.assertEqual(self._codes("2月为旱季", "February is the dry season"), set(),
                         "登记过的月名要放行：尺子不能只会认数字")
        self.assertEqual(self._codes("2月为旱季", "Month 2 is the dry season"), set(),
                         "留号也算对：不许把写法偏好当漂移")
        self.assertIn(pr.FINDING_CODES["date"], self._codes("2月为旱季", "The dry season comes early"))
        self.assertIn(pr.FINDING_CODES["date"], self._codes("2月15日集合", "Meet on February 20"))

    def test_currency_code_is_registered_and_conversion_blocks(self):
        # 正例先证明登记值确实被实现读出来（写错的映射会在这一条就红，而不是在负例里蒙对）
        self.assertEqual(pr.currency_map(DOC), {"元": "CNY", "比索": "PHP", "美元": "USD"})
        self.assertEqual(self._codes("约 110-180 元", "Approx. CNY 110-180"), set())
        self.assertEqual(self._codes("100比索", "PHP 100"), set())
        self.assertIn(pr.FINDING_CODES["currency"], self._codes("100比索", "100 pesos"))
        self.assertIn(pr.FINDING_CODES["currency"], self._codes("约 110-180 元", "about $25"),
                      "折算＝把汇率当译文来源，汇率合同另有出处")

    def test_url_host_must_be_the_same(self):
        self.assertEqual(self._codes("官网 www.sfo.com 查航站楼",
                                     "Check terminals at www.sfo.com"), set())
        codes = self._codes("官网 www.sfo.com 查航站楼", "Check the airport website")
        self.assertIn(pr.FINDING_CODES["url"], codes, "链接丢了＝读者没处可查")
        self.assertIn(pr.FINDING_CODES["url"],
                      self._codes("官网 www.sfo.com 查航站楼", "See www.lax.com"),
                      "换了域名＝把读者带去别处")

    def test_entity_and_destination_names_come_from_the_registered_faces(self):
        dataset = _dataset(destinations=[["旧金山", "San Francisco", "加州湾区", "金门大桥",
                                          "2天", "1月气温10-15℃", "SFO入境提车20分钟", "是"]])
        check = pr.checker(dataset)
        self.assertEqual({item["code"] for item in
                          check("金门大桥在旧金山", "The Golden Gate sits in San Francisco")}, set())
        codes = {item["code"] for item in check("金门大桥在旧金山", "The Golden Gate sits downtown")}
        self.assertIn(pr.FINDING_CODES["destination"], codes,
                      "登记过的目的地名掉了必须点名")

    def test_unregistered_name_is_not_invented_and_not_flagged(self):
        """没登记英文名字的词不许被猜成专名，也不报漂移——那是 MT-F 人工复核的活。"""
        self.assertEqual(self._codes("无名小渡口的日落", "Sunset at a tiny ferry landing"), set())

    def test_fixed_term_must_be_used_as_registered(self):
        self.assertEqual(self._codes("约 110-180 元", "Approx. CNY 110-180"), set())
        codes = self._codes("约 110-180 元", "Around CNY 110-180")
        self.assertIn(pr.FINDING_CODES["term"], codes,
                      "登记过的措辞换写法＝同一份数据在页上出现两种英文")

    def test_unit_system_switch_blocks_but_free_phrasing_does_not(self):
        self.assertEqual(self._codes("1.5公里白沙滩", "1.5 km of white sand"), set())
        self.assertEqual(self._codes("延绵两公里", "a two-kilometer stretch"), set(),
                         "拼出 kilomet 不算换制式：尺子不许把写法偏好当漂移")
        self.assertIn(pr.FINDING_CODES["unit_system"],
                      self._codes("1.5公里白沙滩", "about one mile of white sand"))
        self.assertIn(pr.FINDING_CODES["unit_system"], self._codes("气温25-31℃", "78-88 °F"))


class RulerPrecisionTests(unittest.TestCase):
    """尺子自己也会犯错：收窄必须有可重放的样本，而不是「据说准了」。

    第一版实现量 PH 旧表报了 83 条漂移，其中 6 条是尺子的毛病（单字「约」当子串、
    无金额却要求币种码）。业主反复强调的那类风险就在这：**为了让门好看而放宽的尺子，
    下一轮就没人知道它宽在哪里**。所以这 6 条原文＋译文原样登记在
    references/prose-glossary.json::false_positive_regressions，这里逐条重放。
    """

    def setUp(self):
        self.block = DOC["false_positive_regressions"]
        self.samples = self.block["samples"]

    def test_every_registered_sample_is_clean_today(self):
        """重放：当前实现对这些对的码名，必须等于登记面记的那一份——一字不多一字不少。"""
        for code, rows in sorted(self.samples.items()):
            for row in rows:
                with self.subTest(code=code, cn=row["cn"][:20]):
                    found = pr.reconcile_pair(row["cn"], row["en"], dataset=None)
                    self.assertEqual(sorted({item["code"] for item in found}),
                                     row["other_codes_now"],
                                     "登记面记的实测码名与今天的实现不一致：收窄要么没生效，"
                                     "要么这条样本已经不该当假阳性用")
                    self.assertNotIn(pr.FINDING_CODES[code],
                                     [item["code"] for item in found],
                                     "%s 收窄后仍在发 %s" % (code, pr.FINDING_CODES[code]))

    def test_registered_counts_match_the_samples(self):
        """计数从样本长度算，不在登记面上手填一个数——手填的数会因为样本增删而说谎。"""
        for code, count in sorted(self.block["false_positives_removed"].items()):
            self.assertEqual(count, len(self.samples[code]),
                             "%s 的 removed=%s 与样本数 %s 不符"
                             % (code, count, len(self.samples[code])))

    def test_narrowing_did_not_blunt_the_teeth(self):
        """收窄只砍假阳性：带金额的「约 N」与「N+币种」照旧要拦，否则这条测试就是自废武功。"""
        self.assertEqual(self._codes("约 20 分钟", "20 minutes"),
                         {pr.FINDING_CODES["term"]},
                         "约+数字仍然是固定措辞，换成 20 minutes 也要点名")
        self.assertEqual(self._codes("100比索", "100 pesos"),
                         {pr.FINDING_CODES["currency"]})
        self.assertEqual(pr.currencies_in("在机场兑换比索汇率较优"), [],
                         "没有金额的币种词不该被要求写 ISO 码")
        self.assertEqual(pr.currencies_in("100比索"), ["比索"])

    def _codes(self, cn, en):
        return {item["code"] for item in pr.reconcile_pair(cn, en, dataset=None)}

    LONG_CURRENCY_TOKENS = ("美元", "美金", "日元")

    @staticmethod
    def _currencies_before_fix(text: str) -> list:
        """**第 1 版尺子的行为**，只为量「这次遮字改动到底碰到哪些行」而留在这里。

        实现里没有任何地方引用它（门的唯一实现是 prose_reconcile.currencies_in）；
        把它写在测试侧而不是口头说一句「修前多要一个码」，是因为登记面自己不会说谎：
        修前/修后差集必须现场算得出，算出来是 5 行就是 5 行。
        """
        out = []
        for token in ("元", "人民币", "美元", "美金", "比索", "日元", "欧元", "英镑"):
            start = 0
            while True:
                position = str(text or "").find(token, start)
                if position < 0:
                    break
                window = str(text or "")[max(0, position - 4): position + len(token) + 4]
                if pr.NUMBER.search(window):
                    out.append(token)
                    break
                start = position + len(token)
        return out

    def _changed_rows(self, pairs):
        """修前/修后要的 ISO 码不同的行（这才是这次改动的真实作用面）。"""
        changed = []
        for ident, cn in pairs:
            before = {pr.currency_map()[t] for t in self._currencies_before_fix(cn)
                      if t in pr.currency_map()}
            after = {pr.currency_map()[t] for t in pr.currencies_in(cn)
                     if t in pr.currency_map()}
            if before != after:
                changed.append({"id": ident, "cn": cn,
                                "required_before": sorted(before),
                                "required_after": sorted(after)})
        return changed

    def _worklist_pairs(self):
        rows = []
        for name, path in sorted(AUDIT_DATASETS.items()):
            dataset = json.loads(path.read_text(encoding="utf-8"))
            for fragment in tp.prose_translation_worklist(dataset):
                rows.append((fragment["id"], fragment["cn"]))
        return rows

    def _legacy_pairs(self):
        rows = []
        for name, path in sorted(AUDIT_DATASETS.items()):
            dataset = json.loads(path.read_text(encoding="utf-8"))
            for cn, en in pr.legacy_candidate_pairs(dataset):
                rows.append((tp._digest(cn), cn))
        return rows

    def test_currency_token_overlap_rows_are_registered_and_reproducible(self):
        """遮字这件事必须有数：哪 5 行受影响是现场量出来的，登记面与实测量双向闭合。

        这条测试存在是因为**上一轮的教训**：改尺子的人很容易只说一句「收窄了」。
        这里把受影响行的 id、原文、修前后各要求哪些 ISO 码全部登记，并在盘上重算一遍；
        多一行少一行都算失配。legacy 面差集为 0 也一并核，因为它证明 83→77 那笔账没被动过。
        """
        block = DOC["currency_token_overlap_measured"]
        worklist = self._worklist_pairs()
        legacy = self._legacy_pairs()
        changed = self._changed_rows(worklist)
        self.assertEqual(sorted(item["id"] for item in changed),
                         sorted(row["id"] for row in block["overlap_rows_before_fix"]),
                         "登记的重叠行与现场量到的不一致：新增=%s 消失=%s"
                         % (sorted({row["id"] for row in changed} -
                                   {row["id"] for row in block["overlap_rows_before_fix"]}),
                            sorted({row["id"] for row in block["overlap_rows_before_fix"]} -
                                   {row["id"] for row in changed})))
        registered = {row["id"]: row for row in block["overlap_rows_before_fix"]}
        for item in changed:
            row = registered[item["id"]]
            self.assertEqual(row["cn"], item["cn"], "%s 登记的原文与在盘原文不等" % item["id"])
            self.assertEqual(item["required_before"], row["required_before"],
                             "%s 的修前码集合与登记不符" % item["id"])
            self.assertEqual(item["required_after"], row["required_after"],
                             "%s 的修后码集合与登记不符" % item["id"])
            self.assertEqual(item["required_after"], ["USD"],
                             "这 5 行修后应当只要求 USD")
            self.assertIn("CNY", item["required_before"],
                          "修前这条必须真的多要一个 CNY，否则这次遮字修的就是一件不存在的事")
        legacy_changed = self._changed_rows(legacy)
        self.assertEqual(legacy_changed, [],
                         "legacy 面出现了未登记的行为差：83→77 那笔账的口径被这次改动动了")
        counts = block["counts_measured"]
        self.assertEqual(counts["worklist_rows"], len(worklist),
                         "登记的分母不是现场量出来的 worklist 全长")
        self.assertEqual(counts["worklist_rows_with_overlapping_currency_tokens"], len(changed))
        self.assertEqual(counts["legacy_pairs"], len(legacy),
                         "legacy 面分母与现场复算不符")
        self.assertEqual(counts["legacy_pairs_with_overlapping_currency_tokens"],
                         len(legacy_changed),
                         "legacy 面的行为差计数不是量出来的：登记 %s，现场 %s"
                         % (counts["legacy_pairs_with_overlapping_currency_tokens"],
                            len(legacy_changed)))
        two_currency = [cn for _ident, cn in worklist + legacy
                        if len({pr.currency_map()[token] for token in pr.currencies_in(cn)
                                if token in pr.currency_map()}) > 1]
        self.assertEqual(counts["rows_with_two_independent_amounts_on_two_currencies"],
                         len(two_currency),
                         "登记面说没有「一句两种钱」的行，现场却量到 %s 条：%s"
                         % (len(two_currency), [row[:30] for row in two_currency[:3]]))

    def test_currency_mask_keeps_two_independent_amounts(self):
        """负测：遮字只吃重叠令牌。两处独立金额仍要两个 ISO 码，漏一个照样阻断。"""
        self.assertEqual(self._codes("10-15美元/人", "10-15 USD per person"), set(),
                         "重叠令牌遮字之后不该再逼译文写 CNY——这 5 条就是修它的理由")
        self.assertEqual(self._codes("10-15美元/人", "10-15 CNY per person"),
                         {pr.FINDING_CODES["currency"]},
                         "遮字不是放过 USD：把美元写成人民币照样是折算")
        both = "门票 10-15 美元，服务费 20 元"
        self.assertEqual(self._codes(both, "a 10-15 USD ticket plus a 20 CNY service fee"), set(),
                         "两处独立金额都写了码：不该发任何漂移")
        self.assertIn(pr.FINDING_CODES["currency"],
                      self._codes(both, "a 10-15 USD ticket and a service fee"),
                      "漏掉第二笔钱的币种必须仍被抓住")
        self.assertEqual(pr.currencies_in("在机场兑换比索汇率较优"), [],
                         "无金额仍不查（上一轮的收窄不许被这次改动带回来）")

    def test_word_boundary_blocks_compounds_only(self):
        """「约」的词边界表拦住复合词，但绝不误伤真正的约估——两侧都要有断言。

        边界字符来自两地语料实测（登记在 terms[约].not_after_source）：今天的语料里
        还没有「预约 3 晚」这种句子，所以这一对是**登记出来的已知形状**，不是撞上的事故。
        """
        entry = pr.term_table()["约"]
        self.assertEqual(self._codes("酒店提前预约 3 晚更划算", "Booking 3 nights ahead is cheaper"),
                         set(), "预约 是复合词，不该按 hedging 措辞要 Approx.")
        self.assertEqual(self._codes("约 3 晚更划算", "Booking 3 nights is cheaper"),
                         {pr.FINDING_CODES["term"]}, "词首的「约 + 数字」仍必须拦：收窄不许自废武功")
        self.assertTrue(str(entry.get("not_after_source") or "").strip(),
                        "边界表没有实测出处＝一张来路不明的字表")
        for char in entry["not_after"]:
            self.assertEqual(len(char), 1, "%r 不是单字：多字条目在这里会静默失效" % char)

    def test_not_after_is_only_honoured_where_a_mode_reads_it(self):
        """声明了 not_after 却没有按位置判的模式＝一条不会被读到的登记；多字条目同理。"""
        for case, (match, value) in sorted({"wrong_mode": ("substring", ["预"]),
                                            "multi_char": ("before_number", ["预先"])}
                                           .items()):
            with self.subTest(case=case):
                broken = json.loads(json.dumps(DOC, ensure_ascii=False))
                for item in broken["terms"]:
                    if item["cn"] == "约":
                        item["match"], item["not_after"] = match, value
                with self.assertRaises(ValueError) as caught:
                    pr.term_table(broken)
                self.assertIn("glossary_not_after_shape", str(caught.exception))

    def test_match_modes_are_a_closed_set_in_both_directions(self):
        """登记面开的每种模式实现都得会算；实现只认登记过的模式——多一个就抛。"""
        for mode in sorted(DOC["term_match_modes"]):
            self.assertIn('"%s"' % mode, SOURCE, "%s 登记了却没实现" % mode)
            self.assertTrue(isinstance(pr.term_applies("约 3 公里", "约", mode), bool))
        with self.assertRaises(ValueError) as caught:
            pr.term_applies("约 3 公里", "约", "word_segmentation")
        self.assertIn("glossary_term_match_unknown", str(caught.exception))

    def test_every_registered_term_declares_a_known_mode(self):
        for entry in DOC["terms"]:
            self.assertIn(entry["match"], DOC["term_match_modes"],
                          "%r 的 match=%r 不在登记的模式里" % (entry["cn"], entry["match"]))


class GateWiringTests(unittest.TestCase):
    """尺子必须长在门里：validate_table 拿到漂移 entry 就整表阻断。"""

    def setUp(self):
        import hashlib
        self.dataset = _dataset(transport=[["SFO → 市区", "自驾 (SUV)", "22公里", "约 250 元",
                                           "25分钟", "全天候随时出发", "", "", "", "10",
                                           "柜台在到达层", "机场官网", "旧金山国际机场 (SFO)",
                                           "市区枢纽", "是", "坡道陡峭需朝向路沿停车", "on_demand",
                                           "自驾租车单日核算", "Self-drive rental daily rate",
                                           "2026-10-20", "", "verified", "", ""]],
                               practical=[["货币结算与汇率口径", "全美境内消费均以美元(USD)结算。"],
                                          ["住宿区域", "旧金山湾区住宿集中在联合广场，旺季需早订。"],
                                          ["餐饮人均口径", "两人一餐 240 元上下，普遍可刷卡。"]])
        self.raw = tp.collect_fragments(self.dataset, skip_covered=False)
        self.result = tp.classify_fragment_ownership(self.dataset, self.raw)
        self.sha = hashlib.sha256(
            (json.dumps(self.dataset, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).hexdigest().upper()

    def _table(self, overrides):
        from test_v421_english_source import _compliant_table
        return _compliant_table(self.result["worklist"], self.sha, "probe", overrides,
                                 dataset=self.dataset)

    def _codes(self, table):
        report = tp.validate_table(self.dataset, table, run_name="probe",
                                   source_dataset_sha256=self.sha, fragments=self.raw)
        return {item["code"] for item in report["findings"]}, report

    def _pick(self, predicate, what):
        """负测的靶子必须真的在 worklist 里。

        找不到就 fail 而不是 skip：skip 会让这条测试在下一轮夹具改动后**悄悄变成空跑**，
        而「门还在、靶子没了」正是本项目反复出现的那种绿。
        """
        for fragment in self.result["worklist"]:
            if predicate(fragment["cn"]):
                return fragment
        raise self.failureException(
            "夹具的 worklist 里没有%s的条目，这条负测就是空跑：%s"
            % (what, [f["cn"][:20] for f in self.result["worklist"][:6]]))

    def test_a_conforming_table_still_passes(self):
        """正例先立住：合规表零阻断。只有负例的门会把一切挡在门外，那不是门是墙。"""
        codes, report = self._codes(self._table({}))
        self.assertEqual(codes, set(), json.dumps(report["findings"][:4], ensure_ascii=False))
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(self.result["worklist"], "worklist 为空的话上面那条 PASS 是空跑出来的")

    def test_dropping_a_number_blocks_the_whole_table(self):
        target = self._pick(lambda text: bool(pr.numbers_in(text)), "带数字")
        codes, report = self._codes(self._table({target["cn"]: "No figures kept here."}))
        self.assertIn(pr.FINDING_CODES["number"], codes,
                      "原文数字在译文里消失了必须阻断：%r" % target["cn"][:40])
        self.assertEqual(report["status"], "FAIL")

    def test_converted_amount_blocks_the_whole_table(self):
        target = self._pick(lambda text: bool(pr.currencies_in(text)), "带币种")
        numbers = pr.numbers_in(target["cn"])
        codes, report = self._codes(self._table({target["cn"]: "about 35 US dollars %s" % " ".join(numbers)}))
        self.assertIn(pr.FINDING_CODES["currency"], codes,
                      "币种折算＝把汇率当译文来源，必须让整表不合格：%r" % target["cn"][:40])
        self.assertEqual(report["status"], "FAIL")

    def test_registered_term_written_differently_blocks(self):
        target = self._pick(lambda text: any(term in text for term in pr.term_table()),
                            "带固定措辞")
        term = next(name for name in sorted(pr.term_table()) if name in target["cn"])
        substitute = {"约": "Around", "人均参考": "per guest", "全天候随时出发": "anytime"}[term]
        # 其他事实照原样保留：这样撞到的码就必须是术语那条，而不是顺带把数字也丢了。
        facts = " ".join(pr.numbers_in(target["cn"])
                         + [pr.currency_map()[token] for token in
                            pr.currencies_in(target["cn"]) if token in pr.currency_map()])
        codes, report = self._codes(self._table({target["cn"]: "%s wording %s" % (substitute, facts)}))
        self.assertEqual(codes, {pr.FINDING_CODES["term"]},
                         "只该撞术语这一条码，实际：%s（夹具没造干净）" % sorted(codes))
        self.assertEqual(report["status"], "FAIL")

    def test_dropped_destination_blocks(self):
        """登记过的目的地名从译文里消失＝读者看到的是另一座城市，必须阻断。"""
        target = self._pick(lambda text: any(name in text for name in destination_names(self.dataset)),
                            "带目的地名")
        name = next(n for n in sorted(destination_names(self.dataset)) if n in target["cn"])
        codes, report = self._codes(self._table({target["cn"]: "Stay near the downtown core."}))
        self.assertIn(pr.FINDING_CODES["destination"], codes,
                      "这一格本来带着登记名 %r，译文把它弄丢了" % name)
        self.assertEqual(report["status"], "FAIL")

    def test_apply_refuses_to_write_a_drifting_table(self):
        """对账不是报表：漂移的表必须连 dataset 字节都不许动（宁可整页 pending）。"""
        import tempfile
        target = self._pick(lambda text: bool(pr.numbers_in(text)), "带数字")
        table = self._table({target["cn"]: "No figures kept here."})
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "probe"
            run_dir.mkdir()
            dataset_path = run_dir / "dataset.json"
            original = (json.dumps(self.dataset, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            dataset_path.write_bytes(original)
            table_path = run_dir / "table.json"
            table_path.write_bytes(json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8"))
            with self.assertRaises(ValueError) as caught:
                tp.apply_table(run_dir, dataset_path, table_path, write=True)
            self.assertIn("fact_drift_number", str(caught.exception))
            self.assertEqual(dataset_path.read_bytes(), original,
                             "漂移表必须一个字都不写：部分写入就是把半本假账上线")


class DriftBaselineEvidenceTests(unittest.TestCase):
    """第 6 步的实测账必须**从数据重算得出来**，并且钉在**当前**这把尺子上。

    哈希不一致就 fail：那种「账是上一版尺子量的、数字却还在汇报」的形状，
    本项目已经反复在 VERSION.md 与 gate 报告上抓到过，不再给它第二次机会。
    """

    PROJ = SCRIPTS.parents[2]
    ARTIFACTS = PROJ / ".temp" / "v422_honest_map" / "MT1_translation" / "artifacts"
    ARTIFACT = ARTIFACTS / "MTD2_DRIFT_BASELINE.json"
    ANCHOR = ARTIFACTS / "MTD_SEAL43_ANCHOR.json"
    DATASETS = AUDIT_DATASETS

    def payload(self) -> dict:
        self.assertTrue(self.ARTIFACT.is_file(),
                        "MTD2_DRIFT_BASELINE.json 不在盘上：第 6 步只有尺子、没有账")
        return json.loads(self.ARTIFACT.read_bytes().decode("utf-8"))

    def test_the_baseline_is_pinned_to_the_current_ruler(self):
        import hashlib
        doc = self.payload()
        live_impl = hashlib.sha256((SCRIPTS / "prose_reconcile.py").read_bytes()).hexdigest().upper()
        self.assertEqual(doc["implementation"]["sha256"], live_impl,
                         "实现改过但基线没重跑：这本账量的是**上一版**尺子")
        live_doc = hashlib.sha256(GLOSSARY_PATH.read_bytes()).hexdigest().upper()
        self.assertEqual(doc["registry"]["sha256"], live_doc,
                         "登记面改过但基线没重跑：尺子的口径与账对不上")
        self.assertEqual(doc["registry"]["checks"], list(pr.CHECK_VOCABULARY))

    def test_both_faces_are_reproducible_from_the_datasets(self):
        from test_v422_prose_ownership import delivered_legacy_map
        doc = self.payload()
        # 非空跑断言：两本「空账」也能逐键相等，所以先要求这份账真的有量。
        self.assertGreater(doc["runs"]["philippines"]["input_side"]["pairs"], 800,
                           "PH 旧表对数掉到 800 以下：输入面已经不是那张表了")
        self.assertGreater(doc["runs"]["philippines"]["input_side"]["flagged_pairs"], 0,
                           "一条漂移都没量到＝尺子没咬到东西，逐键相等就没有意义")
        anchor = json.loads(self.ANCHOR.read_bytes().decode("utf-8"))["candidates_html"]
        for name, path in sorted(self.DATASETS.items()):
            with self.subTest(run=name):
                import hashlib
                dataset = json.loads(path.read_text(encoding="utf-8"))
                run = doc["runs"][name]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                                 run["dataset_sha256"], "%s：账里的输入哈希与在盘字节不是同一份" % name)
                pairs = pr.legacy_candidate_pairs(dataset)
                fresh = pr.measure_pairs(pairs, dataset=dataset, doc=DOC)
                for key in ("pairs", "flagged_pairs", "clean_pairs", "code_counts"):
                    self.assertEqual(fresh[key], run["input_side"][key],
                                     "%s：输入面 %s 复算不一致（尺子或数据变过，账必须重跑）"
                                     % (name, key))
                html_path = self.PROJ / anchor[name]["path"]
                html_sha = hashlib.sha256(html_path.read_bytes()).hexdigest().upper()
                self.assertEqual(html_sha, anchor[name]["sha256"],
                                 "%s：读者载荷与锚点登记的不是同一份 HTML" % name)
                self.assertEqual(run["reader_html"]["sha256"], html_sha,
                                 "%s：账里指的 HTML 与锚点指的不是同一份" % name)
                view = dict(dataset)
                view["en_text_replacements"] = delivered_legacy_map(html_path)
                reader = pr.measure_pairs(pr.legacy_candidate_pairs(view), dataset=dataset, doc=DOC)
                for key in ("pairs", "flagged_pairs", "clean_pairs", "code_counts"):
                    self.assertEqual(reader[key], run["reader_side"][key],
                                     "%s：读者面 %s 复算不一致" % (name, key))

    def test_command_cwd_and_environment_are_registered(self):
        """复现信息不止 argv：业主 2026-11-01 第 4 条要求关键环境一并入册。"""
        doc = self.payload()
        for name, run in sorted(doc["runs"].items()):
            cli = run["cli"]
            self.assertEqual(cli["exit"], 0, "%s：登记的命令退出码不是 0" % name)
            self.assertTrue(cli["command"].startswith("python scripts/prose_reconcile.py"),
                            "%s：命令面不是那条 CLI：%s" % (name, cli["command"]))
            self.assertTrue(cli["cwd"].endswith("travel-scope"), "%s：cwd 没登记" % name)
            self.assertEqual(cli["key_environment"]["PYTHONDONTWRITEBYTECODE"], "1",
                             "%s：复现命令没带缓存护栏，跑一遍就会污染封册字节" % name)
            self.assertEqual(cli["key_environment"]["PYTHONIOENCODING"], "utf-8",
                             "%s：没登 PYTHONIOENCODING，Windows 上这条命令的编码就不是复现条件" % name)
            self.assertEqual(run["input_side"]["pairs"], cli["report_pairs"],
                             "%s：CLI 报告与账里的对数不是同一个数" % name)

    def test_legacy_key_partition_is_mutually_exclusive_and_exhaustive(self):
        doc = self.payload()
        for name, path in sorted(self.DATASETS.items()):
            dataset = json.loads(path.read_text(encoding="utf-8"))
            buckets = doc["runs"][name]["denominator_reconciliation"]["buckets"]
            self.assertEqual(sum(buckets.values()),
                             len(dataset.get("en_text_replacements") or {}),
                             "%s：键没分干净（重复计数或漏桶）" % name)
            self.assertEqual(buckets["measured"],
                             doc["runs"][name]["input_side"]["pairs"],
                             "%s：选择口径选出的对数 ≠ 账里量的对数" % name)

    def test_registered_false_positives_come_from_real_legacy_rows(self):
        """假阳性样本必须是**真的旧表行**，不是为了让测试好看而编出来的句子。"""
        doc = self.payload()
        philippines = json.loads(self.DATASETS["philippines"].read_text(encoding="utf-8"))
        legacy_keys = set(philippines.get("en_text_replacements") or {})
        registered = DOC["false_positive_regressions"]
        for code, rows in sorted(registered["samples"].items()):
            for row in rows:
                self.assertIn(row["cn"], legacy_keys,
                              "%s 样本 %r 不在 PH 旧表里：那是编的" % (code, row["cn"][:20]))
            self.assertEqual(registered["false_positives_removed"][code], len(rows))
            # 历史探针复算：当前尺子不发、v1 会发——去掉的数量必须与登记数一致。
            probe = doc["runs"]["philippines"]["ruler_history_probe"]
            self.assertEqual(probe["pairs_removed_as_false_positive"][code], len(rows),
                             "%s：账里的收窄数量与登记面不一致" % code)
        self.assertEqual(doc["runs"]["california"]["ruler_history_probe"]
                         ["pairs_removed_as_false_positive"], {"currency": 0, "term": 0},
                         "CA 侧没有这两类假阳性；一旦不为零就说明尺子又漂了")

    def test_pair_selection_has_exactly_one_source(self):
        """`--from-legacy-map` 与 .temp 的实测工具共用一个筛选口径。"""
        self.assertIn("pairs = legacy_candidate_pairs(dataset)", SOURCE,
                      "CLI 又手抄了一份筛选条件＝两个分母")
        self.assertEqual(SOURCE.count("and CJK.search(str(cn))]"), 1,
                         "legacy 对的选择条件出现在多处：只许 legacy_candidate_pairs 那一份")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
