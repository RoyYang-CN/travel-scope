# -*- coding: utf-8 -*-
"""MT-B5（业主 2026-11-01 裁决 #96）：酒店里程碑是**数据事实**，不许跟着译文一起消失。

修复前的真实缺陷（PH 成品实测）：徽标年份是从 `poiNote`（`tr()` 之后的文本）正则出来的，
而 PH 那 7 家酒店的说明正是待补译的 `dataset_cell` ⇒ 英文态变 `(translation pending)` ⇒
正则找不到年份 ⇒ ✨/🛠️ 徽标整块不产出。既不是泄漏也不是 pending，是第三种隐身：
`MTB_HIDDEN_REGRESSION_PROBE.json` 量到 PH `cn_only 7 / en_only 0`、`structure_identical false`。

业主六条都在这里**真跑 DOM**，不是看代码觉得对：

  1. 每张酒店的徽标在 CN 与 EN 都存在（数量一一对应）；
  2. 年份与 opened/renovated 类型逐项相同（读 `article.poi[data-milestone]`）；
  3. 说明仍是 pending 时徽标不得消失（同一张卡片：说明 marker + 徽标在）；
  4. 无年份／非法年份／低于下限不生成徽标（不越界、不当 0、不原样印）；
  5. 结构化 x[11]/x[12] 优先于说明解析（`source:structured_field`）；
  6. 提取源是原始 x[10]，**译文永不参与**（`poiNote.match(` 这种写法不许回来）。

另加治理牙齿：`data-model.json::hotel_milestone_badges` 的列号/年份范围/徽标文案与 `spa-layout.js`
常量双向对账；实现只许有一处；里程碑只许落进 `article[data-milestone]` 一个槽，不升级为证据。
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
POLICY = json.loads((ROOT.parent / "references" / "data-model.json")
                    .read_text(encoding="utf-8"))["hotel_milestone_badges"]
PENDING = "(translation pending)"

# 说明文本形状取自 PH 成品那 7 家（✨ 开业 / 🛠️ 焕新 两类都要有）。
MILESTONE_ROWS = [
    ["宿务", "麦丹岛香格里拉", "Shangri-La Mactan", "海岛度假村", "1800-3500", "4.8", "1500",
     "10.307959,124.020848", "", "", "350米私人沙滩，2022年全新开业，含生态湿地步道"],
    ["宿务", "种植园湾度假村", "Plantation Bay", "泻湖度假村", "1500-2800", "4.7", "1500",
     "10.287567,124.000256", "", "", "2021全面焕新，私享人工泻湖与免费皮艇"],
    ["宿务", "哥打雷迪森", "Radisson Blu Cebu", "城市商务酒店", "700-1300", "4.6", "1500",
     "10.312150,123.918450", "", "", "紧邻 SM City Cebu 与机场枢纽，2020年全新开业"],
    ["薄荷岛", "邦劳海岸度假村", "Panglao Coast", "海景度假村", "900-1600", "4.5", "800",
     "9.592000,123.870000", "", "", "2022全新开业，推门即可浮潜"],
    ["薄荷岛", "巧克力山酒店", "Chocolate Hills Inn", "山地民宿", "400-700", "4.3", "350",
     "9.812100,124.142600", "", "", "2021年翻新重装，可观日落草坪"],
    ["杜马盖地", "黎刹海滨大道旅馆", "Rizal Boulevard Inn", "海滨客栈", "300-520", "4.2", "260",
     "9.308200,123.306000", "", "", "2020全新开业，步行可达码头"],
    ["锡基霍尔", "海洋保护区度假村", "Siquijor Marine Resort", "生态度假村", "600-1000", "4.4", "520",
     "9.142000,123.602000", "", "", "2022全面焕新，私享800米白沙滩"],
]
BADGE_ROWS = len(MILESTONE_ROWS)

READ_JS = """() => {
  const arts = [...document.querySelectorAll('article.poi')];
  const badgeSel = '.poi-sub .badge-ok, .poi-sub .badge-info';
  return {
    articles: arts.length,
    badge_count: document.querySelectorAll(badgeSel).length,
    milestones: arts.map(a => ({
      name: ((a.querySelector('h4') || {}).innerText || '').trim(),
      milestone: a.getAttribute('data-milestone') || '',
      isNew: (a.dataset.isNew || ''),
      badge: ((a.querySelector(badgeSel) || {}).innerText || '').trim(),
      note: ((a.querySelector('p') || {}).innerText || '').trim()
    }))
  };
}"""


def dom_state(dataset: dict) -> dict:
    """渲染 → 中文态抓一次 → 切英文态再抓一次（真实 DOM，同一棵树）。"""
    with tempfile.TemporaryDirectory() as folder:
        html = Path(folder) / "probe-milestone.html"
        from spa_renderer import render_spa_document
        render_spa_document(html, dataset, reader_profile="en-audit")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(html.as_uri(), wait_until="load")
            page.wait_for_timeout(200)
            page.evaluate("() => document.querySelectorAll('#main .panel')"
                          ".forEach(p => p.hidden = false)")
            page.wait_for_timeout(120)
            cn = page.evaluate(READ_JS)
            page.locator("#lang-btn").dispatch_event("click")
            page.evaluate("() => document.querySelectorAll('#main .panel')"
                          ".forEach(p => p.hidden = false)")
            page.wait_for_timeout(250)
            en = page.evaluate(READ_JS)
            browser.close()
    return {"cn": cn, "en": en, "errors": errors}


def hotel_dataset(hotels: list) -> dict:
    return base._dataset(hotels=hotels)


def hotel_row(name: str, note: str = "", opened=None, renovated=None) -> list:
    """按登记的列号摆行：note=10，opened=11，renovated=12（缺字段留空串，不是缺位）。"""
    row = ["宿务", name, name + " EN", "海岛度假村", "300-500", "4.2", "300",
           "10.3,123.9", "", "", note, "", ""]
    if opened is not None:
        row[11] = opened
    if renovated is not None:
        row[12] = renovated
    return row


class MilestoneBadgeAcrossLanguagesTests(unittest.TestCase):
    """裁决 1/2/3：两种语言同一批徽标，年份与类型逐项相同，说明 pending 不许带走徽标。"""

    @classmethod
    def setUpClass(cls):
        cls.state = dom_state(hotel_dataset(MILESTONE_ROWS))

    def test_fixture_actually_renders_the_hotel_cards(self):
        self.assertEqual(self.state["errors"], [], "页面报错时任何断言都不成立")
        self.assertEqual(self.state["cn"]["articles"], BADGE_ROWS,
                         "夹具没渲染出这 %d 张酒店卡，本文件就量不到徽标（先修夹具再说通过）" % BADGE_ROWS)

    def test_every_badge_survives_the_language_switch(self):
        self.assertEqual(self.state["cn"]["badge_count"], BADGE_ROWS,
                         "中文态就少了徽标：说明文本形状没被识别，那是量的问题不是修复的问题")
        self.assertEqual(self.state["en"]["badge_count"], BADGE_ROWS,
                         "英文态徽标数量掉了＝MT-B5 的隐身缺陷还在：说明变 marker 不该带走年份事实")

    def test_year_and_kind_are_item_by_item_identical(self):
        cn = [(m["name"], m["milestone"]) for m in self.state["cn"]["milestones"]]
        en = self.state["en"]["milestones"]
        self.assertEqual([c[1] for c in cn], [e["milestone"] for e in en],
                         "CN/EN 的 {kind,year,source} 必须逐条相同——两种语言讲的是同一个事实")
        self.assertTrue(all(c[1] for c in cn), "有卡片没有里程碑属性：徽标与属性同生同死")
        self.assertEqual({c[1].split(":")[0] for c in cn}, {"opened", "renovated"},
                         "夹具要同时覆盖 ✨ 开业与 🛠️ 焕新两类，否则只验到一半")
        self.assertTrue(all(c[1].endswith(":dataset_note") or c[1].endswith(":structured_field")
                             for c in cn), "来源种类必须登记在册，不能是空或自造")

    def test_pending_note_does_not_hide_the_badge(self):
        pending = [m for m in self.state["en"]["milestones"] if PENDING in m["note"]]
        self.assertTrue(pending,
                        "夹具里没有一个说明是 pending＝本条没被量到；这条测的正是「说明没译成英文时徽标还在不在」")
        for m in pending:
            self.assertTrue(m["milestone"], "说明 pending 的卡片丢了里程碑：%s" % m["name"])
            self.assertTrue(m["badge"], "说明 pending 的卡片丢了徽标：%s" % m["name"])

    def test_is_new_flag_and_badge_agree_in_both_languages(self):
        for face in ("cn", "en"):
            rows = self.state[face]["milestones"]
            self.assertEqual([r["isNew"] for r in rows], ["1"] * len(rows),
                             "%s 态 data-is-new 与徽标不一致：筛选器会漏掉这些酒店" % face)


class InvalidAndStructuredTests(unittest.TestCase):
    """裁决 4/5：无年份／非法年份／低于下限不出徽标；结构化字段优先于说明解析。"""

    def test_absent_illegal_and_below_floor_years_produce_no_badge(self):
        rows = [hotel_row("无年份", "海景房步行三分钟"),
                hotel_row("说明年份不匹配", "1899年开业，历史建筑"),
                hotel_row("中文数字", "二零二二年全新开业"),
                hotel_row("结构化低于下限", "", opened="2019"),
                hotel_row("结构化越界", "", opened="1899"),
                hotel_row("结构化非数字", "", opened="二○二二"),
                hotel_row("结构化焕新越界", "", renovated="2200")]
        state = dom_state(hotel_dataset(rows))
        self.assertEqual(state["errors"], [], "非法输入把页面跑崩了：更危险")
        self.assertEqual(len(state["cn"]["milestones"]), len(rows))
        for face in ("cn", "en"):
            got = [m["milestone"] for m in state[face]["milestones"]]
            self.assertEqual(got, [""] * len(rows),
                             "%s 态无年份/非法/低于下限仍生成里程碑（越界判定被放宽就是造事实）：%s"
                             % (face, got))
            self.assertEqual(state[face]["badge_count"], 0, "%s 态非法年份仍印出徽标" % face)
            self.assertEqual([m["isNew"] for m in state[face]["milestones"]], ["0"] * len(rows),
                             "没有合法里程碑却把 data-is-new 置 1＝筛选器收到假条目")

    def test_structured_fields_beat_note_parsing(self):
        state = dom_state(hotel_dataset([hotel_row("结构化优先", "2022全面焕新，私享泻湖",
                                                   opened="2021")]))
        for face in ("cn", "en"):
            milestone = state[face]["milestones"][0]["milestone"]
            self.assertEqual(milestone, "opened:2021:structured_field",
                             "%s 态没走「结构化字段优先」，得到 %s" % (face, milestone))

    def test_note_only_source_is_labelled_dataset_note(self):
        state = dom_state(hotel_dataset([hotel_row("仅说明", "2022年全新开业，含私人沙滩")]))
        for face in ("cn", "en"):
            self.assertEqual(state[face]["milestones"][0]["milestone"], "opened:2022:dataset_note",
                             "%s 态来源标记不对：原始说明只能算 dataset_note" % face)

    def test_renovated_kind_when_only_renovation_exists(self):
        state = dom_state(hotel_dataset([hotel_row("只焕新", "2021年翻新重装")]))
        for face in ("cn", "en"):
            self.assertEqual(state[face]["milestones"][0]["milestone"],
                             "renovated:2021:dataset_note", "%s 态焕新类型判错" % face)


class RegistrationAndSingleOwnerTests(unittest.TestCase):
    """裁决 6 + 治理：登记↔实现一致；译文永不参与提取；实现与写入点各只有一处。"""

    def test_registered_numbers_match_the_renderer_constants(self):
        self.assertIn("MILESTONE_MIN_BADGE_YEAR = %d" % POLICY["year_rules"]["min_badge_year"], SPa,
                      "登记的徽标下限与实现不一致：改一处必须同步另一处，否则门禁读的是空气")
        lo, hi = POLICY["year_rules"]["valid_year_range"]
        self.assertIn("MILESTONE_VALID_YEAR_RANGE = [%d, %d]" % (lo, hi), SPa,
                      "合法年份范围登记值与实现不一致")
        self.assertIn("MILESTONE_NOTE_FIELD = %d" % POLICY["columns"]["note"], SPa,
                      "说明列号与登记不符")
        want = "MILESTONE_STRUCTURED_FIELDS = {opened: %d, renovated: %d}" % (
            POLICY["columns"]["opened_structured"], POLICY["columns"]["renovated_structured"])
        self.assertIn(want, SPa,
                      "结构化字段列号与登记不符（登记 opened=%s renovated=%s，实现那一行必须逐字对得上）"
                      % (POLICY["columns"]["opened_structured"],
                         POLICY["columns"]["renovated_structured"]))

    def test_registered_badge_copy_matches_the_renderer(self):
        for kind, copy in POLICY["badges"].items():
            block = SPa.split("MILESTONE_BADGE_COPY", 1)[1]
            section = block.split(kind, 1)
            self.assertEqual(len(section), 2, "登记了 %s 的徽标文案但 JS 里没有这一支" % kind)
            head = section[1][:260]
            for key in ("cls", "glyph", "cn", "en"):
                want = str(copy[key])
                # 同一个串在源文件里可以是原生字符也可以是 \u 转义（两种写法 JS 语义相同，
                # 而本文件里既有原生中文也有转义正则）。对账认这两种，但认不到才是真不一致。
                self.assertTrue(want in head or escape_js(want) in head,
                                "%s 徽标的 %s 与登记不一致（登记 %r，JS 片段 %s）"
                                % (kind, key, want, head[:140]))

    def test_translation_is_never_the_fact_source(self):
        self.assertNotIn("poiNote.match(", SPa,
                         "徽标又回到从**译文**提取事实：那就是 PH 七个徽标消失的根因")
        body = SPa.split("function poiMilestone(", 1)[1].split("\n}", 1)[0]
        self.assertIn("x[MILESTONE_NOTE_FIELD]", body,
                      "提取源必须是原始 x[10]（登记的 note 列），不是任何翻译后的文本")
        self.assertNotIn("poiNote", body, "里程碑实现里不许出现译文变量")

    def test_extraction_and_the_attribute_each_have_one_owner(self):
        self.assertEqual(SPa.count("function poiMilestone("), 1, "第二份提取规则＝第二套事实")
        self.assertEqual(SPa.count("milestone: milestone"), 1,
                         "data-milestone 只能写在一个槽；多一处就有 CN/EN 不一致的第二来源")
        self.assertEqual(SPa.count("const milestone = poiMilestone("), 1,
                         "第二个调用点会绕过语言无关的统一规则")

    def test_milestone_never_flows_into_evidence_or_identity(self):
        hits = [line.strip()[:90] for line in SPa.splitlines()
                if "milestone" in line.lower()
                and any(token in line for token in ("evidence", "identity_status", "VERIFIED",
                                                    "resolution_status"))]
        self.assertEqual(hits, [], "里程碑串进了核验/身份字段：原始说明只是 dataset_note，不是独立核验证据")
        self.assertIn("不得升级为 VERIFIED", json.dumps(POLICY, ensure_ascii=False),
                      "登记面要写明来源等级边界，否则下一轮会拿它当核验依据")


def escape_js(text: str) -> str:
    """JS 里非 ASCII 写作 \\uXXXX（沿用文件既有写法）；登记值要与实际字节对得上。

    代理对要拆成两个 \\u 单位：`🛠️` 在 JS 源里写作 `\\ud83d\\udee0\\ufe0f`，
    一个码点一个转义写不出来（\\u1f6e0 不是合法 JS），照那样对账永远对不上。
    """
    out = []
    for ch in text:
        code = ord(ch)
        if code < 128:
            out.append(ch)
        elif code <= 0xFFFF:
            out.append("\\u%04x" % code)
        else:
            value = code - 0x10000
            out.append("\\u%04x\\u%04x" % (0xD800 + (value >> 10), 0xDC00 + (value & 0x3FF)))
    return "".join(out)


if __name__ == "__main__":
    unittest.main()
