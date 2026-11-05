from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from formal_data_gate import audit
from build_truth_worklist import build as build_truth_worklist
from local_media_gate import validate_section_media
from map_contract import audit_map_targets, map_urls
from test_formal_data_gate import fixture


class TruthContractTests(unittest.TestCase):
    def test_worklist_never_self_verifies(self):
        data, *_ = fixture()
        result = build_truth_worklist(data)
        self.assertTrue(result["map_targets"])
        self.assertTrue(all(item["target_level"] == "search_candidate" for item in result["map_targets"].values()))
        self.assertTrue(all(item["verification_status"] == "pending" for item in result["source_evidence_meta"]))

    def test_placeholder_place_id_and_search_candidate_fail(self):
        data, *_ = fixture()
        target = data["map_targets"]["A|住宿一"]
        target.update(target_level="verified_place_id", google_place_id="ChIJ_th_south_hotel_001", id_provenance="")
        errors, _ = audit_map_targets(data)
        self.assertTrue(any("Place ID" in error for error in errors))
        target.update(target_level="search_candidate", verification_status="candidate")
        errors, _ = audit_map_targets(data)
        self.assertTrue(any("搜索候选" in error for error in errors))

    def test_coordinate_target_builds_single_pin_query(self):
        urls = map_urls({"canonical_name": "Raya Restaurant", "destination": "Phuket", "country": "Thailand", "entity_type": "named_entity",
                         "target_level": "verified_coordinate", "coords": "7.8858515,98.3909338"})
        self.assertIn("query=Raya%20Restaurant%2C%20Phuket%2C%20Thailand", urls["google"])
        self.assertIn("ll=7.8858515,98.3909338", urls["google"])
        self.assertIn("ll=7.8858515,98.3909338", urls["apple"])

    def test_search_result_is_not_direct_entity_evidence(self):
        values = fixture()
        data = values[0]
        for item in data["source_evidence_meta"]:
            if item["name"] == "住宿一":
                item["url"] = "https://www.google.com/search?q=hotel"
        result = audit(*values)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("实体级直达" in error for error in result["errors"]))

    def test_self_reported_media_without_source_identity_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets/section").mkdir(parents=True)
            (root / "evidence").mkdir(parents=True, exist_ok=True)
            image = root / "assets/section/card.jpg"
            img = Image.new("RGB", (1200, 720))
            img.putdata([((x * 200 // 1200) % 256, (y * 200 // 720) % 256, ((x + y) * 7) % 256) for y in range(720) for x in range(1200)])
            img.save(image)
            (root / "evidence/review.txt").write_text("verified contact sheet reviewed\nOrigin: Field QA", encoding="utf-8")
            item = {"destination": "Phuket", "modules": ["hotels"], "module_category": "accommodation",
                    "primary_module": "hotels", "selection_level": "same_destination_same_category_reference",
                    "asset_role": "destination_atmosphere", "image": "assets/section/card.jpg", "focal_point": "50% 50%"}
            manifest = {"assets": [{"local_file": item["image"], "category": "SECTION_MEDIA", "destination": "Phuket",
                                    "modules": ["hotels"], "module_category": "accommodation", "primary_module": "hotels",
                                    "source_page": "https://commons.wikimedia.org/wiki/File:Invented.jpg", "license": "CC BY",
                                    "author": "Unknown", "retrieved_at": "2026-09-12", "verification_status": "verified",
                                    "verification_evidence": "evidence/review.txt", "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}]}
            (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Commons exact-file"):
                validate_section_media(root, [item], [("hotels", [["Phuket"]])], require_complete=True)

    def test_synthetic_wireframe_image_fails_authenticity_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets/section").mkdir(parents=True)
            (root / "evidence").mkdir()
            image = root / "assets/section/wireframe.jpg"
            Image.new("RGB", (1200, 720), "#16434b").save(image)
            (root / "evidence/review.txt").write_text("verified contact sheet reviewed\nOrigin: Field QA", encoding="utf-8")
            item = {"destination": "Phuket", "modules": ["hotels"], "module_category": "accommodation",
                    "primary_module": "hotels", "selection_level": "same_destination_same_category_reference",
                    "asset_role": "destination_atmosphere", "image": "assets/section/wireframe.jpg", "focal_point": "50% 50%"}
            manifest = {"assets": [{"local_file": item["image"], "category": "SECTION_MEDIA", "destination": "Phuket",
                                    "modules": ["hotels"], "module_category": "accommodation", "primary_module": "hotels",
                                    "source_page": "https://commons.wikimedia.org/wiki/File:Invented.jpg", "license": "CC BY",
                                    "author": "Unknown", "retrieved_at": "2026-09-12", "verification_status": "verified",
                                    "verification_evidence": "evidence/review.txt", "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                                    "source_provider": "wikimedia_commons", "source_file_title": "File:Invented.jpg",
                                    "source_page_id": 123, "source_asset_url": "https://upload.wikimedia.org/invented.jpg",
                                    "source_verification_status": "verified", "source_verification_method": "wikimedia_api_exact_file"}]}
            (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Authenticity gate failed"):
                validate_section_media(root, [item], [("hotels", [["Phuket"]])], require_complete=True)


if __name__ == "__main__":
    unittest.main()
