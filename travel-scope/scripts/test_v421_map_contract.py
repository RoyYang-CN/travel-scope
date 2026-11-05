# -*- coding: utf-8 -*-
"""v4.2.1 §17 W1 — map contract static consistency and schema validation tests.

Scope discipline: this file tests the *contract layer* only (`references/*.json`, `references/*.md`,
`scripts/data_model.py`). The SKILL.md / VERSION.md phrase scan is deliberately NOT here -- those two
files are synchronised in W8 per §17.7, and asserting their text today would either fail honestly and
break the component baseline or pass by editing the claim first. Both are worse than a stated NOT RUN.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
import data_model  # noqa: E402
import map_contract  # noqa: E402  W2R2：名称判定在两处必须同结论，跨模块比对在本文件锁

PRODUCTION_POLICY = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
POLICY = copy.deepcopy(PRODUCTION_POLICY)
# W1R-B2: positive fixture tests use an explicit test-only policy. Production policy keeps
# pending real adapters out of identity verdicts and rejects .example adapters even as surfaces.
_test_classifier = POLICY["url_reference_classifier"]
_test_classifier["surface_eligible_approval_statuses"] = list(dict.fromkeys(
    list(_test_classifier["surface_eligible_approval_statuses"])
    + ["contract_fixture_only_not_for_shipment"]))
_test_classifier["identity_eligible_approval_statuses"] = list(dict.fromkeys(
    list(_test_classifier["identity_eligible_approval_statuses"])
    + ["measured_in_frozen_input_pending_terms_check", "contract_fixture_only_not_for_shipment"]))
CONTRACT = json.loads((ROOT / "references" / "renderer-contract.json").read_text(encoding="utf-8"))
# v4.2.2 §13: the value comes from the selection config, not from a literal in the test, so a
# fixture can never silently attest a different selection machine than the one shipping.
MAP_SELECTION = json.loads((ROOT / "references" / "map-link-selection.json").read_text(encoding="utf-8"))
MAP_LINK_POLICY = (ROOT / "references" / "map-link-policy.md").read_text(encoding="utf-8")
EVIDENCE_POLICY = (ROOT / "references" / "evidence-policy.md").read_text(encoding="utf-8")
CAFES = (ROOT / "references" / "cafes.md").read_text(encoding="utf-8")
MIGRATION = (ROOT / "references" / "map-contract-migration.md").read_text(encoding="utf-8")


def target(**override):
    """One complete §17.2.5 target. Defaults are the *honest* states, not convenient ones."""
    base = {
        "target_id": "t-1",
        "entity_type": "named_entity",
        "category": "hotel",
        "criticality": "IMPORTANT",
        "required_location_role": "MAIN_ENTRANCE",
        "display_name": "Grand Hotel Cebu",
        "names": {"en": "Grand Hotel Cebu", "cn": "宿务大酒店"},
        "country_code": "PH",
        "destination_scope": "宿务",
        "address_status": "VERIFIED",
        "identity_status": "UNVERIFIED",
        "coordinate_status": "MISSING",
        "link_mode": "NAMED_SEARCH",
        "link_provider": "google",
        "link_builder_version": "linkbuilder-0",
        "link_selection_reason": "no publisher entity link collected yet",
        "classifier_version": "refclassifier-4",
        "link_selection_version": MAP_SELECTION["selection_version"],
        "google_resolution_status": "NOT_OBSERVED",
        "evidence": [{"source_type": "official_area_reference",
                      "source_url_or_ref": "https://tourism.example.gov/ph/cebu",
                      "retrieved_at": "2026-10-26", "supported_fields": ["destination_scope"],
                      "lineage_group": "lg-tourism-board", "content_digest": "sha256:abc",
                      "usage_scope": "background", "status": "complete"}],
        "lineage_group": "lg-1",
        "resolver_used": False,  # v4.2.2 V1R：正式链不用 W3 resolver，显式 false，不写版本号
        "policy_version": "v4.2.1-w1",
        "evaluated_at": "2026-10-26",
    }
    base.update(override)
    return base


class ContractShapeTests(unittest.TestCase):
    def test_four_dimensions_are_enumerated_exactly_as_the_contract(self):
        self.assertEqual(POLICY["identity_status"],
                         ["UNVERIFIED", "VERIFIED", "AMBIGUOUS", "CONFLICT", "UNRESOLVED", "STALE"])
        self.assertEqual(POLICY["coordinate_status"],
                         ["MISSING", "UNVERIFIED", "VERIFIED", "CONFLICT", "STALE"])
        self.assertEqual(POLICY["link_mode"],
                         ["PUBLISHER_ENTITY_LINK", "NAMED_SEARCH", "COORDINATE", "NONE"])
        self.assertEqual(POLICY["google_resolution_status"],
                         ["NOT_OBSERVED", "CORRECT_ENTITY", "MULTIPLE_RESULTS", "WRONG_ENTITY",
                          "NO_RESULT", "BLOCKED", "STALE"])

    def test_required_fields_are_the_contract_list_not_a_shorter_copy(self):
        for field in ("target_id", "entity_type", "category", "criticality",
                      "display_name", "names", "country_code",
                      "destination_scope", "address_status", "identity_status",
                      "coordinate_status", "link_mode", "google_resolution_status",
                      "policy_version", "evaluated_at"):
            self.assertIn(field, POLICY["map_target_required_fields"])
        # v4.2.2 V1R：这三项没有消失，是换了语义位置——仍然必须被校验器覆盖。
        self.assertEqual(sorted(POLICY["map_target_explicit_empty_fields"]["fields"]),
                         ["evidence", "lineage_group"])
        self.assertIn("resolver_version", POLICY["map_target_conditional_fields"])
        # v4.2.2 V4-A（业主指令 §5）：required_location_role 也不是消失，是从「无条件必填」
        # 挪进「按类别适用矩阵条件必填」。它必须同时出现在条件字段表和适用矩阵里，
        # 少任何一边都算没接住。
        self.assertIn("required_location_role", POLICY["map_target_conditional_fields"])
        self.assertIn("required_location_role", POLICY["required_location_role_applicability"]
                      ["rule"] + POLICY["map_target_conditional_fields"]["required_location_role"]
                      ["required_when"])
        self.assertNotIn("required_location_role", POLICY["map_target_required_fields"])
        # W1R-B 把 classifier_version 加进来是 20；V1R 改判为 18；V4-A 再改判为 17：
        # evidence/lineage_group 改成「必须显式在场、允许显式为空」，resolver_version 条件必填，
        # required_location_role 按类别矩阵条件必填。
        self.assertEqual(len(POLICY["map_target_required_fields"]), 17)

    def test_legacy_levels_are_consistent_between_the_two_contract_files(self):
        # v4.2.1 W1 survey: data-model.json listed 4 levels while renderer-contract listed 5, and
        # map_contract.py raises on any drift. The two lists must be equal and marked non-authoritative.
        self.assertEqual(CONTRACT["presentation"]["map_target_levels"], POLICY["map_target_levels"])
        self.assertFalse(CONTRACT["presentation"]["map_target_levels_authority"])
        self.assertFalse(CONTRACT["presentation"]["live_map_minimum_level_authority"])
        self.assertFalse(POLICY["legacy_migration"]["legacy_mapping_authority"])

    def test_place_id_is_not_required_a_metric_or_a_gate(self):
        policy = POLICY["place_id_policy"]
        self.assertIs(policy["required"], False)
        self.assertIs(policy["is_coverage_metric"], False)
        self.assertIs(policy["is_release_gate"], False)
        self.assertEqual(policy["synthetic_or_regex_only"], "quarantine")

    def test_billing_counters_must_all_be_zero(self):
        billing = POLICY["billing"]
        self.assertIs(billing["google_apis_allowed"], False)
        for counter in ("google_billable_api_calls", "google_api_keys_used",
                        "google_maps_scrape_attempts", "paid_fallback_attempts"):
            self.assertEqual(billing["required_counter_values"][counter], 0)
            self.assertIn(counter, billing["reported_counters"])

    def test_render_contract_covers_every_link_mode_with_bilingual_labels(self):
        modes = CONTRACT["presentation"]["map_link_contract"]["link_modes"]
        self.assertEqual(sorted(modes), sorted(POLICY["link_mode"]))
        for mode, row in modes.items():
            if mode == "NONE":
                self.assertIs(row["render_button"], False)
                continue
            self.assertTrue(row.get("label_cn") and row.get("label_en"), f"{mode} 缺双语文案")
            self.assertTrue(row.get("forbids") or row.get("forbidden_labels")
                            or row.get("allowed_only_when"), f"{mode} 缺可执行约束")
        self.assertNotIn("render_button", modes["COORDINATE"])
        self.assertIs(modes["COORDINATE"]["named_entity_may_render"], False)

    def test_dom_audit_attributes_are_the_six_contract_fields(self):
        attrs = CONTRACT["presentation"]["map_link_contract"]["dom_audit_attributes"]
        for attr in ("data-target-id", "data-entity-type", "data-identity-status",
                     "data-coordinate-status", "data-link-mode",
                     "data-google-resolution-status"):
            self.assertIn(attr, attrs)


class PolicyTextTests(unittest.TestCase):
    """§17.7 W1 also has to *delete* conflicting rules, not only add new ones."""

    def test_map_link_policy_dropped_the_old_obligations(self):
        for forbidden in ("保存实体标题、地址/坐标和落点截图",
                          "Google Places 付费媒体流程保持禁用，除非另有合规授权",
                          "Place ID 必须是真实",
                          "Live 成品不允许 search_candidate"):
            self.assertNotIn(forbidden, MAP_LINK_POLICY, f"旧规则未删除: {forbidden}")

    def test_map_link_policy_states_the_new_boundaries(self):
        for required in ("NOT_OBSERVED", "命名实体永不显示纯坐标按钮", "零自证循环",
                         "零 Google Billing/API/Key", "零 Google Maps 抓取",
                         "不是必填字段、不是覆盖率指标、不是发布门槛"):
            self.assertIn(required, MAP_LINK_POLICY, f"新规则缺失: {required}")

    def test_cafes_no_longer_routes_overseas_discovery_through_google_places(self):
        self.assertIn("no API key", CAFES)
        self.assertNotIn("Google Places for overseas destinations", CAFES)
        self.assertNotIn("Overseas images use the shared collector", CAFES)

    def test_evidence_policy_carries_the_minimal_field_list(self):
        for field in POLICY["evidence_required_fields"]:
            self.assertIn(field, EVIDENCE_POLICY)
        self.assertIn("只算**一个血缘组**", EVIDENCE_POLICY)
        self.assertIn("不得默认成为生产依赖", EVIDENCE_POLICY)
        self.assertIn("SOURCE_ERROR", EVIDENCE_POLICY)

    def test_migration_doc_lists_forbidden_mappings_and_measured_start(self):
        for mapping in POLICY["legacy_migration"]["forbidden_auto_mappings"]:
            source = mapping.split(" -> ")[0]
            if "=" not in source or source.strip() == "any":
                continue          # prose-only sources cannot be table-checked
            self.assertIn(source, MIGRATION, "禁止映射未写进迁移说明: %s" % mapping)
        self.assertIn("1 / 19", MIGRATION)


class MapTargetValidationTests(unittest.TestCase):
    def errors(self, one):
        return data_model.validate_map_targets({"t-1": one}, POLICY)

    def test_a_complete_honest_target_is_clean(self):
        self.assertEqual(self.errors(target()), [])

    def test_missing_required_fields_are_all_listed_not_the_first_one(self):
        broken = target()
        del broken["criticality"]
        del broken["country_code"]
        found = self.errors(broken)
        self.assertTrue(any(f.startswith("MAP_FIELD_MISSING") and "criticality" in f
                            and "country_code" in f for f in found),
                        "缺字段必须一次性全部报出，不得首中即停")

    def test_named_entity_can_never_ship_a_pure_coordinate_button(self):
        found = self.errors(target(link_mode="COORDINATE", coordinate_status="VERIFIED",
                                   lat=10.3, lng=123.9))
        self.assertTrue(any(f.startswith("LINK_NAMED_ENTITY_COORDINATE") for f in found))

    def test_coordinate_button_requires_verified_coordinates(self):
        found = self.errors(target(entity_type="coordinate_landmark", link_mode="COORDINATE",
                                   coordinate_status="UNVERIFIED", lat=10.3, lng=123.9))
        self.assertTrue(any(f.startswith("LINK_COORDINATE_UNVERIFIED") for f in found))

    def test_coordinate_verified_needs_datum_axis_source_and_precision(self):
        found = self.errors(target(coordinate_status="VERIFIED", lat=10.3, lng=123.9))
        self.assertTrue(any(f.startswith("COORD_CONTEXT_MISSING") for f in found))

    def test_missing_coordinates_must_stay_missing(self):
        self.assertEqual(self.errors(target()), [], "MISSING 是合法状态，不得被要求填值")
        found = self.errors(target(coordinate_status="UNVERIFIED"))
        self.assertTrue(any(f.startswith("COORD_ABSENT_BUT_CLAIMED") for f in found),
                        "没有坐标却记非 MISSING 状态即为谎报")
        found = self.errors(target(coordinate_status="VERIFIED", lat=34.0522, lng=-118.2437,
                                   datum="WGS84", axis_order="lat,lng",
                                   coordinate_source_ref="osm:node/1", precision_m=5))
        self.assertTrue(any(f.startswith("COORD_DEFAULT_VALUE") for f in found),
                        "已知默认坐标不得充当该地点位置")
        found = self.errors(target(coordinate_status="MISSING", lat=10.3, lng=123.9))
        self.assertTrue(any(f.startswith("COORD_STATE_CONTRADICTION") for f in found))

    def test_self_generated_map_url_cannot_be_evidence(self):
        for url in ("https://www.google.com/maps/search/?api=1&query=X",
                    "https://maps.apple.com/?q=X"):
            found = self.errors(target(evidence=[dict(target()["evidence"][0],
                                                      source_url_or_ref=url)]))
            self.assertTrue(any(f.startswith("EVIDENCE_SELF_ATTESTATION") for f in found), url)

    def test_homepage_and_search_urls_are_not_identity_evidence(self):
        # W1R-B1 ④：出处主机必须是登记过的来源，否则先撞上“未登记域名”这一层，
        # 就测不到 home / search 形状本身了。改用合同 fixture 主机专测这两种形状。
        for url, code in (("https://grandhotel.example/", "EVIDENCE_HOMEPAGE_ONLY"),
                          ("https://grandhotel.example/search?q=cebu", "EVIDENCE_SEARCH_URL")):
            found = self.errors(target(evidence=[dict(target()["evidence"][0],
                                                      source_url_or_ref=url)]))
            self.assertTrue(any(f.startswith(code) for f in found), url)

    def test_evidence_missing_fields_makes_it_unsupporting(self):
        row = copy.deepcopy(target()["evidence"][0])
        del row["content_digest"]
        del row["lineage_group"]
        found = self.errors(target(evidence=[row]))
        self.assertTrue(any(f.startswith("EVIDENCE_INCOMPLETE") for f in found))

    def test_verified_identity_requires_evidence_rule_version_and_time(self):
        found = self.errors(target(identity_status="VERIFIED", evidence=[]))
        self.assertTrue(any(f.startswith("IDENTITY_VERIFIED_WITHOUT_EVIDENCE") for f in found))
        complete = target(identity_status="VERIFIED",
                          evidence=[dict(target()["evidence"][0],
                                         source_type="official_entity_page",
                                         supported_fields=["display_name", "address"],
                                         address="Oslob, Cebu City, 6000")])
        self.assertEqual(self.errors(complete), [], "带官方实体页证据的 VERIFIED 应当干净")

    def test_publisher_entity_link_needs_a_publisher_evidence_row(self):
        found = self.errors(target(link_mode="PUBLISHER_ENTITY_LINK"))
        self.assertTrue(any(f.startswith("LINK_EVIDENCE_MISSING") for f in found))

    def test_google_observation_cannot_be_claimed_without_an_observation_record(self):
        found = self.errors(target(google_resolution_status="CORRECT_ENTITY"))
        self.assertTrue(any(f.startswith("GOOGLE_OBSERVATION_UNSANCTIONED") for f in found))
        recorded = target(google_resolution_status="CORRECT_ENTITY",
                          google_observation={"environment": "desktop-chrome-lab",
                                              "observed_at": "2026-10-26T10:00:00+08:00",
                                              "observed_by": "independent-auditor"})
        self.assertEqual(self.errors(recorded), [])

    def test_critical_target_must_be_identity_verified(self):
        found = self.errors(target(criticality="CRITICAL_ITINERARY"))
        self.assertTrue(any(f.startswith("CRITICAL_NOT_VERIFIED") for f in found))

    def test_illegal_enum_value_is_named(self):
        found = self.errors(target(identity_status="ALMOST_VERIFIED"))
        self.assertTrue(any(f.startswith("MAP_ENUM_INVALID") and "identity_status" in f
                            for f in found))

    def test_character_level_name_repair_is_still_a_placeholder(self):
        """v4.2.2 V1R：反删字的牙仍然咬模板串与数字残片；有来源的本地正式名称不再是错误。"""
        for name in ("California Venue, California, California", "518"):
            found = self.errors(target(display_name=name))
            self.assertTrue(any(f.startswith("NAME_PLACEHOLDER") for f in found), name)
        local = self.errors(target(display_name="宿务大酒店",
                                    names={"cn": "宿务大酒店"},
                                    link_mode="NAMED_SEARCH"))
        self.assertFalse([f for f in local if f.startswith(("NAME_CJK_IN_LINK", "NAME_PLACEHOLDER"))],
                         "本地正式名称被拒说明 §4 line 102 的放开没有真正落到校验器：%s" % local)

    def test_pure_numeric_residue_is_still_rejected(self):
        """W2R：数字残片必须继续被拒——整串只有数字与分隔符。"""
        for name in ("39", "17", "518", "17, 20", "17.5", " 2026 "):
            found = self.errors(target(display_name=name))
            self.assertTrue(any(f.startswith("NAME_PLACEHOLDER") for f in found),
                            "%s 应判为数字残片，实际 %s" % (name, found))

    def test_digit_led_real_names_are_not_numeric_residue(self):
        """W2R：真实以数字开头的店名不得仅因数字前缀被拒（旧正则误伤 2 Story Kitchen）。"""
        for name in ("2 Story Kitchen", "7-Eleven", "21 Choices", "1367 Coffee Roasters",
                     "39号码头"):
            found = self.errors(target(display_name=name))
            self.assertFalse(any(f.startswith("NAME_PLACEHOLDER") for f in found),
                             "%s 被误判为数字残片：%s" % (name, found))

    def test_numeric_residue_regex_shape_is_directly_locked(self):
        self.assertIsNotNone(data_model.NUMERIC_RESIDUE_RE.match("39"))
        self.assertIsNotNone(data_model.NUMERIC_RESIDUE_RE.match("17, 20"))
        self.assertIsNone(data_model.NUMERIC_RESIDUE_RE.match("2 Story Kitchen"))
        self.assertIsNone(data_model.NUMERIC_RESIDUE_RE.match("7-Eleven"))
        self.assertIsNone(data_model.NUMERIC_RESIDUE_RE.match("21 Choices"))
        self.assertIsNone(data_model.NUMERIC_RESIDUE_RE.match("39号码头"))

    # ---- W2R2 第 4 条：占位名判定改成配置驱动的精确清单 -------------------------------

    def test_placeholder_policy_is_config_driven_and_exact(self):
        """正负样本都从 policy 清单读，不在测试里另写一套判定口径。"""
        block = PRODUCTION_POLICY["name_placeholder_policy"]
        for name in block["known_good_names_must_pass"]:
            self.assertFalse(data_model.is_placeholder_name(name),
                             "%r 是真实名称，被误判为占位" % name)
            self.assertFalse(any(f.startswith("NAME_PLACEHOLDER")
                                 for f in self.errors(target(display_name=name))),
                             "%r 在校验器里仍被拒" % name)
        for name in block["known_bad_names_must_fail"]:
            self.assertTrue(data_model.is_placeholder_name(name),
                            "%r 是占位/旧模板值，却被放行" % name)
            self.assertTrue(any(f.startswith("NAME_PLACEHOLDER")
                                for f in self.errors(target(display_name=name))),
                            "%r 在校验器里没被拦：%s" % (name, self.errors(target(display_name=name))))

    def test_legacy_template_california_venue_still_rejected_by_registry(self):
        self.assertIn("California Venue",
                      PRODUCTION_POLICY["name_placeholder_policy"]["legacy_template_values"])
        self.assertTrue(data_model.is_placeholder_name("California Venue"))
        self.assertTrue(data_model.is_placeholder_name("california venue"))
        self.assertTrue(data_model.is_placeholder_name("  California   Venue  "))
        self.assertTrue(data_model.is_placeholder_name("California Venue, California, California"))

    def test_no_second_placeholder_implementation_survives(self):
        """分叉必须真的删掉，而不是留着没人用的第二套正则。"""
        for module in (data_model, map_contract):
            self.assertFalse(hasattr(module, "PLACEHOLDER_NAME_RE"),
                             "%s 还带着占位名正则" % module.__name__)
        self.assertFalse(hasattr(map_contract, "NUMERIC_RESIDUE_RE"))
        self.assertFalse(hasattr(map_contract, "CJK_NAME_RE"))

    def test_data_model_and_map_contract_never_disagree_on_a_name(self):
        """业主门槛：同一个名称在两处不得得到相反结论。"""
        probes = (["California Venue", "Venue", "Location", "Place", "Point", "Spot", "Unnamed",
                   "POI", "TODO", "N/A", "TBD", "未命名", "待定", "39", "17", "518", "17, 20",
                   "宿务大酒店", "日本語カフェ", "한국어명소", "Alfred Coffee Melrose Place",
                   "Ragged Point Vista Point", "Point Reyes", "The Venue at the Nassau Inn",
                   "Marketplace", "2 Story Kitchen", "7-Eleven", "", "  "])
        for name in probes:
            with self.subTest(name=name):
                self.assertEqual(map_contract.is_manufactured_name(name),
                                 data_model.is_manufactured_name(name))
                usable = map_contract.usable_entity_name(name)
                reject = bool(data_model.is_manufactured_name(name)
                              or data_model.CJK_RE.search(name) or not name.strip())
                self.assertEqual(bool(usable), not reject)

    def test_missing_placeholder_config_fails_loudly(self):
        """配置缺失不能静默降级成"什么名字都放行"。"""
        for broken in ({}, {"name_placeholder_policy": {}},
                       {"name_placeholder_policy": {"exact_placeholder_values": ["Venue"],
                                                    "legacy_template_values": []}}):
            with self.assertRaises(ValueError):
                data_model.is_placeholder_name("California Venue", broken)

    def test_legacy_fields_without_a_migration_trail_are_reported(self):
        found = self.errors(target(target_level="verified_coordinate", verification_status="verified"))
        self.assertTrue(any(f.startswith("LEGACY_MIGRATION_UNDOCUMENTED") for f in found))
        with_trail = target(target_level="verified_coordinate",
                            migration={"from": {"target_level": "verified_coordinate"},
                                       "reason_code": "LEGACY_COORDINATE_ONLY",
                                       "migrated_at": "2026-10-26", "policy_version": "v4.2.1-w1"})
        self.assertEqual(self.errors(with_trail), [])

    def test_legacy_verified_coordinate_may_not_imply_identity_verified(self):
        found = self.errors(target(identity_status="VERIFIED",
                                   target_level="verified_coordinate",
                                   evidence=[dict(target()["evidence"][0],
                                                  source_type="publisher_entity_page")],
                                   migration={"reason_code": "LEGACY_COORDINATE_ONLY"}))
        self.assertTrue(any(f.startswith("LEGACY_AUTO_MAPPING_FORBIDDEN") for f in found))

    def test_absent_place_id_is_never_a_failure_and_present_one_needs_provenance(self):
        self.assertEqual(self.errors(target()), [], "没有 Place ID 不得成为缺陷")
        found = self.errors(target(google_place_id="ChIJabc123"))
        self.assertTrue(any(f.startswith("PLACE_ID_UNPROVENANCED_QUARANTINE") for f in found))
        self.assertFalse(any("REQUIRED" in f for f in found))

    def test_non_dict_target_is_reported_not_crashed(self):
        found = data_model.validate_map_targets({"t-1": "just a string"}, POLICY)
        self.assertTrue(any(f.startswith("MAP_TARGET_NOT_OBJECT") for f in found))


class W1RHardeningTests(unittest.TestCase):
    """§17.7 W1R：独立复核发现的五个合同校验空洞，逐个补负测。"""

    errors = MapTargetValidationTests.errors

    # ① 容器与非对象成员：不得在进入逐项校验前崩溃
    def test_non_object_member_in_a_list_is_reported_not_crashed(self):
        found = data_model.validate_map_targets([target(), "just a string", None, 42], POLICY)
        codes = [f.split("|")[0] for f in found]
        self.assertEqual(codes.count("MAP_TARGET_NOT_OBJECT"), 3, found)
        self.assertTrue(all(f.startswith("MAP_TARGET_NOT_OBJECT") or "t-1" not in f for f in found))

    def test_container_that_is_neither_dict_nor_list_is_named(self):
        for bad in ("map targets", 7, None):
            found = data_model.validate_map_targets(bad, POLICY)
            self.assertTrue(any(f.startswith("MAP_TARGETS_CONTAINER_INVALID") for f in found), repr(bad))

    # ② VERIFIED 的证据必须自身合格，区域背景证据不得放行
    def test_regional_background_evidence_cannot_endorse_verified_identity(self):
        found = self.errors(target(identity_status="VERIFIED",
                                   evidence=[dict(target()["evidence"][0],
                                                  source_type="official_area_reference",
                                                  supported_fields=["destination_scope"])]))
        self.assertTrue(any(f.startswith("IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE")
                            for f in found), found)

    def test_unusable_or_ineligible_evidence_status_and_type_are_refused(self):
        for change, code in (
                ({"status": "expired"}, "EVIDENCE_STATUS_UNUSABLE"),
                ({"source_type": "search_result"}, "IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE"),
                ({"source_type": "entity_page_v2"}, "EVIDENCE_SOURCE_TYPE_UNKNOWN"),
                ({"supported_fields": ["destination_scope"]},
                 "IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE"),
                ({"supported_fields": ["country_code"]},
                 "IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE"),
                ({"supported_fields": ["category"]},
                 "IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE"),
                ({"supported_fields": ["display_name"]},
                 "IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE")):
            row = dict(target()["evidence"][0])
            row.update(change)
            if change.get("source_type") == "entity_page_v2":
                row["source_type"] = "entity_page_v2"
            found = self.errors(target(identity_status="VERIFIED", evidence=[row]))
            self.assertTrue(any(f.startswith(code) for f in found),
                            "%s -> %s" % (change, found))

    def test_a_qualified_identity_evidence_row_is_clean(self):
        row = dict(target()["evidence"][0], source_type="official_entity_page",
                   supported_fields=["display_name", "address"],
                   address="Oslob, Cebu City, 6000")  # name + disambiguator (W1R-A ③ / W1R-B ③)
        self.assertEqual(self.errors(target(identity_status="VERIFIED", evidence=[row])), [])

    # ③ PUBLISHER_ENTITY_LINK 必须由实际发布关系与 provider 支撑，不能靠 source_type 字样
    def publisher_row(self, **over):
        row = {"source_type": "publisher_entity_page",
               "source_url_or_ref": "https://grandhotel.example/cebu",
               "retrieved_at": "2026-10-26", "supported_fields": ["display_name"],
               "lineage_group": "lg-pub", "content_digest": "sha256:def", "usage_scope": "link",
               "status": "complete",
               "declared_link_url": "https://www.google.com/maps/place/grand-hotel-cebu/@10.3,123.9,17z/data=!3m1!4b1",
               "link_url_provider": "google"}
        row.update(over)
        return row

    def test_substring_source_type_does_not_buy_an_entity_link(self):
        for fake in ("our publisher-ish page", "entity_page_v2", "Publisher"):
            found = self.errors(target(link_mode="PUBLISHER_ENTITY_LINK", link_provider="google",
                                       evidence=[self.publisher_row(source_type=fake)]))
            self.assertTrue(any(f.startswith("LINK_EVIDENCE_MISSING") for f in found),
                            "%s -> %s" % (fake, found))

    def test_publisher_link_requires_declared_url_and_provider(self):
        missing_declared = self.errors(target(link_mode="PUBLISHER_ENTITY_LINK", link_provider="google",
                                              evidence=[self.publisher_row(declared_link_url="")]))
        self.assertTrue(any(f.startswith("LINK_EVIDENCE_MISSING") for f in missing_declared))
        bogus_url = self.errors(target(link_mode="PUBLISHER_ENTITY_LINK", link_provider="google",
                                       evidence=[self.publisher_row(
                                           declared_link_url="https://grandhotel.example/cebu")]))
        self.assertTrue(any(f.startswith("LINK_DECLARED_URL_INVALID") for f in bogus_url))
        mismatch = self.errors(target(link_mode="PUBLISHER_ENTITY_LINK", link_provider="apple",
                                      evidence=[self.publisher_row(link_url_provider="google")]))
        self.assertTrue(any(f.startswith("LINK_EVIDENCE_PROVIDER_MISMATCH") for f in mismatch), mismatch)

    def test_a_properly_supported_publisher_link_is_clean(self):
        self.assertEqual(self.errors(target(link_mode="PUBLISHER_ENTITY_LINK", link_provider="google",
                                            link_builder_version="linkbuilder-0",
                                            link_selection_reason="publisher declared it",
                                            evidence=[self.publisher_row()])), [])

    # ④ 坐标必须是有限数值且在域内
    def test_coordinate_garbage_and_out_of_range_are_refused(self):
        cases = [
            ({"lat": "10.3,123.9", "lng": None}, "lat", "字符串化的坐标对"),
            ({"lat": "abc", "lng": "123.9"}, "lat", "非数值"),
            ({"lat": float("nan"), "lng": 123.9}, "lat", "NaN"),
            ({"lat": 10.3, "lng": float("inf")}, "lng", "无穷"),
            ({"lat": 200.0, "lng": 123.9}, "lat", "超出 ±90"),
            ({"lat": 10.3, "lng": 1900.0}, "lng", "超出 ±180"),
            ({"lat": True, "lng": 123.9}, "lat", "布尔"),
            ({"lat": "10.3", "lng": "123.9"}, "lat", "字符串数字"),
        ]
        for change, offender, hint in cases:
            row = target(coordinate_status="UNVERIFIED")
            row.update(change)
            found = [f for f in self.errors(row) if f.startswith("COORD_VALUE_INVALID")]
            self.assertTrue(found, "%s 未被拒绝（期望含 %s）" % (change, hint))
            self.assertIn(offender, found[0], "%s 应点名 %s，实报 %s" % (change, offender, found[0]))

    def test_valid_coordinates_stay_clean(self):
        row = target(coordinate_status="VERIFIED", lat=10.3014, lng=123.8916, datum="WGS84",
                     axis_order="lat,lng", coordinate_source_ref="licensed_open_data:node/1",
                     precision_m=12)
        self.assertEqual(self.errors(row), [])

    # ⑤ names 精确结构 + target_id 唯一性与键一致性
    def test_names_structure_is_frozen(self):
        cases = [
            ({"names": ["Grand Hotel Cebu"]}, "NAMES_STRUCTURE_INVALID"),
            ({"names": {"cn": "宿务大酒店"}}, "NAMES_KEY_MISSING"),
            ({"names": {"en": "Grand Hotel Cebu", "local_name": "GH"}}, "NAMES_KEY_UNKNOWN"),
            ({"names": {"en": "宿务大酒店", "cn": "宿务大酒店"}}, "NAMES_EN_NOT_LATIN"),
            ({"names": {"en": "Grand Hotel Cebu", "cn": "  "}}, "NAMES_VALUE_INVALID"),
        ]
        for change, code in cases:
            found = self.errors(target(**change))
            self.assertTrue(any(f.startswith(code) for f in found), "%s -> %s" % (change, found))
        self.assertEqual(self.errors(target(names={"en": "Grand Hotel Cebu",
                                                   "cn": "宿务大酒店", "local": "GH"})), [])

    def test_duplicate_and_mismatched_target_ids_are_reported(self):
        found = data_model.validate_map_targets({"t-1": target(), "t-2": target()}, POLICY)
        self.assertTrue(any(f.startswith("MAP_TARGET_ID_DUPLICATE") for f in found), found)
        found = data_model.validate_map_targets({"宿务|Grand Hotel": target()}, POLICY)
        self.assertTrue(any(f.startswith("MAP_TARGET_ID_KEY_MISMATCH") for f in found), found)
        # 用键本身作 target_id 时不应误报
        self.assertEqual(self.errors(target(target_id="t-1")), [])


class W1RABypassTests(unittest.TestCase):
    """§17.7 W1R-A：独立复核用绕过探针发现的 4 类假通过，逐个用执行型负测封死。"""

    errors = MapTargetValidationTests.errors

    def publisher_target(self, declared, **over):
        base = dict(link_mode="PUBLISHER_ENTITY_LINK", link_provider="google",
                    link_builder_version="linkbuilder-0",
                    link_selection_reason="publisher declared it",
                    evidence=[{
                        "source_type": "publisher_entity_page",
                        "source_url_or_ref": "https://grandhotel.example/cebu",
                        "retrieved_at": "2026-10-26", "supported_fields": ["display_name"],
                        "lineage_group": "lg-pub", "content_digest": "sha256:def",
                        "usage_scope": "link", "status": "complete",
                        "declared_link_url": declared, "link_url_provider": "google"}])
        base.update(over)
        return target(**base)

    # ① hostname 必须精确解析，不得对整条 URL 做子串搜索
    def test_lookalike_hosts_are_not_map_urls(self):
        # 组 A：解析出的 hostname 本身不是任何登记 provider 的主机名——字符串里带 google.com 也没用
        host_fakes = ("https://evil.example/path/google.com/maps/place/x",
                      "https://notgoogle.com/maps/place/x",
                      "https://google.com.evil.example/maps/place/x",
                      "https://www.google.com@evil.example/maps/place/x",
                      "https://evil.example:443/?redirect=https://www.google.com/maps/place/x")
        for fake in host_fakes:
            shape = data_model.map_url_shape(fake, POLICY)
            self.assertFalse(shape["is_map_host"], "%s 被判成地图 URL（hostname=%s）"
                             % (fake, shape["host"]))
            self.assertFalse(shape["path_ok"], "%s 在非法主机上仍给出 path_ok" % fake)
            found = self.errors(self.publisher_target(fake))
            self.assertTrue(any(f.startswith("LINK_DECLARED_URL_INVALID") for f in found),
                            "%s 未被拒绝: %s" % (fake, found))

        # 组 B：主机名确实是 provider 的合法主机，绕过载荷藏在路径里——hostname 判不出来，
        # 必须由「路径前缀落在边界上」的形态校验拒绝，不得当成合法主机直接放行。
        path_fakes = ("https://www.google.com/maps.evil.example/",
                      "https://www.google.com/mapsearch/x",
                      "https://openstreetmap.org/waylist/1")
        for fake in path_fakes:
            shape = data_model.map_url_shape(fake, POLICY)
            self.assertTrue(shape["is_map_host"], "%s 的 hostname 本该是登记主机: %s"
                            % (fake, shape["host"]))
            self.assertFalse(shape["path_ok"], "%s 的路径载荷被判成合法地图路径" % fake)
            found = self.errors(self.publisher_target(fake))
            self.assertTrue(any(f.startswith("LINK_DECLARED_URL_SHAPE_INVALID") for f in found),
                            "%s 未被拒绝: %s" % (fake, found))

    def test_genuine_map_host_is_still_refused_as_its_own_evidence(self):
        found = self.errors(target(evidence=[dict(target()["evidence"][0],
                                                  source_url_or_ref=
                                                  "https://www.google.com/maps/search/?api=1&q=x")]))
        self.assertTrue(any(f.startswith("EVIDENCE_SELF_ATTESTATION") for f in found))

    def test_real_host_with_wrong_path_or_scheme_is_rejected(self):
        bad_path = self.errors(self.publisher_target("https://www.google.com/hotels/cebu"))
        self.assertTrue(any(f.startswith("LINK_DECLARED_URL_SHAPE_INVALID") for f in bad_path), bad_path)
        bad_scheme = self.errors(self.publisher_target("http://www.google.com/maps/place/x"))
        self.assertTrue(any(f.startswith("LINK_DECLARED_URL_SHAPE_INVALID") for f in bad_scheme),
                        bad_scheme)
        clean = self.errors(self.publisher_target("https://www.google.com/maps/place/grand-hotel"))
        self.assertEqual(clean, [])

    def test_declared_url_host_provider_must_match_the_button_provider(self):
        found = self.errors(self.publisher_target("https://www.google.com/maps/place/x",
                                                  link_provider="apple"))
        self.assertTrue(any(f.startswith(("LINK_EVIDENCE_PROVIDER_MISMATCH",
                                           "LINK_DECLARED_URL_PROVIDER_MISMATCH")) for f in found),
                        found)

    def test_substring_probe_regression_on_the_old_helper(self):
        # 旧实现用 `item in url` 判定，这两个绕过样本都会被判成地图 URL；回归锁定解析式判定
        self.assertFalse(data_model.map_url_shape("https://evil.example/google.com/maps",
                                                  POLICY)["is_map_host"])
        self.assertTrue(data_model.map_url_shape("https://maps.apple.com/?q=x", POLICY)["is_map_host"])

    # ② 链接上下文字段对所有 link mode 生效
    def test_link_context_is_required_for_every_url_bearing_mode(self):
        for mode in ("PUBLISHER_ENTITY_LINK", "NAMED_SEARCH", "COORDINATE"):
            for field in ("link_provider", "link_builder_version", "link_selection_reason"):
                row = target(link_mode=mode, coordinate_status="VERIFIED",
                             entity_type="coordinate_landmark", lat=10.3, lng=123.9,
                             datum="WGS84", axis_order="lat,lng",
                             coordinate_source_ref="licensed_open_data:node/1", precision_m=10,
                             link_provider="google", link_builder_version="lb-0",
                             link_selection_reason="reason")
                row.pop(field)
                found = self.errors(row)
                hit = [f for f in found if f.startswith("LINK_CONTEXT_MISSING")]
                self.assertTrue(hit and field in hit[0],
                                "%s 缺 %s 未被点名: %s" % (mode, field, found))

    def test_none_mode_still_requires_an_explicit_reason(self):
        row = target(link_mode="NONE", link_provider="", link_builder_version="",
                     link_selection_reason="")
        found = self.errors(row)
        self.assertTrue(any(f.startswith("LINK_CONTEXT_MISSING") and "link_selection_reason" in f
                            for f in found), found)
        row["link_selection_reason"] = "未取得任何可交付位置证据"
        self.assertEqual(self.errors(row), [])

    def test_unknown_provider_is_refused(self):
        found = self.errors(target(link_provider="baidu"))
        self.assertTrue(any(f.startswith("LINK_PROVIDER_UNKNOWN") for f in found), found)

    # ③ 身份证据的组合规则
    def test_stable_entity_reference_can_substitute_for_address(self):
        row = dict(target()["evidence"][0], source_type="licensed_open_data_entity",
                   source_url_or_ref="https://www.openstreetmap.org/way/12345",
                   lineage_group="lg-osm-12345", supported_fields=["display_name"],
                   source_entity_ref="osm:way/12345")
        self.assertEqual(self.errors(target(identity_status="VERIFIED", evidence=[row])), [])

    def test_an_osm_id_claimed_on_a_publisher_page_is_not_a_stable_reference(self):
        # W1R-B：同一字符串换个来源就不成立——OSM 编号必须回到那个 OSM 对象本身
        row = dict(target()["evidence"][0], source_type="official_entity_page",
                   source_url_or_ref="https://grandhotel.example/cebu",
                   supported_fields=["display_name"], source_entity_ref="osm:way/12345")
        found = self.errors(target(identity_status="VERIFIED", evidence=[row]))
        self.assertTrue(any(f.startswith("IDENTITY_REF_KIND_NOT_ENTITY") and
                            "REF_ORIGIN_UNPROVEN" in f for f in found), found)

    def test_name_field_only_is_not_enough(self):
        row = dict(target()["evidence"][0], source_type="official_entity_page",
                   supported_fields=["display_name"])
        found = self.errors(target(identity_status="VERIFIED", evidence=[row]))
        self.assertTrue(any(f.startswith("IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE")
                            for f in found), found)

    # ④ evidence 成员类型
    def test_non_object_evidence_members_are_reported_per_item(self):
        found = self.errors(target(evidence=["see the website", 7, None, {"broken": True}]))
        codes = [f.split("|")[0] for f in found]
        self.assertEqual(codes.count("EVIDENCE_MEMBER_NOT_OBJECT"), 3, found)
        self.assertTrue(any("EVIDENCE_INCOMPLETE" in code or
                            "EVIDENCE_MEMBER_NOT_OBJECT" in code for code in codes))

    def test_evidence_container_that_is_a_bare_string_is_reported(self):
        found = self.errors(target(evidence="来源见官网"))
        self.assertTrue(any(f.startswith("EVIDENCE_CONTAINER_INVALID") for f in found), found)

    def test_single_object_evidence_is_still_allowed_by_contract(self):
        self.assertEqual(self.errors(target(evidence=dict(target()["evidence"][0]))), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
