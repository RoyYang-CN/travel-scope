# -*- coding: utf-8 -*-
"""MT-1 REVISE 第 3 条：d-theme / day-card 的 EN 中文回落必须消失，缺译要显式登记。

业主裁得很细，四条都要**真实 DOM** 量到，不是看代码觉得对：

  1. EN 模式下 `.d-theme` 与 `.dc-plan` 两个槽里没有汉字（以前 `planStr = planEn || rawPlan`
     和 `(planEn || rawPlan)` 会把中文直接印到英文页上）；
  2. 缺译时槽里出现的是登记的 `(translation pending)` 标记，而不是空白、也不是中文；
  3. 缺口清单（`data-en-untranslated-list`，由 `tr()`/`loc()` 在返回 marker 时登记原始文本）
     里仍然**登记着原始 rawPlan**——显式化的代价不能是把账丢了；
  4. 给了译文之后：槽里是英文、没有 marker，且该条从缺口清单里消失（不能两榜同名都在）。

另有一条文本扫描牙齿：`planEn || rawPlan` 这种回落形态不许在渲染层里再出现第二处。

浏览器与夹具复用 test_v421_english_source 的同一套（`_dataset` / 英文态切换），不另起一份形状
不同的人工页面——那种页面量不到真实渲染分支。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import test_v421_english_source as base
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SPa = (ROOT.parent / "assets" / "spa-layout.js").read_text(encoding="utf-8")
DAY_PLAN = "洛杉矶提车·I-5内陆北上"
PENDING = "(translation pending)"


def english_slots(dataset: dict) -> dict:
    """渲染 → 切英文态 → 读两个槽的文本与缺口清单（真实 DOM，不解析字符串）。"""
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
            read = page.evaluate(
                """() => ({
                  theme: [...document.querySelectorAll('.d-theme')].map(e => e.textContent.trim()),
                  plan: [...document.querySelectorAll('.dc-plan')].map(e => e.innerText.trim()),
                  pending: JSON.parse(document.documentElement.dataset.enUntranslatedList || '[]')
                })""")
            browser.close()
    read["errors"] = errors
    return read


def day_dataset(**overrides) -> dict:
    data = {"itinerary": [["闭环线", "1", "上午", "机场取车后北上", "旧金山",
                          "I-5 内陆线", "旧金山"]]}
    data.update(overrides)
    return base._dataset(**data)


class DayThemeFallbackTests(unittest.TestCase):
    maxDiff = None

    def test_en_mode_leaks_no_chinese_in_the_two_plan_slots(self):
        slots = english_slots(day_dataset())
        self.assertEqual(slots["errors"], [], "页面报错时任何断言都不成立")
        self.assertTrue(slots["theme"] or slots["plan"],
                        "夹具没能渲染出这两个槽，本文件就量不到回落路径（先修夹具再说通过）")
        for label, texts in (("d-theme", slots["theme"]), ("dc-plan", slots["plan"])):
            leaked = [t for t in texts if any("\\u4e00" <= ch <= "\\u9fff" for ch in t)]
            self.assertEqual(leaked, [], "EN 模式 %s 槽回落中文：%s" % (label, leaked[:3]))

    def test_missing_translation_shows_the_marker_not_a_blank(self):
        slots = english_slots(day_dataset())
        joined = " ".join(slots["theme"] + slots["plan"])
        self.assertIn(PENDING, joined,
                      "缺译不许变空白：空白把缺口从读者和门禁眼前同时藏掉")

    def test_gap_ledger_still_registers_the_original_plan_text(self):
        slots = english_slots(day_dataset())
        self.assertIn(DAY_PLAN, slots["pending"],
                      "槽里换成 marker 之后，原始 rawPlan 必须仍在缺口清单里，否则账就丢了")

    def test_with_translation_no_marker_and_no_ledger_entry(self):
        slots = english_slots(day_dataset(prose_en={DAY_PLAN: "Pick-up in LA, north on I-5"}))
        for text in slots["theme"] + slots["plan"]:
            self.assertNotIn(PENDING, text, "有译文还挂 marker，等于宣布自己的来源不可信")
        self.assertIn("Pick-up in LA, north on I-5", " ".join(slots["theme"] + slots["plan"]))
        self.assertNotIn(DAY_PLAN, slots["pending"],
                         "已经覆盖的条目不许继续留在缺口清单里充数")

    def test_the_fallback_expression_is_gone_from_the_renderer(self):
        for banned in ("planEn || rawPlan", "(planEn || rawPlan)"):
            self.assertNotIn(banned, SPa,
                             "EN 中文回落的写法 %s 又回来了：它就是这批 pending 假象的来源" % banned)


if __name__ == "__main__":
    unittest.main()
