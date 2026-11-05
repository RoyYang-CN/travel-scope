# -*- coding: utf-8 -*-
"""MT-1 REVISE 第 4 条：money() 只认登记过的明确语法，认不出就显式未解析。

业主裁的根因：PH 那七条 `transport[*][3]` 是 `约 50-80 元` 这种**带币种的范围**，以前 money()
没有这条语法，落到函数尾部的 `return s` ⇒ 英文页原样漏中文，而且不登记缺口（等于既泄漏又隐身）。
这不是 prose 翻译问题，所以不进 prose_en、不复用只面向 POI 句子的 note_price_prefix()。

四条断言都在真实浏览器里量：

  1. 登记语法 `约 50-80 元` → `≈¥50–80`；`约 120 元/晚` → `≈¥120 / night`；`12 美元` → `$12`；
  2. **不猜汇率**：输出币种符号由来源币种决定，新语法一律不调用 usdAmount()/fxFactor()；
     数字与范围逐位保留（50 与 80 都必须在结果里）；
  3. 认不出（`五十元起大约`）时英文页显示 `(translation pending)`，且原文进缺口清单——
     既不泄漏汉字也不编一个数；
  4. 中文态不变：原文照印，缺口清单为空（这次修的是 EN 回落，不许顺手改 CN 读者看到的东西）；
  5. 同一个槽位装距离时（CA 的 `22公里`）不许变成英文缺口——未解析前先交给唯一的度量翻译器
     `enMetrics()`。这一条是我上一版改出来的回归，实测前后对照在
     `.temp/v422_honest_map/MT1_translation/tooling/mtb_money_distance_probe.py`。

牙齿：money() 尾部那条「原样返回」的路径只允许存在于中文态；英文尾部必须停在 marker 上。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import test_v421_english_source as base
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SPa = (ROOT.parent / "assets" / "spa-layout.js").read_text(encoding="utf-8")
PENDING = "(translation pending)"
UNPARSEABLE = "五十元起大约"
# transport[n][3] 是**度量槽**：PH 在这里放价格，CA 在这里放距离（22公里 / 145公里）。
# 把距离当成「没登记的钱」是我上一版引入的回归，实测见
# .temp/v422_honest_map/MT1_translation/tooling/mtb_money_distance_probe.py（before 用与封册
# sha256 相符的内联渲染器，唯一变量是渲染器版本）。
DISTANCE = "22公里"


def transport_row(price: str, leg: str) -> list:
    return [leg, "自驾 (SUV)", "25分钟", price, "25分钟", "全天候随时出发", "", "", "10", "72",
            "沿US-101直达市区", "Hertz官网", "旧金山国际机场 (SFO)", "市区枢纽", "是",
            "坡道陡峭需朝向路沿停车", "on_demand", "自驾租车单日核算",
            "Self-drive rental daily rate", "2026-10-20", "", "verified", "", ""]


def money_slots(lang: str) -> dict:
    dataset = base._dataset(transport=[transport_row("约 50-80 元", "SFO → 市区"),
                                       transport_row("约 120 元/晚", "机场 → 酒店"),
                                       transport_row("12 美元", "市区 → 码头"),
                                       transport_row(UNPARSEABLE, "码头 → 灯塔"),
                                       transport_row(DISTANCE, "灯塔 → 红杉林")])
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
            if lang == "en":
                page.locator("#lang-btn").dispatch_event("click")
            page.evaluate("() => document.querySelectorAll('#main .panel')"
                          ".forEach(p => p.hidden = false)")
            page.wait_for_timeout(300)
            texts = page.evaluate(
                """() => { const out = [];
                  for (const el of document.querySelectorAll('body *')) {
                    const own = [...el.childNodes].filter(n => n.nodeType === 3)
                      .map(n => n.textContent).join('');
                    if (own.trim().length && own.trim().length < 80) out.push(own.trim());
                  }
                  return out; }""")
            ledger = json.loads(page.evaluate(
                "() => document.documentElement.dataset.enUntranslatedList || '[]'"))
            browser.close()
    return {"texts": texts, "joined": " | ".join(texts), "ledger": ledger, "errors": errors}


class MoneyScaffoldTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.english = money_slots("en")
        cls.chinese = money_slots("cn")

    def test_registered_range_and_unit_syntaxes_render_deterministically(self):
        self.assertEqual(self.english["errors"], [])
        self.assertIn("≈¥50–80", self.english["joined"])
        self.assertIn("≈¥120 / night", self.english["joined"])
        self.assertIn("$12", self.english["joined"])

    def test_no_exchange_rate_is_invented(self):
        # 动态面：新语法输出的币种必须由来源字符串自己决定，人民币区间不许被换算成美元。
        for text in self.english["texts"]:
            if "≈¥50–80" in text or "≈¥120" in text:
                self.assertNotIn("$", text, "新语法不许顺手换算成美元：V5-B 汇率状态是 UNREGISTERED")
                self.assertNotIn("USD", text, "同上——出现 USD 就是有人在这里猜了汇率")
        self.assertIn("$12", self.english["joined"],
                      "`12 美元` 本币就是美元，加符号不算换算；这条用来防止有人把币种判断也写死成 ¥")
        # 静态面：money() 里「只为英文态存在」的那一段（两条登记金额语法 + 未解析兜底）里，
        # 一次换算调用都不许出现。用 body 而不是整份文件切，否则会把别处的 usdAmount 也算进来。
        body = SPa.split("function money(cnyVal){", 1)[1].split("\n}", 1)[0]
        region = body.split("const mCurRange", 1)[1]
        self.assertIn("mCurOne", region, "分支切片没切对，测试会假绿")
        self.assertIn("enMetrics(s)", region, "度量兜底就在这段里，切丢了等于没测")
        for forbidden in ("usdAmount", "fxFactor"):
            self.assertNotIn(forbidden, region,
                             "登记的金额语法一旦调换算，`≈¥50–80` 就会变成没人核对过的美元数")

    def test_range_numbers_are_preserved_digit_by_digit(self):
        line = next((t for t in self.english["texts"] if "≈¥50–80" in t), "")
        self.assertTrue(line, "区间整条没渲染出来")
        self.assertIn("50", line)
        self.assertIn("80", line)
        self.assertNotIn("65", line, "取中值就是把区间改成一个新的价格事实")
        self.assertIn("¥", line, "区间必须带着来源币种出现，不带币种的裸数字没法对账")

    def test_unparseable_money_shows_marker_and_registers_the_source(self):
        self.assertIn(PENDING, self.english["joined"])
        self.assertNotIn(UNPARSEABLE, self.english["joined"],
                         "认不出就印原文是泄漏；认不出就留空白是隐身，两条都不许")
        self.assertIn(UNPARSEABLE, self.english["ledger"],
                      "缺口清单必须还留着原始文本，否则门禁看得见但没人能找到那一格")
        leaked = [t for t in self.english["texts"]
                  if any(chr(0x4e00) <= ch <= chr(0x9fff) for ch in t)]
        self.assertEqual([t for t in leaked if t != "中文"], [],
                         "英文态只允许语言开关那一个中文标签：%s" % leaked[:4])

    def test_chinese_mode_output_is_untouched(self):
        self.assertIn("约 50-80 元", self.chinese["joined"])
        self.assertIn(UNPARSEABLE, self.chinese["joined"])
        self.assertNotIn(PENDING, self.chinese["joined"])
        self.assertEqual(self.chinese["ledger"], [], "中文态没有英文缺口")
        self.assertIn("¥1,000", self.chinese["joined"],
                      "中文态的纯金额必须还是 `¥1,000`：我一度把中文早退放到纯数字分支之前，"
                      "CN 页的 1000 就丢了货币符号——test_v422_budget_contract 当场抓到，这条钉住它")

    def test_the_numeric_branch_exists_exactly_once_and_precedes_the_chinese_guard(self):
        body = SPa.split("function money(cnyVal){", 1)[1].split("\n}", 1)[0]
        self.assertEqual(body.count("const num = Number(s);"), 1,
                         "纯数字分支出现第二份拷贝：同一格钱迟早会给出两种写法")
        self.assertLess(body.index("const num = Number(s);"),
                        body.index("if (state.lang === 'cn') return s;"),
                        "中文早退必须排在纯数字分支之后，否则 CN 的 `¥1,000` 退化成 `1000`")

    def test_the_measure_slot_keeps_distances_out_of_the_money_gap(self):
        """距离不是钱，也不该变成英文缺口：CA 十条 transport[3] 都是 `N公里`。"""
        self.assertIn("22 km", self.english["joined"],
                      "money() 的未解析尾部必须先把度量交给唯一的 enMetrics()，否则 CA 距离整列回归")
        self.assertNotIn(DISTANCE, self.english["ledger"],
                         "能确定性显示的度量不该进缺口清单；进去了就是拿假缺口污染分母")

    def test_chinese_mode_keeps_the_distance_verbatim(self):
        self.assertIn(DISTANCE, self.chinese["joined"])
        self.assertNotIn("22 km", self.chinese["joined"], "中文页不许被我改成英文单位")

    def test_the_bare_passthrough_only_exists_for_the_chinese_branch(self):
        body = SPa.split("function money(cnyVal){", 1)[1].split("\n}", 1)[0]
        self.assertIn("if (state.lang === 'cn') return s;", body,
                      "中文态照印原文（本次不碰它）")
        self.assertIn("UNTRANSLATED.push(s);", body, "英文态未解析必须登记")
        self.assertIn("return TRANSLATION_PENDING;", body, "英文态未解析必须显式可见")
        self.assertLess(body.index("enMetrics(s)"), body.index("UNTRANSLATED.push(s);"),
                        "顺序就是结论：先让度量翻译器接手，它也不认才算缺口")
        tail = body.rstrip().rsplit("\n", 3)
        self.assertTrue(any("TRANSLATION_PENDING" in line for line in tail),
                        "money() 的英文尾部必须停在 marker 上，不能停回 return s")


if __name__ == "__main__":
    unittest.main()
