from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import hashlib
import tempfile
import unittest

from PIL import Image

from local_media_gate import validate_section_media


class SectionMediaGateTests(unittest.TestCase):
    def build_run(self, folder: str):
        root = Path(folder)
        (root / "assets/section").mkdir(parents=True)
        (root / "evidence").mkdir(parents=True, exist_ok=True)
        image_path = root / "assets/section/stay.jpg"
        img = Image.new("RGB", (1200, 720))
        img.putdata([((x * 200 // 1200) % 256, (y * 200 // 720) % 256, ((x + y) * 7) % 256) for y in range(720) for x in range(1200)])
        img.save(image_path)
        (root / "evidence/review.txt").write_text("contact sheet reviewed", encoding="utf-8")
        item = {
            "destination": "示例岛", "modules": ["hotels"], "module_category": "accommodation",
            "primary_module": "hotels",
            "selection_level": "same_destination_same_category_reference", "asset_role": "destination_atmosphere",
            "image": "assets/section/stay.jpg", "focal_point": "50% 50%",
        }
        entry = {
            "local_file": item["image"], "poi_name": "stay-example", "category": "SECTION_MEDIA",
            "destination": item["destination"], "modules": item["modules"], "module_category": item["module_category"],
            "primary_module": item["primary_module"],
            "source_page": "https://commons.wikimedia.org/wiki/File:Example.jpg", "license": "CC BY 4.0",
            "author": "Example", "retrieved_at": "2026-09-11", "verification_status": "verified",
            "verification_evidence": "evidence/review.txt",
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "source_provider": "wikimedia_commons", "source_file_title": "File:Example.jpg",
            "source_page_id": 123, "source_asset_url": "https://upload.wikimedia.org/example.jpg",
            "source_verification_status": "verified", "source_verification_method": "wikimedia_api_exact_file",
        }
        (root / "asset-manifest.json").write_text(json.dumps({"assets": [entry]}), encoding="utf-8")
        return root, item

    def test_valid_section_media_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root, item = self.build_run(folder)
            validate_section_media(root, [item], [("hotels", [["示例岛"]])], require_complete=True)

    def test_editorial_fallback_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, item = self.build_run(folder)
            with self.assertRaises(ValueError):
                validate_section_media(root, [item], [("hotels", [["示例岛"]])], require_complete=True,
                                       editorial_media=[{"image": item["image"]}])

    def test_missing_destination_module_slot_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, item = self.build_run(folder)
            with self.assertRaises(ValueError):
                validate_section_media(root, [item], [("hotels", [["另一个岛"]])], require_complete=True)

    def test_cross_country_contamination_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, item = self.build_run(folder)
            (root / "intake.json").write_text(json.dumps({"country": "中国 呼伦贝尔"}), encoding="utf-8")
            # Inject contaminated Thai temple metadata into manifest
            manifest = json.loads((root / "asset-manifest.json").read_text(encoding="utf-8"))
            manifest["assets"][0]["source_file_title"] = "File:Wat Chedi Luang Chiang Mai.jpg"
            manifest["assets"][0]["source_page"] = "https://commons.wikimedia.org/wiki/File:Wat_Chedi_Luang_Chiang_Mai.jpg"
            manifest["assets"][0]["caption"] = "呼伦贝尔大草原 - 清迈契迪龙寺"
            (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                validate_section_media(root, [item], [("hotels", [["示例岛"]])], require_complete=False)
            self.assertIn("Geographic consistency gate failed", str(ctx.exception))
            self.assertIn("chiang mai", str(ctx.exception).lower())

    def test_excluded_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, item = self.build_run(folder)
            # Add scope.json with excluded destination "阿尔山"
            (root / "scope.json").write_text(json.dumps({
                "selected_destinations": [
                    {"name": "海拉尔", "status": "included"},
                    {"name": "阿尔山", "status": "排除 (超出本次范围)"}
                ]
            }), encoding="utf-8")
            manifest = json.loads((root / "asset-manifest.json").read_text(encoding="utf-8"))
            manifest["assets"][0]["source_file_title"] = "File:Aershan National Forest Park.jpg"
            manifest["assets"][0]["caption"] = "阿尔山森林公园天池"
            (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                validate_section_media(root, [item], [("hotels", [["示例岛"]])], require_complete=False)
            self.assertIn("Asset metadata contains excluded destination", str(ctx.exception))

    def test_accommodation_inappropriate_purpose_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, item = self.build_run(folder)
            manifest = json.loads((root / "asset-manifest.json").read_text(encoding="utf-8"))
            # Accommodation category referencing railway station
            manifest["assets"][0]["source_file_title"] = "File:Manzhouli Railway Station.jpg"
            manifest["assets"][0]["caption"] = "满洲里火车站"
            (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                validate_section_media(root, [item], [("hotels", [["示例岛"]])], require_complete=False)
            self.assertIn("Accommodation asset carries inappropriate infrastructure marker", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

