"""Travel-Scope v4.1.4 Regression and Feature Verification Suite.

Validates:
1. Four-tier release version synchronization (4.1.4 across all contracts).
2. iOS Safari / WebKit positive stacking context (zero negative z-index).
3. Themed dynamic SVG placeholder generator and image error fallback in SPA client.
4. Tab switch lazy-load unblocking and opacity awakening.
5. Configuration-driven standalone Base64 inline delivery mode in spa_renderer.py.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class V413RegressionTests(unittest.TestCase):
    def test_four_tier_version_alignment_413(self):
        """Verifies four-tier version alignment across all release policies."""
        version_policy = json.loads((ROOT / "references/version-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(version_policy["current_version"], "5.0.0")

        provenance_policy = json.loads((ROOT / "references/provenance-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance_policy["target_version"], "5.0.0")

        contract = json.loads((ROOT / "references/renderer-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["version"], "5.0.0")

        gate_content = (ROOT / "scripts/formal_data_gate.py").read_text(encoding="utf-8")
        self.assertIn('CURRENT_VERSION = "5.0.0"', gate_content)

        gen_content = (ROOT / "scripts/gen_travel_scope.py").read_text(encoding="utf-8")
        self.assertIn("Version: V5.0.0", gen_content)

        spa_content = (ROOT / "scripts/spa_renderer.py").read_text(encoding="utf-8")
        self.assertIn("Travel-Scope v5.0.0", spa_content)

    def test_spa_cover_positive_stacking_context_and_no_negative_z_index(self):
        """Verifies that iOS Safari WebKit negative z-index bug is eliminated."""
        css = (ROOT / "assets/spa-layout.css").read_text(encoding="utf-8")

        # Zero negative z-indexes in entire CSS
        negative_matches = re.findall(r"z-index:\s*-\d+", css)
        self.assertEqual(negative_matches, [], f"Found negative z-index instances: {negative_matches}")

        # Positive stacking order on cover
        self.assertIn(".cover-bg{position:absolute;inset:0;z-index:0;", css)
        self.assertIn(".cover:before{content:\"\";position:absolute;inset:0;z-index:1;pointer-events:none;", css)
        self.assertIn(".cover-inner{position:relative;z-index:2;", css)
        self.assertIn(".cover-foot{position:relative;z-index:2;", css)

    def test_spa_img_onerror_fallback_and_placeholder_generator(self):
        """Verifies that spa-layout.js defines SVG placeholder and error fallback."""
        js = (ROOT / "assets/spa-layout.js").read_text(encoding="utf-8")

        # Placeholder SVG function exists and returns data URI
        self.assertIn("function makePlaceholderSvg(", js)
        self.assertIn("data:image/svg+xml;charset=utf-8,", js)

        # img factory in h() attaches error listener
        self.assertIn("el.addEventListener('error'", js)
        self.assertIn("makePlaceholderSvg(", js)

        # cover-bg has error fallback
        self.assertIn("bg.onerror = function()", js)

    def test_spa_tab_switch_awakening(self):
        """Verifies that selectTab awakens any opacity-trapped lazy images."""
        js = (ROOT / "assets/spa-layout.js").read_text(encoding="utf-8")
        self.assertIn("const activePanel = document.getElementById('panel-'+id);", js)
        self.assertIn("if (img.style.opacity === '0') img.style.opacity = '1';", js)

    def test_spa_renderer_standalone_vs_linked_mode(self):
        """Tests configuration-driven standalone Base64 inline delivery mode."""
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from spa_renderer import render_spa_document

        temp_dir = Path(tempfile.mkdtemp(prefix="travel_scope_v413_test_"))
        try:
            assets_dir = temp_dir / "assets"
            assets_themes = assets_dir / "themes"
            assets_themes.mkdir(parents=True, exist_ok=True)
            dummy_img = assets_themes / "nature.jpg"
            dummy_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xFF\xC0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xFF\xC4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xFF\xDA\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xFF\xD9"
            dummy_img.write_bytes(dummy_bytes)

            dataset = {
                "country": "Testland",
                "duration_days": 3,
                "routes": [["Route A", "Route A En", "A->B", "3天", "Car", 1000, "Desc", "Route A En"]],
                "route_budgets": {"Route A": 1000},
                "hero_image": "assets/themes/nature.jpg",
                "editorial_media": [
                    {"route": "Route A", "title": "Photo 1", "image": "assets/themes/nature.jpg"}
                ],
                "section_media": [
                    {"module": "hotels", "title": "Hotel 1", "image": "assets/themes/nature.jpg"}
                ],
                "destinations": [["Dest A", "Dest A En"]],
            }

            # 1. Linked mode (default: hero is inlined for instant mobile paint, section media remains linked)
            linked_out = temp_dir / "guide_linked.html"
            render_spa_document(linked_out, dataset, media_delivery_mode="linked", assets_dir=assets_dir)
            linked_html = linked_out.read_text(encoding="utf-8")
            self.assertIn('"image": "assets/themes/nature.jpg"', linked_html)  # Section media is linked
            self.assertIn("data:image/jpeg;base64,", linked_html)  # Hero is inlined

            # 2. Standalone mode (embedded Base64 for all media)
            standalone_out = temp_dir / "guide_standalone.html"
            render_spa_document(standalone_out, dataset, media_delivery_mode="standalone", assets_dir=assets_dir)
            standalone_html = standalone_out.read_text(encoding="utf-8")
            self.assertIn("data:image/jpeg;base64,", standalone_html)
            self.assertNotIn('"image": "assets/themes/nature.jpg"', standalone_html)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
