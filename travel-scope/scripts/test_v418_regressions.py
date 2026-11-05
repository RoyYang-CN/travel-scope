"""Executable regressions for the Travel-Scope v4.1.8 contract."""
from __future__ import annotations

import json
import subprocess

import pyc_hygiene as pyc
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from playwright.sync_api import sync_playwright

from init_run import _current_version, init_run
from map_contract import _is_coordinate_query_url, audit_map_targets, map_urls
from spa_renderer import render_spa_document


ROOT = Path(__file__).resolve().parents[1]


def browser_dataset() -> dict:
    return {
        "country": "菲律宾",
        "country_en": "Philippines",
        "artifact_slug": "philippines",
        "duration_days": 3,
        "routes": [["海岸线", "Coast Route", "宿务", "3天", "Car", 1000, ""]],
        "route_budgets": {"海岸线": {"total_cny": 1000}},
        "destinations": [["宿务", "Cebu"]],
        "itinerary": [],
        "hotels": [["宿务", "香格里拉麦克坦度假酒店", "Shangri-La Mactan, Cebu", "度假酒店", 900, "", "", "10.307959,124.020848", "", "", "海滨度假村"]],
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [], "transport_nodes": [],
        "budget": [["1", "TBD", "抵达", 500, 200, 100, 100, 100, 1000]],
        "practical": [], "worth_it": [], "local_chains": [], "packing": [],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [], "section_media": [],
        "map_targets": {
            "宿务|香格里拉麦克坦度假酒店": {
                "canonical_name": "Shangri-La Mactan, Cebu",
                "destination": "宿务",
                "country": "Philippines",
                "entity_type": "named_entity",
                "target_level": "verified_coordinate",
                "verification_status": "verified",
                "coords": "10.307959,124.020848",
                "google_url": "https://www.google.com/maps/search/?api=1&query=10.307959,124.020848",
                "link_mode": "NAMED_SEARCH", "link_provider": "google",
                "link_builder_version": "v422-link-selection-1",
                "link_selection_version": "v422-link-selection-1",
                "link_selection_reason": "R4|SELECTED_NAMED_SEARCH",
                "map_link_url": ("https://www.google.com/maps/search/?api=1&query="
                                  "Shangri-La%20Mactan%2C%20Cebu%2C%20Philippines"),
                "link_notices": ["key_target_unverified"],
                "isolated_link_url": "", "map_query_name_source": "names.en",
                "selection_signals": ["critical_target"],
                "entity_type": "named_entity", "criticality": "CRITICAL_ITINERARY",
                "identity_status": "UNVERIFIED", "coordinate_status": "VERIFIED",
                "google_resolution_status": "NOT_OBSERVED",
                "map_link_by_provider": {
                    "google": {"link_mode": "NAMED_SEARCH", "link_provider": "google",
                               "map_link_url": ("https://www.google.com/maps/search/?api=1&query="
                                                "Shangri-La%20Mactan%2C%20Cebu%2C%20Philippines"),
                               "link_notices": ["key_target_unverified"],
                               "link_selection_reason": "R4|SELECTED_NAMED_SEARCH",
                               "link_selection_version": "v422-link-selection-1",
                               "link_builder_version": "v422-link-selection-1",
                               "query_fields_used": ["sourced_canonical_name",
                                                     "sourced_destination", "sourced_country"],
                               "isolated_link_url": "", "map_query_name_source": "names.en",
                               "selection_signals": ["critical_target"]},
                    "apple": {"link_mode": "NAMED_SEARCH", "link_provider": "apple",
                              "map_link_url": "https://maps.apple.com/?q=Shangri-La%20Mactan",
                              "link_notices": ["key_target_unverified"],
                              "link_selection_reason": "R4|SELECTED_NAMED_SEARCH",
                              "link_selection_version": "v422-link-selection-1",
                              "link_builder_version": "v422-link-selection-1",
                              "query_fields_used": ["sourced_canonical_name"],
                              "isolated_link_url": "", "map_query_name_source": "names.en",
                              "selection_signals": ["critical_target"]},
                },
            }
        },
    }


class V418RegressionTests(unittest.TestCase):
    def test_init_run_profiles_match_generator_contract(self):
        expected = {
            "reader": ["philippines-travel-guide.html"],
            "review": ["philippines-travel-guide.html", "philippines-travel-research.xlsx"],
            "full_audit": [
                "philippines-travel-guide.html", "philippines-travel-research.xlsx",
                "菲律宾旅行攻略-地图标记.html", "菲律宾旅行攻略-地图标记-en.html",
                "菲律宾旅行攻略-双语.html", "菲律宾旅行攻略大全.xlsx",
                "菲律宾旅行攻略大全-en.xlsx", "菲律宾旅行攻略大全.md",
                "菲律宾旅行攻略大全-en.md",
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            for profile, artifacts in expected.items():
                run = init_run("菲律宾", f"run-{profile}", Path(folder), artifact_slug="philippines", delivery_profile=profile)
                manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["skill_version"], "5.0.0")
                self.assertEqual(manifest["artifacts_expected"], artifacts)
                self.assertIn(f"--delivery-profile {profile}", manifest["generation_command"])
                self.assertIn("--artifact-slug philippines", manifest["generation_command"])
        self.assertEqual(_current_version(), "5.0.0")
        with mock.patch("init_run.Path.read_text", return_value="{}"):
            with self.assertRaises(ValueError):
                _current_version()

    def test_generator_executes_all_delivery_profiles(self):
        expected = {
            "reader": {"demo-trip-travel-guide.html"},
            "review": {"demo-trip-travel-guide.html", "demo-trip-travel-research.xlsx"},
            "full_audit": {
                "demo-trip-travel-guide.html", "demo-trip-travel-research.xlsx",
                "Demo China Trip旅行攻略-地图标记.html", "Demo China Trip旅行攻略-地图标记-en.html",
                "Demo China Trip旅行攻略-双语.html", "Demo China Trip旅行攻略大全.xlsx",
                "Demo China Trip旅行攻略大全-en.xlsx", "Demo China Trip旅行攻略大全.md",
                "Demo China Trip旅行攻略大全-en.md",
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            for profile, wanted in expected.items():
                output = Path(folder) / profile
                cmd = [sys.executable, str(ROOT / "scripts/gen_travel_scope.py"), "--mode", "demo",
                       "--output-dir", str(output), "--language", "both", "--delivery-profile", profile,
                       "--artifact-slug", "demo-trip"]
                completed = subprocess.run(pyc.interpreter(cmd), cwd=ROOT, capture_output=True,
                                           text=True, errors="replace", env=pyc.env())
                self.assertEqual(completed.returncode, 0, (completed.stdout or "") + (completed.stderr or ""))
                reader_files = {p.name for p in output.iterdir() if p.suffix in {".html", ".xlsx", ".md"}}
                self.assertEqual(reader_files, wanted)

    def test_formal_map_contract_requires_named_entity_and_rejects_coordinate_url(self):
        data = browser_dataset()
        errors, _ = audit_map_targets(data, require_exact=False)
        self.assertTrue(any("纯坐标查询" in error for error in errors), errors)
        target = data["map_targets"]["宿务|香格里拉麦克坦度假酒店"]
        target.pop("entity_type")
        errors, _ = audit_map_targets(data, require_exact=False)
        self.assertTrue(any("entity_type" in error for error in errors), errors)
        self.assertTrue(_is_coordinate_query_url(target["google_url"]))
        self.assertFalse(_is_coordinate_query_url("https://www.google.com/maps/search/?api=1&query=Shangri-La%20Mactan&ll=10.307959,124.020848"))
        target["entity_type"] = "named_entity"
        urls = map_urls(target)
        self.assertIn("query=Shangri-La%20Mactan%2C%20Cebu%2C%20%E5%AE%BF%E5%8A%A1%2C%20Philippines", urls["google"])
        self.assertNotIn("query=10.307959", urls["google"])

    def test_browser_dom_uses_named_href_and_unverified_rate_label(self):
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / "philippines-travel-guide.html"
            render_spa_document(html, browser_dataset(), reader_profile="en-audit")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                console_errors = []
                page.on("pageerror", lambda exc: console_errors.append(str(exc)))
                page.goto(html.as_uri(), wait_until="load")
                href = page.locator("#panel-stays .map-links a").first.get_attribute("href")
                self.assertIn("Shangri-La", href)
                self.assertNotIn("query=10.307959", href)
                # v4.2.2 §7/§9：dataset → renderer → DOM → href 必须逐字一致，八项属性齐全，
                # 文案取自登记配置；Apple 按钮不出现是依据已接受 Checklist §7 的最小 reader 范围
                # （§7 只登记了 Google 一种文案），决策仍留在 dataset 容器与逐 target 报告里。
                link = page.locator("#panel-stays .map-links a").first
                self.assertEqual(link.get_attribute("href"),
                                 browser_dataset()["map_targets"][
                                     "宿务|香格里拉麦克坦度假酒店"]["map_link_url"])
                self.assertEqual(link.get_attribute("rel"), "noopener noreferrer")
                for attr in ("data-target-id", "data-entity-type", "data-criticality",
                             "data-identity-status", "data-coordinate-status", "data-link-mode",
                             "data-google-resolution-status", "data-provider"):
                    self.assertIsNotNone(link.get_attribute(attr), "%s 缺失（§7 八项属性）" % attr)
                self.assertEqual(link.get_attribute("data-link-mode"), "NAMED_SEARCH")
                self.assertEqual(link.get_attribute("data-google-resolution-status"), "NOT_OBSERVED",
                                 "具名搜索不得把观察状态写成已核验（§3.4）")
                self.assertIn("在 Google Maps 搜索此地点（落点未核验）",
                              page.locator("#panel-stays .map-links").first.inner_text())
                self.assertIn("地图落点未核验",
                              page.locator("#panel-stays .map-links").first.inner_text())
                self.assertEqual(page.locator("#panel-stays .map-links a").count(), 1,
                                 "依据已接受 Checklist §7 的最小 reader 范围：读者页只出 Google 按钮")
                page.locator("#lang-btn").dispatch_event("click")
                # 说明文字在 Budget 面板里；读者要点开才看得到，所以测试也按读者的路径点开。
                page.locator("#tab-budget").dispatch_event("click")
                page.wait_for_timeout(200)
                body = page.locator("body").inner_text()
                # v4.2.2 V5-B（V0-L05）改写这两行：夹具没有登记汇率，所以英文态必须显示
                # 记录币种（¥）并向读者说明原因。旧断言 `assertIn("$", body)` 依赖的是 JS 里
                # 写死的 7.15 兜底——那个 $ 从来不是换算结果，是编出来的；旧的第二行则把
                # 「承认没有汇率」当成缺陷。两条都不再是本合同想要的行为。
                self.assertNotIn("$", body, "未登记汇率却出现换算金额＝回到编数字的老路")
                policy = json.loads((ROOT / "references" / "budget-policy.json").read_text(
                    encoding="utf-8"))
                self.assertIn(policy["ui"]["notice_unregistered"]["en"], body,
                              "未登记汇率却没有向读者说明")
                self.assertIn("¥", body, "英文态应退回记录币种而不是消失")
                self.assertNotIn("[object Object]", body)
                self.assertNotIn("NaN", body)
                self.assertNotIn("undefined", body)
                self.assertEqual(console_errors, [])
                browser.close()


if __name__ == "__main__":
    unittest.main()
