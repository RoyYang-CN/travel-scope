# -*- coding: utf-8 -*-
"""v4.2.2 V5-B — 汇率契约（V0-L05）：没有来源的数字不得伪装成换算结果。

V0 记的是「PH run 缺 budget_meta.rates.USD，SPA 无汇率可换算」。现场复算比登记更糟：
JS 写死 `return 7.15`／`return 0.125`，生成器缺数据时注入 `{"USD": 0.14}` 并盖
`rate_verified: True`——英文页上每一个 `$` 都来自这两个常数，而文案承诺「仅在数据集
提供已核验汇率时换算」。所以本文件的每一条都对着**读者屏幕上出现的符号**：

1. 未登记 ⇒ 金额保持人民币原样 + 双语说明原因，页面上一个 `$` 都不许出现；
2. 已登记 ⇒ 必须有来源与日期，页面显示来源，换算才允许出现；
3. 自称已核验却给不出出处、或自称未登记却留着数值 ⇒ 报错并降级为未登记；
4. 发布产物里重新出现兜底常数 ⇒ 门禁直接发现（`FX_FALLBACK_LITERAL_IN_ASSET`）。

浏览器用例走真渲染、真点击 #lang-btn，不看注释也不扫字符串。
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

import budget_contract as bc
import visual_qa
from test_v422_map_execution import built_case, dataset_for

ROOT = Path(__file__).resolve().parent.parent
VERIFIED_META = {"base_currency": "CNY", "rate_status": "VERIFIED",
                 "rates": {"CNY": 1.0, "USD": 0.14, "PHP": 8.0},
                 "rate_source": "国家外汇管理局 2026-10 人民币汇率中间价",
                 "rate_date": "2026-10-15"}
UNREGISTERED_META = {"base_currency": "CNY", "rate_status": "UNREGISTERED", "rates": {}}
NOTICE = json.loads((ROOT / "references" / "budget-policy.json").read_text(
    encoding="utf-8"))["ui"]["notice_unregistered"]


def page_with(budget_meta):
    """真渲染：dataset → render_spa_document → Chromium，返回读者看到的汇率形状。"""
    from playwright.sync_api import sync_playwright

    dataset = dataset_for({"fx": built_case("named")})
    dataset["budget_meta"] = copy.deepcopy(budget_meta)
    with tempfile.TemporaryDirectory() as folder:
        html_path = Path(folder) / "fx-guide.html"
        import spa_renderer as sr
        sr.render_spa_document(html_path, dataset, media_delivery_mode="linked", reader_profile="en-audit")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(html_path.as_uri(), wait_until="load")
            view = {"errors": errors,
                    "cn": page.evaluate(visual_qa.BUDGET_FX_JS)}
            page.locator("#lang-btn").dispatch_event("click")
            page.wait_for_timeout(300)
            view["en"] = page.evaluate(visual_qa.BUDGET_FX_JS)
            view["html"] = html_path.read_text(encoding="utf-8", errors="replace")
            browser.close()
    return view


class PolicyLoadTests(unittest.TestCase):
    def test_policy_loads_and_is_closed_set(self):
        policy = bc.load_policy()
        self.assertEqual(policy["rate_status"]["allowed"], ["VERIFIED", "UNREGISTERED"])
        self.assertIn("rate_source", policy["rate_status"]["verified_requires"])

    def test_tampered_policy_raises(self):
        policy = json.loads((ROOT / "references" / "budget-policy.json").read_text(encoding="utf-8"))
        for mutate, needle in (
                (lambda p: p["rate_status"].__setitem__("allowed", ["VERIFIED"]), "allowed"),
                (lambda p: p["rate_status"].pop("verified_requires"), "verified_requires"),
                (lambda p: p["derivation_rule"].__setitem__("banned_fallbacks", []), "banned_fallbacks"),
                (lambda p: p["ui"]["notice_unregistered"].__setitem__("en", "汇率未登记"), "含汉字")):
            broken = json.loads(json.dumps(policy))
            mutate(broken)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "budget-policy.json"
                path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(bc.BudgetPolicyError) as ctx:
                    bc.load_policy(path)
                self.assertIn(needle, str(ctx.exception), needle)

    def test_registered_copy_is_what_the_reader_sees(self):
        """文案唯一来源是登记处：JS 里没有这句，页面上出现的必须是登记处那句。"""
        js = (ROOT / "assets" / "spa-layout.js").read_text(encoding="utf-8")
        self.assertNotIn(NOTICE["cn"], js, "提示文案被复制进 JS＝第二套规则（§9）")
        view = page_with(UNREGISTERED_META)
        self.assertEqual(view["cn"]["note"], NOTICE["cn"])
        self.assertEqual(view["en"]["note"], NOTICE["en"])


class StatusDecisionTests(unittest.TestCase):
    def test_verified_needs_source_and_date(self):
        policy = bc.load_policy()
        for missing in ("rate_source", "rate_date"):
            meta = dict(VERIFIED_META)
            meta.pop(missing)
            status, codes = bc.declared_status(meta, policy)
            self.assertEqual(status, "UNREGISTERED", missing)
            self.assertEqual(codes, ["FX_VERIFIED_WITHOUT_PROVENANCE"], missing)

    def test_verified_without_numbers_is_not_verified(self):
        meta = dict(VERIFIED_META, rates={})
        status, codes = bc.declared_status(meta, bc.load_policy())
        self.assertEqual(status, "UNREGISTERED")
        self.assertEqual(codes, ["FX_VERIFIED_WITHOUT_USABLE_RATE"])

    def test_absent_status_is_reported_not_silently_assumed(self):
        status, codes = bc.declared_status({"base_currency": "CNY", "rates": {}}, bc.load_policy())
        self.assertEqual(status, "UNREGISTERED")
        self.assertEqual(codes, ["FX_RATE_STATUS_MISSING"])

    def test_unknown_status_is_a_blocking_code(self):
        status, codes = bc.declared_status(
            {"base_currency": "CNY", "rate_status": "PROBABLY_FINE", "rates": {}}, bc.load_policy())
        self.assertEqual((status, codes), ("UNREGISTERED", ["FX_RATE_STATUS_UNKNOWN"]))

    def test_unregistered_but_rates_left_behind_is_contradiction(self):
        """自称未登记却留着数值：UI 迟早会拿它换算，状态与数据互相打脸。"""
        meta = {"base_currency": "CNY", "rate_status": "UNREGISTERED",
                "rates": {"CNY": 1.0, "USD": 0.14}}
        status, codes = bc.declared_status(meta, bc.load_policy())
        self.assertEqual(status, "UNREGISTERED")
        self.assertEqual(codes, ["FX_UNREGISTERED_WITH_RATES"])

    def test_legacy_rate_verified_boolean_is_a_claim_without_source(self):
        """V0-L05 的根：v4.2.0/4.2.1 的 dataset 就是这么写的（rate_verified: true，无来源）。"""
        legacy = {"base_currency": "CNY", "target_currency": "USD", "rate_verified": True,
                  "rate_date": "2026-10", "rates": {"CNY": 1.0, "USD": 0.14}}
        status, codes = bc.declared_status(legacy, bc.load_policy())
        self.assertEqual(status, "UNREGISTERED")
        self.assertIn("FX_LEGACY_RATE_CLAIM", codes, codes)
        self.assertIn("FX_RATE_STATUS_MISSING", codes, codes)
        self.assertIn("FX_UNREGISTERED_WITH_RATES", codes, codes)
        self.assertEqual(bc.reader_projection(legacy, bc.load_policy())["factors"], {},
                         "没有出处的数字不得投影成换算因子")

    def test_missing_budget_meta_entirely(self):
        self.assertEqual(bc.findings(None, bc.load_policy()), ["FX_BUDGET_META_MISSING"])


class FactorDerivationTests(unittest.TestCase):
    def test_cny_to_usd_uses_registered_numbers(self):
        self.assertAlmostEqual(bc.factor(VERIFIED_META["rates"], "CNY", "CNY", "USD"), 0.14)

    def test_php_to_cny_follows_the_data_model_not_the_old_inversion(self):
        """旧 getPhpRate() 在 base_currency=PHP 时返回 1/rates.CNY，与登记语义相反。

        data-model 写的是「rates.CNY = 1 单位本币折 CNY 的乘数」：1 PHP ≈ 0.125 CNY 时
        rates.CNY 就是 0.125，旧代码会给出 8，把 1200 比索换算成 9600 元人民币（64 倍）。
        """
        rates = {"PHP": 1.0, "CNY": 0.125}
        self.assertAlmostEqual(bc.factor(rates, "PHP", "PHP", "CNY"), 0.125)
        self.assertAlmostEqual(bc.factor(VERIFIED_META["rates"], "CNY", "PHP", "CNY"), 0.125)

    def test_missing_pair_yields_none_never_a_guess(self):
        self.assertIsNone(bc.factor({"CNY": 1.0}, "CNY", "CNY", "USD"))
        self.assertIsNone(bc.factor({}, "CNY", "CNY", "USD"))
        self.assertIsNone(bc.factor({"CNY": 0}, "CNY", "CNY", "CNY"))

    def test_projection_drops_factors_when_not_verified(self):
        projection = bc.reader_projection(UNREGISTERED_META, bc.load_policy())
        self.assertEqual(projection["rate_status"], "UNREGISTERED")
        self.assertEqual(projection["factors"], {})
        verified = bc.reader_projection(VERIFIED_META, bc.load_policy())
        self.assertAlmostEqual(verified["factors"]["CNY_USD"], 0.14)
        self.assertEqual(verified["rate_source"], VERIFIED_META["rate_source"])


class FallbackLiteralTests(unittest.TestCase):
    def test_release_artifacts_carry_no_fallback_rate(self):
        self.assertEqual(bc.artifact_findings(), [], "发布产物里又出现了兜底汇率常数")
        self.assertEqual(bc.findings_for({"budget_meta": dict(VERIFIED_META)}), [])

    def test_a_real_fallback_line_is_caught(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            (root / "scripts").mkdir()
            (root / "assets" / "spa-layout.js").write_text(
                "const f = () => {\n  return 7.15;\n};\n", encoding="utf-8")
            (root / "scripts" / "gen_travel_scope.py").write_text(
                "RATES = {\"USD\": 0.14}\n", encoding="utf-8")
            findings = bc.artifact_findings(root)
        self.assertEqual(len(findings), 2, findings)
        self.assertTrue(all(f.startswith("FX_FALLBACK_LITERAL_IN_ASSET") for f in findings))

    def test_a_comment_about_the_old_bug_is_not_a_violation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            (root / "scripts").mkdir()
            (root / "assets" / "spa-layout.js").write_text(
                "// 旧实现在这里 return 7.15（已删除）\nconst f = () => null;\n", encoding="utf-8")
            (root / "scripts" / "gen_travel_scope.py").write_text(
                "# 曾经注入 {\"USD\": 0.14}\n", encoding="utf-8")
            self.assertEqual(bc.artifact_findings(root), [])

    def test_generator_no_longer_fabricates_rates(self):
        gen = (ROOT / "scripts" / "gen_travel_scope.py").read_text(encoding="utf-8")
        self.assertNotIn('"rates": {"CNY": 1.0, "USD": 0.14}', gen)
        self.assertIn('BUDGET_META["rate_status"] = "UNREGISTERED"', gen,
                      "缺登记时必须如实写 UNREGISTERED，而不是留给 JS 兜底")


class ReaderDomTests(unittest.TestCase):
    def test_unregistered_page_shows_yuan_and_says_why(self):
        view = page_with(UNREGISTERED_META)
        self.assertEqual(view["errors"], [], "渲染期报错")
        self.assertIn(NOTICE["cn"], view["cn"]["note"])
        self.assertIn(NOTICE["en"], view["en"]["note"])
        for phase in ("cn", "en"):
            self.assertEqual(view[phase]["state"], "UNREGISTERED", phase)
            money = view[phase]["money"]
            self.assertTrue(money, "%s 态金额节点全解析为空＝渲染断了，不是没有 $ 就算通过" % phase)
            self.assertFalse([text for text in money if text.strip().startswith("$")],
                             "%s 态汇率未登记却出现换算金额：%s" % (phase, money))
            self.assertTrue(all(text.strip().startswith("¥") for text in money),
                            "%s 态未登记时金额应保持记录币种：%s" % (phase, money))

    def test_verified_page_converts_and_publishes_the_source(self):
        view = page_with(VERIFIED_META)
        self.assertIn(VERIFIED_META["rate_source"], view["cn"]["note"])
        self.assertEqual(view["cn"]["state"], "VERIFIED")
        self.assertEqual(view["en"]["state"], "VERIFIED")
        self.assertFalse([text for text in view["cn"]["money"] if text.strip().startswith("$")],
                         "中文态按记录币种显示，不应出现 $")
        usd = [text for text in view["en"]["money"] if text.strip().startswith("$")]
        self.assertTrue(usd, "已登记带来源的汇率，英文态却没有换算金额：%s" % view["en"]["money"])
        self.assertIn("$140", usd, "1000 CNY × 0.14 应为 $140，实得 %s" % usd)

    def test_reader_payload_carries_the_registered_state(self):
        view = page_with(UNREGISTERED_META)
        self.assertIn('"budget_fx"', view["html"], "读者载荷必须自带登记的汇率状态")
        self.assertIn(NOTICE["en"], view["html"], "双语提示随载荷下发，JS 不自己写文案")

    def test_dom_state_is_checked_against_the_register(self):
        """页面把状态改成 VERIFIED 而 dataset 没登记 ⇒ QA 必须发现（不是「信 DOM」）。"""
        dataset = dataset_for({"fx": built_case("named")})
        dataset["budget_meta"] = dict(UNREGISTERED_META)
        with tempfile.TemporaryDirectory() as folder:
            html_path = Path(folder) / "fx-guide.html"
            import spa_renderer as sr
            sr.render_spa_document(html_path, dataset, media_delivery_mode="linked", reader_profile="en-audit")
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(html_path.as_uri(), wait_until="load")
                failures, result = [], {}
                visual_qa.check_budget_rate_state(page, dataset, failures, result, "cn")
                self.assertEqual(failures, [], failures)
                self.assertEqual(result["budget_fx_cn"]["registered_status"], "UNREGISTERED")
                page.evaluate("() => { document.querySelector('[data-rate-state]')"
                              ".dataset.rateState = 'VERIFIED'; }")
                forged, forged_result = [], {}
                visual_qa.check_budget_rate_state(page, dataset, forged, forged_result, "cn")
                self.assertTrue(any(f.startswith("FX_RATE_STATE_DOM_DIFFERS") for f in forged),
                                forged)
                browser.close()


class RegisterIntegrityTests(unittest.TestCase):
    def test_registered_codes_match_emitted_codes(self):
        """登记 ↔ 产出双向核对：在册却没人产＝哑规则，产了却不在册＝没人知道的检查。

        这条不是形式主义：写它的时候 `FX_UI_COPY_MISSING` 就在册却没人产（load_policy
        用异常在更早的位置拦住），而 `FX_READER_PROJECTION_MISSING` 登记成 exposed、
        实际却出现在 QA 的 failures 里——两处都登记与实现各说各话。
        """
        sources = "".join((ROOT / "scripts" / name).read_text(encoding="utf-8")
                          for name in ("budget_contract.py", "visual_qa.py"))
        emitted = set(re.findall(r"\bFX_[A-Z][A-Z_]+\b", sources)) - {"FX_DOM_STATE_JS"}
        registered = set(bc.load_policy()["reason_codes"])
        self.assertEqual(emitted - registered, set(),
                         "产出了未登记的 code：%s" % sorted(emitted - registered))
        self.assertEqual(registered - emitted, set(),
                         "登记了却没有任何代码会产出：%s" % sorted(registered - emitted))
        self.assertEqual(set(bc.load_policy()["reason_codes"].values()), {"blocking"},
                         "汇率影响整页金额，没有『暴露后继续发』的空间")

    def test_dataset_side_codes_are_all_reachable(self):
        emitted = set()
        for meta in (None, {}, {"base_currency": "CNY"},
                    {"base_currency": "CNY", "rate_status": "MAYBE"},
                    dict(VERIFIED_META, rate_source=""),
                    dict(VERIFIED_META, rates={}),
                    {"base_currency": "CNY", "rate_status": "UNREGISTERED",
                     "rates": {"CNY": 1.0}},
                    {"base_currency": "CNY", "rate_verified": True}):
            emitted |= set(bc.findings(meta, bc.load_policy()))
        self.assertEqual(emitted, {"FX_BUDGET_META_MISSING", "FX_RATE_STATUS_MISSING",
                                   "FX_RATE_STATUS_UNKNOWN", "FX_VERIFIED_WITHOUT_PROVENANCE",
                                   "FX_VERIFIED_WITHOUT_USABLE_RATE",
                                   "FX_UNREGISTERED_WITH_RATES", "FX_LEGACY_RATE_CLAIM"},
                         sorted(emitted))

    def test_formal_gate_wires_the_register(self):
        gate = (ROOT / "scripts" / "formal_data_gate.py").read_text(encoding="utf-8")
        self.assertIn("budget_contract.findings_for", gate,
                      "正式门禁没有调用汇率登记处＝FX 规则只是文档")
        self.assertNotIn("必须为有效正浮点数", gate,
                        "旧检查仍在逼生成器造一个 USD 数值出来")

    def test_data_model_defers_to_the_register(self):
        model = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
        self.assertEqual(model["budget_meta"]["required"], ["base_currency", "rate_status"])
        self.assertEqual(model["budget_meta"]["properties"]["rate_status"]["enum"],
                         ["VERIFIED", "UNREGISTERED"])
        self.assertNotIn("rates", model["budget_meta"]["required"],
                         "rates 被写成必填＝逼着 dataset 塞一个没来源的数字（V0-L05 的成因）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
