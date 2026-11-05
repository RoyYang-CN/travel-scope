# -*- coding: utf-8 -*-
"""v4.2.2 V5-C — 英文模式汉字残留的唯一口径（V0-L06）。

v4.2.1 的清册里同时留着两个数：§3.2.5 写 7.5%，§16.2 第 5 条写 2/7080＝0.03%。
复算时发现的不是「哪个数对」，而是**发布树里有四处各写一套 CJK 计数**
（visual_qa 两处、delivery_gate 两处），字类宽窄不同、分母不同，
其中 `delivery_gate` 还要求 `cjk_chars > 5` 才报错——5 个汉字可以静默通过；
四处都没排除语言切换按钮上刻意保留的「中文」，于是英文态最干净的那 2 个字
反而被当成残留计入。

所以本文件测三件必须成立的事：
1. 口径只有一份实现，且登记的字类与代码一致（改一处不改另一处就 import 失败）；
2. 刻意项**单独计数并出现在报告里**，不是被减掉就当它不存在；
3. 阈值判定用调整后的 leaked 数，且不再允许「小于等于 5 个字」静默通过。

浏览器用例走真渲染：证明真实成品里 raw_cjk≥2（那颗切换按钮）而 leaked_cjk=0，
即口径修正改变的是判定，不是把数字抹掉。
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import en_residue_measure as erm
from test_v422_map_execution import built_case, dataset_for

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "references" / "run-quality-policy.json").read_text(encoding="utf-8"))


def code_lines(source: str) -> str:
    """跳过行首注释再比对：注释里引用旧写法是交代历史，可执行行里再写一套才是分叉。"""
    kept = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*", '"""')):
            continue
        kept.append(line)
    return "\n".join(kept)


class DefinitionTests(unittest.TestCase):
    def test_definition_is_registered_and_authoritative(self):
        definition = erm.load_definition(POLICY)
        self.assertTrue(definition["authoritative"])
        self.assertIn("spa-en-text.txt", definition["scope"])
        self.assertIn("中文", definition["intentional_cjk"])

    def test_missing_or_downgraded_definition_raises(self):
        for mutate, needle in (
                (lambda d: d.pop("english_residue_measurement"), "缺少"),
                (lambda d: d["english_residue_measurement"].pop("denominator"), "缺少字段"),
                (lambda d: d["english_residue_measurement"].__setitem__("authoritative", False),
                 "authoritative"),
                (lambda d: d["english_residue_measurement"].__setitem__("counts_as_residue",
                                                                       "\\u4e00-\\u9fa5"),
                 "不一致")):
            broken = copy.deepcopy(POLICY)
            mutate(broken)
            with self.assertRaises(ValueError) as ctx:
                erm.load_definition(broken)
            self.assertIn(needle, str(ctx.exception), needle)

    def test_empty_intentional_list_is_legal(self):
        """「没有刻意项」是一种合法登记，不等于字段失踪——所以不能拿空清单当报错用例。"""
        clean = copy.deepcopy(POLICY)
        clean["english_residue_measurement"]["intentional_cjk"] = []
        erm.load_definition(clean)
        measured = erm.measure("Coast Route 中文", clean)
        self.assertEqual(measured["leaked_cjk"], 2,
                         "取消刻意项后，那颗按钮就该被算成残留：口径改动必须立刻反映到数字上")

    def test_js_and_python_char_class_agree(self):
        """浏览器那份字类必须由同一来源注入：两边认的不是同一批字符＝口径又分叉了。"""
        self.assertTrue(erm._js_class_matches())
        for ch in ("一", "鿿", "㐀", "䶿", "豈", "﫿"):
            self.assertTrue(erm.contains_cjk(ch), ch)
        for ch in ("a", "，", "。", "！", "1", " "):
            self.assertFalse(erm.contains_cjk(ch), repr(ch))


class CountingTests(unittest.TestCase):
    def test_toggle_label_is_intentional_yet_still_visible(self):
        measured = erm.measure("Coast Route 中文 ¥1,000", POLICY)
        self.assertEqual(measured["raw_cjk"], 2)
        self.assertEqual(measured["intentional_cjk"], 2)
        self.assertEqual(measured["leaked_cjk"], 0)
        self.assertEqual(measured["intentional_tokens"], ["中文"])
        self.assertGreater(measured["ratio_unadjusted"], 0)
        self.assertEqual(measured["ratio"], 0.0)

    def test_a_real_leak_is_counted_and_located(self):
        measured = erm.measure("Coast Route 山景酒店 Stay", POLICY)
        self.assertEqual(measured["leaked_cjk"], 4)
        self.assertEqual(measured["intentional_cjk"], 0)
        self.assertTrue(measured["leaked_samples"], "残留必须能定位，否则读者看到的缺口找不到出处")
        self.assertTrue(all("山景酒店" in sample for sample in measured["leaked_samples"]),
                        measured["leaked_samples"])

    def test_fullwidth_punctuation_is_excluded_but_not_erased(self):
        measured = erm.measure("Arrival，Cebu。出发", POLICY)
        self.assertEqual(measured["fullwidth_punctuation"], 2)
        self.assertEqual(measured["leaked_cjk"], 2, "标点之外的汉字仍要数出来")

    def test_empty_text_does_not_divide_by_zero(self):
        measured = erm.measure("", POLICY)
        self.assertEqual((measured["chars"], measured["ratio"], measured["leaked_cjk"]),
                         (0, 0.0, 0))

    def test_the_two_v421_numbers_are_same_formula_different_scope(self):
        """7.5% 与 0.03% 不是两个口径打架的答案，而是两取样地的同一公式。

        本用例把两个历史数字按现行公式重算一遍，确认比值能复现——
        以后谁再引用「EN 残留 X%」，必须同时给出 scope，否则数字无意义。
        """
        audit_scope = "山" * 292 + "x" * (3904 - 292)
        gate_scope = "中文" + "y" * (7080 - 2)
        first = erm.measure(audit_scope, POLICY)
        second = erm.measure(gate_scope, POLICY)
        self.assertAlmostEqual(first["ratio"], 292 / 3904, places=5)
        self.assertAlmostEqual(second["raw_cjk"] / second["chars"], 2 / 7080, places=5)
        self.assertEqual(second["leaked_cjk"], 0,
                         "整页那 2 个汉字恰好是语言切换按钮：调整后残留为 0")
        self.assertEqual(first["intentional_cjk"], 0)


class ThresholdTests(unittest.TestCase):
    def test_small_leak_is_not_silently_allowed(self):
        """旧实现要求 cjk_chars>5 才报，等于允许 5 个汉字静默通过。"""
        measured = erm.measure("Stay " + "山" * 2 + " " * 300, POLICY)
        decision = erm.verdict(measured, POLICY)
        self.assertTrue(decision["breach"], decision)
        self.assertEqual(decision["floor"], 1)

    def test_clean_english_text_does_not_breach(self):
        measured = erm.measure("Coast Route 中文 · 3 days · Car", POLICY)
        self.assertFalse(erm.verdict(measured, POLICY)["breach"])

    def test_gate_no_longer_hard_codes_a_five_character_allowance(self):
        source = code_lines((ROOT / "scripts" / "delivery_gate.py").read_text(encoding="utf-8"))
        self.assertNotIn("cjk_chars > 5", source,
                         "阈值回到了代码字面量里，登记处就又不是唯一来源了")


class SingleImplementationTests(unittest.TestCase):
    def test_measuring_files_do_not_define_their_own_char_class(self):
        """数残留的地方只许调用唯一口径；别处为别的用途用 CJK 类不在本条约束内。"""
        for name in ("visual_qa.py", "delivery_gate.py"):
            source = code_lines((ROOT / "scripts" / name).read_text(encoding="utf-8"))
            self.assertNotIn("[\\u4e00-\\u9fff]", source,
                             "%s 又自己写了一份汉字字类（V0-L06 的成因）" % name)
            self.assertNotIn("[\\u4e00-\\u9fa5]", source, "%s 的字类宽窄与登记处不同" % name)
            self.assertIn("en_residue_measure", source,
                          "%s 没有调用唯一口径" % name)
        definition = (ROOT / "scripts" / "en_residue_measure.py").read_text(encoding="utf-8")
        self.assertIn("CJK_IDEOGRAPHS", definition)

    def test_registered_threshold_moves_with_the_verdict(self):
        source = (ROOT / "scripts" / "delivery_gate.py").read_text(encoding="utf-8")
        self.assertIn("EN 阈值漂移", source,
                      "调用方传阈值与登记处不一致时必须可见，而不是静默取其一")


class RealRenderTests(unittest.TestCase):
    def test_rendered_page_measured_in_the_browser(self):
        """真渲染 + 真英文态：raw 里含刻意项，调整后必须为 0；植入的真泄漏必须被抓住。"""
        import spa_renderer as sr
        import en_residue_measure as measure_mod
        from playwright.sync_api import sync_playwright

        dataset = dataset_for({"fx": built_case("named")})
        dataset["budget_meta"] = {"base_currency": "CNY", "rate_status": "UNREGISTERED",
                                  "rates": {}}
        with tempfile.TemporaryDirectory() as folder:
            html_path = Path(folder) / "en-guide.html"
            sr.render_spa_document(html_path, dataset, media_delivery_mode="linked", reader_profile="en-audit")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(html_path.as_uri(), wait_until="load")
                page.locator("#lang-btn").dispatch_event("click")
                page.wait_for_timeout(300)
                en_body = page.locator("body").inner_text()
                baseline = measure_mod.measure(en_body, POLICY)
                planted = en_body.replace("Coast Route", "Coast Route 海岸线未翻译")
                leaked = measure_mod.measure(planted, POLICY)
                browser.close()
        self.assertGreaterEqual(baseline["raw_cjk"], 2,
                                "语言切换按钮的「中文」应当在原始计数里，不应当被抹掉")
        self.assertEqual(baseline["leaked_cjk"], 0,
                         "干净英文页的调整后残留必须是 0：%s" % baseline["leaked_samples"])
        expected = 6 * en_body.count("Coast Route")   # 「海岸线未翻译」每个出现点 6 个汉字
        self.assertGreaterEqual(expected, 6, "夹具里至少要有一个可替换的英文串")
        self.assertEqual(leaked["leaked_cjk"], expected, leaked["leaked_samples"])
        self.assertTrue(erm.verdict(leaked, POLICY)["breach"])
        self.assertTrue(any("海岸线" in sample for sample in leaked["leaked_samples"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
