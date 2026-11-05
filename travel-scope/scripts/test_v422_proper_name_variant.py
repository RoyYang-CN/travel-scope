# -*- coding: utf-8 -*-
"""MT-F4（#119）：同一语义对内部的**拉丁专名形状冲突**门。

业主 2026-11-02 第 2 条把这条门的形状定死了，本文件逐句变成能跑的断言：

  · 只查同一对内部（中文格 ⇄ 英文格），不做全 run 的近重复扫描——全 run 那 1039 对已否决；
  · 只产 finding，不改中文也不改英文；
  · `Cathy's / Cathys` 阻断，不许用「忽略标点」放过；
  · `Ciopinno / Cioppino` 阻断，并说清错在**中文原格**：只改英文不算结案；
  · `Flat White / Flat Whites` 只对这一个具体 pair 放行，不许立「所有复数都放」的宽规则；
  · 必须有负测证明：删掉豁免、豁免挂到别的 pair、把豁免的字段写错、只修英文，门仍然阻断。

另外把这条门的**边界**也钉在测试里：它保证的是两面对齐，不是谁作准。
把英文改成跟着中文一起错，本门会闭嘴——那是登记在案的漏洞（known_loophole），不是本门的失职，
补它的办法是按来源登记专名，而不是让字符串检查冒充事实裁判。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import prose_reconcile as pr                                        # noqa: E402

GLOSSARY_PATH = ROOT / "references" / "prose-glossary.json"
DOC = json.loads(GLOSSARY_PATH.read_bytes().decode("utf-8"))
SOURCE = (SCRIPTS / "prose_reconcile.py").read_bytes().decode("utf-8")

CODE = "fact_drift_proper_name_variant"
# 三对都是**实测原文**（两地 MT-E0 候选表里的行），不是编的例子：
# 编的例子只能证明规则自洽，证明不了它对着真数据还灵不灵。
CA_P0097_CN = "好莱坞山道 Cathy's Corner 漫舞观景点"
CA_P0097_EN = "Cathys Corner Mt Hollywood Dr"
CA_P0283_CN = "加州著名海岸海鲜排档，海鲜浓汤炖锅Ciopinno击败名厨鲍比弗雷"
CA_P0283_EN = ("A famous California coast seafood counter, whose Cioppino stew "
               "beat star chef Bobby Flay")
PH_P0803_CN = "纯正澳白Flat White与牛油果酸酵母吐司，邦劳早晨最受欢迎的能量补给站"
PH_P0803_EN = ("Authentic Aussie Flat Whites and avocado sourdough toast, "
               "Panglao's premier morning energy haven")


def registry():
    return DOC["proper_name_variants"]


def rule(doc=None):
    return pr.proper_name_rule(doc if doc is not None else DOC)


def codes(cn, en):
    return [item["code"] for item in pr.reconcile_pair(cn, en)]


class RuleShapeTests(unittest.TestCase):
    """门的形状：登记面与实现一处一份，参数被真读。"""

    def test_check_and_code_are_registered_on_both_sides(self):
        self.assertIn("proper_name_variant", DOC["checks"])
        self.assertEqual(DOC["finding_codes"]["proper_name_variant"], CODE)
        self.assertIn(CODE, DOC["blocking_findings"] if "blocking_findings" in DOC else
                      json.loads((ROOT / "references" / "prose-translation-contract.json")
                                 .read_bytes().decode("utf-8"))["blocking_findings"],
                      "新码不进 blocking_findings ⇒ 发了也没人拦，等于纸面门")

    def test_registry_shape_literal_equals_the_implementation_regex(self):
        self.assertEqual(registry()["token_shape"], pr.PROPER_NAME_TOKEN.pattern)
        with self.assertRaises(ValueError) as caught:
            broken = json.loads(json.dumps(DOC, ensure_ascii=False))
            broken["proper_name_variants"]["token_shape"] = r"\b[A-Za-z]+\b"
            pr.proper_name_rule(broken)
        self.assertIn("glossary_proper_name_shape_unknown", str(caught.exception))

    def test_parameters_must_be_positive_integers(self):
        for name in ("min_token_length", "shared_prefix_length", "max_levenshtein"):
            broken = json.loads(json.dumps(DOC, ensure_ascii=False))
            broken["proper_name_variants"][name] = 0
            with self.assertRaises(ValueError) as caught:
                pr.proper_name_rule(broken)
            self.assertIn("glossary_proper_name_param_unregistered", str(caught.exception), name)

    def test_the_rule_never_touches_the_dataset(self):
        """只查同一对内部：实现里若出现「扫载荷找相似名字」就是把已否决的 1039 对请回来。"""
        body = SOURCE[SOURCE.index("def proper_name_conflicts"):
                      SOURCE.index("def urls_in")]
        self.assertNotIn("dataset", body)
        self.assertNotIn("display_names", body)
        self.assertNotIn("destinations", body)

    def test_whole_run_census_stays_rejected(self):
        census = registry()["rejected_census"]["whole_run_pairs"]
        self.assertEqual(registry()["rejected_census"]["verdict"], "REJECTED_NOT_A_GATE")
        self.assertEqual(census["total"], 1039, "反例计数是实测登记值，改了就是有人动过口径")
        self.assertEqual(census["california"] + census["philippines"], census["total"])


class BlockingTests(unittest.TestCase):
    """两条该拦的必须拦，且措辞不许替业主下结论。"""

    def test_apostrophe_is_not_normalised_away(self):
        self.assertIn(CODE, codes(CA_P0097_CN, CA_P0097_EN))
        hits = pr.proper_name_conflicts(CA_P0097_CN, CA_P0097_EN, rule())
        self.assertEqual([h["cn_token"] for h in hits], ["Cathy"])
        self.assertEqual([h["en_token"] for h in hits], ["Cathys"])
        self.assertEqual(hits[0]["distance"], 1,
                         "撇号算边界 ⇒ Cathy 与 Cathys 距离 1；若哪天有人加『去标点再比』，这条会跳")

    def test_source_side_spelling_conflict_blocks(self):
        self.assertIn(CODE, codes(CA_P0283_CN, CA_P0283_EN))
        detail = [item for item in pr.reconcile_pair(CA_P0283_CN, CA_P0283_EN)
                  if item["code"] == CODE][0]["detail"]
        self.assertIn("Ciopinno", detail)
        self.assertIn("Cioppino", detail)
        self.assertIn("只改英文不算结案", detail, "Cioppino 这类必须说清错在中文原格")
        self.assertNotIn("正确写法是", detail, "字符串门不许自称知道谁作准")

    def test_both_live_blocking_rows_are_the_registered_examples(self):
        registered = {(item["cn_token"], item["en_token"])
                      for item in registry()["blocking_examples"]}
        fired = set()
        for cn, en in ((CA_P0097_CN, CA_P0097_EN), (CA_P0283_CN, CA_P0283_EN)):
            for hit in pr.proper_name_conflicts(cn, en, rule()):
                fired.add((hit["cn_token"], hit["en_token"]))
        self.assertEqual(fired, registered,
                         "实测发码的两条与登记面例子里的两条必须一模一样，多一条少一条都是口径漂了")


class AllowanceTests(unittest.TestCase):
    """豁免只能是**这一个 pair**，且不许静默失效。"""

    def test_registered_pair_is_allowed(self):
        self.assertNotIn(CODE, codes(PH_P0803_CN, PH_P0803_EN))
        self.assertEqual(pr.proper_name_conflicts(PH_P0803_CN, PH_P0803_EN, rule()), [])

    def test_stripping_the_allowance_blocks_again(self):
        """业主点名要的负测 1：删掉具体豁免 ⇒ 门必须阻断。"""
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken["proper_name_variants"]["allowed_pairs"] = []
        hits = pr.proper_name_conflicts(PH_P0803_CN, PH_P0803_EN, pr.proper_name_rule(broken))
        self.assertEqual([(h["cn_token"], h["en_token"]) for h in hits], [("White", "Whites")])

    def test_allowance_moved_to_another_pair_blocks_again(self):
        """负测 2：把豁免挂到别的原文对上 ⇒ 原对不许跟着一起放行。"""
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken["proper_name_variants"]["allowed_pairs"][0]["cn_text"] = "另一行完全不同的原文"
        self.assertTrue(pr.proper_name_conflicts(PH_P0803_CN, PH_P0803_EN,
                                                 pr.proper_name_rule(broken)))

    def test_allowance_with_a_wrong_field_value_still_blocks(self):
        """负测 3：把豁免的字段值写错一个字符 ⇒ 它就不再命中 ⇒ 门仍阻断（不许模糊匹配兜住）。"""
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken["proper_name_variants"]["allowed_pairs"][0]["en_text"] = PH_P0803_EN + " "
        self.assertTrue(pr.proper_name_conflicts(PH_P0803_CN, PH_P0803_EN,
                                                 pr.proper_name_rule(broken)))

    def test_allowance_missing_a_field_is_incomplete(self):
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken["proper_name_variants"]["allowed_pairs"][0]["en_token"] = ""
        with self.assertRaises(ValueError) as caught:
            pr.proper_name_rule(broken)
        self.assertIn("glossary_allowed_pair_incomplete", str(caught.exception))

    def test_dead_allowance_is_rejected(self):
        """豁免自己必须真是一对冲突：登记一条永远不会命中的豁免＝骗下一个读者。"""
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken["proper_name_variants"]["allowed_pairs"][0]["en_token"] = "Whitesies"
        with self.assertRaises(ValueError) as caught:
            pr.proper_name_rule(broken)
        self.assertIn("glossary_allowed_pair_not_a_conflict", str(caught.exception))

    def test_duplicate_allowance_is_rejected(self):
        broken = json.loads(json.dumps(DOC, ensure_ascii=False))
        broken["proper_name_variants"]["allowed_pairs"].append(
            dict(broken["proper_name_variants"]["allowed_pairs"][0]))
        with self.assertRaises(ValueError) as caught:
            pr.proper_name_rule(broken)
        self.assertIn("glossary_allowed_pair_duplicate", str(caught.exception))

    def test_no_generalised_plural_or_apostrophe_rule_exists(self):
        """宽规则一个都不许有：豁免表只准逐对精确，条数本身就是牙。"""
        registry_dump = json.dumps(registry(), ensure_ascii=False)
        self.assertEqual(len(registry()["allowed_pairs"]), 1,
                         "豁免表现只有业主点名的那一条（Flat White/Whites）；"
                         "多一条就得先有业主对该具体 pair 的裁决")
        entry = registry()["allowed_pairs"][0]
        for field in ("cn_text", "en_text", "cn_token", "en_token"):
            self.assertTrue(str(entry.get(field)).strip(), "%s 不许留空：空字段会把豁免放大成一类" % field)
        self.assertNotIn("\"mode\"", registry_dump.replace(" ", ""),
                         "豁免不许有模式开关（pattern／class／regex 之类），只有四项全等")
        self.assertNotIn("pattern", registry_dump)
        self.assertNotIn("glob", registry_dump)


class BoundaryTests(unittest.TestCase):
    """边界与正对照：门闭嘴的时候，我们必须知道它为什么闭嘴。"""

    def test_aligned_pair_is_silent(self):
        cn = "北滩小意大利招牌海鲜杂烩炖锅Cioppino，大虾、扇贝、青口与珍宝蟹"
        en = ("North Beach little Italy signature Cioppino stew with prawns, scallops, "
              "mussels and Dungeness crab")
        self.assertNotIn(CODE, codes(cn, en))

    def test_english_rewritten_to_a_third_spelling_still_blocks(self):
        """负测 4（只修英文的一种）：英文换成第三种拼写 ⇒ 两面对不上，照拦。"""
        self.assertTrue(pr.proper_name_conflicts(CA_P0283_CN,
                                                 CA_P0283_EN.replace("Cioppino", "Ciopino"), rule()))

    def test_copying_the_wrong_source_spelling_into_english_silences_the_gate(self):
        """登记在案的漏洞，测试把它钉成**已知边界**而不是惊喜。

        中文原格写 `Ciopinno`，英文跟着改成 `Ciopinno` ⇒ 形状对齐 ⇒ 本门不发码。
        这条不是门的失职：字符串对齐不等于事实正确。补它的办法是按来源登记专名
        （tier1/tier2 或 prose-glossary），不是把这条检查改成猜谁对谁错。
        """
        self.assertEqual(pr.proper_name_conflicts(CA_P0283_CN,
                                                  CA_P0283_EN.replace("Cioppino", "Ciopinno"),
                                                  rule()), [])
        contract = json.loads((ROOT / "references" / "prose-translation-contract.json")
                              .read_bytes().decode("utf-8"))
        self.assertIn("known_loophole",
                      contract["no_new_facts"]["reconciliation_layer"]
                      ["measured_2026_11_02_proper_name_variant"],
                      "漏洞必须写在合同里；只在注释里说过＝下一个读者看不见")

    def test_cjk_glued_token_is_still_extracted(self):
        """`\\b` 在『炖锅Cioppino』处不成立（中文也算 `\\w`）——换成边界捕获形状后不许再漏。"""
        self.assertTrue(pr.proper_name_conflicts("海鲜浓汤炖锅Cioppino击败名厨",
                                                 "whose Ciopinno stew beat the chef", rule()))

    def test_two_different_names_are_not_a_conflict(self):
        """不同前缀的两个真名不许被算成拼写变体——这就是全 run 级 1039 对太钝的原因。"""
        self.assertEqual(pr.proper_name_conflicts("Solvang 风车屋", "Blevissard Winery", rule()), [])

    def test_checker_uses_the_doc_it_was_given(self):
        doc = json.loads(json.dumps(DOC, ensure_ascii=False))
        check = pr.checker(None, doc)
        self.assertNotIn(CODE, [item["code"] for item in check(PH_P0803_CN, PH_P0803_EN)])
        doc["checks"] = [item for item in doc["checks"] if item != "proper_name_variant"]
        with self.assertRaises(ValueError) as caught:
            pr.checker(None, doc)(CA_P0097_CN, CA_P0097_EN)
        self.assertIn("glossary_check_unregistered", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
