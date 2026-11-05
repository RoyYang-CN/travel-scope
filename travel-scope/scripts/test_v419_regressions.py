"""Executable regressions for the Travel-Scope v5.0.0 release identity."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from intake_contract import parse_custom_budget_range, validate_intake
from init_run import _current_version
from spa_renderer import render_spa_document


ROOT = Path(__file__).resolve().parents[1]


def browser_dataset_v419() -> dict:
    return {
        "country": "菲律宾",
        "country_en": "Philippines",
        "artifact_slug": "philippines",
        "duration_days": 3,
        "routes": [["海岸线", "Coast Route", "宿务", "3天", "Car", 1000, ""]],
        "route_budgets": {"海岸线": {"total_cny": 1000}},
        "destinations": [["宿务", "Cebu"]],
        "itinerary": [],
        "hotels": [
            [
                "宿务", "香格里拉麦克坦度假酒店", "Shangri-La Mactan, Cebu", "度假酒店", 900, "", "",
                "10.307959,124.020848", "", "", "海滨度假村", "", "", "", "", "", "", "",
                2022, "" # open_year=2022, renovate_year=""
            ],
            [
                "宿务", "老牌海滩度假村", "Heritage Beach Resort", "度假村", 600, "", "",
                "10.300000,124.010000", "", "", "传统经典", "", "", "", "", "", "", "",
                1998, 2023 # open_year=1998, renovate_year=2023
            ],
        ],
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [
            [
                "宿务", "薄荷岛", "快艇", "OceanJet", "1.5小时", "53公里", "¥120", "舒适便捷",
                "提前30分钟到码头", "宿务1号码头", "薄荷岛塔比拉兰码头", "每日多班",
                "宿务1号码头", "薄荷岛塔比拉兰码头", "Cebu Pier 1", "Tagbilaran Port",
                "10.2917,123.9056", "9.6542,123.8522", "宿务", "薄荷岛", "https://oceanjet.net",
                "https://oceanjet.net/booking", "08:00", "09:30"
            ]
        ],
        "transport_nodes": [],
        "budget": [["1", "TBD", "抵达", 500, 200, 100, 100, 100, 1000]],
        "practical": [], "worth_it": [], "local_chains": [], "packing": [],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [], "section_media": [],
        "map_targets": {},
    }


class V419RegressionTests(unittest.TestCase):
    def test_version_alignment_v419(self):
        """Verifies four-tier version alignment across all release policies."""
        version_policy = json.loads((ROOT / "references/version-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(version_policy["current_version"], "5.0.0")

        provenance_policy = json.loads((ROOT / "references/provenance-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance_policy["target_version"], "5.0.0")

        contract = json.loads((ROOT / "references/renderer-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["version"], "5.0.0")

        gate_content = (ROOT / "scripts/formal_data_gate.py").read_text(encoding="utf-8")
        self.assertIn('CURRENT_VERSION = "5.0.0"', gate_content)

        gen_content = (ROOT / "scripts/gen_travel_scope.py").read_text(encoding="utf-8")
        self.assertIn("Version: V5.0.0", gen_content)

        spa_content = (ROOT / "scripts/spa_renderer.py").read_text(encoding="utf-8")
        self.assertIn("Travel-Scope v5.0.0", spa_content)

        init_content = (ROOT / "scripts/init_run.py").read_text(encoding="utf-8")
        self.assertIn("Travel-Scope 运行环境安全初始化脚本 (v5.0.0)", init_content)

        map_policy = (ROOT / "references/map-link-policy.md").read_text(encoding="utf-8")
        self.assertIn("# 地图跳转规则（v5.0.0）", map_policy)

    def test_custom_budget_range_parser(self):
        """Test parse_custom_budget_range with various Chinese/currency formats."""
        res1 = parse_custom_budget_range("350~900")
        self.assertIsNotNone(res1)
        self.assertEqual(res1[0], 350)
        self.assertEqual(res1[1], 900)

        res2 = parse_custom_budget_range("¥500-1000/晚")
        self.assertIsNotNone(res2)
        self.assertEqual(res2[0], 500)
        self.assertEqual(res2[1], 1000)

        res3 = parse_custom_budget_range("每晚不超过800元")
        self.assertIsNotNone(res3)
        self.assertEqual(res3[0], 0)
        self.assertEqual(res3[1], 800)

        res4 = parse_custom_budget_range("800以上")
        self.assertIsNotNone(res4)
        self.assertEqual(res4[0], 800)
        self.assertIsNone(res4[1])

        res5 = parse_custom_budget_range("城区可以中档，海岛偏500-900左右")
        self.assertIsNotNone(res5)
        self.assertEqual(res5[0], 500)
        self.assertEqual(res5[1], 900)

    def test_intake_validation_accepts_custom_budget(self):
        """Test intake contract accepts custom budget string and canonical tiers."""
        valid_custom = {
            "q0_destination": "菲律宾",
            "q1_time": "2027-02",
            "q2_days": 12,
            "q3_tier": "350~900",
            "q4_transport": "non-self-drive",
            "q5_arrival": "宿务",
            "q6_departure": "宿务",
            "q7_depth": "deep",
            "q8_pace": "moderate",
        }
        # Should not raise
        validate_intake(valid_custom)

    def test_spa_layout_prevents_dropped_pins(self):
        """Verify spa-layout.js does not fall back to synthetic coordinate place URLs."""
        js_content = (ROOT / "assets/spa-layout.js").read_text(encoding="utf-8")
        # Ensure deprecated pattern `/maps/place/{Name}/@{coords}` is absent
        self.assertNotIn("/maps/place/' + encodeURIComponent(name) + '/@'", js_content)
        # Ensure clean search API with entity query is used
        # v4.2.2 §9：渲染层不得维护第二套主机/路径规则——模板只住配置文件。
        self.assertNotIn("https://www.google.com/maps/search/", js_content,
                         "Google 搜索模板出现在 JS 即说明渲染层又开始自己拼 URL（v4.2.2 §6/§9 禁止）")
        self.assertIn("map_link_by_provider", js_content,
                      "渲染器必须按 provider 读 dataset 容器，而不是读 legacy google_url")
        self.assertIn("D.map_link_ui", js_content,
                      "按钮文案的唯一来源是随 dataset 下发的登记文案（§7）")

    def test_transport_card_parameter_fix(self):
        """Verify transfersBlock in spa-layout.js correctly extracts fromLoc (x[12]) and toLoc (x[13])."""
        js_content = (ROOT / "assets/spa-layout.js").read_text(encoding="utf-8")
        # Ensure old buggy parameters x[2] and x[3] are NOT passed into mapLinks for transfers
        self.assertNotIn("mapLinks(x[2]||fromLoc", js_content)
        self.assertNotIn("mapLinks(x[3]||toLoc", js_content)
        # Verify corrected parameters
        self.assertIn("const rawFromLoc = x[12] || '';", js_content)
        self.assertIn("const rawToLoc = x[13] || '';", js_content)

    def test_hotel_vintage_badges_and_filter_in_spa(self):
        """Verify hotel vintage badges and filter bar are rendered in SPA."""
        js_content = (ROOT / "assets/spa-layout.js").read_text(encoding="utf-8")
        self.assertIn("hotel-filter-bar", js_content)
        self.assertIn("setHotelFilter", js_content)
        self.assertIn("全新开业", js_content)
        self.assertIn("全面焕新", js_content)

        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / "philippines-travel-guide.html"
            render_spa_document(html, browser_dataset_v419())
            html_content = html.read_text(encoding="utf-8")
            self.assertIn("dataset", html_content)
            self.assertIn("Shangri-La Mactan, Cebu", html_content)


if __name__ == "__main__":
    unittest.main()
