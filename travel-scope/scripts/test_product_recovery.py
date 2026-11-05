"""Offline renderer tests. Synthetic fixtures are not live travel evidence."""
import json
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from travel_renderer import ROOT, combine_bilingual_html, render_travel_scope_html
from verify_product import verify as verify_release


def sample():
    data = json.loads((ROOT / 'fixtures/demo.json').read_text(encoding='utf-8'))
    data.update(language='cn', demo_mode=True, is_overseas=True, theme='city',
                theme_label='Modern City', hero_image='assets/themes/city-manhattan-ultra.jpg')
    for key in ('hotels', 'restaurants', 'attractions'):
        index = 7 if key == 'attractions' else 8
        for row in data[key]:
            row[index] = ''
            row[index+1] = ''
    data['cafes'] = [['演示城市', f'演示咖啡馆{i}', f'Demo Café {i}', 'Synthetic café record', '', '', '', '', '', ''] for i in range(6)]
    return data


class RecoveryTests(unittest.TestCase):
    def test_release_identity_and_inventory(self):
        manifest = verify_release()
        self.assertEqual(manifest['product'], 'Travel-Scope')
        self.assertEqual(manifest['version'], '5.0.0')
        active_files = (
            'SKILL.md',
            'references/renderer-contract.json',
            'references/run-quality-policy.json',
            'references/intake-policy.json',
            'references/version-policy.json',
            'references/destination-discovery.md',
            'references/route-exploration.md',
            'references/map-link-policy.md',
            'V4_HANDOFF.md',
            'scripts/travel_renderer.py',
            'scripts/gen_travel_scope.py',
            'scripts/formal_data_gate.py',
            'scripts/intake_contract.py',
            'scripts/route_explorer.py',
            'scripts/delivery_gate.py',
        )
        active = '\n'.join(
            (ROOT / path).read_text(encoding='utf-8')
            for path in active_files
        ).lower()
        for marker in ('oceanpulse', 'jungle-cover', 'better-interface'):
            self.assertNotIn(marker, active)
        for destination_marker in ('bali', 'indonesia', 'philippines'):
            self.assertIsNone(re.search(rf'\b{destination_marker}\b', active))
        for destination_marker in ('菲律宾', '印度尼西亚'):
            self.assertNotIn(destination_marker, active)

    def test_route_and_day_checks_are_destination_and_duration_agnostic(self):
        visual = (ROOT / 'scripts/visual_qa.py').read_text(encoding='utf-8')
        explorer = (ROOT / 'scripts/route_explorer.py').read_text(encoding='utf-8')
        self.assertIn('expected_route_days', visual)
        self.assertNotIn('!= 12', visual)
        self.assertIn('--min-corridors', explorer)
        self.assertIn('候选路线节点序列重复', explorer)

    def test_remote_probe_is_disabled(self):
        import gen_travel_scope as gen
        import validate_output
        for module in (gen, validate_output):
            with self.assertRaises(ValueError):
                module.verify_remote_image('https://places.googleapis.com/never-request-this')

    def test_branch_does_not_depend_on_coordinates(self):
        import gen_travel_scope as gen
        original=gen.DOMESTIC_DESTINATION
        try:
            gen.DOMESTIC_DESTINATION=False
            self.assertTrue(gen._is_overseas())
            gen.DOMESTIC_DESTINATION=True
            self.assertFalse(gen._is_overseas())
        finally:
            gen.DOMESTIC_DESTINATION=original

    def test_single_dom_and_complete_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cn = sample()
            render_travel_scope_html(root/'cn.html', cn)
            render_travel_scope_html(root/'en.html', dict(cn, language='en'))
            combine_bilingual_html(root/'cn.html', root/'en.html', root/'both.html')
            result = (root/'both.html').read_text(encoding='utf-8')
            self.assertEqual(result.count('class="brand"'), 1)
            self.assertEqual(result.count('id="language"'), 1)
            self.assertIn('Demo Café 5', result)
            self.assertIn('Demo Attraction Five', result)
            self.assertNotIn('12°C', result)
            self.assertNotIn('canonical/product', result)
            self.assertNotIn('maps.googleapis.com', result)
            self.assertIn('</header></section>\n<section class="content"', result)

    def test_html_navigation_covers_route_plan(self):
        contract = json.loads((ROOT / 'references/renderer-contract.json').read_text(encoding='utf-8'))
        overview = next(item for item in contract['tabs'] if item['id'] == 'overview')
        self.assertEqual(overview['cn'], '行程规划')
        self.assertEqual(overview['modules'][:2], ['routes', 'itinerary'])
        self.assertIn('editorial_media', overview['modules'])
        self.assertIn('destinations', overview['modules'])
        self.assertIn('destination_coverage', overview['modules'])
        self.assertEqual(contract['modules']['routes']['cn'], '路线灵感')

    def test_content_modules_use_destination_branches_and_reader_labels(self):
        contract = json.loads((ROOT / 'references/renderer-contract.json').read_text(encoding='utf-8'))
        food = next(item for item in contract['tabs'] if item['id'] == 'food')
        sights = next(item for item in contract['tabs'] if item['id'] == 'sights')
        budget = next(item for item in contract['tabs'] if item['id'] == 'budget')
        local_toolkit = next(item for item in contract['tabs'] if item['id'] == 'local_toolkit')
        notes = next(item for item in contract['tabs'] if item['id'] == 'notes')
        self.assertEqual(len(contract['tabs']), 8)
        self.assertEqual(food['modules'], ['local_chains', 'restaurants', 'cafes'])
        self.assertEqual(sights['modules'], ['worth_it', 'attractions', 'dive_sites'])
        self.assertEqual(budget['modules'], ['budget'])
        self.assertEqual(local_toolkit['modules'], ['local_apps'])
        self.assertEqual(notes['modules'], ['local_knowledge', 'practical', 'packing', 'source_evidence'])
        self.assertEqual(contract['modules']['local_chains']['cn'], '当地连锁与便捷选择')
        self.assertEqual(contract['modules']['worth_it']['cn'], '核心体验')
        self.assertEqual(contract['modules']['local_knowledge']['cn'], '当地旅行要点')
        self.assertEqual(contract['modules']['practical']['cn'], '入境与当地事务')
        self.assertEqual(contract['modules']['packing']['cn'], '行前准备')
        self.assertEqual(contract['presentation']['hero_carousel']['interval_ms'], 5000)
        self.assertFalse(contract['presentation']['hero_carousel']['pause_control'])
        self.assertFalse(contract['presentation']['poi_item_images'])
        self.assertFalse(contract['presentation']['poi_raw_coordinates'])
        self.assertTrue(contract['presentation']['branch_cover_role_badges'])
        script = (ROOT / 'assets/split-layout.js').read_text(encoding='utf-8')
        for marker in ('destination-branches', 'transport-branches', 'budget-cards', 'source-groups'):
            self.assertIn(marker, script)
        self.assertIn("key==='budget'?budgetHTML(rows)", script)
        self.assertIn("const totals={}", script)
        self.assertIn("key==='source_evidence'?sourcesHTML(rows)", script)
        self.assertIn("transportHTML(rows)", script)
        self.assertIn("key==='local_apps'?localAppsHTML", script)
        self.assertIn("localKnowledgeHTML(rows)", script)
        self.assertIn("['practical','packing'].includes(key)?tipBranches(rows,key)", script)
        self.assertIn('scheduleLabels', script)
        self.assertIn('budget-overview', script)
        for legacy_copy in ('本次行程亮点', '值得专程去', '本地连锁安心选', '到了当地，心里有数', '慢慢探索。'):
            self.assertNotIn(legacy_copy, script)

    def test_navigation_motion_keeps_accessibility_fallback(self):
        css = (ROOT / 'assets/split-layout.css').read_text(encoding='utf-8')
        script = (ROOT / 'assets/split-layout.js').read_text(encoding='utf-8')
        self.assertIn('prefers-reduced-motion:reduce', css)
        self.assertIn("panel.setAttribute('aria-busy','true')", script)
        self.assertIn("$('tabs').onkeydown", script)
        self.assertIn('.navigation.is-docked.is-visible', css)
        self.assertIn("navigation.classList.toggle('is-visible',docked)", script)
        self.assertNotIn("delta<-2", script)
        self.assertNotIn("delta>4", script)
        self.assertIn("body.classList.add('route-leaving')", script)
        self.assertIn("if(reducedMotion()){route=next;renderPanel();renderHeroCarousel(true);return;}", script)
        self.assertIn("heroTimer=setInterval(()=>showHero(heroIndex+1),5000)", script)
        self.assertIn("item.route===route", script)
        self.assertNotIn("$('motion-toggle')", script)

    def test_route_media_and_map_semantics(self):
        script = (ROOT / 'assets/split-layout.js').read_text(encoding='utf-8')
        self.assertIn("rows.filter(row=>row[0]===route)", script)
        self.assertIn("/^ChIJ[A-Za-z0-9_-]{15,}$/", script)
        self.assertIn("data-map-level", script)
        self.assertIn("verified_coordinate", script)
        self.assertIn('function mapIdentity(label,context)', script)
        self.assertIn("maps(name(row),row[spec.coords]||'',typeof id==='string'?id:'',placeLabel(row[0]))", script)
        self.assertNotIn("[label,coords].filter(Boolean)", script)
        self.assertNotIn("const sources=[row[spec.image]", script)
        self.assertIn("index!==spec.image+1", script)
        self.assertIn("index!==spec.coords", script)
        self.assertIn("aggregat(?:e|ed) platform rating", script)
        self.assertIn("poi poi-text-only", script)
        self.assertIn("key==='editorial_media'?editorial(rows)", script)
        self.assertIn("filter(key=>key!=='editorial_media')", script)
        self.assertIn('editorial-inline', script)
        self.assertNotIn("const ambient=(current().editorial_media||[]).find", script)
        self.assertIn("media.focal_point||'50% 50%'", script)
        self.assertIn("item.primary_module===moduleKey", script)
        self.assertIn("item.destination===place&&item.image&&item.asset_role==='destination_atmosphere'", script)
        self.assertIn('data-media-destination', script)
        self.assertNotIn("roleLabel=", script)

    def test_map_generators_preserve_place_identity_and_context(self):
        import gen_travel_scope as gen
        previous = gen.COUNTRY
        try:
            gen.COUNTRY = "Country Z"
            google = gen.gen_google_maps_uri(12.3, 45.6, "Central Station", "osm:123", "Gateway City")
            parsed = urllib.parse.urlsplit(google)
            self.assertEqual(urllib.parse.parse_qs(parsed.query)["query"][0], "Central Station, Gateway City, Country Z")
            self.assertNotIn("query_place_id", parsed.query)
            self.assertNotIn("12.3", urllib.parse.parse_qs(parsed.query)["query"][0])
            apple = gen.gen_apple_maps_uri(12.3, 45.6, "Central Station", "Gateway City")
            self.assertIn("ll=12.3,45.6", apple)
        finally:
            gen.COUNTRY = previous

    def test_checkpoint_depth_uses_q7_vocabulary(self):
        import checkpoint_store
        parser = checkpoint_store.build_parser()
        self.assertEqual(parser.parse_args(["init", "--country", "Country Z", "--mode", "concise"]).mode, "concise")
        with self.assertRaises(SystemExit):
            parser.parse_args(["init", "--country", "Country Z", "--mode", "super_deep"])

    def test_intake_contract_keeps_options_and_known_answers(self):
        import intake_contract
        import preflight_qa
        questionnaire = intake_contract.render_questionnaire({"q0_destination": "Country Z"})
        self.assertIn("Q0【目的地/国家或自定义区域】：Country Z", questionnaire)
        self.assertIn("Q3【消费与住宿档次】：", questionnaire)
        for opt in ["经济", "中档", "舒适", "高端", "混合"]:
            self.assertIn(opt, questionnaire)
        self.assertIn("Q4【交通方式】：自驾 / 非自驾", questionnaire)
        self.assertIn("Q7【研究深度】：精简 / 标准 / 深度 / 超级深度", questionnaire)
        self.assertIn("Q8【行程节奏】：紧凑 / 适中 / 宽松", questionnaire)
        valid = {question["id"]: "示例" for question in intake_contract.load_policy()["questions"]}
        valid.update(q3_tier="中档（海岛偏度假村）", q4_transport="非自驾", q7_depth="standard", q8_pace="适中")
        intake_contract.validate_intake(valid)
        preflight_qa.validate_values({"mode": "1", "branch": "1", "map_mode": "1", "route_granularity": "1", "scope_review": "1", "intake": valid})
        valid["q3_tier"] = "豪华但未定义"
        with self.assertRaises(ValueError):
            intake_contract.validate_intake(valid)
        with self.assertRaises(ValueError):
            preflight_qa.validate_values({"mode": "1", "branch": "1", "map_mode": "1", "route_granularity": "1", "scope_review": "1", "intake": valid})

    def test_version_policy_matches_release(self):
        policy = json.loads((ROOT / "references/version-policy.json").read_text(encoding="utf-8"))
        contract = json.loads((ROOT / "references/renderer-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["current_version"], "5.0.0")
        self.assertEqual(policy["current_version"], contract["version"])
        self.assertEqual(policy["rollover"]["4.0.99"], "4.1.0")

    def test_section_media_policy_is_separate_and_configured(self):
        policy = json.loads((ROOT / 'references/media-policy.json').read_text(encoding='utf-8'))
        self.assertEqual(policy['module_categories']['hotels'], 'accommodation')
        self.assertEqual(policy['module_categories']['restaurants'], 'food')
        self.assertEqual(policy['module_categories']['attractions'], 'sights')
        self.assertTrue(policy['providers']['wikimedia_commons']['download_locally'])
        self.assertTrue(policy['providers']['openverse']['origin_license_recheck_required'])
        self.assertTrue(any('same-destination atmosphere' in rule for rule in policy['rules']))

    def test_guide_uses_natural_page_scroll(self):
        css = (ROOT / 'assets/split-layout.css').read_text(encoding='utf-8')
        self.assertIn('Natural document flow', css)
        self.assertIn('.shell{height:auto;min-height:100svh', css)
        self.assertIn('.content{grid-column:1/-1;grid-row:2', css)
        self.assertIn('overflow:visible', css)
        self.assertIn('.module:only-child{grid-column:1/-1;display:grid', css)

    def test_paid_media_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            data=sample()
            data['hotels'][0][8]='https://places.googleapis.com/v1/places/x/photos/y/media?key=not-a-key'
            with self.assertRaises(ValueError):
                render_travel_scope_html(Path(folder)/'bad.html', data)

    def test_foreign_template_cannot_combine(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'foreign.html'
            path.write_text('<html>Other template</html>', encoding='utf-8')
            with self.assertRaises(ValueError):
                combine_bilingual_html(path,path,Path(folder)/'out.html')


if __name__ == '__main__':
    unittest.main()
