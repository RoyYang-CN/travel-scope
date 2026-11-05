# -*- coding: utf-8 -*-
"""MT-B3：display-only 专名通道——两档来源、撞名不选边、provenance 不齐不进显示面、身份不升级。

业主 2026-10-31 第 6 条（原话要点）：地名、酒店、机场、码头、车站、餐厅等专名优先使用已有
`name_en` 或官方英文来源；没有官方英文时只能写明来源的 `machine_translated_display_name`/音译显示名，
**不得升级 canonical identity、map query、evidence 或 VERIFIED 状态**；`圣西蒙 (大苏尔1号公路)`
同样按显示专名处理，不能靠词根拼出后冒充权威英文名。

这个文件按四条合同量，每条都可能单独失败：

  1. tier1（同一行里本来就有的英文）：`老渔人码头吉罗伊海鲜` 的 `Old Fishermans Grotto`
     就在餐厅行第 3 格，但它出现在 itinerary/destination_coverage 这类单元格时以前没人接手
     （enEntityName 只吃 map_targets 与 destinations/routes/destination_coverage 三种对）。
     现在列清单住在 references/display-name-channel.json，构建期算成 D.name_pairs，英文页接得上。
  2. 撞名：同一个中文名在同一列对到两个不同英文时，两边一起剔出显示面并登记
     display_name_conflicts——实测 CA 交付载荷里就有两条（圣西蒙海滨游客中心 /
     旧金山市区联合广场枢纽），选一个就是冒充权威。
  3. tier2（机器翻译显示名）：provenance 必须是结构化对象且登记字段一条不缺；
     不合格整条**从载荷里被过滤掉**（渲染层拿不到），原格继续显式 pending。
  4. 不升级身份：显示面不许被地图链路读取，也不许写回 map_targets/evidence/VERIFIED——
     正面证据是 annotate 前后 map_targets 与 source_evidence 逐字节相等，
     反面牙齿是地图链接代码路径里不出现这两个显示字段。

浏览器与夹具复用 test_v421_english_source 的同一套（`_dataset` / 英文态切换）。
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import display_names as dn
import test_v421_english_source as base
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SPA = (ROOT.parent / "assets" / "spa-layout.js").read_text(encoding="utf-8")
CHANNEL = json.loads((ROOT.parent / "references" / "display-name-channel.json")
                     .read_text(encoding="utf-8"))
PENDING = "(translation pending)"

GROTTO_CN = "老渔人码头吉罗伊海鲜"
GROTTO_EN = "Old Fishermans Grotto"
NODE_CN = "宿务麦克坦国际机场"
NODE_EN = "Mactan-Cebu International Airport"
TITLE_CN = "薄荷岛巧克力山"
TITLE_EN = "Chocolate Hills of Bohol"

GOOD_PROVENANCE = {
    "method": "machine_translation",
    "engine": "qoder-agent", "engine_version": "test-harness",
    "generated_at": "2026-10-31T00:00:00+08:00",
    "source_dataset_sha256": "0" * 64, "table_sha256": "1" * 64,
    "language_direction": "zh-Hans->en", "glossary": "travel-scope-category-lexicon",
    "glossary_version": "4.2.2-1", "review_status": "pending_independent_review",
}


def grotto_dataset(**overrides) -> dict:
    data = {
        "restaurants": [["蒙特雷与卡梅尔", GROTTO_CN, GROTTO_EN, "码头海鲜",
                         "10-15美元/人", "4.5", "海鲜", "", "", "", "", ""]],
        "itinerary": [["闭环线", "1", "上午", "午餐", GROTTO_CN, "", "蒙特雷与卡梅尔"]],
    }
    data.update(overrides)
    return base._dataset(**data)


def english_render(dataset: dict) -> dict:
    """真实浏览器读英文态的三个槽：行程文本、图题、缺口清单。"""
    with tempfile.TemporaryDirectory() as folder:
        html = Path(folder) / "probe-travel-guide.html"
        from spa_renderer import render_spa_document
        render_spa_document(html, dataset, reader_profile="en-audit")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(html.as_uri(), wait_until="load")
            page.wait_for_timeout(150)
            page.locator("#lang-btn").dispatch_event("click")
            page.evaluate("() => document.querySelectorAll('#main .panel')"
                          ".forEach(p => p.hidden = false)")
            page.wait_for_timeout(300)
            read = page.evaluate(r"""() => ({
              tlText: [...document.querySelectorAll('.tl-text')].map(e => e.textContent.trim()),
              edTitles: [...document.querySelectorAll('#sub-editorial h4')].map(e => e.textContent.trim()),
              ledger: (() => { try {
                  return JSON.parse(document.documentElement.dataset.enUntranslatedList || '[]');
                } catch (e) { return []; } })()
            })""")
            browser.close()
    read["errors"] = errors
    return read


def cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


class TierOnePairTests(unittest.TestCase):
    def test_restaurant_list_row_pair_is_collected_with_its_address(self):
        pairs, conflicts = dn.read_pairs(grotto_dataset())
        self.assertEqual(pairs[GROTTO_CN]["english"], GROTTO_EN)
        self.assertEqual(pairs[GROTTO_CN]["address"], "restaurants[0][1]")
        self.assertEqual(pairs[GROTTO_CN]["tier"], "tier1_dataset_pair")
        self.assertEqual(conflicts, [])

    def test_transport_node_dict_row_pair_is_collected(self):
        dataset = {"transport_nodes": [{"name": NODE_CN, "name_en": NODE_EN,
                                        "type": "机场", "place": "宿务"}]}
        pairs, _c = dn.read_pairs(dataset)
        self.assertEqual(pairs[NODE_CN]["english"], NODE_EN,
                         "dict 行的 name/name_en 对没接上：枢纽名的英文来源就在这同一行")

    def test_colliding_display_names_are_dropped_instead_of_picked(self):
        dataset = {"transport_nodes": [
            {"name": "圣西蒙海滨游客中心", "name_en": "San Simeon Coastal Visitor Center"},
            {"name": "圣西蒙海滨游客中心", "name_en": "San Simeon Highway 1 Visitor Center"}]}
        pairs, conflicts = dn.read_pairs(dataset)
        self.assertNotIn("圣西蒙海滨游客中心", pairs,
                         "两个英文来源相撞时选一个，就是把没核过的那条冒充成权威名")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["englishes"],
                         ["San Simeon Coastal Visitor Center", "San Simeon Highway 1 Visitor Center"])

    def test_real_dom_itinerary_cell_resolves_from_the_registered_pair(self):
        dataset = grotto_dataset()
        dn.annotate_dataset(dataset)
        read = english_render(dataset)
        self.assertEqual(read["errors"], [], "页面报错时任何断言都不成立")
        self.assertTrue(read["tlText"], "夹具没渲染出行程文本槽，本文件量不到显示通道")
        joined = " | ".join(read["tlText"])
        self.assertIn(GROTTO_EN, joined)
        self.assertNotIn(GROTTO_CN, joined, "tier1 有英文来源却仍印中文，就是这次要修的洞")
        self.assertNotIn(GROTTO_CN, read["ledger"],
                         "已经由名对接上的专名不许再占缺口账，否则分母被重复计数")

    def test_without_the_channel_the_same_cell_is_an_explicit_gap(self):
        read = english_render(grotto_dataset())      # 不 annotate：没有 name_pairs
        self.assertIn(PENDING, " | ".join(read["tlText"]))
        self.assertIn(GROTTO_CN, read["ledger"])


class TierTwoProvenanceTests(unittest.TestCase):
    def test_complete_provenance_lets_the_display_name_through(self):
        dataset = grotto_dataset(machine_translated_display_name={TITLE_CN: TITLE_EN},
                                  display_name_provenance={TITLE_CN: dict(GOOD_PROVENANCE)})
        report = dn.annotate_dataset(dataset)
        self.assertEqual(report["tier2_usable"], 1)
        self.assertEqual(dataset["machine_translated_display_name"], {TITLE_CN: TITLE_EN})

    def test_string_placeholder_provenance_is_rejected_not_trusted(self):
        dataset = grotto_dataset(machine_translated_display_name={TITLE_CN: TITLE_EN},
                                 display_name_provenance={TITLE_CN: "machine translation"})
        report = dn.annotate_dataset(dataset)
        self.assertEqual(report["tier2_usable"], 0)
        self.assertEqual(dataset["machine_translated_display_name"], {},
                         "provenance 是字符串占位值还进显示面，等于给读者一个看起来有来源的名字")
        self.assertEqual(report["tier2_rejected"], 1)
        self.assertIn("provenance_not_object", dataset["display_name_rejected"][0]["reasons"][0])

    def test_missing_required_field_names_the_field_and_blocks_the_entry(self):
        weak = dict(GOOD_PROVENANCE)
        weak.pop("glossary_version")
        dataset = grotto_dataset(machine_translated_display_name={TITLE_CN: TITLE_EN},
                                 display_name_provenance={TITLE_CN: weak})
        dn.annotate_dataset(dataset)
        reasons = dataset["display_name_rejected"][0]["reasons"]
        self.assertTrue(any("glossary_version" in r for r in reasons),
                        "拒绝理由必须点名缺哪一条，否则下一个人只能重新猜：%s" % reasons)
        self.assertEqual(dataset["machine_translated_display_name"], {})

    def test_real_dom_editorial_title_follows_the_gate(self):
        media = [{"title": TITLE_CN, "destination": "薄荷岛", "route": "闭环线",
                  "image": "assets/editorial/bohol-chocolate-hills.jpg",
                  "author": "tester", "license": "CC BY-SA 4.0",
                  "selection_level": "exclusive_hero"}]
        ok = grotto_dataset(editorial_media=media,
                            machine_translated_display_name={TITLE_CN: TITLE_EN},
                            display_name_provenance={TITLE_CN: dict(GOOD_PROVENANCE)})
        dn.annotate_dataset(ok)
        good = english_render(ok)
        self.assertTrue(good["edTitles"], "夹具没渲染出配图标题槽（editorialBlock 按 route 过滤），先修夹具")
        self.assertIn(TITLE_EN, " | ".join(good["edTitles"]))
        self.assertNotIn(TITLE_CN, good["ledger"])

        bad = grotto_dataset(editorial_media=media,
                             machine_translated_display_name={TITLE_CN: TITLE_EN},
                             display_name_provenance={TITLE_CN: "TBD"})
        dn.annotate_dataset(bad)
        poor = english_render(bad)
        self.assertIn(PENDING, " | ".join(poor["edTitles"]),
                      "来源不合格时宁可让读者看见缺口，也不给一个像官方名的字符串")
        self.assertIn(TITLE_CN, poor["ledger"])


class NoUpgradeTests(unittest.TestCase):
    def test_display_channel_never_touches_the_identity_face(self):
        dataset = grotto_dataset()
        before_targets = copy.deepcopy(dataset["map_targets"])
        before_evidence = copy.deepcopy(dataset["source_evidence"])
        dn.annotate_dataset(dataset)
        self.assertEqual(dataset["map_targets"], before_targets,
                         "显示通道写进了 map_targets——业主红线：显示名不许参与身份")
        self.assertEqual(dataset["source_evidence"], before_evidence)

    def test_map_link_code_path_does_not_read_the_display_channel(self):
        body = SPA.split("function mapLinks(", 1)[1].split("\nfunction ", 1)[0]
        for banned in ("name_pairs", "machine_translated_display_name", "tr(", "loc("):
            self.assertNotIn(banned, body,
                             "地图链接读了显示面或走了翻译回落（%s）：MT 显示名一旦进查询串就是合成身份" % banned)

    def test_registry_declares_the_forbidden_targets(self):
        forbidden = " ".join(CHANNEL["no_upgrade"]["forbidden_targets"])
        for required in ("canonical_name", "identity_status", "google_resolution_status",
                         "evidence", "VERIFIED", "map_link_url"):
            self.assertIn(required, forbidden, "禁升级面少了 %s，这条红线就成了口头承诺" % required)

    def test_display_names_module_never_writes_map_fields(self):
        source = (ROOT / "display_names.py").read_text(encoding="utf-8")
        for banned in ('dataset["map_targets"]', '["identity_status"]', '["google_resolution_status"]'):
            self.assertNotIn(banned, source, "通道实现里出现了身份字段写入面：%s" % banned)


class RegistryClosureTests(unittest.TestCase):
    def test_pair_columns_are_shape_valid_and_closed(self):
        cols = CHANNEL["pair_columns"]
        self.assertTrue(cols, "登记列为空，tier1 整档就是空转")
        for col in cols:
            has_index = col.get("cn_index") is not None and col.get("en_index") is not None
            has_field = bool(col.get("cn_field")) and bool(col.get("en_field"))
            self.assertTrue(has_index != has_field,
                            "列登记必须二选一（index 对 或 field 对），%r 两条都不成立" % col)
            self.assertTrue(col.get("role"), "列没有角色说明，撞名账就没法读")
        registered = {str(c["dataset"]) for c in cols}
        self.assertEqual(registered, {"hotels", "restaurants", "cafes", "attractions",
                                      "dive_sites", "transport_nodes", "editorial_media"},
                         "专名对列清单漂移：多出来的是没实测依据的列，缺的那列会退回隐身缺口")

    def test_provenance_required_fields_match_the_owner_list(self):
        required = set(dn.provenance_fields())
        for field in ("method", "engine", "engine_version", "generated_at",
                      "source_dataset_sha256", "table_sha256", "language_direction",
                      "glossary", "glossary_version", "review_status"):
            self.assertIn(field, required, "MT-1 第 3 条点名的 provenance 字段缺了 %s" % field)


if __name__ == "__main__":
    unittest.main()
