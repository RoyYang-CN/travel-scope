"""Executable regressions for the Travel-Scope v4.2.1 contract."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from init_run import _current_version
from spa_renderer import render_spa_document
from formal_data_gate import audit
from map_contract import audit_map_targets


ROOT = Path(__file__).resolve().parents[1]


def dataset_v420() -> dict:
    return {
        "country": "美国",
        "country_en": "United States",
        "artifact_slug": "usa-california",
        "duration_days": 3,
        "map_region": "international",
        "domestic_destination": False,
        "routes": [
            [
                "加州一号公路全景线",
                "California Highway 1 Scenic Route",
                "旧金山 - 蒙特雷与卡梅尔 - 圣塔芭芭拉 - 洛杉矶",
                "3天",
                "自驾",
                1500,
                "加州黄金海岸线经典自驾",
                "Pacific Coast Highway self-drive"
            ]
        ],
        "route_budgets": {"加州一号公路全景线": {"total_cny": 1500}},
        "destinations": [
            ["旧金山", "San Francisco"],
            ["蒙特雷与卡梅尔", "Monterey & Carmel"],
            ["圣塔芭芭拉", "Santa Barbara"],
            ["洛杉矶", "Los Angeles"]
        ],
        "budget_meta": {
            "base_currency": "CNY",
            "target_currency": "USD",
            "rate_verified": True,
            "rate_date": "2026-10",
            "rates": {
                "CNY": 1.0,
                "USD": 0.14
            }
        },
        "itinerary": [
            ["加州一号公路全景线", "Day 1", 1, "游", "旧金山艺术宫与天鹅湖", "37.8029,-122.4484"],
            ["加州一号公路全景线", "Day 2", 1, "游", "17哩黄金海岸线", "36.5700,-121.9500"],
            ["加州一号公路全景线", "Day 3", 1, "游", "圣塔芭芭拉历史修道院", "34.4380,-119.7140"],
        ],
        "hotels": [
            [
                "旧金山", "旧金山机场雅乐轩酒店", "Aloft San Francisco Airport", "海景精品度假村", 950, "", "",
                "37.6000,-122.3800", "", "", "近机场便捷", "", "", "", "", "", "", "",
                2021, 2023
            ]
        ],
        "restaurants": [
            [
                "圣塔芭芭拉", "圣塔芭芭拉加州法式小馆", "Bouchon Santa Barbara", "法式小馆", 450, "", "",
                "34.4200,-119.7000", "", "", "地道加州风味法餐", "", "", "", "", "", "", ""
            ]
        ],
        "cafes": [
            [
                "圣塔芭芭拉", "标靶艺术手冲咖啡", "Dart Coffee Co Funk Zone", "特色精品咖啡", 45, "", "",
                "34.4150,-119.6920", "", "", "艺术街区特色手冲", "", "", "", "", "", "", ""
            ]
        ],
        "attractions": [
            [
                "旧金山", "艺术宫与天鹅湖", "Palace of Fine Arts", "历史文化地标", 0, "",
                "37.8029,-122.4484", "", "", "经典古典柱廊湖景", "", "", "", "", "", "", ""
            ]
        ],
        "dive_sites": [],
        "transport": [],
        "transport_nodes": [
            ["旧金山", "旧金山国际机场 (SFO)", "SFO International Airport", "国际机场", "37.6213,-122.3790"]
        ],
        "budget": [
            ["Day 1", "2026-01-04", "SFO接机提车·湾区入住休整", 500, 200, 100, 100, 50, 950],
            ["Day 2", "2026-01-05", "17哩黄金海岸·艺术小镇漫步", 500, 200, 100, 100, 50, 950],
            ["Day 3", "2026-01-06", "修道院与日落海滩·抵达洛杉矶", 500, 200, 100, 100, 50, 950],
        ],
        "practical": [], "worth_it": [], "local_chains": [], "packing": [],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [
            {
                "route": "加州一号公路全景线",
                "destination": "旧金山",
                "title": "旧金山艺术宫",
                "title_en": "Palace of Fine Arts",
                "image": "assets/sf_palace.jpg",
                "author": "Travel-Scope",
                "license": "CC-BY-SA"
            }
        ],
        "section_media": [
            {
                "destination": "旧金山",
                "modules": ["hotels", "restaurants"],
                "image": "assets/sf_atmos.jpg",
                "asset_role": "destination_atmosphere",
                "selection_level": "same_destination_same_category_reference"
            }
        ],
        "map_targets": {
            "旧金山|旧金山机场雅乐轩酒店": {
                "destination": "旧金山",
                "canonical_name": "Aloft San Francisco Airport",
                "entity_type": "named_entity",
                "target_level": "verified_place_id",
                "verification_status": "verified",
                "coords": "37.6000,-122.3800",
                "google_place_id": "ChIJb_Z8f3Wxj4ARW52wK0mJ6oM",
                "id_provenance": "Google Maps Official Place ID",
                "source_url": "https://maps.google.com/?cid=12345",
                "google_url": "https://www.google.com/maps/search/?api=1&query=Aloft+San+Francisco+Airport,+San+Francisco,+United+States&query_place_id=ChIJb_Z8f3Wxj4ARW52wK0mJ6oM",
                "apple_url": "https://maps.apple.com/?q=Aloft+San+Francisco+Airport&ll=37.6000,-122.3800",
                "checked_at": "2026-10-24",
                "qa_evidence": "evidence/map_qa.json"
            },
            "圣塔芭芭拉|标靶艺术手冲咖啡": {
                "destination": "圣塔芭芭拉",
                "canonical_name": "Dart Coffee Co Funk Zone",
                "entity_type": "named_entity",
                "target_level": "verified_coordinate",
                "verification_status": "verified",
                "coords": "34.4150,-119.6920",
                "source_url": "https://dartcoffee.com",
                "google_url": "https://www.google.com/maps/search/?api=1&query=Dart+Coffee+Co+Funk+Zone,+Santa+Barbara,+United+States&ll=34.4150,-119.6920",
                "apple_url": "https://maps.apple.com/?q=Dart+Coffee+Co+Funk+Zone&ll=34.4150,-119.6920",
                "checked_at": "2026-10-24",
                "qa_evidence": "evidence/map_qa.json"
            }
        },
        "en_text_replacements": {
            "加州一号公路全景线": "California Highway 1 Scenic Route",
            "SFO接机提车·湾区入住休整": "SFO Arrival & Bay Area Rest",
            "17哩黄金海岸·艺术小镇漫步": "17-Mile Drive & Carmel Stroll",
            "修道院与日落海滩·抵达洛杉矶": "Mission Tour & Arrival in LA"
        }
    }


class V420RegressionTests(unittest.TestCase):
    def test_version_alignment_v420(self):
        self.assertEqual(_current_version(), "5.0.0")
        contract = json.loads((ROOT / "references/renderer-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["version"], "5.0.0")
        v_policy = json.loads((ROOT / "references/version-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(v_policy["current_version"], "5.0.0")
        p_policy = json.loads((ROOT / "references/provenance-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(p_policy["target_version"], "5.0.0")

    def test_branch_cover_role_badges_default_true(self):
        """V4.2.1 Checklist §10.2.1: branch_cover_role_badges must default to true."""
        contract = json.loads((ROOT / "references/renderer-contract.json").read_text(encoding="utf-8"))
        self.assertTrue(contract["presentation"]["branch_cover_role_badges"])

    def test_spa_renderer_html_contains_v420_features(self):
        """Test rendered SPA HTML has v4.2.1 category dictionary, robust regex, and zero unverified rate text."""
        dataset = dataset_v420()
        with tempfile.TemporaryDirectory() as folder:
            out_file = Path(folder) / "guide.html"
            render_spa_document(out_file, dataset)
            html = out_file.read_text(encoding="utf-8")
        self.assertIn("Travel-Scope v4.2.2 Single-Page Application", html)
        self.assertIn("CATEGORY_DICT", html)
        self.assertIn("Seaview Boutique Resort", html)
        self.assertIn("Cliffside Pool Villa", html)
        self.assertIn("Tropical Garden Boutique Hotel", html)
        self.assertNotIn("buildMapQuery", html)
        self.assertIn('\"map_link_ui\"', html,
                      "成品必须自带 §7 登记文案（spa_renderer 从 map-link-selection.json 下发）")
        self.assertIn("badge-atmosphere", html)
        self.assertNotIn("exchange rate unverified", html)

    def test_route_line_splitter_supports_hyphens(self):
        """V4.2.1 Checklist §4.3.1: Corridor regex must split on ' - ' and '—' as well as arrows."""
        splitter = re.compile(r"→|->|\s+-\s+|—")
        corridor = "旧金山 - 蒙特雷与卡梅尔 - 大苏尔与中心海岸 - 圣塔芭芭拉 - 洛杉矶大都会区"
        nodes = [s.strip() for s in splitter.split(corridor) if s.strip()]
        self.assertEqual(len(nodes), 5)
        self.assertEqual(nodes[0], "旧金山")
        self.assertEqual(nodes[1], "蒙特雷与卡梅尔")
        self.assertEqual(nodes[4], "洛杉矶大都会区")

    def test_overseas_map_url_local_name_rule_withdrawn(self):
        """v4.2.1 §6.3.3「海外 URL 严禁汉字」在 v4.2.2 被**撤回**（业主 2026-10-30 按 V1R 裁决）。

        旧规则只给两条路：要么用官方英文名，要么不出货。而清册 §4 禁止动作第 2 条写的是
        「不删除中文/本地文字后猜英文名；没有可信英文名时保留有来源的本地正式名称」——旧规则
        唯一允许的做法恰恰是合同禁止的做法。references/map-link-selection.json::
        query_rules.local_name_query_decision 登记原话：「海外地图 URL 含本地文字自 v4.2.2 起
        不再是地图错误」。名字来源、删字残片与英文 UI 泄漏另有各自的门禁，本撤回不放松它们。
        """
        dataset = dataset_v420()
        data_local = dict(dataset)
        data_local["map_targets"] = dict(dataset["map_targets"])
        data_local["map_targets"]["圣塔芭芭拉|标靶艺术手冲咖啡"] = dict(
            dataset["map_targets"]["圣塔芭芭拉|标靶艺术手冲咖啡"])
        data_local["map_targets"]["圣塔芭芭拉|标靶艺术手冲咖啡"]["google_url"] = (
            "https://www.google.com/maps/search/?api=1&query=标靶艺术手冲咖啡%2C+United+States")
        errors_local, _ = audit_map_targets(data_local, require_exact=False)
        self.assertEqual([e for e in errors_local if "包含中文汉字" in e], [],
                         "本地正式名称进搜索串已被 v4.2.2 合同放开，仍按旧规则报错就是两条规则互相矛盾")

        # 撤回不等于放行伪造名：占位名照旧是缺陷（这条与汉字无关，判的是名字有没有来源）。
        data_fake = dict(dataset)
        data_fake["map_targets"] = dict(dataset["map_targets"])
        data_fake["map_targets"].pop("圣塔芭芭拉|标靶艺术手冲咖啡", None)
        for key in sorted(data_fake["map_targets"]):
            row = dict(data_fake["map_targets"][key])
            row["canonical_name"] = "California Venue"
            row.pop("quarantine", None)          # 未隔离在案的假名才是本用例要拦的形态
            data_fake["map_targets"][key] = row
            break
        errors_fake, _ = audit_map_targets(data_fake, require_exact=False)
        self.assertTrue([e for e in errors_fake if "伪造/残留串" in e],
                        "汉字门撤了，占位名门必须还在：没有来源的名字不能因为改规则一起消失")

    def test_withdrawn_cjk_ban_has_no_leftover_copy_in_the_release(self):
        """撤回一条规则要撤回干净：v4.2.1 时同一件事在 map_contract 与 formal_data_gate 各写一份，
        V6-D 端到端跑第一次就撞上『改了一处、另一处还在拦』。这里扫全部脚本，任何按汉字判 URL 的
        错误文案都不允许再出现（本地文字判定统一由 map_link_selector 的名称来源规则负责）。"""
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "严禁包含中文汉字" in text or "包含中文汉字" in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         "撤回的汉字门还在这些地方活着：%s" % offenders)

    def test_budget_meta_rate_contract_in_formal_gate(self):
        """V4.2.1 Checklist §2.3.3 的「rates.USD 必须是正浮点数」在 v4.2.2 被**撤回**（V5-B/V0-L05）。

        那条规则本身就是伪造汇率的成因：dataset 没有来源时，门禁不是拒绝发布，而是要求
        一个正浮点数，于是生成器直接补了 0.14 并标 rate_verified=True。v4.2.2 换成
        「登记制」：缺登记可以，但必须如实写 UNREGISTERED 且不得留着没出处的数值。
        本用例把撤回后的边界钉住——三种形状各自的结论都不能含糊。
        """
        dataset = dataset_v420()
        manifest = {
            "skill_version": "5.0.0",
            "generation_command": "python {SKILL_ROOT}/scripts/gen_travel_scope.py",
            "intake": {"q0_destination": "加州", "q1_month": "1月", "q2_days": "3", "q3_tier": "中档", "q4_transport": "自驾", "q5_arrival": "SFO", "q7_depth": "standard", "q8_pace": "moderate"},
            "destination_profile": {"map_region": "international", "country": "美国", "currency": "USD", "theme": "ocean"}
        }
        scope = {}
        corridors = {"corridors": [{"continuity": 100.0}]}

        unsourced = dict(dataset)
        unsourced["budget_meta"] = {"base_currency": "CNY", "rates": {}}
        errors = audit(unsourced, manifest, scope, corridors)["errors"]
        self.assertTrue(any(error.startswith("FX_RATE_STATUS_MISSING") for error in errors),
                        "缺 rate_status 必须报错，而不是由代码补一个数：%s" % errors[:5])

        claimed = dict(dataset)
        claimed["budget_meta"] = {"base_currency": "CNY", "rate_status": "VERIFIED",
                                  "rates": {"CNY": 1.0, "USD": 0.14}}
        errors = audit(claimed, manifest, scope, corridors)["errors"]
        self.assertTrue(any(error.startswith("FX_VERIFIED_WITHOUT_PROVENANCE") for error in errors),
                        errors[:5])

        registered = dict(dataset)
        registered["budget_meta"] = {"base_currency": "CNY", "rate_status": "VERIFIED",
                                     "rates": {"CNY": 1.0, "USD": 0.14},
                                     "rate_source": "国家外汇管理局 2026-10 人民币汇率中间价",
                                     "rate_date": "2026-10-15"}
        errors = audit(registered, manifest, scope, corridors)["errors"]
        self.assertEqual([error for error in errors if error.startswith("FX_")], [], errors[:5])

    def test_editorial_media_route_parity_in_formal_gate(self):
        """V4.2.1 Checklist §9.2.1: Orphaned route names in editorial_media must fail gate."""
        dataset = dataset_v420()
        manifest = {
            "skill_version": "5.0.0",
            "generation_command": "python {SKILL_ROOT}/scripts/gen_travel_scope.py",
            "intake": {"q0_destination": "加州", "q1_month": "1月", "q2_days": "3", "q3_tier": "中档", "q4_transport": "自驾", "q5_arrival": "SFO", "q7_depth": "standard", "q8_pace": "moderate"},
            "destination_profile": {"map_region": "international", "country": "美国", "currency": "USD", "theme": "ocean"}
        }
        scope = {}
        corridors = {"corridors": [{"continuity": 100.0}]}

        # Corrupt editorial media route to an orphaned route
        bad_dataset = dict(dataset)
        bad_dataset["editorial_media"] = [
            {"route": "加州一号公路海滨奇观与爱乐之城浪漫影迷贯通线", "destination": "旧金山", "title": "旧金山艺术宫"}
        ]
        res = audit(bad_dataset, manifest, scope, corridors)
        orphaned_errs = [e for e in res["errors"] if "编辑大图路线名与候选路线脱钩" in e]
        self.assertTrue(len(orphaned_errs) >= 1)


if __name__ == "__main__":
    unittest.main()
