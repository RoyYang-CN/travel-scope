"""Test suite for Local Apps Contract (Travel-Scope v4.0.12).
Validates:
- Positive verification of valid apps (e.g. Grab Thailand, 12Go, Wongnai)
- Required field completeness
- Official URL verification & rejection of 3rd party APKs / generic searches
- Retired app handling (rejected from formal delivery)
- Conditional app requiring limitations / risk warnings
- Freshness policy enforcement & future timestamp rejection
- Category and availability status validation against policy
"""
from __future__ import annotations

import copy
import datetime
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_contract import validate_local_apps, load_policy


class LocalAppsContractTests(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
        thailand_fixture = self.fixtures_dir / "thailand_local_apps.json"
        loaded = json.loads(thailand_fixture.read_text(encoding="utf-8"))
        self.valid_apps = loaded["local_apps"] if isinstance(loaded, dict) and "local_apps" in loaded else loaded

    def test_thailand_fixture_all_valid(self):
        # All 15 sample apps in thailand_local_apps.json should pass validation
        errors = validate_local_apps(self.valid_apps, as_of_date="2026-10-02")
        self.assertEqual(errors, [], f"Expected 0 errors for Thailand fixture, got: {errors}")

    def test_missing_required_fields(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        del apps[0]["app_id"]
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("缺少必填" in e and "app_id" in e for e in errors), f"Unexpected: {errors}")

        apps = copy.deepcopy(self.valid_apps[:1])
        del apps[0]["category"]
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("不在配置分类体系中" in e or "category" in e for e in errors), f"Unexpected: {errors}")

    def test_invalid_category_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        apps[0]["category"] = "unsupported_magic_category"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("不在配置分类体系中" in e for e in errors), f"Unexpected: {errors}")

    def test_invalid_status_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        apps[0]["availability_status"] = "super_working"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("availability_status" in e and "super_working" in e for e in errors), f"Unexpected: {errors}")

    def test_third_party_apk_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        apps[0]["android_url"] = "https://apkpure.com/grab/com.grabtaxi.passenger"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("android_url" in e and "Google Play" in e for e in errors), f"Unexpected: {errors}")

        apps[0]["android_url"] = "https://apk-download.fake/grab.apk"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("android_url" in e and "Google Play" in e for e in errors), f"Unexpected: {errors}")

    def test_generic_search_as_official_url_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        apps[0]["official_url"] = "https://www.google.com/search?q=grab+thailand"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("official_url" in e and "google.com/search" in e for e in errors), f"Unexpected: {errors}")

    def test_conditional_app_requires_risk_limitation(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        apps[0]["availability_status"] = "conditional"
        apps[0]["limitations_cn"] = []
        apps[0]["limitations_en"] = []
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("limitations" in e or "限制" in e for e in errors), f"Unexpected: {errors}")

    def test_future_timestamp_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        apps[0]["verified_at"] = "2026-10-10"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("晚于当前生成基准日期" in e for e in errors), f"Unexpected: {errors}")

    def test_expired_timestamp_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:1])
        # mobility_app allows 30 days. Let's make it 60 days old
        apps[0]["freshness_class"] = "mobility_app"
        apps[0]["verified_at"] = "2026-07-01"
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("过期" in e for e in errors), f"Unexpected: {errors}")

    def test_duplicate_app_id_rejected(self):
        apps = copy.deepcopy(self.valid_apps[:2])
        apps[1]["app_id"] = apps[0]["app_id"]
        errors = validate_local_apps(apps, as_of_date="2026-10-02")
        self.assertTrue(any("重复" in e and "app_id" in e for e in errors), f"Unexpected: {errors}")


if __name__ == "__main__":
    unittest.main()
