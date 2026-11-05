# -*- coding: utf-8 -*-
"""Regression tests for Travel-Scope v4.1.6.

Verifies:
1. Mobile navigation enhancements (.tabs mask, .route-pick proximity & mask, .route-line vertical timeline).
2. Elimination of hardcoded Bali/Indonesia strings (routes, ferry URLs, country fallback).
3. Parity with classic Split-v1: restoration of destinations cards, destination_coverage matrix, and POI planning details.
4. Hero-only inline media embedding.
5. Clean DAY 1..DAY X without TBD date repetition or "DAY Day 1" concatenation.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from spa_renderer import render_spa_document, _adapt_spa_dataset

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent


class TestV416Regressions(unittest.TestCase):
    def setUp(self):
        self.css_content = (ROOT_DIR / "assets/spa-layout.css").read_text(encoding="utf-8")
        self.js_content = (ROOT_DIR / "assets/spa-layout.js").read_text(encoding="utf-8")

    def test_css_navigation_enhancements(self):
        """P1: Verify tabs mask, route-pick proximity & mask, and route-line vertical timeline."""
        # 1. Tabs horizontal fade mask
        self.assertIn("mask-image:linear-gradient(90deg,transparent,#000 14px", self.css_content)
        # 2. Route-pick proximity & mask
        self.assertIn("scroll-snap-type:x proximity", self.css_content)
        # 3. Route-line mobile vertical timeline
        self.assertIn(".route-line{flex-direction:column;gap:16px", self.css_content)
        self.assertIn("border-left:2px dashed #8a978f", self.css_content)

    def test_js_dehardcoding_and_parity(self):
        """P1: Verify complete elimination of Bali/Indonesia hardcoded strings and restoration of parity blocks."""
        # 1. No hardcoded Bali route name in budget
        self.assertNotIn("巴厘文化海岸深度线", self.js_content)
        # 2. No hardcoded Bali ferry booking URL
        self.assertNotIn("sanur/nusa-penida", self.js_content)
        # 3. No developer jargon '目的地分支'
        self.assertNotIn("目的地分支", self.js_content)
        self.assertNotIn("'Branch'", self.js_content)
        # 4. Presence of restored destinations & coverage blocks
        self.assertIn("function destinationsBlock()", self.js_content)
        self.assertIn("function coverageBlock()", self.js_content)
        # 5. Presence of selectTab scrollIntoView centering
        self.assertIn("b.scrollIntoView({inline:'center',block:'nearest'", self.js_content)
        # 6. Presence of date TBD check and parseDayNum
        self.assertIn("isDateTBD", self.js_content)
        self.assertIn("parseDayNum", self.js_content)

    def test_hero_only_inline_delivery(self):
        """P1: Verify that in linked mode, only hero cover images are inlined, keeping others linked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = Path(tmpdir) / "assets"
            editorial_dir = assets_dir / "editorial"
            section_dir = assets_dir / "section"
            editorial_dir.mkdir(parents=True)
            section_dir.mkdir(parents=True)

            hero_file = editorial_dir / "hero.jpg"
            hero_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
            other_ed_file = editorial_dir / "other.jpg"
            other_ed_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
            sec_file = section_dir / "hotel.jpg"
            sec_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)

            dataset = {
                "country": "测试国",
                "country_en": "Testland",
                "routes": [["经典线", "Classic", "A→B", "5天", "Bus", "1000", "描述"]],
                "hero_image": "assets/editorial/hero.jpg",
                "editorial_media": [
                    {"route": "经典线", "destination": "A", "image": "assets/editorial/hero.jpg", "title": "首图"},
                    {"route": "经典线", "destination": "B", "image": "assets/editorial/other.jpg", "title": "沿途图"}
                ],
                "section_media": [
                    {"destination": "A", "modules": ["hotels"], "primary_module": "hotels", "image": "assets/section/hotel.jpg"}
                ]
            }

            adapted = _adapt_spa_dataset(dataset, media_delivery_mode="linked", assets_dir=assets_dir)
            # v4.2.1 SS5: hero + route cover are the SAME file, so the base64 must appear once in
            # D.asset_blobs and both fields must carry the same content-addressed reference.
            blobs = adapted.get("asset_blobs") or {}
            self.assertTrue(str(adapted["hero_image"]).startswith("asset://sha256:"), adapted["hero_image"][:60])
            self.assertEqual(adapted["editorial_media"][0]["image"], adapted["hero_image"])
            digest = adapted["hero_image"].split("asset://sha256:", 1)[1]
            self.assertEqual(list(blobs), [digest], "one shared bitmap ships once, not twice")
            self.assertTrue(blobs[digest].startswith("data:image/"))
            # other editorial media must REMAIN linked
            self.assertEqual(adapted["editorial_media"][1]["image"], "assets/editorial/other.jpg")
            # section media must REMAIN linked
            self.assertEqual(adapted["section_media"][0]["image"], "assets/section/hotel.jpg")

    def test_philippines_dataset_render_spa(self):
        """End-to-End: Render Philippines dataset and verify clean output."""
        ph_dataset_path = Path("D:/文档/项目开发/Travel-Scope/travel_scope_run_202702_philippines_cebu_visayas_001/dataset.json")
        if not ph_dataset_path.is_file():
            self.skipTest("Philippines dataset not available for integration check")

        data = json.loads(ph_dataset_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "output.html"
            render_spa_document(out_file, data)
            self.assertTrue(out_file.is_file())
            content = out_file.read_text(encoding="utf-8")
            # Must not contain hardcoded strings
            self.assertNotIn("巴厘文化海岸深度线", content)
            self.assertNotIn("sanur/nusa-penida", content)
            # Must contain Philippines identity
            self.assertIn("菲律宾", content)
            self.assertIn("travel-scope-spa-v1", content)


if __name__ == "__main__":
    unittest.main()
