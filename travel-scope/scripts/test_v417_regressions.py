# -*- coding: utf-8 -*-
"""Comprehensive regression test suite for Travel-Scope v4.1.7.

Validates:
1. P0: route_budgets dictionary schema with total_cny cleanly handled; zero [object Object], undefined, NaN, or null人均.
2. P0: Named entities in map links prioritize verified platform URLs / Place IDs / named search queries, never falling back to pure coordinate query (query=lat,lng).
3. P1: Absence of .poi-details / '规划详情' accordion in rendered SPA DOM and CSS.
4. P1: Streamlined delivery profiles (reader, review, full_audit) and clean ASCII kebab-case slug outputs.
5. P1: Official App Store and Google Play details page URLs with rel="noopener noreferrer".
6. P1: Dynamic rates in budget calculations from dataset.budget_meta, zero hardcoded USD_RATE = 7.20.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from spa_renderer import render_spa_document, _adapt_spa_dataset


class V417RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmpdir.name)
        self.js_content = (ROOT / "assets/spa-layout.js").read_text(encoding="utf-8")
        self.css_content = (ROOT / "assets/spa-layout.css").read_text(encoding="utf-8")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_route_budgets_schema_and_zero_object_object(self):
        """P0: route_budgets with object schema renders clean total amounts without [object Object]."""
        dataset = {
            "country": "Testland",
            "country_en": "Testland",
            "artifact_slug": "testland",
            "routes": [
                ["Route A", "Route A En", "A->B", "3天", "Car", 1000, "Desc", "Route A En"],
                ["Route B", "Route B En", "A->C", "3天", "Car", 1200, "Desc", "Route B En"],
            ],
            "route_budgets": {
                "Route A": {
                    "total_cny": 1000,
                    "lodging_cny": 400,
                    "food_cny": 300,
                    "transport_cny": 200,
                    "activities_cny": 100,
                    "other_cny": 0,
                    "summary": "Midrange budget"
                },
                "Route B": {
                    "total_cny": 1200,
                    "lodging_cny": 500,
                    "food_cny": 350,
                    "transport_cny": 250,
                    "activities_cny": 100,
                    "other_cny": 0,
                    "summary": "Comfort budget"
                }
            },
            "destinations": [["A", "A En"], ["B", "B En"], ["C", "C En"]],
            "budget": [["1", "2027-02", "Day 1", 300, 200, 100, 50, 0, 650]],
            "hotels": [["A", "Hotel 1", "Hotel 1 En", "hotel", 400, "", "", "10.1,123.1", "", "", "Great hotel"]],
        }

        # Adapter must preserve and validate total_cny
        adapted = _adapt_spa_dataset(dataset)
        self.assertEqual(adapted["route_budgets"]["Route A"]["total_cny"], 1000)
        self.assertEqual(adapted["route_budgets"]["Route B"]["total_cny"], 1200)

        # Output HTML must not contain [object Object] anywhere
        out_html = self.output_dir / "testland-travel-guide.html"
        render_spa_document(out_html, dataset)
        content = out_html.read_text(encoding="utf-8")
        self.assertNotIn("[object Object]", content)
        self.assertNotIn("undefined人均", content)
        self.assertNotIn("NaN人均", content)

    def test_named_entity_map_landing_never_pure_coordinates_query(self):
        """P0: Named entities in mapLinks never use query=lat,lng as their primary query."""
        # Check mapLinks implementation in JS
        # v4.2.2 §7/§9 把这根 pin 反过来钉：渲染器**不许**再自己拼查询串。
        # 原意图（具名实体绝不落到纯坐标 query）由更强的三条承担：JS 里没有任何 URL 模板、
        # 没有 query_place_id、没有 &ll=，href 只能来自选择器写好的 map_link_url。
        self.assertNotIn("buildMapQuery", self.js_content)
        self.assertNotIn("query_place_id", self.js_content)
        self.assertNotIn("&ll=", self.js_content)
        self.assertNotIn("maps/search/?api=1", self.js_content,
                         "URL 模板只住 references/map-link-selection.json，渲染层出现即第二套实现")
        self.assertIn("record.map_link_url", self.js_content,
                      "href 必须取自 dataset 里选择器写好的字段")
        self.assertIn("function usableName(value)", self.js_content)
        self.assertNotIn("replace(/[\u4e00-\u9fa5]/g, '').trim()", self.js_content)
        self.assertNotIn("|| 'Location'", self.js_content)
        self.assertNotIn("|| 'Unnamed'", self.js_content)
        self.assertIn("map-unlocated", self.js_content)

    def test_poi_details_accordion_removed(self):
        """P1: The .poi-details / '规划详情' component is removed from reader-facing SPA."""
        self.assertNotIn("poi-details", self.js_content)
        self.assertNotIn(".poi-details", self.css_content)

    def test_app_store_links_secure_rel_attributes(self):
        """P1: App Store and Google Play links contain rel='noopener noreferrer'."""
        self.assertIn("rel:'noopener noreferrer'", self.js_content)
        self.assertIn("href:a.ios_url,target:'_blank',rel:'noopener noreferrer'", self.js_content)
        self.assertIn("href:a.android_url,target:'_blank',rel:'noopener noreferrer'", self.js_content)

    def test_dynamic_rates_support(self):
        """P1: 缺汇率时必须「明说没有」，而不是由代码补一个数——v4.2.2 V5-B 重写了这条。

        旧断言写的是 `assertIn("const getUsdRate"/"const getPhpRate")`，那两个函数正是
        `return 7.15`／`return 0.125` 的所在；docstring 说「缺失汇率保持未核验」，
        断言却把实现钉死在会编造数字的那组函数上。现在按登记处复算：
        JS 不得再自带汇率数字，也不得自带提示文案，两者都必须来自读者载荷 D.budget_fx。
        """
        import budget_contract
        policy = budget_contract.load_policy()
        self.assertEqual(budget_contract._literal_hits(self.js_content,
                                                       budget_contract.banned_fallback_literals(policy)),
                         [], "assets/spa-layout.js 又出现了兜底汇率常数（V0-L05）")
        self.assertIn("D.budget_fx", self.js_content,
                      "客户端必须读登记投影，而不是自己算汇率状态")
        self.assertNotIn("getUsdRate", self.js_content,
                         "旧兜底函数还在：它会返回一个没有来源的汇率")
        self.assertNotIn("getPhpRate", self.js_content, "同上")
        self.assertNotIn("exchange rate unverified", self.js_content.lower(),
                         "JS 不得自带汇率提示文案；文案唯一来源是 budget-policy.json 的 ui 段")
        self.assertNotIn("汇率未登记", self.js_content, "同上：提示文案不许写进 JS 字面量")


if __name__ == "__main__":
    unittest.main()
