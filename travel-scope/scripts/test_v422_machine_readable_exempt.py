# -*- coding: utf-8 -*-
"""v4.2.2 ZH-RELEASE-2 步② — 机读面精确路径豁免的牙齿测试（业主 2026-11-03 裁②）。

裁②逐字要的是六件事，本文件按这六件分组咬，一组都不许用「别的门」代替：

1. 只豁免**精确路径** `map_targets.*.names.en`，不得全局放行键名 en／`names.en`／所有 `*_en`；
2. 继续要求值不含中文并符合既有 `names_schema`（豁免 ≠ 免检）；
3. 哨兵放进该路径后，地图查询／身份合同仍能读到它；
4. 哨兵不得出现在可见 DOM 文本；
5. 同名字段放在其他路径必须被剥离或阻断；
6. alias 指纹必须与迁移前一致，地图最终 findings 恢复为 0——**不是**把基准改成 30＋30。

规则沿用 #113：「被别的门拦下＝不算证」，所以每条负测都断言它点名的那个码，
并且和同数据集上未篡改的正对照配对（正对照绿＝尺子是活的）。
分母全部从冻结加州 run 现算，不手写在本文件里（登记值另有 `EXEMPT_MAP_CONSEQUENCE_MEASURED.json`）。
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
ROOT = SCRIPTS.parent
CA_RUN = (ROOT.parent / "candidate_runs"
          / "travel_scope_run_202701_usa_california_v422_001" / "dataset.json")

from playwright.sync_api import sync_playwright  # noqa: E402

import map_gate_v422 as mg  # noqa: E402
import map_link_selector as mls  # noqa: E402
import reader_payload_scope as rps  # noqa: E402
import spa_renderer as sr  # noqa: E402

FORMAL = sr.formal_reader_profile()
SHAPE = "$.map_targets.*.names.en"
SEGMENTS = ["map_targets", "*", "names", "en"]
SENTINEL = "ZZSENTINEL4237Q"
PROBE_JS = """(SENT) => {
  const visible = document.body ? (document.body.innerText || '') : '';
  const hits = {visible: visible.includes(SENT), href: [], data: [], payload: 0};
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (href.includes(SENT)) hits.href.push(href.slice(0, 150));
  });
  document.querySelectorAll('*').forEach(el => {
    for (const [k, v] of Object.entries(el.dataset || {})) {
      if (String(v).includes(SENT)) hits.data.push('data-' + k);
    }
  });
  const s = document.getElementById('dataset');
  if (s) hits.payload = (s.textContent || '').split(SENT).length - 1;
  hits.lang_btn = document.querySelectorAll('#lang-btn').length;
  return hits;
}"""


def run_dataset() -> dict:
    """冻结加州 run 的输入面：只读，任何测试都不许写它。"""
    return json.loads(CA_RUN.read_bytes().decode("utf-8"))


def project(data: dict, *, without_exemption: bool = False) -> tuple:
    """走正式档投影；`without_exemption` 只是把合同里那条豁免拔掉（模拟迁移前）。"""
    saved = rps.scope_contract
    if without_exemption:
        def patched(path=None):
            block = copy.deepcopy(saved(path) if path is not None else saved())
            spec = ((block.get("profiles") or {}).get(FORMAL) or {}).get("payload_scope")
            if not isinstance(spec, dict):
                raise AssertionError("夹具前提不成立：profiles.%s.payload_scope 不在盘上" % FORMAL)
            spec["machine_readable_exempt_paths"] = []
            return block
        rps.scope_contract = patched
    try:
        return rps.project_reader_payload(copy.deepcopy(data), FORMAL, formal_profile=FORMAL)
    finally:
        rps.scope_contract = saved


def map_face(targets: dict, country: str) -> dict:
    """地图合同在这一面 map_targets 上读到什么：alias findings／期望按钮／逐条别名指纹。"""
    gate, selection = mg.load_gate(), mls.load_selection()
    alias_by_id, findings = mg.resolve_aliases(targets, gate, selection, country=country)
    expected = mg.expected_dom_links(targets, selection, alias_by_id=alias_by_id)
    contract = mg.alias_contract(gate)
    compared = [str(f) for f in (contract.get("compared_fields") or [])]
    providers = [str(p) for p in selection["ui"]["rendered_providers"]]
    prints = []
    for entry in (contract.get("entries") or []):
        scope = str(entry.get("scope") or "")
        if scope and scope != country:
            continue
        alias = targets.get(str(entry.get("alias_key") or ""))
        canonical = targets.get(str(entry.get("canonical_key") or ""))
        if not isinstance(alias, dict) or not isinstance(canonical, dict):
            prints.append({"alias_key": entry.get("alias_key"), "fingerprint": None,
                           "registered": str(entry.get("identical_fields_digest") or "").upper(),
                           "match": False})
            continue
        _ok, _diff, fingerprint = mg.alias_identity(alias, canonical, compared, providers, selection)
        registered = str(entry.get("identical_fields_digest") or "").upper()
        prints.append({"alias_key": entry.get("alias_key"), "fingerprint": fingerprint.upper(),
                       "registered": registered, "match": fingerprint.upper() == registered})
    return {"findings": [str(f) for f in findings],
            "codes": sorted({str(f).split("|", 1)[0] for f in findings}),
            "expected_buttons": len(expected), "fingerprints": prints}


def independent_names_en_count(data: dict) -> int:
    """独立表达式（不用豁免那把尺子）：map_targets 里合法拉丁 names.en 有几条。"""
    total = 0
    for target in (data.get("map_targets") or {}).values():
        names = target.get("names") if isinstance(target, dict) else None
        value = (names or {}).get("en") if isinstance(names, dict) else None
        if isinstance(value, str) and value.strip() and not re.search(r"[㐀-鿿]", value):
            total += 1
    return total


def patterns_used() -> list:
    """EN 形状模式取自合同登记（本文件不另立一套词表）。"""
    return list((rps.profile_scope(FORMAL) or {}).get("nested_en_patterns") or rps.NESTED_EN_PATTERNS)


def pick_named_search_target(data: dict) -> str:
    for key, target in sorted((data.get("map_targets") or {}).items()):
        container = target.get("map_link_by_provider") or {}
        if str((container.get("google") or {}).get("link_mode")) == "NAMED_SEARCH" \
                and (target.get("names") or {}).get("en"):
            return key
    raise AssertionError("夹具前提不成立：加州 run 里没有 NAMED_SEARCH 且带 names.en 的目标")


def render_sentinel_page(data: dict, key: str, *, rebuild_href: bool = True) -> tuple:
    """把哨兵放进 names.en（并按合同重算选路记录），渲染成中文正式件形态的页面。"""
    probe = copy.deepcopy(data["map_targets"][key])
    probe["names"]["en"] = SENTINEL
    if rebuild_href:
        rec = mls.select(key, probe, "google", sel=mls.load_selection()).as_record()
        probe["map_link_by_provider"] = {**(probe.get("map_link_by_provider") or {}), "google": rec}
        probe["map_link_url"] = rec.get("map_link_url")
    folder = tempfile.TemporaryDirectory()
    out = pathlib.Path(folder.name) / "sentinel-travel-guide.html"
    sr.render_spa_document(out, {**data, "map_targets": {**data["map_targets"], key: probe}},
                           reader_profile=FORMAL)
    return out, folder


def browser_probe(html_path: pathlib.Path) -> dict:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(html_path.as_uri(), wait_until="load")
            page.wait_for_timeout(1200)
            return page.evaluate(PROBE_JS, SENTINEL)
        finally:
            browser.close()


class RegisteredShapeTests(unittest.TestCase):
    """①豁免只有一条精确路径，而且「不够精确」的形状编译不出来。"""

    def test_exactly_one_precise_path_is_registered(self):
        exempt = rps.machine_readable_exempt_paths(FORMAL)
        self.assertEqual(len(exempt), 1, "豁免位不止一条 ⇒ 「只豁免精确路径」已经失守：%s" % exempt)
        entry = exempt[0]
        self.assertEqual(entry["segments"], SEGMENTS)
        self.assertEqual(entry["shape"], SHAPE)
        self.assertEqual(sorted(entry["value_checks"]), sorted(rps.VALUE_CHECKS),
                         "登记了没实现的检查＝豁免面没人复检")
        block = rps.scope_contract()
        registered = ((block.get("profiles") or {}).get(FORMAL) or {})["payload_scope"] \
            ["machine_readable_exempt_paths"][0]
        self.assertIs(registered.get("reader_visible"), False,
                      "豁免位若自称读者可见，就和「读者页不印英文」这句话打架")
        self.assertTrue(registered.get("must_not_extend_to"),
                        "没登记「不许延伸到哪里」＝这条豁免随时可以被解释成全局放行")

    def test_global_wildcard_shapes_are_not_compilable(self):
        """首段／末段是通配、或没有父路径锚点 ⇒ 就是按键名或按顶层放行，必须阻断。"""
        for segments in (["*", "*", "*", "en"],              # 任意父路径下的 en
                         ["map_targets", "*", "names", "*"],  # 末段通配＝按 names 里的任意键名放行
                         ["*"], ["map_targets", "*", "*"],    # 只有一个字面段
                         ["map_targets", "*", "*", "*"]):
            with self.assertRaises(rps.ScopeError) as caught:
                rps._compile_exemptions([{"path_segments": segments, "value_checks": []}])
            self.assertEqual(caught.exception.code, "scope_exempt_path_shape_unregistered",
                             "%r 应该被形状码拦下，实测 %s" % (segments, caught.exception.code))
        # 正对照：全字面序列是合法的精确路径（不是越精确越好——但要能编出来）
        compiled = rps._compile_exemptions([{"path_segments": ["map_targets", "names", "en"],
                                             "value_checks": ["nonempty_string"]}])
        self.assertEqual(len(compiled), 1)

    def test_matcher_requires_the_whole_segment_sequence(self):
        pattern = SEGMENTS
        self.assertTrue(rps._match_exempt(pattern, ["map_targets", "旧金山|X", "names", "en"]))
        for actual in (["map_targets", "X", "en"],                       # 少一段
                       ["map_targets", "X", "names", "sub", "en"],       # 多一段
                       ["hotels", "X", "names", "en"],                   # 换父路径
                       ["map_targets", "X", "labels", "en"],             # 换结构段
                       ["map_targets", "X", "names", "cn"],              # 换字段名
                       ["map_targets", "X", "names", "EN"]):             # 大小写不同也不算
            self.assertFalse(rps._match_exempt(pattern, actual),
                             "这个形状不该命中精确路径，却命中了：%r" % (actual,))
        # `*` 只吃恰好一段：两级嵌套不能被一条通配跨过
        self.assertFalse(rps._match_exempt(pattern, ["map_targets", "X", "Y", "names", "en"]))


class ReconciliationTests(unittest.TestCase):
    """豁免前后的账必须闭合：保留下来的每一条都恰好是原本会被剥掉的那一条。"""

    @classmethod
    def setUpClass(cls):
        cls.data = run_dataset()
        cls.projected, cls.report = project(cls.data)
        cls.stripped_all, cls.report_before = project(cls.data, without_exemption=True)

    def test_kept_plus_stripped_equals_pre_exemption_total(self):
        kept = int(self.report.get("machine_readable_kept_total") or 0)
        stripped = int(self.report.get("nested_en_total") or 0)
        before = int(self.report_before.get("nested_en_total") or 0)
        self.assertEqual(kept + stripped, before,
                         "恒等式不闭合：保留 %d ＋剥离 %d ≠ 迁移前剥离 %d" % (kept, stripped, before))
        self.assertEqual(kept, independent_names_en_count(self.data),
                         "保留数与独立表达式（直接数 map_targets 的拉丁 names.en）不符")
        self.assertEqual(self.report_before.get("machine_readable_kept_total"), 0,
                         "拔掉豁免后还「保留」＝豁免不是合同驱动的，代码里另记了一份")

    def test_removed_exemption_deletes_the_key_not_the_value(self):
        """拔掉豁免那必须是**整键删除**：留一个空串等于给「豁免只覆盖形状」之外又开了个口子。"""
        self.assertEqual(self.report.get("machine_readable_exempt_shapes"), [SHAPE],
                         "投影报告登记的豁免形状与合同那一条不同 ⇒ 生效的不是登记的那一条")
        self.assertEqual(list(self.report.get("machine_readable_kept") or {}), [SHAPE])
        key = pick_named_search_target(self.data)
        before = dict(self.data["map_targets"][key]["names"])
        after = dict(self.stripped_all["map_targets"][key]["names"])
        self.assertNotIn("en", after, str(after)[:160])
        self.assertEqual({k: v for k, v in after.items() if k != "en"},
                         {k: v for k, v in before.items() if k != "en"},
                         "拔掉豁免时不该顺手改 names 里的其他键")
        kept = dict(self.projected["map_targets"][key]["names"])
        self.assertEqual(kept, before, "带豁免的那一遍应逐字保留整个 names 对象")

    def test_projection_leaves_no_unregistered_leftover(self):
        """残留自检：带豁免投影后仍不许有任何 EN 形状键活着（豁免位之外的漏网即阻断）。"""
        leftovers = rps._scan_en(self.projected, patterns=patterns_used(),
                                 exempt=rps.machine_readable_exempt_paths(FORMAL))
        self.assertEqual(leftovers, [], str(leftovers)[:200])
        without = rps._scan_en(self.stripped_all, patterns=patterns_used(), exempt=[])
        self.assertEqual(without, [], "拔掉豁免的那一遍也不该有残留，否则正对照不成立")


class ValueIsStillCheckedTests(unittest.TestCase):
    """②豁免只覆盖形状：值仍须非空字符串、不含汉字、符合 names_schema。"""

    @classmethod
    def setUpClass(cls):
        cls.data = run_dataset()
        cls.key = pick_named_search_target(cls.data)

    def _trial(self, names: dict):
        trial = copy.deepcopy(self.data)
        trial["map_targets"][self.key] = {**trial["map_targets"][self.key], "names": names}
        return project(trial)

    def test_positive_control_the_real_run_projects_clean(self):
        projected, report = self._trial(dict(self.data["map_targets"][self.key]["names"]))
        self.assertEqual(projected["map_targets"][self.key]["names"],
                         self.data["map_targets"][self.key]["names"], "正对照：原值必须原样保留")
        self.assertGreater(int(report.get("machine_readable_kept_total") or 0), 0,
                           "正对照为 0 ⇒ 尺子是死的，下面的负测都不算数")

    def test_cjk_value_is_rejected_by_name(self):
        with self.assertRaises(rps.ScopeError) as caught:
            self._trial({"en": "中文混进机读面"})
        self.assertEqual(caught.exception.code, "scope_exempt_value_rejected")

    def test_empty_and_whitespace_and_non_scalar_values_are_rejected(self):
        for value in ("", "   ", 42, ["一个列表"], None):
            with self.assertRaises(rps.ScopeError) as caught:
                self._trial({"en": value})
            self.assertEqual(caught.exception.code, "scope_exempt_value_rejected",
                             "%r 应被值检查码拦下，实测 %s" % (value, caught.exception.code))

    def test_names_schema_is_applied_not_just_the_value(self):
        """names 里出现冻结结构之外的键 ⇒ 同一个码（豁免不给 schema 开口子）。"""
        with self.assertRaises(rps.ScopeError) as caught:
            self._trial({"en": SENTINEL, "fr": "Une chaîne"})
        self.assertEqual(caught.exception.code, "scope_exempt_value_rejected")
        with self.assertRaises(rps.ScopeError) as caught:
            self._trial({"en": "中文在前 Best Western 在后"})
        self.assertEqual(caught.exception.code, "scope_exempt_value_rejected",
                         "拉丁名里夹汉字必须走同一条检查（no_cjk 与 names_schema.en_must_be_latin 同源）")


class OtherPathsStillStrippedTests(unittest.TestCase):
    """⑤同名字段放在其他路径必须被剥离：豁免不全局放行键名 en，也不放行 `*_en`。"""

    @classmethod
    def setUpClass(cls):
        cls.data = run_dataset()
        cls.key = pick_named_search_target(cls.data)

    def test_same_key_name_at_other_paths_is_stripped(self):
        sibling, elsewhere = SENTINEL + "-SIBLING", SENTINEL + "-ELSEWHERE"
        trial = copy.deepcopy(self.data)
        trial["map_targets"][self.key]["en"] = sibling        # map_targets.<目标>.en（不是 names.en）
        trial["local_apps"][0]["en"] = elsewhere              # 另一个顶层面的同名键
        projected, report = project(trial)
        blob = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(sibling, blob, "同名字段换个位置就被放行 ⇒ 豁免已经不精确")
        self.assertNotIn(elsewhere, blob, "别处的键名 en 被放行 ⇒ 等于全局放行键名 en")
        stripped = report.get("nested_en_stripped") or {}
        self.assertTrue(any(".en" in shape for shape in stripped),
                        "剥离登记里没有 .en 形状＝这两个注入没被这条尺子看见：%s" % list(stripped))
        self.assertEqual((projected["map_targets"][self.key].get("names") or {}).get("en"),
                         self.data["map_targets"][self.key]["names"]["en"],
                         "旁边的键被剥，精确路径上的值却该原样保留")

    def test_latin_name_survives_while_every_english_field_does_not(self):
        projected, report = project(self.data)
        stripped = report.get("nested_en_stripped") or {}
        for shape in ("$.local_apps[*].name_en", "$.local_apps[*].use_cases_en",
                      "$.section_media[*].caption_en"):
            self.assertIn(shape, stripped, "%s 不再被剥离＝候审英文面重新进来了" % shape)
        self.assertNotIn("names.en", json.dumps(list(stripped)),
                         "剥离清册里出现 names.en ⇒ 豁免没生效")


class MapContractConsequenceTests(unittest.TestCase):
    """③⑥地图合同：findings 恢复为 0 是豁免做到的，不是改基准改出来的。"""

    @classmethod
    def setUpClass(cls):
        cls.data = run_dataset()
        cls.country = str(cls.data.get("country") or "")
        cls.input_face = map_face(cls.data["map_targets"], cls.country)
        cls.projected, _report = project(cls.data)
        cls.reader_face = map_face(cls.projected["map_targets"], cls.country)
        cls.stripped, _rb = project(cls.data, without_exemption=True)
        cls.before_face = map_face(cls.stripped["map_targets"], cls.country)

    def test_reader_projection_reproduces_the_input_map_contract(self):
        self.assertEqual(self.reader_face["findings"], [],
                         "读者载荷上的地图 findings 不是 0：%s" % self.reader_face["findings"][:2])
        self.assertEqual(self.reader_face["expected_buttons"], self.input_face["expected_buttons"],
                         "期望按钮数与输入面不符：投影把地图行为改了")
        self.assertEqual([p["fingerprint"] for p in self.reader_face["fingerprints"]],
                         [p["fingerprint"] for p in self.input_face["fingerprints"]],
                         "alias 指纹与迁移前不一致：豁免改了身份等价判定")
        self.assertTrue(all(p["match"] for p in self.reader_face["fingerprints"]),
                        "现算指纹与登记值不符 ⇒ 有人动了基准或算法")

    def test_final_findings_are_zero_not_a_rewritten_baseline(self):
        self.assertEqual(self.input_face["codes"], [])
        self.assertEqual(self.reader_face["codes"], [])
        entries = [e for e in (mg.alias_contract(mg.load_gate()).get("entries") or [])
                   if not str(e.get("scope") or "") or str(e.get("scope") or "") == self.country]
        self.assertEqual(len(entries), 5, "加州 run 的别名登记应是 5 条，实测 %d" % len(entries))
        self.assertTrue(all(str(e.get("identical_fields_digest") or "") for e in entries),
                        "登记指纹缺失＝基准是空的，任何「一致」都是自证")

    def test_removing_the_exemption_reproduces_the_migration_defect(self):
        """牙齿：把豁免拔掉就应当看到业主裁②描述的那个缺陷，而不是继续报 0。"""
        self.assertEqual(self.before_face["codes"], ["GATE_DOM_ALIAS_CONFLICT"],
                         "拔掉豁免却不报别名冲突 ⇒ 上面那个 0 是别的门给的，不算证")
        self.assertEqual(len(self.before_face["findings"]), 5, self.before_face["findings"][:2])
        self.assertGreater(self.before_face["expected_buttons"], self.reader_face["expected_buttons"],
                           "剥离 names.en 后期望按钮应当变多（alias 不再等价）——现在没变，尺子死了")
        self.assertFalse(all(p["match"] for p in self.before_face["fingerprints"]),
                         "剥离后指纹仍等于登记值 ⇒ 指纹没把 names 当输入，第 6 条要求落空")

    def test_names_is_a_registered_compared_field(self):
        compared = [str(f) for f in (mg.alias_contract(mg.load_gate()).get("compared_fields") or [])]
        self.assertIn("names", compared, "names 不在指纹字段里 ⇒ 豁免根本不影响身份，第 6 条要保护的是空气")
        self.assertIn("map_query_name_source", compared)


class BrowserSentinelTests(unittest.TestCase):
    """③④真浏览器里量：机读面读得到、读者面看不见。"""

    @classmethod
    def setUpClass(cls):
        cls.data = run_dataset()
        cls.key = pick_named_search_target(cls.data)

    def test_sentinel_is_reachable_by_the_map_query_contract(self):
        rec = mls.select(self.key, {**self.data["map_targets"][self.key],
                                    "names": {"en": SENTINEL}}, "google",
                         sel=mls.load_selection()).as_record()
        self.assertEqual(rec.get("map_query_name_source"), "names.en",
                         "查询名不再来自 names.en ⇒ 这一面已经不是身份输入，豁免的理由就没了")
        self.assertIn(SENTINEL, str(rec.get("map_link_url") or ""),
                      "选择器读不到放进精确路径的值：%s" % str(rec.get("map_link_url"))[:160])

    def test_sentinel_reaches_href_but_not_visible_text(self):
        out, folder = render_sentinel_page(self.data, self.key)
        try:
            measured = browser_probe(out)
            self.assertFalse(measured["visible"],
                             "哨兵出现在读者可见文本里 ⇒ 「机读面保留」这句话侵占了读者面")
            self.assertTrue(measured["href"],
                            "哨兵既不在可见文本也不在任何 href ⇒ 机读面其实没被保留，只是没印出来")
            self.assertGreaterEqual(measured["payload"], 1,
                                    "读者载荷里读不到该值：投影把这面删了")
            self.assertEqual(measured["lang_btn"], 0, "语言切换按钮又回来了")
        finally:
            folder.cleanup()

    def test_strip_would_have_removed_the_value_from_the_shipped_payload(self):
        """同一份哨兵数据，拔掉豁免后连内嵌载荷都不含它 ⇒ DOM 断言测的是投影，不是运气。"""
        probe = copy.deepcopy(self.data["map_targets"][self.key])
        probe["names"]["en"] = SENTINEL
        payload_before = {**self.data, "map_targets": {**self.data["map_targets"], self.key: probe}}
        stripped, _report = project(payload_before, without_exemption=True)
        self.assertNotIn(SENTINEL, json.dumps(stripped["map_targets"][self.key], ensure_ascii=False))
        kept, report = project(payload_before)
        self.assertEqual((kept["map_targets"][self.key].get("names") or {}).get("en"), SENTINEL)
        self.assertEqual(report.get("machine_readable_exempt_shapes"), [SHAPE])

    def test_sibling_injection_never_reaches_the_page(self):
        marker = SENTINEL + "-SIBLING"
        trial = copy.deepcopy(self.data)
        trial["map_targets"][self.key]["en"] = marker
        out, folder = render_sentinel_page(trial, pick_named_search_target(trial))
        try:
            document = out.read_text(encoding="utf-8")
            self.assertNotIn(marker, document,
                             "同名字段没被剥离：豁免已经延伸到 map_targets.<目标>.en")
            self.assertIn(SENTINEL, document, "正对照：精确路径上的哨兵应当在文件里（机读面）")
        finally:
            folder.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
