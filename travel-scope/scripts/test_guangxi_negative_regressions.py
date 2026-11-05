# -*- coding: utf-8 -*-
"""
Negative Regression Test Suite for Travel-Scope v4.0.5+.
Version: V4.0.11
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from formal_data_gate import audit as audit_formal_data, _direct_url
from map_contract import audit_map_targets, map_urls


class GuangxiNegativeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = str(os.environ.get("TRAVEL_SCOPE_GUANGXI_REGRESSION_RUN") or "").strip()
        cls.guangxi_dir = (Path(configured).expanduser() if configured
                           else ROOT / "fixtures" / "guangxi-negative-run")

    def test_synthetic_urls_rejected(self):
        fake_url1 = "https://wlt.gxzf.gov.cn/entity/0001"
        fake_url2 = "https://you.ctrip.com/entity/0001.html"
        real_url = "https://wlt.gxzf.gov.cn/zwgk/fdzdgknr/ml/gljg/202305/t20230519_2508119.html"
        self.assertFalse(_direct_url(fake_url1))
        self.assertFalse(_direct_url(fake_url2))
        self.assertTrue(_direct_url(real_url))

    def test_domestic_map_contract(self):
        target = {
            "canonical_name": "象鼻山",
            "destination": "桂林",
            "country": "中国",
            "target_level": "verified_coordinate",
            "coords": "25.2694,110.2974"
        }
        urls = map_urls(target, international=False)
        self.assertIn("uri.amap.com/marker", urls["amap"])
        self.assertIn("api.map.baidu.com/marker", urls["baidu"])

    def test_missing_qa_evidence_file_rejected(self):
        if not self.guangxi_dir.is_dir():
            self.skipTest(f"Guangxi dir {self.guangxi_dir} not found")
        data = json.loads((self.guangxi_dir / "dataset.json").read_text(encoding="utf-8"))
        errors, _ = audit_map_targets(data, base_dir=self.guangxi_dir, require_exact=True)
        self.assertTrue(any("QA 证据文件不存在" in e or "qa_evidence" in e for e in errors))

    def test_budget_mismatch_and_independence(self):
        if not self.guangxi_dir.is_dir():
            self.skipTest(f"Guangxi dir {self.guangxi_dir} not found")
        data = json.loads((self.guangxi_dir / "dataset.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.guangxi_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["skill_version"] = "4.0.11"
        scope = json.loads((self.guangxi_dir / "scope.json").read_text(encoding="utf-8"))
        corridors = json.loads((self.guangxi_dir / "route_corridors.json").read_text(encoding="utf-8"))
        result = audit_formal_data(data, manifest, scope, corridors, base_dir=self.guangxi_dir)
        self.assertTrue(any("预算" in e for e in result["errors"]))

    def test_depth_threshold_custom_area(self):
        if not self.guangxi_dir.is_dir():
            self.skipTest(f"Guangxi dir {self.guangxi_dir} not found")
        data = json.loads((self.guangxi_dir / "dataset.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.guangxi_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["skill_version"] = "4.0.11"
        scope = json.loads((self.guangxi_dir / "scope.json").read_text(encoding="utf-8"))
        corridors = json.loads((self.guangxi_dir / "route_corridors.json").read_text(encoding="utf-8"))
        result = audit_formal_data(data, manifest, scope, corridors, base_dir=self.guangxi_dir)
        self.assertTrue(any("全案可见 POI 总数" in e and "180" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
