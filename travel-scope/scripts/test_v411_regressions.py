"""V4.0.11 Regression Test Suite.
Validates:
- Map search URL degradation to search_candidate (rejection of generic search as verified_platform_url)
- Template fake address rejection (Premises, Coast Rd, Cebu 6000)
- Route claims contract (title destinations must be subset of corridor; off-corridor media disallowed)
- Media timestamp time travel prevention (retrieved_at / checked_at in future rejected)
- Historical schedule timestamp enforcement (2023 timetable without historical label rejected)
- Anti-scraping blocked / 403 / captcha source status enforcement (must be pending, not verified)
- Synthetic TripAdvisor and PADI URL structural verification
- English artifact clean-gate (area placeholder explosion, CJK residue, banned phrases)
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_gate import _check_english_text
from formal_data_gate import audit
from map_contract import _is_generic_search_url, audit_map_targets
from test_formal_data_gate import fixture


class V411RegressionTests(unittest.TestCase):
    def test_generic_search_url_detection_and_degradation(self):
        # Generic Google Maps search queries must be detected as search candidates
        search_urls = [
            "https://www.google.com/maps/search/?api=1&query=Shangri-La+Mactan",
            "https://www.google.com/maps/search/Kawasan+Falls",
            "https://maps.apple.com/?q=Chocolate+Hills",
        ]
        for url in search_urls:
            self.assertTrue(_is_generic_search_url(url), f"Should detect generic search: {url}")

        # Real entity pages or URLs with place_id/cid should NOT be generic search
        entity_urls = [
            "https://www.google.com/maps/place/Shangri-La+Mactan/@10.301,124.019,17z/data=!4m9!1m2!2m1!1s",
            "https://www.google.com/maps/search/?api=1&query=Hotel&query_place_id=ChIJ123456789012345",
            "https://maps.google.com/?cid=123456789012345",
        ]
        for url in entity_urls:
            self.assertFalse(_is_generic_search_url(url), f"Should recognize entity page: {url}")

    def test_search_url_as_verified_platform_url_rejected(self):
        data, *_ = fixture()
        target = data["map_targets"]["A|住宿一"]
        target.update({
            "target_level": "verified_platform_url",
            "verification_status": "verified",
            "google_url": "https://www.google.com/maps/search/?api=1&query=Hotel+1",
        })
        errors, _ = audit_map_targets(data)
        self.assertTrue(any("普通搜索候选链接" in e or "search_candidate" in e for e in errors), f"Unexpected: {errors}")

    def test_template_fake_address_rejected(self):
        data, *_ = fixture()
        target = data["map_targets"]["A|住宿一"]
        target.update({
            "target_level": "verified_coordinate",
            "verification_status": "verified",
            "qa_evidence": "evidence/maps_fake.json",
        })
        # Mock QA data with templated address
        qa_mock = {
            "targets": {
                "A|住宿一": {
                    "resolved_name": "Hotel 1 Real",
                    "resolved_address": "Main Premises, Coast Rd, Cebu 6000, Philippines",
                    "landing_url": "https://www.google.com/maps/place/Hotel1/@1.11,1.11,17z",
                }
            }
        }
        test_dir = Path(__file__).resolve().parent / ".temp_v411_test"
        (test_dir / "evidence").mkdir(parents=True, exist_ok=True)
        evidence_file = test_dir / "evidence/maps_fake.json"
        maps_file = test_dir / "evidence/maps.json"
        try:
            evidence_file.write_text(json.dumps(qa_mock, ensure_ascii=False), encoding="utf-8")
            maps_file.write_text(json.dumps({"targets": {}}, ensure_ascii=False), encoding="utf-8")
            errors, _ = audit_map_targets(data, base_dir=test_dir)
            self.assertTrue(any("批量模板伪造特征" in e for e in errors), f"Unexpected: {errors}")
        finally:
            if evidence_file.exists():
                evidence_file.unlink()
            if maps_file.exists():
                maps_file.unlink()
            if (test_dir / "evidence").exists():
                (test_dir / "evidence").rmdir()
            if test_dir.exists():
                test_dir.rmdir()

    def test_route_claims_title_corridor_subset_enforcement(self):
        # Route 3 claims "巴拉望" in title, but corridor sequence only has Cebu, Bohol, Dumaguete
        data, manifest, scope, corridors, assets = fixture()
        scope["selected_destinations"] = [
            {"name": "宿务", "name_en": "Cebu", "status": "正式纳入"},
            {"name": "薄荷岛", "name_en": "Bohol", "status": "正式纳入"},
            {"name": "杜马盖地", "name_en": "Dumaguete", "status": "正式纳入"},
            {"name": "巴拉望", "name_en": "Palawan", "status": "正式纳入"},
        ]
        routes = [
            ["米沙鄢与巴拉望双核心飞跃线", "3天", "A→B", "特色", "适合", "3000", "专车", "Route 3"],
            ["路线2", "3天", "A→C", "特色", "适合", "3000", "专车", "Route 2"],
            ["路线1", "3天", "A→B", "特色", "适合", "3000", "专车", "Route 1"],
        ]
        data["routes"] = routes
        corridors["corridors"] = [
            {
                "corridor_id": "c3",
                "name": "米沙鄢与巴拉望双核心飞跃线",
                "corridor_sequence": ["宿务", "薄荷岛", "杜马盖地"],
                "continuity": 100.0,
                "edge_audit": [],
            },
            {
                "corridor_id": "c2",
                "name": "路线2",
                "corridor_sequence": ["宿务", "薄荷岛"],
                "continuity": 100.0,
                "edge_audit": [],
            },
            {
                "corridor_id": "c1",
                "name": "路线1",
                "corridor_sequence": ["宿务", "薄荷岛"],
                "continuity": 100.0,
                "edge_audit": [],
            },
        ]
        result = audit(data, manifest, scope, corridors)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("route_claims" in e and "巴拉望" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

    def test_off_corridor_media_rejected(self):
        data, manifest, scope, corridors, *_ = fixture()
        routes = [
            ["走廊路线A", "3天", "A→B", "特色", "适合", "3000", "专车", "Route A"],
            ["走廊路线B", "3天", "A→C", "特色", "适合", "3000", "专车", "Route B"],
            ["走廊路线C", "3天", "A→D", "特色", "适合", "3000", "专车", "Route C"],
        ]
        data["routes"] = routes
        corridors["corridors"] = [
            {"corridor_id": "ca", "name": "走廊路线A", "corridor_sequence": ["A"], "continuity": 100.0, "edge_audit": []},
            {"corridor_id": "cb", "name": "走廊路线B", "corridor_sequence": ["A"], "continuity": 100.0, "edge_audit": []},
            {"corridor_id": "cc", "name": "走廊路线C", "corridor_sequence": ["A"], "continuity": 100.0, "edge_audit": []},
        ]
        data["editorial_media"] = [
            {"image": "assets/siquijor.jpg", "route": "走廊路线A", "destination": "锡基霍尔", "title": "Siquijor"},
            {"image": "assets/a1.jpg", "route": "走廊路线A", "destination": "A", "title": "A1"},
            {"image": "assets/a2.jpg", "route": "走廊路线A", "destination": "A", "title": "A2"},
            {"image": "assets/b1.jpg", "route": "走廊路线B", "destination": "A", "title": "B1"},
            {"image": "assets/b2.jpg", "route": "走廊路线B", "destination": "A", "title": "B2"},
            {"image": "assets/b3.jpg", "route": "走廊路线B", "destination": "A", "title": "B3"},
            {"image": "assets/c1.jpg", "route": "走廊路线C", "destination": "A", "title": "C1"},
            {"image": "assets/c2.jpg", "route": "走廊路线C", "destination": "A", "title": "C2"},
            {"image": "assets/c3.jpg", "route": "走廊路线C", "destination": "A", "title": "C3"},
        ]
        result = audit(data, manifest, scope, corridors)
        self.assertTrue(any("走廊外目的地" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

    def test_media_timestamp_time_travel_rejected(self):
        data, manifest, scope, corridors, *_ = fixture()
        data["editorial_media"] = [
            {"image": "assets/img1.jpg", "destination": "A", "retrieved_at": "2027-02-15", "title": "Photo 1"},
        ]
        result = audit(data, manifest, scope, corridors)
        self.assertTrue(any("时空穿越" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

    def test_stale_schedule_without_historical_label_rejected(self):
        data, manifest, scope, corridors, *_ = fixture()
        data["transport"] = [[
            "A→B", "ferry", "OceanJet", "", "2h", "每日多班", "1,1", "2,2", "", "", "", "verified",
            "A站", "B站", "", "", "published_reference", "2026-2027参考时刻", "2026-2027 Schedule", "2026-09-12",
            "https://oceanjet.net/schedule-2023.html", "", "08:00,10:00", "09:00,11:00"
        ]]
        data["source_evidence_meta"].append({
            "destination": "A",
            "name": "A→B",
            "url": "https://oceanjet.net/schedule-2023.html",
            "source_provider": "official",
            "evidence_level": "direct_schedule",
            "verification_status": "verified",
            "retrieved_at": "2026-09-12",
            "cross_source_review": "",
            "notes": "fixture: 历史参考时刻的来源",
        })
        result = audit(data, manifest, scope, corridors)
        self.assertTrue(any("历史参考时刻" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

    def test_anti_scraping_blocked_marked_verified_rejected(self):
        data, manifest, scope, corridors, *_ = fixture()
        # Source evidence with 403 or captcha must be marked pending
        item = data["source_evidence_meta"][0]
        item["verification_status"] = "verified"
        item["http_status"] = "403"
        item["crawl_status"] = "cloudflare_captcha_blocked"
        result = audit(data, manifest, scope, corridors)
        self.assertTrue(any("反爬阻断" in e and "pending" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

    def test_synthetic_tripadvisor_and_padi_urls_rejected(self):
        data, manifest, scope, corridors, *_ = fixture()
        item = data["source_evidence_meta"][0]
        item["verification_status"] = "verified"
        item["evidence_level"] = "direct_entity"
        # Synthetic TripAdvisor URL without -g\d+ or -d\d+
        item["url"] = "https://www.tripadvisor.com/hotel-review-shangri-la-cebu.html"
        result = audit(data, manifest, scope, corridors)
        self.assertTrue(any("不符合实体级直达规范" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

        # Synthetic PADI URL without /dive-site/<country>/<site-slug>/
        item["url"] = "https://www.padi.com/dive-site/hilutungan-island.html"
        result = audit(data, manifest, scope, corridors)
        self.assertTrue(any("不符合实体级直达规范" in e for e in result["errors"]), f"Unexpected: {result['errors']}")

    def test_english_artifact_clean_gate_checks(self):
        errors = []
        # Area explosion check
        polluted_text = "This area offers 12 days 11 area with area and area view. " + ("area " * 50) + "great sights."
        _check_english_text("TestArtifact", polluted_text, ["days area"], ["area"], 0.008, 0.001, errors)
        self.assertTrue(any("异常高频重复" in e or "占位符病句模板" in e for e in errors), f"Unexpected: {errors}")

        # CJK residue check
        cjk_errors = []
        cjk_polluted = "Welcome to Cebu Island. 这里有极度清澈的海水和美丽的珊瑚礁. Enjoy your trip!"
        _check_english_text("TestCJK", cjk_polluted, [], ["area"], 0.008, 0.001, cjk_errors)
        self.assertTrue(any("中文残留超标" in e for e in cjk_errors), f"Unexpected: {cjk_errors}")


if __name__ == "__main__":
    unittest.main()
