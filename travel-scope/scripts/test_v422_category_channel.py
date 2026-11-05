# -*- coding: utf-8 -*-
"""MT-B2：类别词根通道——列登记、逐词根、组合、真实 DOM，四层都要有牙。

业主 2026-10-31 的原话是「机场/枢纽/公路走类别词根且须**逐词根与组合**测试」。这个文件按
四层来量，每层单独会失败：

  1. 列登记：`references/category-lexicon.json::category_columns` 是「哪几列是类别列」的唯一
     登记面。v4.2.1 把这份清单硬写在 gen_travel_scope.py 里，只列了五张 POI 表，
     transport_nodes 的枢纽类别因此从来没进过 category_en（实测：CA 六个、PH 五个类别值
     全部以 pending 形式漏在英文页的缺口账上）。
  2. 逐词根：本轮新加的 综合/市区/客运/轮渡/滚装 每个单独组合得出自己那条英文；
     并且每个都能回指「因为哪个实测类别值组合不出才加的」——说不出依据的词根不许进表。
  3. 组合：两地实测出现过的全部枢纽口岸类别值，组合结果逐条等于登记译文。
  4. 真实 DOM：夹具走完「登记列 → annotate_dataset → 载荷 → tr() → 浏览器」这条链，
     英文态枢纽卡的小字里没有汉字，也没有 marker，且缺口清单里不含这些类别值。

另有 fail-closed 一条：组合不出来的类别值必须进 category_unmapped（保持 v4.2.1 的写法），
不许静默显示中文。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import category_lexicon as cl
import test_v421_english_source as base
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
GEN = (ROOT / "gen_travel_scope.py").read_text(encoding="utf-8")
LEX_SRC = (ROOT / "category_lexicon.py").read_text(encoding="utf-8")
LEXICON_JSON = cl.LEXICON
DISPLAY_CHANNEL = json.loads((ROOT.parent / "references" / "display-name-channel.json")
                             .read_text(encoding="utf-8"))
CHANNEL_NAME_ONLY = DISPLAY_CHANNEL.get("name_only_columns") or []

PENDING = "(translation pending)"

# 本轮依据实测加的字根（mtb_category_channel.py → MTB_CATEGORY_CHANNEL.json）
NEW_ROOTS = {"综合": "Integrated", "市区": "Urban", "客运": "Passenger",
             "轮渡": "Ferry", "滚装": "Ro-Ro"}

# 两地交付载荷里 transport_nodes.type 的全部取值（CA 6 + PH 5，机场两地共用）
MEASURED_NODE_TYPES = {
    "机场": "Airport",
    "公路枢纽": "Highway Hub",
    "枢纽机场": "Hub Airport",
    "海岸枢纽": "Coastal Hub",
    "综合枢纽": "Integrated Hub",
    "市区枢纽": "Urban Hub",
    "公路客运站": "Highway Passenger Station",
    "客运码头": "Passenger Pier",
    "客运轮渡码头": "Passenger Ferry Pier",
    "滚装码头": "Ro-Ro Pier",
}

# 列登记的应然面：注册表 ↔ 实现 双向闭合，多一个少一个都算漂移
EXPECTED_REGISTRY_DATASETS = {"hotels", "restaurants", "cafes", "attractions",
                              "dive_sites", "transport_nodes"}


def node_dataset() -> dict:
    """枢纽卡夹具：一行对象形状（交付载荷就是这个形状），两个未登记的类别值。"""
    return base._dataset(transport_nodes=[
        {"place": "旧金山", "name": "旧金山湾区联合广场枢纽", "name_en": "Union Square Hub",
         "type": "综合枢纽", "coords": "37.78,-122.40", "source_status": "已核验"},
        {"place": "旧金山", "name": "旧金山国际机场 (SFO)",
         "name_en": "San Francisco International Airport",
         "type": "机场", "coords": "37.62,-122.37", "source_status": "已核验"},
    ])


def english_nodes(dataset: dict) -> dict:
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
              nodeTypes: [...document.querySelectorAll('#trans-nodes .node-row small')]
                         .map(e => e.textContent.trim()),
              ledger: (() => { try {
                  return JSON.parse(document.documentElement.dataset.enUntranslatedList || '[]');
                } catch (e) { return []; } })()
            })""")
            browser.close()
    read["errors"] = errors
    return read


class RootTests(unittest.TestCase):
    def test_each_new_root_composes_on_its_own(self):
        for cn, en in NEW_ROOTS.items():
            self.assertEqual(cl.compose(cn), (en, []),
                             "逐词根这一层没过：%s 单独组合不出 %s" % (cn, en))

    def test_every_new_root_is_tied_to_a_measured_label(self):
        for cn in NEW_ROOTS:
            carriers = [label for label in MEASURED_NODE_TYPES if cn in label]
            self.assertTrue(carriers,
                            "%s 进了词根表却回指不出哪个实测类别值需要它——这就是无据扩充" % cn)

    def test_new_roots_live_in_the_form_table_not_the_exception_table(self):
        tables = LEXICON_JSON["tables"]
        for cn, en in NEW_ROOTS.items():
            self.assertEqual(tables["form"].get(cn), en,
                             "%s 必须是可复用词根；写进 phrase 就等于又回到样本字典" % cn)
            self.assertNotIn(cn, tables.get("phrase") or {})


class CompositionTests(unittest.TestCase):
    def test_every_measured_node_type_composes_to_its_registered_gloss(self):
        for label, expected in MEASURED_NODE_TYPES.items():
            gloss, missing = cl.compose(label)
            self.assertEqual(gloss, expected,
                             "组合层不对：%s 现在出 %r（缺字根 %s）" % (label, gloss, missing))

    def test_uncomposable_label_still_fails_closed(self):
        gloss, missing = cl.compose("太空港渡轮")
        self.assertEqual(gloss, "", "组合不出却给了英文，等于编一个没人核过的类别名")
        self.assertTrue(missing, "未覆盖字根必须报出来，不然 category_unmapped 无从登记")

    def test_annotate_dataset_records_the_unmapped_with_the_shipped_wording(self):
        dataset = base._dataset(transport_nodes=[
            {"place": "火星", "name": "火星轨道港", "name_en": "Mars Orbital Port",
             "type": "太空港渡轮", "coords": "", "source_status": "已核验"}])
        cl.annotate_dataset(dataset)
        self.assertIn("太空港渡轮 :: 缺字根", dataset["category_unmapped"][0],
                      "category_unmapped 的写法必须沿用交付物里已有的那条（标签 :: 缺字根 X），"
                      "否则同一条缺口在两处账上长成两个样子")
        self.assertNotIn("太空港渡轮", dataset["category_en"])


class ColumnRegistryTests(unittest.TestCase):
    def test_registry_covers_both_row_shapes(self):
        dataset = {"hotels": [["城市", "示例酒店", "Sample Hotel", "市区核心商务酒店"]],
                   "transport_nodes": [{"place": "宿务", "name": "宿务客运码头",
                                        "name_en": "Cebu Pier", "type": "客运码头"}]}
        values = cl.category_values(dataset)
        self.assertIn("市区核心商务酒店", values, "list 行的 index 列没被收集")
        self.assertIn("客运码头", values, "dict 行的 field 列没被收集（这就是 MT-B2 要修的洞）")

    def test_registry_and_implementation_close_on_the_same_column_set(self):
        registered = {str(col.get("dataset")) for col in LEXICON_JSON["category_columns"]}
        self.assertEqual(registered, EXPECTED_REGISTRY_DATASETS,
                         "类别列登记面漂移了：多出来的是没实测依据的列，缺的那列会重新变成隐身缺口")

    def test_only_one_place_lists_the_category_columns(self):
        for banned in ('("hotels", "restaurants", "cafes", "attractions", "dive_sites")',
                       '"hotels", "restaurants", "cafes", "attractions", "dive_sites"'):
            self.assertNotIn(banned, GEN, "生成器里又出现第二份类别列清单")
            self.assertNotIn(banned, LEX_SRC, "注释器里又出现第二份类别列清单")
        self.assertIn("_annotate_categories(payload)", GEN,
                      "生成器必须走登记列的注释器，而不是自己组一份 category_en")

    def test_lexicon_version_is_registered(self):
        version = LEXICON_JSON.get("lexicon_version") or {}
        self.assertTrue(version.get("name") and version.get("version"),
                        "翻译表要引用固定术语表版本；词根表自己没有版本号就没法被引用")
        self.assertIn("added_roots", version)


class NameColumnOwnershipTests(unittest.TestCase):
    """类别列与专名列是两本账：同一列不许被两个通道都认领，也不许有两列都不认领的实测缺口。"""

    def test_name_only_columns_are_registered_in_the_display_channel(self):
        import display_names

        slots = display_names.name_columns()
        self.assertIn(("transport_nodes", "place"), slots,
                      "CA 的 `旧金山市区` / `圣西蒙 (大苏尔1号公路)` 就住在这列；不登记就只能被错记成无人认领")
        for col in CHANNEL_NAME_ONLY:
            key = col.get("field") if col.get("field") is not None else col.get("index")
            self.assertIn((str(col["dataset"]), key), slots)
            self.assertTrue(col.get("role"), "专名列没有角色说明，判定文本就无从引用")

    def test_category_and_name_channels_do_not_overlap(self):
        import display_names

        category_cols = {(str(c["dataset"]), c.get("index", c.get("field")))
                         for c in LEXICON_JSON["category_columns"]}
        name_cols = set(display_names.name_columns())
        self.assertEqual(category_cols & name_cols, set(),
                         "同一列被类别词根与专名显示面同时认领，等于两个通道都能给它编英文")


class RealDomTests(unittest.TestCase):
    def test_node_category_labels_reach_the_page_as_composed_english(self):
        dataset = node_dataset()
        cl.annotate_dataset(dataset)
        self.assertEqual(sorted((dataset.get("category_en") or {}).get(k, "")
                                 for k in ("机场", "综合枢纽")), ["Airport", "Integrated Hub"])
        read = english_nodes(dataset)
        self.assertEqual(read["errors"], [], "页面报错时任何断言都不成立")
        self.assertTrue(read["nodeTypes"], "夹具没渲染出枢纽卡的类别行，本文件就量不到真实分支")
        joined = " | ".join(read["nodeTypes"])
        self.assertIn("Airport", joined)
        self.assertIn("Integrated Hub", joined)
        leaked = [t for t in read["nodeTypes"] if any("\u4e00" <= ch <= "\u9fff" for ch in t)]
        self.assertEqual(leaked, [], "EN 态枢纽类别漏中文：%s" % leaked[:3])
        self.assertNotIn(PENDING, joined, "登记列已覆盖的类别值不该再挂 marker")
        for label in ("机场", "综合枢纽"):
            self.assertNotIn(label, read["ledger"], "%s 已被词根解决，还留在缺口账上就是重复计数")

    def test_without_annotation_the_same_label_is_an_explicit_gap(self):
        """反向证据：同一个夹具不跑注释器，类别值就变成显式缺口——说明这一层真的在起作用。"""
        read = english_nodes(node_dataset())
        self.assertIn(PENDING, " | ".join(read["nodeTypes"]))
        self.assertIn("综合枢纽", read["ledger"])


if __name__ == "__main__":
    unittest.main()
