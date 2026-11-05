# -*- coding: utf-8 -*-
"""W1R-B2 independent frozen vectors, hand-written from checklist §17.7.2.

This file does not import a generated matrix and is not touched by any matrix/contract writer.
Production-policy refusals and explicit test-policy controls are deliberately separated.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKSPACE = ROOT.parents[1]
sys.path.insert(0, str(HERE))

import data_model  # noqa: E402
from test_v421_map_contract import POLICY as TEST_POLICY, target  # noqa: E402

PRODUCTION_POLICY = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))


def evidence(source: str, source_type: str = "official_directory_entity_page") -> dict:
    return {"source_type": source_type, "source_url_or_ref": source,
            "retrieved_at": "2026-10-27", "supported_fields": ["display_name", "address"],
            "lineage_group": "lg-b2", "content_digest": "sha256:b2", "usage_scope": "identity",
            "status": "complete", "address": "Oslob, Cebu City, 6000"}


class TotalFunctionAndFullTokenTests(unittest.TestCase):
    INVALID = [
        ("https://www.google.com:bad/maps", "REF_PORT_INVALID"),
        ("https://www.google.com:99999/maps", "REF_PORT_INVALID"),
        ("https://[::1/maps", "REF_NOT_HTTPS_URL"),
        ("https://www.openstreetmap.org/map#map=15/10.3/123.9evil",
         "REF_COORDINATE_TOKEN_MALFORMED"),
        ("https://www.openstreetmap.org/map#map=15/10.3/123.9/extra",
         "REF_COORDINATE_TOKEN_MALFORMED"),
        ("https://www.google.com/maps/@10.3,123.9,14z/@evil",
         "REF_COORDINATE_TOKEN_MALFORMED"),
        ("https://www.google.com/maps/@10.3,123.9,14z/@20,30,12z",
         "REF_COORDINATE_TOKEN_MALFORMED"),
        ("https://www.google.com/maps?ll=10.3,123.9&q=20,30", "REF_COORDINATE_CONFLICT"),
        ("https://www.openstreetmap.org/way/123/evil", "REF_ENTITY_PATH_TRAILING"),
        ("https://www.openstreetmap.org/way/123/history", "REF_ENTITY_PATH_TRAILING"),
        ("https://www.tripadvisor.com/Restaurant_Review-%2FPrivacy-Reviews.html",
         "REF_PATH_DECODED_SEPARATOR"),
        ("https://philippines.travel/transport/%2Fprivacy", "REF_PATH_DECODED_SEPARATOR"),
        ("https://maps.apple.com/?auid=123&cid=456", "REF_AMBIGUOUS_ENTITY_SELECTOR"),
        ("https://maps.apple.com/?mid=ABC&auid=123&cid=456",
         "REF_AMBIGUOUS_ENTITY_SELECTOR"),
        ("https://maps.apple.com/?auid=123&cid=123",
         "REF_AMBIGUOUS_ENTITY_SELECTOR"),
        ("https://www.google.com/maps?q=10.3,123.9&q=Grand+Hotel",
         "REF_AMBIGUOUS_SEARCH_SELECTOR"),
        ("https://www.google.com/maps?q=Grand+Hotel&q=10.3,123.9",
         "REF_AMBIGUOUS_SEARCH_SELECTOR"),
        ("https://www.google.com/maps?q=Grand+Hotel&q=Other+Hotel",
         "REF_AMBIGUOUS_SEARCH_SELECTOR"),
        ("https://www.google.com/maps/place/foo\\privacy", "REF_PATH_RAW_SEPARATOR"),
        ("https://www.google.com/maps/place/foo\x00privacy", "REF_URL_CONTROL_CHARACTER"),
    ]

    def test_every_frozen_bad_url_returns_a_structured_refusal(self):
        for value, reason in self.INVALID:
            with self.subTest(value=value):
                found = data_model.classify_reference(value, PRODUCTION_POLICY)
                self.assertEqual(found["kind"], "invalid")
                self.assertEqual(found["reason_code"], reason)
                for field in ("provider", "kind", "canonical_locator", "reason_code"):
                    self.assertIn(field, found)

    def test_total_function_authority_table_never_raises(self):
        inputs = ["", "garbage", "https://", "https://[]/", "https://[::1", "https://x:NaN/",
                  "https://www.google.com:-1/maps", "https://www.google.com:65536/maps",
                  "https://user:pass@www.google.com/maps", "file:///etc/passwd", None, 7, True]
        for value in inputs:
            with self.subTest(value=value):
                found = data_model.classify_reference(value, PRODUCTION_POLICY)
                self.assertIsInstance(found, dict)
                self.assertIn(found["kind"], PRODUCTION_POLICY["url_reference_classifier"]["kinds"])

    def test_name_plus_coordinate_is_allowed_but_two_different_coordinates_conflict(self):
        named = data_model.classify_reference(
            "https://www.google.com/maps?ll=10.3,123.9&q=Grand+Hotel", PRODUCTION_POLICY)
        same = data_model.classify_reference(
            "https://www.google.com/maps?ll=10.3,123.9&q=10.3,123.9", PRODUCTION_POLICY)
        reverse = data_model.classify_reference(
            "https://www.google.com/maps?q=20,30&ll=10.3,123.9", PRODUCTION_POLICY)
        self.assertEqual((named["kind"], named["reason_code"]),
                         ("coordinate", "REF_COORDINATE_SHAPE"))
        self.assertEqual((same["kind"], same["reason_code"]),
                         ("coordinate", "REF_COORDINATE_SHAPE"))
        self.assertEqual((reverse["kind"], reverse["reason_code"]),
                         ("invalid", "REF_COORDINATE_CONFLICT"))

    def test_single_selectors_and_normal_entity_paths_remain_allowed(self):
        controls = [
            ("https://maps.apple.com/?auid=123", "entity", "OK"),
            ("https://maps.apple.com/?auid=123&auid=123", "entity", "OK"),
            ("https://www.google.com/maps?ll=10.3,123.9&q=Grand+Hotel",
             "coordinate", "REF_COORDINATE_SHAPE"),
            ("https://www.google.com/maps/place/foo", "entity", "OK"),
        ]
        for value, kind, reason in controls:
            with self.subTest(value=value):
                found = data_model.classify_reference(value, PRODUCTION_POLICY)
                self.assertEqual((found["kind"], found["reason_code"]), (kind, reason))


class VersionAndApprovalGateTests(unittest.TestCase):
    def verified(self, source: str, source_type: str = "official_directory_entity_page") -> dict:
        return target(identity_status="VERIFIED", address_status="VERIFIED",
                      address="Oslob, Cebu City, 6000",
                      evidence=[evidence(source, source_type)])

    def test_classifier_version_current_stale_and_unknown_are_distinct(self):
        current = self.verified("https://www.openstreetmap.org/way/123456",
                                "licensed_open_data_entity")
        current["evidence"][0]["source_entity_ref"] = "osm:way/123456"
        current["evidence"][0]["lineage_group"] = "lg-osm"
        current["classifier_version"] = "refclassifier-4"
        self.assertEqual(data_model.validate_map_targets({"t-1": current}, PRODUCTION_POLICY), [])
        stale = copy.deepcopy(current)
        stale["classifier_version"] = "refclassifier-3"
        stale_errors = data_model.validate_map_targets({"t-1": stale}, PRODUCTION_POLICY)
        self.assertTrue(any(x.startswith("CLASSIFIER_VERSION_STALE") for x in stale_errors))
        unknown = copy.deepcopy(current)
        unknown["classifier_version"] = "refclassifier-999"
        unknown_errors = data_model.validate_map_targets({"t-1": unknown}, PRODUCTION_POLICY)
        self.assertTrue(any(x.startswith("CLASSIFIER_VERSION_UNKNOWN") for x in unknown_errors))

    def test_pending_and_fixture_sources_cannot_support_verified_in_production(self):
        pending = self.verified("https://www.tripadvisor.com/"
                                "Restaurant_Review-philippines-abaca-baking-company-reviews.html")
        fixture = self.verified("https://grandhotel.example/cebu", "official_entity_page")
        for case, item in (("pending", pending), ("fixture", fixture)):
            with self.subTest(case=case):
                errors = data_model.validate_map_targets({"t-1": item}, PRODUCTION_POLICY)
                self.assertTrue(errors)
                self.assertTrue(any("APPROVAL" in x or
                                    x.startswith("IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE")
                                    for x in errors), errors)

    def test_pending_shape_is_recordable_but_not_identity_eligible(self):
        url = ("https://www.tripadvisor.com/"
               "Restaurant_Review-philippines-abaca-baking-company-reviews.html")
        surface = data_model.classify_reference(url, PRODUCTION_POLICY)
        identity = data_model.classify_reference(url, PRODUCTION_POLICY, purpose="identity")
        self.assertEqual((surface["kind"], surface["reason_code"]), ("entity", "OK"))
        self.assertEqual((identity["kind"], identity["reason_code"]),
                         ("entity", "REF_SOURCE_APPROVAL_PENDING"))

    def test_fixture_is_rejected_by_production_policy_but_test_policy_is_explicit(self):
        prod = data_model.classify_reference("https://grandhotel.example/cebu", PRODUCTION_POLICY)
        test = data_model.classify_reference("https://grandhotel.example/cebu", TEST_POLICY,
                                             purpose="identity")
        self.assertEqual((prod["kind"], prod["reason_code"]),
                         ("invalid", "REF_SOURCE_APPROVAL_NOT_ELIGIBLE"))
        self.assertEqual((test["kind"], test["reason_code"]), ("entity", "OK"))


class FrozenInputCensusTests(unittest.TestCase):
    def test_shape_recognition_is_not_reported_as_identity_eligibility(self):
        expected = {
            "PH": (WORKSPACE / "runs/travel_scope_run_202702_philippines_visayas_v419_001/dataset.json",
                   198, 198, 0),
            "CA": (WORKSPACE / "runs/travel_scope_run_202701_usa_california_v420_001/dataset.json",
                   205, 205, 0),
        }
        for tag, (path, total, shape_want, identity_want) in expected.items():
            data = json.loads(path.read_text(encoding="utf-8"))
            values = list(data["map_targets"].values())
            shape = 0
            identity = 0
            for item in values:
                surface = data_model.classify_reference(item.get("source_url"), PRODUCTION_POLICY)
                judged = data_model.classify_reference(item.get("source_url"), PRODUCTION_POLICY,
                                                       purpose="identity")
                shape += int(surface["kind"] in {"entity", "coordinate", "search", "home"})
                identity += int(data_model.reference_is_identity_qualifying(judged))
            self.assertEqual((len(values), shape, identity),
                             (total, shape_want, identity_want), tag)


if __name__ == "__main__":
    unittest.main()
