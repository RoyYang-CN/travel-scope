"""§2.2.2 regressions: the English page may only print English, and every gap must be enumerable.

These tests exist because the v4.2.1 EN audit found three different ways a *translated* dataset
still produced Chinese on screen: meta lines were translated as one joined string, day labels
were treated as prose, and the destination card read columns that do not exist.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _dataset(**overrides) -> dict:
    data = {
        "country": "美国", "country_en": "United States", "artifact_slug": "probe",
        "duration_days": 14,
        "routes": [["闭环线", "Loop Route", "旧金山 - 洛杉矶", "14天14晚", "纯自驾 (SUV)",
                    "约 25695 元/人", "推荐走内陆再沿海岸南下。"]],
        "route_budgets": {"闭环线": {"total_cny": 25695}},
        "destinations": [["旧金山", "San Francisco", "加州旧金山湾区", "金门大桥/艺术宫",
                          "2天", "1月下旬气温10-15℃偶有海雾", "SFO国际机场入境提车20分钟", "是"]],
        "destination_coverage": [], "itinerary": [],
        "hotels": [], "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [["SFO → 市区", "自驾 (SUV)", "25分钟", "22公里", "25分钟",
                       "全天候随时出发", "", "", "10", "72", "沿US-101直达市区酒店",
                       "Hertz官网", "旧金山国际机场 (SFO)", "市区枢纽", "是",
                       "坡道陡峭需朝向路沿停车", "on_demand", "自驾租车单日核算",
                       "Self-drive rental daily rate", "2026-10-20", "", "verified", "", ""]],
        "transport_nodes": [["旧金山", "旧金山国际机场 (SFO)", "SFO", "机场",
                             "37.6,-122.3", "北部核心国际航空枢纽"]],
        "budget": [["1", "第1天", "洛杉矶提车·I-5内陆北上", 500, 200, 100, 100, 100, 1000]],
        "practical": [["货币结算与汇率口径", "全美境内消费均以美元(USD)结算。"]],
        "worth_it": [["旧金山", "斯坦福大学", "Stanford University", "砂岩罗曼式学术圣殿",
                      "文化学者、摄影爱好者", "2.5-3小时", "工作日上午光线最佳",
                      "校园公共区域免费漫步", "校园平缓开阔", "verified"]],
        "local_chains": [["全加州", "In-N-Out 汉堡", "In-N-Out Burger", "快餐/美式汉堡",
                          "加州地标性汉堡连锁", "自驾中途快速补给", "10-15美元/人",
                          "沿线及机场周边密布", "verified"]],
        "packing": [["证件与财务", "护照原件", "Passport", "随身携带", "全目的地通用",
                     "行前打印备用", "护照有效期需6个月以上", "verified"]],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [], "section_media": [], "map_targets": {},
    }
    data.update(overrides)
    return data


def _placeholder_english(cn: str, dataset=None, base: str = "English wording for this cell.") -> str:
    """测试占位英文：形状合规**且过结构事实对账**（MT-D2 第 6 步之后 validate_table 会查）。

    这是两份夹具（本文件的 _compliant_table 与 test_v422_prose_translation_contract 的 _table）
    共同的构造口——各写一份回声逻辑就会有两把尺子。它只回声**登记面上有出处**的事实：
    数字、年份、币种码、固定措辞、以及载荷里成对登记的实体名与目的地名。
    调用方自己给的英文不走这里：那才是它想测的东西，替它补事实就是夹具作弊。
    """
    import prose_reconcile
    doc = prose_reconcile.glossary()
    currencies = prose_reconcile.currency_map(doc)
    terms = prose_reconcile.term_table(doc)
    faces = prose_reconcile.dataset_faces(dataset)
    facts = (prose_reconcile.numbers_in(cn) + prose_reconcile.years_in(cn)
             + [currencies[token] for token in prose_reconcile.currencies_in(cn)
                if token in currencies]
             + [terms[term]["en"] for term in terms
                if prose_reconcile.term_applies(cn, term, terms[term]["match"],
                                                terms[term].get("not_after") or ())]
             + [en for name, en in sorted((faces or {}).get("entity", {}).items()) if name in cn]
             + [en for name, en in sorted((faces or {}).get("destination", {}).items())
                if name in cn])
    unique = " ".join(dict.fromkeys(facts))
    return "%s %s" % (base, unique) if unique else base


def _compliant_table(fragments, dataset_sha: str, run_name: str, en_by_cn=None,
                     dataset=None) -> dict:
    """MT-C 之后，测试夹具也得造一张**真过合同**的表：缺字段、占位串、裸字符串都会被阻断。

    这张表的来源面写的是「代理会话内的机器翻译 + 业主复核未完成」，不是假装有人审过；
    字段含义见 references/prose-translation-contract.json。

    MT-D2 第 6 步之后 validate_table 还会跑结构事实对账，所以占位英文必须带上原文的数字/年份/
    币种码/登记名——`dataset` 就是为这件事传的（实体名与目的地名只从载荷的登记面读，夹具不自建
    名字表）。不传 dataset 时那两类事实自然为空，测试也就不会假装量到了它们。
    """
    import hashlib
    import translate_prose
    reg = translate_prose.contract()
    common = {
        "method": "controlled_machine_translation_in_agent_session",
        "engine": "qoder-desktop-agent-session",
        "engine_version": "test-fixture-session",
        "generated_at": "2026-11-01T12:00:00+08:00",
        "language_direction": "zh-CN->en",
        "glossary_version": "prose-glossary-0.precheck",
        "review_status": "owner_review_pending",
    }
    provenance = dict(common)
    provenance.update({"glossary": "references/prose-glossary.json",
                       "source_dataset_sha256": dataset_sha,
                       "input_snapshot_sha256": hashlib.sha256(b"fixture-snapshot").hexdigest().upper(),
                       "run_dir": run_name})
    entries = {}
    for fragment in fragments:
        cn = fragment["cn"]
        entry = dict(common)
        entry["source_fragment_sha256"] = hashlib.sha256(cn.encode("utf-8")).hexdigest().upper()
        supplied = (en_by_cn or {}).get(cn)
        # 调用方自己给的英文**不补事实**：那才是它想测的东西，夹具替它把数字塞回去就是作弊。
        english = supplied or _placeholder_english(cn, dataset)
        entries[fragment["id"]] = {
            "id": fragment["id"], "cn": cn, "kind": fragment["kind"],
            "addresses": fragment["addresses"],
            "en": english, "provenance": entry}
    table = {"schema_version": reg["table_shape"]["schema_version_value"],
             "run": run_name, "provenance": provenance, "entries": entries}
    table["table_sha256"] = translate_prose.digest_of_table(table)
    return table


TRANSLATED = {
    "加州地标性汉堡连锁": "A Californian burger institution",
    "自驾中途快速补给": "A fast roadside top-up",
    "10-15美元/人": "USD 10-15 per person",
    "沿线及机场周边密布": "Dense coverage along the route",
    "砂岩罗曼式学术圣殿": "A sandstone Romanesque temple of learning",
    "文化学者、摄影爱好者": "Culture travellers and photographers",
    "工作日上午光线最佳": "Best light on weekday mornings",
    "校园公共区域免费漫步": "Free to walk the open campus",
    "全天候随时出发": "Any time, any weather",
    "沿US-101直达市区酒店": "US-101 straight to a downtown hotel",
    "Hertz官网": "Hertz website",
    "坡道陡峭需朝向路沿停车": "Steep streets: turn the wheels to the kerb",
    "护照有效期需6个月以上": "Passport valid for six months",
    "随身携带": "Carry with you",
    "证件与财务": "Documents and money",
    "货币结算与汇率口径": "Currency and exchange rate",
    "全美境内消费均以美元(USD)结算。": "Everything is paid in USD.",
    "纯自驾 (SUV)": "Self-drive only (SUV)",
    "推荐走内陆再沿海岸南下。": "Go inland first, then south along the coast.",
    "闭环线": "Loop Route",
    "旧金山": "San Francisco",
    "加州旧金山湾区": "San Francisco Bay Area, California",
    "金门大桥/艺术宫": "Golden Gate Bridge / Palace of Fine Arts",
    "1月下旬气温10-15℃偶有海雾": "Late January: 10-15C with sea fog",
    "SFO国际机场入境提车20分钟": "20 min from SFO arrivals to the car",
    "是": "Yes",
    "洛杉矶提车·I-5内陆北上": "Pick up in LA, I-5 north to Silicon Valley",
    "旧金山国际机场 (SFO)": "San Francisco International Airport (SFO)",
    "机场": "Airport",
    "北部核心国际航空枢纽": "Northern California's main international gateway",
    "市区枢纽": "City-centre hub",
    "自驾 (SUV)": "Self-drive (SUV)",
    "斯坦福大学": "Stanford University",
    "In-N-Out 汉堡": "In-N-Out Burger",
    "快餐/美式汉堡": "Fast food / American burgers",
    "洛杉矶": "Los Angeles",
    "SFO → 市区": "SFO → Downtown",
    "护照原件": "Passport",
}


def _english_view(dataset: dict) -> tuple:
    from playwright.sync_api import sync_playwright
    from spa_renderer import render_spa_document
    with tempfile.TemporaryDirectory() as folder:
        html = Path(folder) / "probe-travel-guide.html"
        render_spa_document(html, dataset, reader_profile="en-audit")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(html.as_uri(), wait_until="load")
            page.wait_for_timeout(150)
            page.locator("#lang-btn").dispatch_event("click")
            # Only one panel is visible at a time and innerText skips hidden nodes, so a
            # reader-visible defect in another tab would be invisible to this test.
            page.evaluate("() => document.querySelectorAll('#main .panel').forEach(p => p.hidden = false)")
            page.wait_for_timeout(250)
            body = page.locator("body").inner_text()
            pending = page.evaluate(
                "() => JSON.parse(document.documentElement.dataset.enUntranslatedList || '[]')")
            browser.close()
    return body, pending, errors


class EnglishPageSourceTests(unittest.TestCase):
    def test_translated_dataset_reaches_zero_pending(self):
        body, pending, errors = _english_view(_dataset(prose_en=dict(TRANSLATED)))
        self.assertEqual(errors, [])
        self.assertEqual(pending, [], f"补全英文来源后仍有 pending: {pending}")
        self.assertNotIn("(translation pending)", body)
        for expected in ("USD 10-15 per person", "Best light on weekday mornings",
                         "Any time, any weather", "Carry with you"):
            self.assertIn(expected, body)

    def test_day_labels_and_durations_are_grammar_not_dictionary_lookups(self):
        # 第1天 / 14天14晚 / 2.5-3小时 are measurement grammar: they must convert with no
        # prose_en entry, and '14天14晚' must not collapse into '14 days14 nights'.
        body, _pending, errors = _english_view(_dataset())
        self.assertEqual(errors, [])
        self.assertIn("Day 1", body)
        self.assertIn("14 days 14 nights", body)
        self.assertNotIn("14 days14 nights", body)
        self.assertIn("2.5-3 h", body)

    def test_destinations_card_labels_match_the_canonical_tuple(self):
        body, _pending, errors = _english_view(_dataset(prose_en=dict(TRANSLATED)))
        self.assertEqual(errors, [])
        # The old card printed 最佳季节 under "口岸枢纽 / Gateway" and 到达方式 under
        # "时区货币 / Time & Currency", because it read d[9] and d[10] of an 8-column tuple.
        self.assertNotIn("TIME & CURRENCY", body)
        self.assertIn("ARRIVAL\n20 min from SFO arrivals to the car", body)
        self.assertIn("BEST SEASON\nLate January: 10-15C with sea fog", body)
        self.assertIn("✦ Golden Gate Bridge / Palace of Fine Arts", body)

    def test_untranslated_prose_is_counted_and_listed_for_the_gate(self):
        data = _dataset(prose_en=dict(TRANSLATED))
        data["worth_it"][0][3] = "只有中文才说得清楚的长句描述"
        body, pending, errors = _english_view(data)
        self.assertEqual(errors, [])
        self.assertIn("只有中文才说得清楚的长句描述", pending)
        self.assertIn("(translation pending)", body)


class LayoutGuardTests(unittest.TestCase):
    """§2.2.2 fallout: English is longer than the Chinese it translates, so text slots break."""

    @staticmethod
    def _clipped_at(width: int, prepare=None) -> list[dict]:
        import visual_qa
        from playwright.sync_api import sync_playwright
        from spa_renderer import render_spa_document
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / "probe-travel-guide.html"
            render_spa_document(html, _dataset(prose_en=dict(TRANSLATED)), reader_profile="en-audit")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(html.as_uri(), wait_until="load")
                page.wait_for_timeout(200)
                page.locator("#lang-btn").dispatch_event("click")
                page.evaluate("() => document.querySelectorAll('#main .panel').forEach(p => p.hidden = false)")
                page.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
                if prepare:
                    page.evaluate(prepare)
                rows = page.evaluate(visual_qa.CLIPPED_TEXT_JS)
                browser.close()
        return rows

    def test_layout_guard_actually_fires_on_a_manufactured_slot(self):
        # A guard that can never fire is the v4.2.0 failure mode this release keeps hitting.
        injected = """() => {
          const host = document.querySelector('#main .day > summary') || document.querySelector('#main');
          const el = document.createElement('span');
          el.className = 'd-theme';
          el.style.cssText = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:80px;display:block';
          el.textContent = 'Pick up the car in Los Angeles and run I-5 north through the Central Valley';
          host.append(el);
        }"""
        rows = self._clipped_at(390, prepare=injected)
        self.assertTrue([r for r in rows if r["sig"] == "span.d-theme"], rows)

    def test_phone_summary_does_not_ellipsis_the_day_theme(self):
        rows = self._clipped_at(390)
        self.assertEqual([r for r in rows if r["sig"] == "span.d-theme"], [],
                         f"手机版日主题槽位仍被裁掉: {rows}")


class CollectStageTranslationTests(unittest.TestCase):
    def test_gap_locator_points_at_the_dataset_cell_not_just_the_string(self):
        # §2.2.2 amendment: the deliverable is a gap the owner can *find*, not a counter that
        # reads zero. V6-W 更正了这里的分类学：旧实现只有三种判定，把「登记表没覆盖这一列」也
        # 说成「字符串在 spa-layout.js 里」，而那句其实躺在数据集里——两棵候选实测 213/213 都是
        # 这样被误标的。现在 renderer_literal 必须真在 assets/spa-layout.js 里量到才发；
        # 数据里有、登记表没覆盖的走 dataset_cell_unregistered（带地址）；两边都量不到的走
        # unattributed（承认测不到）。下面用一条真的渲染层字面量（从文件里现取）来钉住这条边界。
        import translate_prose
        layout_literal = next(lit for lit in ("每日行程", "沿途影像", "核心体验")
                              if lit in translate_prose.layout_js_text()
                              and lit not in str(_dataset()))
        rows = {row["cn"]: row for row in translate_prose.locate_gaps(_dataset(), [
            "砂岩罗曼式学术圣殿",                      # a declared dataset cell
            "文化学者、摄影爱好者 · 从没见过的半句",   # a line the renderer joined
            layout_literal,                            # measured inside spa-layout.js
            "此句数据与渲染层都没有",                  # 谁都没法归因
        ])}
        self.assertEqual(rows["砂岩罗曼式学术圣殿"]["verdict"], "dataset_cell")
        self.assertEqual(rows["砂岩罗曼式学术圣殿"]["addresses"], ["worth_it[0][3]"])
        composite = rows["文化学者、摄影爱好者 · 从没见过的半句"]
        self.assertEqual(composite["verdict"], "render_composite")
        self.assertEqual(composite["addresses"], ["worth_it[0][4]"])
        self.assertEqual(composite["unresolved_parts"], ["从没见过的半句"])
        literal = rows[layout_literal]
        self.assertEqual(literal["verdict"], "renderer_literal")
        self.assertEqual(literal["addresses"], [])
        self.assertTrue(literal["in_layout_js"], "renderer_literal 必须带实测的文件命中")
        unlocated = rows["此句数据与渲染层都没有"]
        self.assertEqual(unlocated["verdict"], "unattributed")
        self.assertFalse(unlocated["in_layout_js"])

    def test_collector_covers_every_rendered_prose_block(self):
        import translate_prose
        fragments = translate_prose.collect_fragments(_dataset())
        kinds = {fragment["kind"] for fragment in fragments}
        for block in translate_prose.RENDERED_COLUMNS:
            self.assertTrue(_dataset()[block], f"{block} 在夹具里没有数据，覆盖测试是空的")
        for kind in ("dest_region", "dest_season", "dest_arrival", "worth_desc", "worth_audience",
                     "chain_desc", "chain_price", "packing_group", "packing_note",
                     "practical_body", "leg_title", "leg_guide", "leg_source", "leg_warning",
                     "node_type", "route_mode", "route_desc", "day_theme"):
            self.assertIn(kind, kinds, f"采集器漏掉渲染列 {kind}，英文页会出现 pending")

    def test_apply_refuses_a_half_translated_table(self):
        """§2.2.2 的老牙：半份翻译表不得写进封存输入。MT-C 之后这条要按合规表来量。

        第一版夹具用的是 `{"entries": {id: "英文串"}}` 这种裸串形态——MT-C 起它整张表都不合规
        （33 条全报缺项），「缺 1 条」这个信号就被淹掉了。所以这里造一张合规表再**定点抽掉一条**，
        让 missing 恰好等于 1，测的才是它想测的那件事。
        """
        import hashlib
        import translate_prose
        data = _dataset()
        # MT-D：翻译表的合法分母是 worklist（所有权判成 PROSE_REQUIRED 的那批），不是
        # collect_fragments 的文本相减结果——后者会把「别处已有英文」的行悄悄摘掉，
        # 于是「缺 1 条」会连同被摘掉的那批一起报，定点负测就不定点了。
        fragments = translate_prose.prose_translation_worklist(data)
        self.assertGreater(len(fragments), 5)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dataset_path = root / "dataset.json"
            dataset_path.write_bytes(json.dumps(data, ensure_ascii=False,
                                                indent=2).encode("utf-8"))
            dataset_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest().upper()
            # dataset 传进去不是为了多测一件事：占位英文要回声**登记面上有出处的**目的地名，
            # 不传就会在 validate_table 里撞 fact_drift_destination，把形状测试变成尺子测试。
            table = _compliant_table(fragments, dataset_sha, root.name, dataset=data)
            victim = fragments[1]["id"]
            del table["entries"][victim]
            table["table_sha256"] = translate_prose.digest_of_table(table)
            table_path = root / "table.json"
            table_path.write_bytes(json.dumps(table, ensure_ascii=False,
                                              indent=2).encode("utf-8"))
            before = dataset_path.read_bytes()
            report = translate_prose.apply_table(root, dataset_path, table_path, write=False)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(len(report["missing"]), 1)
            self.assertEqual(report["missing"][0]["id"], victim)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("fragment_missing_from_table", codes)
            with self.assertRaises(ValueError):
                translate_prose.apply_table(root, dataset_path, table_path, write=True)
            written = json.loads(dataset_path.read_bytes().decode("utf-8"))
            self.assertNotIn("prose_en", written, "半份翻译表不得写入封存输入")
            self.assertEqual(dataset_path.read_bytes(), before,
                             "被拒的表动过了 dataset 字节：禁部分写盘这条失效")

    def test_wording_used_as_a_note_and_a_column_gets_both_keys(self):
        # The same text can be a POI note (which carries a money prefix) and a column elsewhere;
        # folding one fragment onto two addresses used to crash the writer.
        import hashlib
        import translate_prose
        data = _dataset()
        data["hotels"] = [["旧金山", "山景酒店", "Hillview Hotel", "精品", 900, "", "",
                           "37.7,-122.4", "", "", "校园公共区域免费漫步"]]
        fragments = translate_prose.prose_translation_worklist(data)
        shared = [f for f in fragments if f["cn"] == "校园公共区域免费漫步"]
        self.assertEqual(len(shared), 1, "同一措辞应合并为一个片段")
        self.assertEqual(len(shared[0]["addresses"]), 2, shared[0]["addresses"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dataset_path = root / "dataset.json"
            dataset_path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
            dataset_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest().upper()
            table_path = root / "table.json"
            table_path.write_bytes(json.dumps(
                _compliant_table(fragments, dataset_sha, root.name,
                                 {"校园公共区域免费漫步": "Free to walk the open campus."},
                                 dataset=data),
                ensure_ascii=False, indent=2).encode("utf-8"))
            report = translate_prose.apply_table(root, dataset_path, table_path, write=True)
            self.assertEqual(report["status"], "PASS", report["findings"][:5])
            prose = json.loads(dataset_path.read_bytes().decode("utf-8"))["prose_en"]
        self.assertEqual(prose["校园公共区域免费漫步"], "Free to walk the open campus.")


if __name__ == "__main__":
    unittest.main()
