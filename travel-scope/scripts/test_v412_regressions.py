"""V4.0.12 Regression Test Suite.
Validates:
- Local Apps integration into formal_data_gate and delivery_gate
- 8-Tab navigation structure (Overview, Stays, Food, Sights, Transport, Budget, Local Toolkit, Tips)
- HTML rendering of local toolkit module and shortcuts in transport/food/notes
- Excel CN/EN workbook generation with '常用APP' / 'Local Apps' sheets
- Markdown CN/EN generation with '## 在地工具' / '## Local Toolkit' sections
- English parity and strict CJK residue filtering in Local Toolkit artifacts
"""
from __future__ import annotations

import copy
import json
import subprocess

import pyc_hygiene as pyc
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from formal_data_gate import audit
from test_formal_data_gate import fixture
from delivery_gate import _check_local_apps_delivery_parity


class V412RegressionTests(unittest.TestCase):
    # as-of 必须自己声明，不能交给墙钟。
    # formal_data_gate.audit() 里 `as_of_date = str(manifest.get("generated_at") or datetime.date.today())`，
    # 而本类喂进去的是**盘上夹具**（fixtures/thailand_local_apps.json，verified_at 固定 2026-10-02，15 条）。
    # 不声明 generated_at 时，这条回归量的其实是「今天离核验日几天」：2026-11-02 起 31 天 > 30 天上限，
    # 树没动、门没错，测试自己变红——同一天的日历把回归套件变成一次性用品。
    # 声明成夹具自己的核验日＝诚实做法（真实 run 的 manifest 里 generated_at 就是当场生成日）；
    # 既不是把 verified_at 改成今天（那是伪造核验日期），也不是放大 30 天上限（那是放宽门换绿）。
    AS_OF = "2026-10-02"

    def setUp(self):
        self.fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
        thailand_fixture = self.fixtures_dir / "thailand_local_apps.json"
        loaded = json.loads(thailand_fixture.read_text(encoding="utf-8"))
        self.valid_apps = loaded["local_apps"] if isinstance(loaded, dict) and "local_apps" in loaded else loaded

    def test_formal_data_gate_with_local_apps(self):
        data, manifest, scope, corridors, assets = fixture()
        manifest["skill_version"] = "5.0.0"
        manifest["generated_at"] = self.AS_OF
        data["local_apps"] = copy.deepcopy(self.valid_apps)
        
        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "PASS", f"Formal data gate failed with valid local_apps: {result['errors']}")
        self.assertEqual(result["metrics"].get("local_apps"), len(self.valid_apps))

    def test_formal_data_gate_catches_invalid_app(self):
        data, manifest, scope, corridors, assets = fixture()
        manifest["skill_version"] = "5.0.0"
        manifest["generated_at"] = self.AS_OF
        bad_apps = copy.deepcopy(self.valid_apps)
        bad_apps[0]["category"] = "invalid_category"
        data["local_apps"] = bad_apps

        result = audit(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("category" in e for e in result["errors"]), f"Expected error not found: {result['errors']}")

    def test_demo_generation_and_local_toolkit_parity(self):
        root = Path(__file__).resolve().parent.parent
        output_dir = root / ".temp_v412_test_out"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(root / "scripts" / "gen_travel_scope.py"),
            "--mode", "demo",
            "--language", "both",
            "--delivery-profile", "full_audit",
            "--artifact-slug", "demo-trip",
            "--output-dir", str(output_dir)
        ]
        try:
            res = subprocess.run(pyc.interpreter(cmd), capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", env=pyc.env())
            self.assertEqual(res.returncode, 0, f"gen_travel_scope failed: {res.stderr}\n{res.stdout}")

            # Check HTML contains 8 tabs including local_toolkit
            html_cn = next(output_dir.glob("*地图标记.html"), None)
            self.assertIsNotNone(html_cn, "HTML CN artifact not found")
            content_cn = html_cn.read_text(encoding="utf-8")
            self.assertIn('"id": "local_toolkit"', content_cn)
            self.assertIn('"local_apps"', content_cn)

            # Check Markdown CN / EN
            md_cn = next(output_dir.glob("*攻略大全.md"), None)
            md_en = next(output_dir.glob("*攻略大全-en.md"), None)
            self.assertIsNotNone(md_cn, "Markdown CN artifact not found")
            self.assertIsNotNone(md_en, "Markdown EN artifact not found")
            self.assertIn("## 在地工具", md_cn.read_text(encoding="utf-8"))
            self.assertIn("## Local Toolkit", md_en.read_text(encoding="utf-8"))

            # Check Excel CN / EN
            import openpyxl
            xlsx_cn = next(output_dir.glob("*攻略大全.xlsx"), None)
            xlsx_en = next(output_dir.glob("*攻略大全-en.xlsx"), None)
            self.assertIsNotNone(xlsx_cn, "Excel CN artifact not found")
            self.assertIsNotNone(xlsx_en, "Excel EN artifact not found")

            wb_cn = openpyxl.load_workbook(xlsx_cn, read_only=True)
            self.assertIn("常用APP", wb_cn.sheetnames)
            wb_cn.close()

            wb_en = openpyxl.load_workbook(xlsx_en, read_only=True)
            self.assertIn("Local Apps", wb_en.sheetnames)
            wb_en.close()

            # Check delivery parity function
            artifacts = {
                "html_cn": str(html_cn),
                "html_en": str(next(output_dir.glob("*地图标记-en.html"))),
                "xlsx_cn": str(xlsx_cn),
                "xlsx_en": str(xlsx_en),
                "md_cn": str(md_cn),
                "md_en": str(md_en),
            }
            delivery_errors = []
            _check_local_apps_delivery_parity(root / "fixtures" / "demo.json", artifacts, delivery_errors)
            self.assertEqual(delivery_errors, [], f"Delivery parity errors: {delivery_errors}")
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_wcag_aa_contrast_ratios(self):
        """P0-1: Verify all key text/background contrast ratios meet WCAG AA (>= 4.5:1)."""
        def rel_lum(hex_c):
            h = hex_c.lstrip("#")
            rgb = [int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
            ch = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
            return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

        def ratio(c1, c2):
            l1, l2 = rel_lum(c1), rel_lum(c2)
            return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

        pairs = [
            ("#525E64", "#FFFFFF", "muted on white card"),
            ("#525E64", "#FBFAF7", "muted on paper"),
            ("#525E64", "#F1F0EB", "muted on canvas"),
            ("#525E64", "#f5f0e8", "muted on footer parchment"),
            ("#4E5B63", "#efe8d5", "chart meta dt on chart paper"),
            ("#2A7080", "#FFFFFF", "teal/accent on white"),
            ("#2A7080", "#FBFAF7", "teal/accent on paper"),
        ]
        for fg, bg, name in pairs:
            cr = ratio(fg, bg)
            self.assertGreaterEqual(
                cr, 4.5,
                f"Contrast ratio for {name} ({fg} on {bg}) is {cr:.2f}:1, below WCAG AA 4.5:1 floor"
            )

    def test_color_scheme_meta_and_css_declaration(self):
        """P0-2: Verify <meta name="color-scheme" content="light"> and CSS color-scheme:light."""
        root = Path(__file__).resolve().parent.parent
        renderer_py = (root / "scripts/spa_renderer.py").read_text(encoding="utf-8")
        self.assertIn('<meta name="color-scheme" content="light">', renderer_py)

        css_content = (root / "assets/spa-layout.css").read_text(encoding="utf-8")
        self.assertIn("color-scheme:light", css_content.replace(" ", ""))

    def test_wai_aria_tabs_and_panels_contract(self):
        """P1-1: Verify WAI-ARIA tab controls, tabindex and keyboard navigation."""
        root = Path(__file__).resolve().parent.parent
        js_content = (root / "assets/spa-layout.js").read_text(encoding="utf-8")

        # Tab button attributes
        self.assertIn("'aria-controls':'panel-'+id", js_content)
        self.assertIn("tabindex:isSelected ? '0' : '-1'", js_content)

        # Keyboard navigation
        self.assertIn("ArrowRight", js_content)
        self.assertIn("ArrowLeft", js_content)
        self.assertIn("Home", js_content)
        self.assertIn("End", js_content)

        # All 8 panels declare role="tabpanel" and aria-labelledby
        tab_ids = ['overview', 'stays', 'food', 'sights', 'transport', 'budget', 'toolkit', 'notes']
        for tid in tab_ids:
            self.assertIn(f"id:'panel-{tid}'", js_content)
            self.assertIn(f"'aria-labelledby':'tab-{tid}'", js_content)

    def test_token_consolidation_and_font_floor(self):
        """P1-2 & P2-1: Verify standardized radius tokens, line token, and 10px font size floor."""
        root = Path(__file__).resolve().parent.parent
        css_content = (root / "assets/spa-layout.css").read_text(encoding="utf-8")

        # Tokens defined
        self.assertIn("--radius-sm:8px;", css_content)
        self.assertIn("--radius-md:12px;", css_content)
        self.assertIn("--radius-lg:16px;", css_content)
        self.assertIn("--radius-xl:22px;", css_content)
        self.assertIn("--radius-pill:999px;", css_content)
        self.assertIn("--line:rgba(28,36,38,.08);", css_content)

        # Font size floor 10px
        self.assertIn("font-size:max(10px,0.65rem);", css_content)

    def test_media_print_roadbook_and_reduced_motion(self):
        """P1-4 & P2-3: Verify print roadbook styles and reduced motion handling."""
        root = Path(__file__).resolve().parent.parent
        css_content = (root / "assets/spa-layout.css").read_text(encoding="utf-8")

        # Print roadbook
        self.assertIn("@media print", css_content)
        self.assertIn("details{display:block!important}", css_content)
        self.assertIn("break-inside:avoid", css_content)

        # Prefers-reduced-motion
        self.assertIn("@media(prefers-reduced-motion:reduce)", css_content)
        self.assertIn("animation:none!important", css_content)
        self.assertIn("transition:none!important", css_content)

    def test_image_async_decoding_and_semantics(self):
        """P2-2: Verify async image decoding and decorative cover aria-hidden."""
        root = Path(__file__).resolve().parent.parent
        js_content = (root / "assets/spa-layout.js").read_text(encoding="utf-8")
        self.assertIn("if (tag === 'img') el.decoding = 'async';", js_content)
        self.assertIn("bg.setAttribute('aria-hidden', 'true');", js_content)

        renderer_py = (root / "scripts/spa_renderer.py").read_text(encoding="utf-8")
        self.assertIn('aria-hidden="true"', renderer_py)


if __name__ == "__main__":
    unittest.main()

