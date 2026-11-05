# -*- coding: utf-8 -*-
"""v4.2.2 V4-C — 清册 §9「执行型测试要求」逐条落地。

§9 的原话是「测试必须运行真实构造器、renderer 和浏览器 DOM，不得只搜索源码字符串」，
所以本文件每一条判据都落在**真实 Chromium 里抓回来的行**上：
`spa_renderer.render_spa_document` 写单文件 → playwright 打开 → 用 `visual_qa.MAP_DOM_ROWS_JS`
取 href / data-* / 可见文案 → 交给 `map_gate_v422.dom_findings` 比对。
取值面与发布 QA 用的是同一段 JS、同一个比对函数：QA 说 PASS 与测试说 PASS 必须是同一件事，
不允许测试自己另写一套规则（那正是本项目反复出问题的形状）。

覆盖 §9 逐条：
* 四种 link mode 的 dataset → renderer → DOM → href 正例（含中英两版文案）；
* 关键目标 `UNVERIFIED + NAMED_SEARCH` 正例，另测 `AMBIGUOUS + NAMED_SEARCH` 多结果提示；
* `CONFLICT / WRONG_ENTITY` 负例：无按钮且逐项进报告；
* 纯坐标命名实体 / 城市级 fallback / 占位名 / 数字残片 / 走廊串 / 字符删名 / 跨 provider 升级负例；
* 渲染层与 QA 不得维护第二套 provider 规则；
* 同输入、同配置、同版本重放两遍：dataset、逐 target 报告、HTML、门禁摘要四项一致。

零调用四项仍只由 `zero_call_sentinel` 的执行期账本提供，本文件不另出计数。
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

import map_gate_v422 as gate_mod
import spa_renderer as sr
import visual_qa
import zero_call_sentinel as sentinel
from test_v422_map_gate import gate, migrated, select_row
from test_v422_map_honest_contract import (LOOKUP, POLICY, SELECTION, publisher_row, target)

# POLICY 是合同夹具策略：它把 .example 一类的夹具域名放进「身份证据允许状态」，
# 生产策略仍然拒绝（test_v422_map_honest_contract 有专门用例钉住这一点）。
# 实体链正例只能靠夹具成立，所以本文件的门禁判定显式带 policy=POLICY——
# 不是把生产配置放宽，而是把「用的是夹具策略」写在调用处。

ROOT = Path(__file__).resolve().parent
DEST = "宿务"
V2R = Path(r"D:/文档/项目开发/Travel-Scope/.temp/v422_honest_map/V2r_migration")


def clean_ledger(scope: str) -> dict:
    with sentinel.guarded(scope):
        return sentinel.ledger({"scope": scope})


def named_case(cn: str, en: str, **over) -> dict:
    row = target(display_name=en, names={"en": en, "cn": cn})
    row.update(over)          # 用例的覆盖值必须赢，否则负例夹具会被默认名洗掉
    return row


def coordinate_case(**over) -> dict:
    row = target(entity_type="coordinate_landmark", names={}, display_name="",
                 canonical_name="", coordinate_status="VERIFIED", lat=11.9352, lng=121.9013,
                 datum="WGS84", axis_order="lat,lng",
                 coordinate_source_ref="offline-survey-2026", precision_m=15,
                 criticality="IMPORTANT")
    row.update(over)
    return row


def entity_link_case(cn: str, en: str, **over) -> dict:
    """R2 实体链夹具：可区分字段用**发布方页面里的地址**，不用地图域名。

    §17.3.3/W1R-B 判定「地图供应商自己的页面不能证明身份」，所以 declared_link_url 只用来
    证明「发布方在自己页面上挂了这条 provider 实体链接」，身份的可区分字段必须另有其值；
    自动链也不能宣称观察过 Google ⇒ google_resolution_status 保持 NOT_OBSERVED（§17.2.4）。
    """
    row = named_case(cn, en, identity_status="VERIFIED",
                     evidence=[publisher_row(
                         declared_link_url=("https://www.google.com/maps/place/%s/@10.3,123.9,17z"
                                            "/data=!3m1!4b1" % en.lower().replace(" ", "-")),
                         address="Unit 1, Osmeña Boulevard, Cebu City 6000, Philippines",
                         supported_fields=["display_name", "canonical_name", "address"])],
                     **over)
    return row


CASES = {
    # case 名 → (读者页可见名, 构造器)；四条放同一条 hotels 分支，按 data-target-id 区分。
    # 名字必须互不相同：map_targets 的字典键就是「目的地|展示名」，重名会互相覆盖（真实数据同理）。
    "publisher": ("格兰德饭店", "Grand Hotel Alpha", entity_link_case),
    "named": ("贝塔饭店", "Grand Hotel Beta", named_case),
    "coordinate": ("", "", coordinate_case),
    "none": ("加利福尼亚场地", "California Venue",
             lambda cn, en: named_case(cn, en, names={"en": "California Venue"},
                                       display_name="California Venue")),
}

# dataset_for 会补 SPA 匹配用的兼容读字段（canonical_name/destination/coords），
# 这些字段在 data-model 的 legacy 名单里——真实迁移行带 migration 说明，夹具也必须带，
# 否则就是「夹具自己犯了产品不许犯的错」。
COMPAT_MIGRATION = {
    "reason_code": "V422_EXECUTION_FIXTURE_COMPAT_FIELDS",
    "from": "scripts/test_v422_map_execution.py::dataset_for",
    "migrator_version": "v422-execution-fixture-1",
    "note": "执行型夹具为 renderer 的坐标/名称索引保留的兼容读字段；不参与任何身份或状态判定。",
}


def built_case(name: str, cn: str | None = None, en: str | None = None, **over) -> dict:
    """真实构造器 ⇒ 真实选择机 ⇒ 一条已选好的 target（本文件不手写任何 link 字段）。

    `dataset_for` 才是决定字典键／target_id 的地方（与 V2R 写入器同一规则：两者必须相等），
    所以这里不发明名称、也不预先塞 target_id。名字可按用例改写（cn/en），
    但同一页里的名字必须互不相同——字典键就是「目的地|展示名」，重名会互相覆盖。
    """
    default_cn, default_en, builder = CASES[name]
    row = builder(**over) if name == "coordinate"         else builder(cn or default_cn, en or default_en, **over)
    return select_row(row, tid=name)


def dataset_for(rows: dict[str, dict]) -> dict:
    """把若干条已选好的 target 装成一份可渲染 dataset（hotel 第 7 列是坐标槽位）。

    副作用是**有意的**：把每条 row 的 `target_id` 改写成它最终在 dataset 里的键，
    与 V2R 写入器同一规则，也满足校验器的 `MAP_TARGET_ID_KEY_MISMATCH` 对账。
    """
    hotels, map_targets = [], {}
    for index, (key, row) in enumerate(sorted(rows.items())):
        lat = float(row.get("lat") or (10.30 + index / 1000.0))
        lng = float(row.get("lng") or (123.90 + index / 1000.0))
        coords = "%.7f,%.7f" % (lat, lng)
        cn_name = str(row.get("display_name") or key)
        en_name = str((row.get("names") or {}).get("en") or "") or cn_name
        hotels.append([DEST, cn_name, en_name, "执行测试", 500, "", "", coords, "", "",
                       "V4-C 执行型用例"])
        entry = dict(row)
        dataset_key = "%s|%s" % (DEST, cn_name)
        entry["target_id"] = dataset_key
        row["target_id"] = dataset_key
        entry.update({"canonical_name": cn_name, "coords": coords, "destination": DEST,
                      "country": "Philippines",
                      "migration": dict(COMPAT_MIGRATION,
                                        fields=["canonical_name", "destination", "coords"])})
        map_targets["%s|%s" % (DEST, cn_name)] = entry
    return {
        "country": "菲律宾", "country_en": "Philippines", "artifact_slug": "execution",
        "duration_days": 2, "routes": [["海岸线", "Coast Route", DEST, "2天", "Car", 1000, ""]],
        "route_budgets": {"海岸线": {"total_cny": 1000}},
        "destinations": [[DEST, "Cebu"]], "itinerary": [], "hotels": hotels,
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [], "transport_nodes": [],
        "budget": [["1", "TBD", "抵达", 500, 200, 100, 100, 100, 1000]],
        "practical": [], "worth_it": [], "local_chains": [], "packing": [],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [], "section_media": [],
        "map_targets": map_targets,
        "map_link_selection": {"selection_version": SELECTION["selection_version"]},
    }


def read_rendered_page(dataset, tamper_js: str | None = None, english: bool = False) -> dict:
    """渲染成单文件 → 真浏览器打开 → 抓读者真正看到的地图入口行。"""
    with tempfile.TemporaryDirectory() as folder:
        html_path = Path(folder) / "execution-guide.html"
        sr.render_spa_document(html_path, copy.deepcopy(dataset), reader_profile="en-audit")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(html_path.as_uri(), wait_until="load")
            if tamper_js:
                page.evaluate(tamper_js)
            view = {"rows": page.evaluate(visual_qa.MAP_DOM_ROWS_JS),
                    "payload": json.loads(page.evaluate(
                        "() => document.getElementById('dataset').textContent")),
                    "text": page.locator("#panel-stays").inner_text(),
                    "html_bytes": html_path.read_bytes(),
                    "page_errors": errors}
            if english:
                page.locator("#lang-btn").dispatch_event("click")
                page.wait_for_timeout(250)
                view["english_rows"] = page.evaluate(visual_qa.MAP_DOM_ROWS_JS)
                view["english_text"] = page.locator("#panel-stays").inner_text()
            browser.close()
    return view


def dom_row(view, case_row, key: str = "rows"):
    hits = [row for row in view[key] if row.get("targetId") == case_row["target_id"]]
    return hits


class FourLinkModeDomTests(unittest.TestCase):
    """§9 第 1 条：四种 link mode 的 dataset → renderer → DOM → href 逐条走通。"""

    @classmethod
    def setUpClass(cls):
        cls.cases = {name: built_case(name) for name in CASES}
        cls.view = read_rendered_page(dataset_for(cls.cases), english=True)

    def rows(self, key):
        return dom_row(self.view, self.cases[key])

    def test_every_mode_renders_exactly_the_registered_shape(self):
        want = {"publisher": 1, "named": 1, "coordinate": 1, "none": 0}
        modes = {"publisher": "PUBLISHER_ENTITY_LINK", "named": "NAMED_SEARCH",
                 "coordinate": "COORDINATE", "none": "NONE"}
        for key, mode in modes.items():
            self.assertEqual(self.cases[key]["link_mode"], mode,
                             "%s 走成了 %s：四种 link mode 的正例其实没跑全"
                             % (key, self.cases[key]["link_mode"]))
        for key, count in want.items():
            got = self.rows(key)
            self.assertEqual(len(got), count, "%s 按钮数=%d 应为 %d：%s"
                             % (key, len(got), count, got))
            if count:
                self.assertEqual(got[0]["linkMode"], self.cases[key]["link_mode"], key)

    def test_href_equals_the_dataset_value_verbatim_and_resolved(self):
        for key in ("publisher", "named", "coordinate"):
            row = self.rows(key)[0]
            record = self.cases[key]["map_link_by_provider"]["google"]
            self.assertEqual(row["href"], record["map_link_url"], key)
            self.assertEqual(row["resolvedHref"], row["href"],
                             "%s 浏览器解析后的 href 与写法不一致：读者点的不是 dataset 里那条" % key)

    def test_button_copy_comes_from_the_register_in_both_languages(self):
        registry = SELECTION["ui"]["button_copy"]
        for key in ("publisher", "named", "coordinate"):
            row = self.rows(key)[0]
            self.assertEqual(row["text"], registry[row["linkMode"]]["cn"], key)
            english = dom_row(self.view, self.cases[key], "english_rows")[0]
            self.assertEqual(english["text"], registry[english["linkMode"]]["en"], key)
            self.assertEqual(english["href"], row["href"], "切语言不得改 href")

    def test_eight_audit_attributes_are_present_and_match_the_dataset(self):
        for key in ("publisher", "named", "coordinate"):
            row, source = self.rows(key)[0], self.cases[key]
            for attribute in ("targetId", "entityType", "criticality", "identityStatus",
                              "coordinateStatus", "linkMode", "resolutionStatus", "provider"):
                self.assertTrue(str(row.get(attribute) or ""), "%s/%s 属性为空（§7 八项）"
                                % (key, attribute))
            for attribute, field in (("entityType", "entity_type"), ("criticality", "criticality"),
                                     ("identityStatus", "identity_status"),
                                     ("coordinateStatus", "coordinate_status"),
                                     ("resolutionStatus", "google_resolution_status")):
                self.assertEqual(row[attribute], str(source[field]), "%s/%s" % (key, attribute))
            self.assertEqual(row["provider"], "google", key)

    def test_unavailable_target_still_tells_the_reader_why(self):
        self.assertIn(SELECTION["ui"]["button_copy"]["NONE"]["cn_note"], self.view["text"],
                      "没有按钮也要说明，不留空白让读者以为页面坏了")

    def test_gate_finds_no_dom_dataset_inconsistency_on_the_real_page(self):
        findings = gate_mod.dom_findings(self.view["payload"]["map_targets"],
                                         self.view["rows"], gate(), SELECTION)
        self.assertEqual(findings, [], findings)

    def test_reader_payload_only_carries_rendered_providers(self):
        rendered = set(SELECTION["ui"]["rendered_providers"])
        for key, entry in self.view["payload"]["map_targets"].items():
            self.assertEqual(set(entry["map_link_by_provider"]), rendered, key)
        self.assertEqual({row["provider"] for row in self.view["rows"]}, rendered)
        self.assertEqual(self.view["page_errors"], [], "页面脚本错误会让 DOM 与 dataset 都不可信")


class DomConsistencyTeethTests(unittest.TestCase):
    """§8.1「dataset/DOM/report/href/link mode 不一致 = 0」必须真咬：包括浏览器里被改写的 href。"""

    def setUp(self):
        self.row = built_case("named")
        self.dataset = dataset_for({"named": self.row})

    def test_tampering_the_live_dom_is_caught_by_the_same_gate_function(self):
        view = read_rendered_page(self.dataset, tamper_js=(
            "() => { const a = document.querySelector('.map-links a[data-link-mode]');"
            " a.setAttribute('href', a.getAttribute('href').replace('query=', 'query=Fake%20'));"
            " a.dataset.identityStatus = 'VERIFIED'; }"))
        findings = gate_mod.dom_findings(view["payload"]["map_targets"], view["rows"],
                                         gate(), SELECTION)
        codes = sorted({item.split("|")[0] for item in findings})
        self.assertIn("GATE_DOM_HREF_DIFFERS", codes, findings)
        self.assertIn("GATE_DOM_STATUS_DIFFERS", codes,
                      "读者页状态被脚本改写成 VERIFIED，就是 §3.4 禁止的升级")

    def test_missing_extra_and_unregistered_rows_are_each_named(self):
        view = read_rendered_page(self.dataset)
        base, good = view["payload"]["map_targets"], view["rows"]
        self.assertTrue(any(item.startswith("GATE_DOM_HREF_MISSING")
                            for item in gate_mod.dom_findings(base, [], gate(), SELECTION)))
        ghost = [dict(good[0], targetId="ghost|宿务")]
        self.assertTrue(any(item.startswith("GATE_DOM_HREF_UNEXPECTED")
                            for item in gate_mod.dom_findings(base, list(good) + ghost,
                                                              gate(), SELECTION)))
        wrong = [dict(good[0], provider="baidu")]
        self.assertTrue(any(item.startswith("GATE_DOM_PROVIDER_UNREGISTERED")
                            for item in gate_mod.dom_findings(base, wrong, gate(), SELECTION)))
        no_id = [dict(good[0], targetId="")]
        self.assertTrue(any(item.startswith("GATE_DOM_TARGET_ID_MISSING")
                            for item in gate_mod.dom_findings(base, no_id, gate(), SELECTION)))
        mode = [dict(good[0], linkMode="PUBLISHER_ENTITY_LINK")]
        self.assertTrue(any(item.startswith("GATE_DOM_LINK_MODE_DIFFERS")
                            for item in gate_mod.dom_findings(base, mode, gate(), SELECTION)))
        reworded = [dict(good[0], text="查看地点")]
        self.assertTrue(any(item.startswith("GATE_DOM_COPY_DIFFERS")
                            for item in gate_mod.dom_findings(base, reworded, gate(), SELECTION)),
                        "具名搜索写成『查看地点』＝把未核验说成已核验，必须被门禁看见")

    def test_same_target_rendered_twice_must_be_identical(self):
        """真实数据实测：PH 198 个目标渲染出 265 颗按钮（同一 POI 出现在多个板块）。
        重复本身合法，重复但不同形就是「读者点哪个不一样」，必须单独判一条。"""
        view = read_rendered_page(self.dataset)
        base, good = view["payload"]["map_targets"], view["rows"]
        self.assertEqual(gate_mod.dom_findings(base, good + [dict(good[0])], gate(), SELECTION),
                         [], "完全一致的重复渲染不该被当成缺陷")
        conflicting = gate_mod.dom_findings(
            base, good + [dict(good[0], href="https://www.google.com/maps/search/?api=1&query=X")],
            gate(), SELECTION)
        self.assertTrue(any(item.startswith("GATE_DOM_DUPLICATE_CONFLICT")
                            for item in conflicting), conflicting)

    def test_visual_qa_path_calls_the_gate_and_carries_no_second_host_rule(self):
        body = (ROOT / "visual_qa.py").read_text(encoding="utf-8")
        start = body.index("def check_map_dom_dataset_consistency(")
        end = body.index("def check_spa_page(")
        block = body[start:end]
        self.assertIn("map_gate_v422.dom_findings", block)
        self.assertIn("MAP_DOM_ROWS_JS", block)
        for needle in ("googleapis", "uri.amap.com", "maps.apple.com", "api=1"):
            self.assertNotIn(needle, block, "QA 侧又长了第二套 provider 规则：%s" % needle)
        self.assertIn("check_map_dom_dataset_consistency(page, dataset, failures, result)",
                      body[end:])

    def test_renderer_map_link_path_builds_no_urls(self):
        """§9：渲染层不得维护第二套主机/路径规则——按函数体查，不按整份文件查。"""
        js = (ROOT.parent / "assets" / "spa-layout.js").read_text(encoding="utf-8")
        for marker in ("function mapLinkRecord", "function mapLinks"):
            body = js[js.index(marker):]
            body = body[:body.index("\n}\n") + 2]
            for needle in ("googleapis", "maps.google", "api=1", "maps.apple", "query=",
                           "encodeURIComponent"):
                self.assertNotIn(needle, body, "%s 里出现了 %r：链接只能来自选择器写下的值"
                                 % (marker, needle))


class HonestDowngradeDomTests(unittest.TestCase):
    """§9 第 2 条 + §5.2：降级要诚实——按钮在、提示在、状态不升级、冲突进报告。"""

    def test_critical_unverified_named_search_shows_notice_and_keeps_state(self):
        row = built_case("named")
        view = read_rendered_page(dataset_for({"named": row}))
        dom = dom_row(view, row)[0]
        self.assertIn(SELECTION["ui"]["notices"]["key_target_unverified"]["cn"], view["text"],
                      "关键目标的『以订单/票证为准』提示不许省（§5.2）")
        self.assertEqual(dom["identityStatus"], "UNVERIFIED")
        self.assertEqual(dom["resolutionStatus"], "NOT_OBSERVED",
                         "具名搜索不许把观察状态写成已核验（§3.4）")
        self.assertNotIn("查看地点", dom["text"])
        self.assertIn("落点未核验", dom["text"])

    def test_ambiguous_named_search_shows_multi_result_notice_and_stays_ambiguous(self):
        # 只用 identity_status=AMBIGUOUS 触发多结果提示：自动链没有独立观察记录，
        # 把 google_resolution_status 写成 MULTIPLE_RESULTS 就是伪造观察（§17.2.4 会阻断）。
        row = built_case("named", identity_status="AMBIGUOUS")
        self.assertEqual(row["link_mode"], "NAMED_SEARCH",
                         "AMBIGUOUS 允许搜索，但必须带多结果核对提示（§5.2/§8.2）")
        self.assertIn("ambiguous_multiple_results",
                      row["map_link_by_provider"]["google"]["link_notices"],
                      row["map_link_by_provider"]["google"])
        dataset = dataset_for({"ambiguous": row})
        view = read_rendered_page(dataset)
        self.assertIn(SELECTION["ui"]["notices"]["ambiguous_multiple_results"]["cn"],
                      view["text"], "多结果提示没进 DOM，读者就会把搜索结果当唯一答案")
        dom = dom_row(view, row)[0]
        self.assertEqual(dom["identityStatus"], "AMBIGUOUS")
        self.assertEqual(dom["resolutionStatus"], "NOT_OBSERVED",
                         "AMBIGUOUS + NAMED_SEARCH 不计为已核验实体，也不许伪造观察（§8.2）")
        result = gate_mod.evaluate(migrated(dataset["map_targets"]), gate(), SELECTION,
                                   policy=POLICY, ledger=clean_ledger("dom"), dom_rows=view["rows"])
        self.assertEqual(result["counts"]["blocking"], 0, result["blocking"][:5])
        # §8.2：AMBIGUOUS + NAMED_SEARCH 不计为已核验实体——门禁不得吐任何「VERIFIED 成立」的判定，
        # 且这一条必须逐项进 AMBIGUOUS 名单，而不是被「有按钮」这件事掩盖掉。
        self.assertFalse([item for item in result["blocking"] + result["exposed"]
                          if item.split("|")[0].startswith("IDENTITY_VERIFIED")],
                         result["blocking"][:5])
        self.assertEqual(result["itemized"]["AMBIGUOUS"], [row["target_id"]], result["itemized"])

    def test_conflict_and_wrong_entity_have_no_button_and_are_itemized_in_the_report(self):
        observation = {"environment": "manual_review_desktop_chrome",
                       "observed_at": "2026-10-29T10:00:00+08:00",
                       "observer": "合同夹具：人工核对，不是自动链的观察"}
        rows = {"conflict": built_case("named", cn="伽马饭店", en="Gamma Hotel",
                                      identity_status="CONFLICT"),
                "wrong": built_case("named", cn="德尔塔饭店", en="Delta Hotel",
                                    google_resolution_status="WRONG_ENTITY",
                                    google_observation=dict(observation))}
        for key, row in rows.items():
            self.assertEqual(row["link_mode"], "NONE", "%s 竟然拿到了按钮" % key)
        dataset = dataset_for(rows)
        view = read_rendered_page(dataset)
        self.assertEqual(view["rows"], [], "CONFLICT/WRONG_ENTITY 仍渲染出 map 按钮")
        self.assertEqual(view["text"].count(SELECTION["ui"]["button_copy"]["NONE"]["cn_note"]), 2,
                         "两条无按钮目标各自说明，不许合并成一句")
        result = gate_mod.evaluate(migrated(dataset["map_targets"]), gate(), SELECTION,
                                   policy=POLICY, ledger=clean_ledger("dom"), dom_rows=view["rows"])
        self.assertEqual(result["batch_verdict"], "FAIL",
                         "业主 2026-10-29 指令 §5：已知冲突既无按钮也整批阻断")
        self.assertEqual(len(result["itemized"]["CONFLICT"]), 1, result["itemized"])
        self.assertEqual(len(result["itemized"]["NONE"]), 2, result["itemized"])
        codes = [item.split("|")[0] for item in result["blocking"]]
        self.assertEqual(codes.count("GATE_HARD_CONFLICT_STATE"), 2, result["blocking"][:6])
        self.assertFalse([item for item in result["blocking"]
                          if item.startswith("GATE_HARD_CONFLICT_HAS_BUTTON")],
                         "已经不给按钮，不该再报『带按钮』")

    def test_gate_reports_itemized_lists_for_every_registered_state(self):
        row = built_case("named", cn="厄塔饭店", en="Epsilon Hotel",
                         identity_status="UNRESOLVED")
        dataset = dataset_for({"u": row})
        result = gate_mod.evaluate(migrated(dataset["map_targets"]), gate(), SELECTION,
                                   policy=POLICY, ledger=clean_ledger("itemized"))
        for name in gate()["reporting"]["itemized_lists_required"]:
            self.assertIn(name, result["itemized"], name)
        self.assertEqual(result["itemized"]["UNRESOLVED"], [row["target_id"]], result["itemized"])


class ContractNegativeDomTests(unittest.TestCase):
    """§9 第 4 条：七类负例都要在真实渲染路径上给出「无按钮 / 不升级」的形态。"""

    def render(self, **over):
        row = built_case("named", **over)
        return row, read_rendered_page(dataset_for({"neg": row}))

    def test_named_entity_never_gets_a_pure_coordinate_button(self):
        row, view = self.render(coordinate_status="VERIFIED")
        self.assertNotEqual(row["link_mode"], "COORDINATE")
        self.assertNotIn("ll=", urllib.parse.unquote(view["rows"][0]["resolvedHref"]))
        findings = gate_mod.coordinate_button_findings(
            {"neg": dict(row, link_mode="COORDINATE")})
        self.assertTrue(findings, "命名实体拿坐标按钮必须由门禁咬住（§8.1）")

    def test_city_country_and_corridor_only_fallback_yield_no_button(self):
        cases = {
            "空名": {"names": {}, "display_name": "", "canonical_name": ""},
            "走廊串": {"names": {"en": "旧金山 - 蒙特雷与卡梅尔 - 大苏尔"},
                       "display_name": "旧金山 - 蒙特雷与卡梅尔 - 大苏尔"},
            "数字残片": {"names": {"en": "39"}, "display_name": "39"},
            "占位名": {"names": {"en": "California Venue"}, "display_name": "California Venue"},
        }
        for label, over in cases.items():
            row, view = self.render(**over)
            self.assertEqual(row["link_mode"], "NONE", "%s ⇒ %s" % (label, row["link_mode"]))
            self.assertEqual(view["rows"], [], "%s 仍在 DOM 里留下了按钮" % label)
            self.assertEqual(row["map_link_url"], "", "%s 的 URL 必须是空的" % label)

    def test_character_stripped_english_name_keeps_the_sourced_local_name(self):
        local = "长滩岛Bulabog"
        row, view = self.render(names={"cn": local, "en": "Bulabog"},
                                display_name=local, canonical_name=local)
        self.assertEqual(row["link_mode"], "NAMED_SEARCH")
        href = view["rows"][0]["resolvedHref"]
        self.assertIn(urllib.parse.quote(local, safe=""), href)
        self.assertNotIn("query=Bulabog", href, "删出来的英文名又回到查询串了（§4 禁止动作）")
        self.assertEqual(row["map_link_by_provider"]["google"]["map_query_name_source"],
                         "names.cn(after_residue)")

    def test_local_name_reaches_the_browser_undamaged(self):
        local = "墨宝佩斯卡多尔岛大断层"
        row, view = self.render(names={"cn": local}, display_name=local, canonical_name=local)
        self.assertIn(local, urllib.parse.unquote(view["rows"][0]["resolvedHref"]),
                      "浏览器收到的串必须与选择器写下的逐字一致")
        self.assertEqual(view["rows"][0]["href"],
                         row["map_link_by_provider"]["google"]["map_link_url"])

    def test_google_evidence_does_not_upgrade_apple(self):
        row = built_case("publisher")
        container = row["map_link_by_provider"]
        self.assertEqual(container["google"]["link_mode"], "PUBLISHER_ENTITY_LINK")
        self.assertNotEqual(container["apple"]["link_mode"], "PUBLISHER_ENTITY_LINK",
                            "Google 的证据不能替 Apple 宣布实体链（§3.3 逐 provider 隔离）")
        view = read_rendered_page(dataset_for({"publisher": row}))
        for entry in view["payload"]["map_targets"].values():
            self.assertEqual(set(entry["map_link_by_provider"]),
                             set(SELECTION["ui"]["rendered_providers"]),
                             "读者载荷里的 provider 必须等于登记值")
        audit = gate_mod.evaluate(migrated(dataset_for({"publisher": row})["map_targets"]),
                                  gate(), SELECTION, policy=POLICY,
                                  ledger=clean_ledger("audit"), payload_kind="audit")
        reader = gate_mod.evaluate(migrated(view["payload"]["map_targets"]), gate(), SELECTION,
                                   policy=POLICY, ledger=clean_ledger("reader"),
                                   payload_kind="reader", dom_rows=view["rows"])
        self.assertEqual(audit["counts"]["blocking"], 0, audit["blocking"][:5])
        self.assertEqual(reader["counts"]["blocking"], 0, reader["blocking"][:5])


class ReplayDeterminismTests(unittest.TestCase):
    """§9 最后一条：同输入、同配置、同版本重放两遍，四项摘要规范化后必须一致。"""

    def digest(self, obj) -> str:
        blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16].upper()

    def one_pass(self) -> dict:
        cases = {name: built_case(name) for name in CASES}
        dataset = dataset_for(cases)
        # 报告行的 target_id 必须等于 dataset 键（V2R 写入器同一规则），否则 §8.1 对不上账
        report = [{"target_id": entry["target_id"], "provider": provider, "after": record}
                  for entry in sorted(dataset["map_targets"].values(),
                                      key=lambda item: item["target_id"])
                  for provider, record in sorted(entry["map_link_by_provider"].items())]
        view = read_rendered_page(dataset)
        gate_report = gate_mod.evaluate(migrated(dataset["map_targets"]), gate(), SELECTION,
                                        report_rows=report, policy=POLICY,
                                        ledger=clean_ledger("replay"), dom_rows=view["rows"],
                                        payload_kind="audit")
        return {"dataset": self.digest(dataset["map_targets"]),
                "report": self.digest(report),
                "html_sha256": hashlib.sha256(view["html_bytes"]).hexdigest()[:16].upper(),
                "gate": self.digest({key: gate_report[key] for key in
                                     ("counts", "code_tally", "batch_verdict", "targets",
                                      "applicability", "blocking", "exposed", "itemized")})}

    def test_two_passes_are_identical(self):
        first, second = self.one_pass(), self.one_pass()
        self.assertEqual(first, second, "同输入两次跑出不同摘要＝本版不可复现")
        self.assertTrue(all(first[key] for key in first))

    def test_gate_replays_identically_over_the_real_v2r_datasets(self):
        if not (V2R / "primary").is_dir():
            self.skipTest("V2R 证据目录不存在：%s" % V2R)
        for run in ("california_v420", "philippines_v419"):
            dataset = json.loads((V2R / "primary" / run / "dataset_v422_selected.json")
                                 .read_text(encoding="utf-8"))
            rows = [json.loads(line) for line in
                    (V2R / "primary" / run / "link_selection_report.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
            passes = [gate_mod.evaluate(dataset, gate(), SELECTION, report_rows=rows,
                                       ledger=clean_ledger("real replay")) for _ in range(2)]
            summaries = [self.digest({key: item[key] for key in
                                      ("counts", "code_tally", "batch_verdict", "targets",
                                       "blocking", "exposed", "itemized")}) for item in passes]
            self.assertEqual(summaries[0], summaries[1], run)
            self.assertTrue(passes[0]["enforced"], run)


if __name__ == "__main__":
    unittest.main()
