import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import datetime
import json
import unittest
from formal_data_gate import audit


def fixture():
    today_str = datetime.date.today().isoformat()
    routes = [
        ["路线1", "3天", "A→B", "特色1", "适合1", "3000", "专车", "Route 1"],
        ["路线2", "3天", "A→C", "特色2", "适合2", "3200", "专车", "Route 2"],
        ["路线3", "3天", "A→D", "特色3", "适合3", "3500", "专车", "Route 3"],
    ]
    itinerary = []
    spots = [("景点", "景点A", "1,1"), ("景点", "景点B", "1.7,1.7"), ("住宿", "住宿一", "1.11,1.11")]
    for route in routes:
        for day in range(1, 4):
            cat, spot_name, sp_coords = spots[day - 1]
            itinerary.append([route[0], f"Day {day}", 1, cat, spot_name, sp_coords])
            if day == 1:
                itinerary.append([route[0], f"Day {day}", 2, "交通", "A→B", "1,1"])
    poi = {
        "hotels": [["A", "住宿一", "Hotel 1", "hotel", "", "", "", "1.11,1.11", "", ""],
                   ["A", "住宿二", "Hotel 2", "hotel", "", "", "", "1.12,1.12", "", ""]] +
                  [["A", f"住宿{i}", f"Hotel {i}", "hotel", "", "", "", f"1.1{i},1.1{i}", "", ""] for i in range(3, 9)],
        "restaurants": [["A", "餐厅一", "Restaurant 1", "food", "", "", "", "1.21,1.21", "", ""],
                        ["A", "餐厅二", "Restaurant 2", "food", "", "", "", "1.22,1.22", "", ""]] +
                       [["A", f"餐厅{i}", f"Restaurant {i}", "food", "", "", "", f"1.2{i},1.2{i}", "", ""] for i in range(3, 13)],
        "cafes": [["A", "咖啡一", "Cafe 1", "cafe", "", "", "", "1.31,1.31", "", ""]] +
                 [["A", f"咖啡{i}", f"Cafe {i}", "cafe", "", "", "", f"1.3{i},1.3{i}", "", ""] for i in range(2, 7)],
        "attractions": [["A", "景点A", "Sight A", "sight", "", "", "1,1", "", ""],
                        ["A", "景点B", "Sight B", "sight", "", "", "1.7,1.7", "", ""]] +
                       [["A", f"景点{i}", f"Sight {i}", "sight", "", "", f"1.4{i},1.4{i}", "", ""] for i in range(3, 11)],
        "dive_sites": [],
    }
    evidence = [[str(index), "A", row[1], f"https://example.com/poi/{index}"] for index, row in enumerate(sum(poi.values(), []), 1)]
    evidence_meta = []
    map_targets = {}
    for index, row in enumerate(sum(poi.values(), []), 1):
        for provider, host in (("official", "example.com"), ("tourism_board", "tourism.example")):
            # ZH-RELEASE-1（业主 2026-11-02 裁 Q2-A）：读者来源面＝source_evidence_meta 的校验投影，
            # 字段集是 references/data-model.json 登记的闭集（scripts/source_projection.py::REQUIRED_FIELDS）。
            # 旧夹具带的 evidence_id 属于十列位置面、且缺 retrieved_at/notes，投影层按未注册形状阻断，
            # 所以夹具改成注册形状——断言一条没动，变的只是夹具是否合法。
            evidence_meta.append({"destination": "A", "name": row[1],
                                  "url": f"https://{host}/poi/{index}", "source_provider": provider,
                                  "evidence_level": "direct_entity", "verification_status": "verified",
                                  "retrieved_at": today_str, "cross_source_review": "pass",
                                  "notes": "fixture: 双源交叉复核通过"})
        coords = row[7] if len(row) > 7 and row[7] else (row[6] if len(row) > 6 and row[6] else f"1.{index},1.{index}")
        map_targets[f"A|{row[1]}"] = {"canonical_name": row[1], "destination": "A", "country": "Country Z", "entity_type": "named_entity",
                                      "target_level": "verified_coordinate", "verification_status": "verified",
                                      "coords": coords, "source_url": f"https://example.com/poi/{index}",
                                      "checked_at": today_str, "qa_evidence": "evidence/maps.json"}
    for name, coords in (("A站", "1,1"), ("B站", "2,2")):
        map_targets[f"A|{name}"] = {"canonical_name": name, "destination": "A", "country": "Country Z", "entity_type": "named_entity",
                                      "target_level": "verified_coordinate", "verification_status": "verified",
                                      "coords": coords, "source_url": "https://example.com/station/" + name,
                                      "checked_at": today_str, "qa_evidence": "evidence/maps.json"}
    transport = [["A→B", "shuttle", "Operator", "", "1h", "预约出行", "1,1", "2,2", "", "", "", "verified",
                  "A站", "B站", "", "", "on_demand", "", "", today_str, "", "", "", ""]]
    budget_row1 = ["Day 1", "2027-02", "Plan", 1000, 1000, 500, 500, 0, 3000]
    budget_row2 = ["Day 1", "2027-02", "Plan", 1100, 1000, 600, 500, 0, 3200]
    budget_row3 = ["Day 1", "2027-02", "Plan", 1200, 1100, 700, 500, 0, 3500]
    th_fixture = Path(__file__).resolve().parent.parent / "fixtures" / "thailand_local_apps.json"
    loaded_apps = json.loads(th_fixture.read_text(encoding="utf-8"))
    local_apps = loaded_apps["local_apps"] if isinstance(loaded_apps, dict) and "local_apps" in loaded_apps else loaded_apps
    for a in local_apps:
        a["country"] = "Country Z"
        a["destinations"] = ["A"]
        a["verified_at"] = today_str
    data = {"routes": routes, "itinerary": itinerary, "destinations": [["A"]], **poi, "source_evidence": evidence,
            "source_evidence_meta": evidence_meta, "map_targets": map_targets,
            "worth_it": [["A"]], "local_chains": [["A"]], "packing": [["A"]], "local_knowledge": [["A"]],
            "local_apps": local_apps,
            "editorial_media": [{}, {}, {}, {}, {}, {}], "section_media": [{}], "image_collection": {"section_media_required": True},
            "transport": transport, "transport_nodes": [["A", "A站", "Station A", "station", "1,1", "verified"], ["A", "B站", "Station B", "station", "2,2", "verified"]],
            "budget": [budget_row1],
            "budget_meta": {"base_currency": "CNY", "rate_status": "VERIFIED",
                            "rates": {"CNY": 1.0, "USD": 0.14},
                            "rate_source": "fixture: 测试夹具登记来源（示例，非商业报价）",
                            "rate_date": "2026-10-15"},
            "route_budgets": {"路线1": [budget_row1], "路线2": [budget_row2], "路线3": [budget_row3]}}
    manifest = {"skill_version": "5.0.0", "intake": {"q0_destination": "Country Z", "q1_time": "2027-02", "q2_days": 3, "q3_tier": "midrange",
                           "q4_transport": "non-self-drive", "q5_arrival": "Gateway A", "q6_departure": "Gateway A", "q7_depth": "deep", "q8_pace": "relaxed"},
                "research_passes": ["route_critical_facts", "material_dynamic_facts", "cross_source_review"],
                "research_pass_evidence": {"route_critical_facts": ["https://example.com/route"], "material_dynamic_facts": ["https://example.com/dynamic"], "cross_source_review": ["https://example.com/cross-check"]},
                "destination_profile": {"scope_type": "country", "geography": ["continental"], "mobility_modes": ["rail", "road"], "map_region": "international", "candidate_pool_count": 12, "coverage_boundary": "national gateways and regions", "data_availability": {"official_timetables": "mixed"}, "uncertainties": [{"topic": "season"}]}}
    scope = {"selected_destinations": [{"name": "A", "status": "included"}]}
    corridors = {"corridors": [{"corridor_id": str(i), "continuity": 100, "edge_audit": [{"documented": True}]} for i in range(3)]}
    assets = {"assets": [{"verification_status": "verified"}]}
    return data, manifest, scope, corridors, assets


class FormalDataGateTests(unittest.TestCase):
    def test_valid_contract(self):
        self.assertEqual(audit(*fixture())["status"], "PASS")

    def test_unsourced_rate_claim_blocks_the_run(self):
        """v4.2.2 V5-B（V0-L05）：没有出处的汇率不能自称已核验，也不能留着数值蒙混。"""
        data, manifest, scope, corridors, assets = fixture()
        data["budget_meta"] = {"base_currency": "CNY", "rate_status": "VERIFIED",
                               "rates": {"CNY": 1.0, "USD": 0.14}}
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(error.startswith("FX_VERIFIED_WITHOUT_PROVENANCE")
                            for error in result["errors"]), result["errors"][:6])

    def test_honest_unregistered_rate_passes(self):
        """缺登记不是罪：如实写 UNREGISTERED 且不留下数值，页面按原币种显示即可通过。"""
        data, manifest, scope, corridors, assets = fixture()
        data["budget_meta"] = {"base_currency": "CNY", "rate_status": "UNREGISTERED", "rates": {}}
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual([error for error in result["errors"] if error.startswith("FX_")], [],
                         result["errors"][:6])

    def test_rejects_single_route_and_empty_media(self):
        data, manifest, scope, corridors, assets = fixture()
        data["routes"] = data["routes"][:1]
        data["editorial_media"] = []
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("至少需要" in error for error in result["errors"]))
        self.assertTrue(any("媒体不足" in error for error in result["errors"]))

    def test_rejects_invented_dates_and_on_demand_timetable(self):
        data, manifest, scope, corridors, assets = fixture()
        data["budget"][0][1] = "2027-02-08"
        data["transport"] = [["A→B", "专车", "Operator", "", "1h", "预约出行", "1,1", "2,2", "", "", "", "verified", "A", "B", "", "", "published_reference", "", "", "", "", "", "09:00", "10:00"]]
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("补造具体日期" in error for error in result["errors"]))
        self.assertTrue(any("误标" in error for error in result["errors"]))

    def test_research_depths_are_distinct_and_unknown_depth_fails(self):
        data, manifest, scope, corridors, assets = fixture()
        manifest["intake"]["q7_depth"] = "standard"
        manifest["research_passes"] = ["route_critical_facts", "material_dynamic_facts"]
        manifest["research_pass_evidence"] = {"route_critical_facts": ["https://example.com/route"], "material_dynamic_facts": ["https://example.com/dynamic"]}
        data["editorial_media"] = data["editorial_media"][:4]
        self.assertEqual(audit(data, manifest, scope, corridors, assets)["status"], "PASS")
        manifest["intake"]["q7_depth"] = "concise"
        manifest["research_passes"] = ["route_critical_facts"]
        manifest["research_pass_evidence"] = {"route_critical_facts": ["https://example.com/route"]}
        data["editorial_media"] = data["editorial_media"][:3]
        self.assertEqual(audit(data, manifest, scope, corridors, assets)["status"], "PASS")
        manifest["intake"]["q7_depth"] = "invalid_depth"
        self.assertTrue(any("未知 Q7 研究深度" in error for error in audit(data, manifest, scope, corridors, assets)["errors"]))
        manifest["intake"]["q7_depth"] = "ultra"
        self.assertFalse(any("未知 Q7 研究深度" in error for error in audit(data, manifest, scope, corridors, assets)["errors"]))

    def test_standard_rejects_all_designed_no_photo_sections(self):
        data, manifest, scope, corridors, assets = fixture()
        manifest["intake"]["q7_depth"] = "standard"
        manifest["research_passes"] = ["route_critical_facts", "material_dynamic_facts"]
        manifest["research_pass_evidence"] = {"route_critical_facts": ["evidence/route.json"], "material_dynamic_facts": ["evidence/dynamic.json"]}
        data["editorial_media"] = data["editorial_media"][:4]
        data["section_media"] = [{"selection_level": "designed_no_photo_state"} for _ in range(5)]
        result = audit(data, manifest, scope, corridors, assets)
        self.assertTrue(any("设计缺图状态占比" in error for error in result["errors"]))

    def test_unencoded_chinese_url_and_synthetic_platform_id_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        # Test Chinese in path
        data["source_evidence_meta"][0]["url"] = "https://hotels.ctrip.com/hotels/detail/天骄宾馆.html"
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("实体独立直达来源不足" in error or "缺少实体级直达来源证据" in error for error in result["errors"]))

    def test_silent_intercity_teleportation_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        # Add another destination B
        scope["selected_destinations"].append({"name": "B", "status": "included"})
        data["destinations"].append(["B"])
        data["hotels"].append(["B", "B城住宿", "Hotel B", "hotel", "", "", "", "2.1,2.1", "", ""])
        data["source_evidence_meta"].append({"destination": "B", "name": "B城住宿",
                                             "url": "https://example.com/hotels/999.html", "source_provider": "official",
                                             "evidence_level": "direct_entity", "verification_status": "verified",
                                             "retrieved_at": "2026-09-12", "cross_source_review": "pass",
                                             "notes": "fixture: 目的地 B 的实体直达来源"})
        data["map_targets"]["B|B城住宿"] = {"canonical_name": "B城住宿", "destination": "B", "country": "Country Z", "entity_type": "named_entity",
                                          "target_level": "verified_coordinate", "verification_status": "verified",
                                          "coords": "2.1,2.1", "source_url": "https://example.com/hotels/999.html",
                                          "checked_at": "2026-09-12", "qa_evidence": "evidence/maps.json"}
        # Day 1 in A, Day 2 switches to B城住宿, but remove transit
        data["itinerary"] = [
            ["路线1", "Day 1", 1, "住宿", "住宿一", "1.11,1.11"],
            ["路线1", "Day 2", 1, "住宿", "B城住宿", "2.1,2.1"],
            ["路线1", "Day 3", 1, "住宿", "B城住宿", "2.1,2.1"],
            ["路线2", "Day 1", 1, "住宿", "住宿一", "1.11,1.11"],
            ["路线2", "Day 2", 1, "住宿", "住宿一", "1.11,1.11"],
            ["路线2", "Day 3", 1, "住宿", "住宿一", "1.11,1.11"],
            ["路线3", "Day 1", 1, "住宿", "住宿一", "1.11,1.11"],
            ["路线3", "Day 2", 1, "住宿", "住宿一", "1.11,1.11"],
            ["路线3", "Day 3", 1, "住宿", "住宿一", "1.11,1.11"],
        ]
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("缺失显式连接交通" in error for error in result["errors"]))

    def test_sequential_numbered_urls_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        data["source_evidence_meta"][0]["url"] = "https://example.com/dest/my-kuala-lumpur-0001.html"
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("缺少实体级直达来源证据" in error or "实体独立直达来源不足" in error for error in result["errors"]))

    def test_domain_category_mismatch_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        # Mismatch: Hotel citing MyRapid (transit domain)
        data["source_evidence_meta"][0]["url"] = "https://myrapid.com.my/hotels/detail/99"
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("来源域名角色错配" in error for error in result["errors"]))

    def test_arithmetic_progression_urls_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        # Inject arithmetic progression IDs with constant step +173
        base_id = 204902
        for i in range(5):
            data["source_evidence_meta"][i]["url"] = f"https://hotels.ctrip.com/hotels/detail/{base_id + i * 173}.html"
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("等差递增步长" in error for error in result["errors"]))

    def test_self_drive_fixed_schedule_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        manifest["intake"]["q4_transport"] = "自驾"
        # Self-drive route with fixed departure times
        data["transport"][0] = [
            "A→B", "租车自驾", "Operator", "", "1h", "预约出行", "1,1", "2,2", "", "", "", "verified",
            "A站", "B站", "", "", "published_reference", "", "", "2026-09-12", "", "", "08:00", "10:00"
        ]
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("自驾/租车路线严禁伪造固定发车时刻" in error or "自驾/租车路线状态必须为 on_demand" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
