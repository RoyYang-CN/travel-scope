# -*- coding: utf-8 -*-
"""v4.2.2 ZH-RELEASE-1 · 中文正式档的功能层牙齿测试（业主 2026-11-02 ZH-1／ZH-4＋P0-1）。

这一支检的是「换个标签就发布」这一整类，而不是某一条文案：

* 载荷面（P0-1）：未登记顶层键 ⇒ 阻断；任意深度的英文形状键 ⇒ 剔除并登记；
  **数字值**的英文形状键（统计/标识面）⇒ 阻断，不许静默削（菲律宾实测
  `source_counts.by_provider["en.wikivoyage.org"]=188` 被旧实现当成英文面删掉，
  出货字节里 provider 合计 386 而行数 574＝#113 那一类假统计）；
* DOM 面（ZH-1）：正式档必须**没有** #lang-btn 元素（CSS 隐藏不算删除）；
* 两份自证必须分开：meta 档位、载荷 reader_profile、载荷范围声明三者必须互相一致，
  任何一方各执一词都各自一个错误码——「DOM 无英文入口」和「载荷无英文数据」是两条判据；
* 交付目录（ZH-4）：候审档（合同 shipping=false）出现在交付目录即阻断，名单从注册表读，
  不写在门的代码里。

规则沿用 #113 那一支：每条负测都断言**它自己点名的码**出现（被别的门拦下＝不算证），
并配一条正对照证明门不是焊死的红灯。
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
ROOT = SCRIPTS.parent
RUNS = ROOT.parent / "candidate_runs"

from playwright.sync_api import sync_playwright  # noqa: E402

import delivery_gate  # noqa: E402
import reader_payload_scope as rps  # noqa: E402  (唯一范围判据，本文件不另写一套)
import spa_renderer as sr  # noqa: E402
import visual_qa  # noqa: E402

CONTRACT = json.loads((ROOT / "references" / "renderer-contract.json").read_bytes().decode("utf-8"))
LANGUAGE = CONTRACT["reader_language"]
META_NAME = str(LANGUAGE["html_meta_name"])
FORMAL = str(LANGUAGE["formal_profile"])
AUDIT_CODE = str(((LANGUAGE["profiles"].get("en-audit") or {}).get("delivery_dir_rule") or {})
                 .get("code") or "")
DEST = "旧金山"

PAYLOAD_RE = re.compile(r'(<script id="dataset" type="application/json">)(.*?)(</script>)',
                        re.DOTALL)
META_RE = re.compile(r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(META_NAME))


def source_rows(count: int) -> list[dict]:
    """注册形状的合法来源台账：正式档的载荷必须有可读台账，否则先被台账门拦下＝不算证。"""
    return [{"destination": DEST, "name": "测试实体%02d" % i,
             "url": "https://www.example.com/hotel/%d" % (10000 + i),
             "source_provider": "www.example.com", "evidence_level": "direct_entity",
             "verification_status": "verified", "retrieved_at": "2026-10-20",
             "cross_source_review": "双重验证属实", "notes": "fixture"} for i in range(count)]


def fixture_dataset() -> dict:
    """一份只够撑起读者骨架的载荷：本文件断言的是语言档位与范围，不是内容完整度。"""
    return {
        "country": "美国", "artifact_slug": "fixture", "duration_days": 2,
        "routes": [["海岸线", "旧金山 → 洛杉矶", "2天", "Car", 1000, ""]],
        "route_budgets": {"海岸线": {"total_cny": 1000}},
        "destinations": [[DEST, "San Francisco"]],
        "itinerary": [["海岸线", "Day 1", 1, "住宿", "测试实体00", "37.700,-122.400"]],
        "hotels": [[DEST, "测试实体00", "", "hotel", "", "", "", "37.700,-122.400", "", ""]],
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [], "transport_nodes": [], "budget": [], "practical": [], "worth_it": [],
        "local_chains": [], "packing": [], "local_knowledge": [], "local_apps": [],
        "editorial_media": [], "section_media": [], "map_targets": {},
        "source_evidence": [], "source_evidence_meta": source_rows(4),
    }


def allowed_key() -> str:
    """从合同允许清单里取一个真实存在的顶层键——注入点必须是「会被放行的面」，
    否则测到的是未登记键门（scope_payload_key_unregistered），不是嵌套剥离。"""
    allow = LANGUAGE["profiles"][FORMAL]["payload_scope"]["top_level_allowlist"]
    for candidate in ("map_targets", "local_apps", "section_media"):
        if candidate in allow:
            return candidate
    raise AssertionError("允许清单里找不到任何一个可注入的嵌套面：%s" % allow[:8])


def deep_inject_key() -> str:
    """嵌套剥离用例的注入键：必须是允许清单里的键，且**不是**豁免路径的父段。

    豁免精确到 `$.map_targets.*.names.en`（业主 2026-11-03 裁②），拿 map_targets 测「一切
    *_en 都被剥」会测到那条被合同允许保留的机读面，等于把豁免读成全局放行。
    """
    allow = LANGUAGE["profiles"][FORMAL]["payload_scope"]["top_level_allowlist"]
    exempt_parents = {entry["segments"][0] for entry in
                      rps.machine_readable_exempt_paths(FORMAL)}
    for candidate in ("section_media", "editorial_media", "local_apps"):
        if candidate in allow and candidate not in exempt_parents:
            return candidate
    raise AssertionError("允许清单里找不到一个未被豁免的嵌套面：%s（豁免父段 %s）"
                         % (allow[:8], sorted(exempt_parents)))


def project(dataset: dict, profile: str = FORMAL):
    """走真渲染器的那一处唯一实现（apply_reader_profile 内部的投影），不在测试里复刻规则。"""
    return sr.apply_reader_profile(dataset, profile), sr.reader_scope_report()


def dropped_ledger(projected: dict, report: dict) -> set:
    """剔除必须留下账：两张登记面（合同 excluded_payload_keys 与 payload_scope 范围报告）都算，
    但「不在载荷里、也不在任何一张账上」＝静默丢弃，正是 #113 的罪名。"""
    return set(projected.get("reader_profile_dropped_keys") or []) | set(
        report.get("top_level_dropped_registered") or [])


def codes(failures) -> list[str]:
    return sorted({str(item).split("|", 1)[0] for item in failures})


def render(dataset: dict, *, profile: str = FORMAL, mutate=None):
    folder = tempfile.TemporaryDirectory()
    out = pathlib.Path(folder.name) / "fixture-travel-guide.html"
    sr.render_spa_document(out, copy.deepcopy(dataset), reader_profile=profile)
    if mutate:
        out.write_bytes(mutate(out.read_bytes()))
    return out, folder


def set_meta(profile: str) -> "function":
    def mutate(html: bytes) -> bytes:
        document = html.decode("utf-8")
        found = META_RE.findall(document)
        assert len(found) == 1, "meta 档位标记必须唯一命中，实测 %r" % found
        return META_RE.sub(lambda _m: '<meta name="%s" content="%s"' % (META_NAME, profile),
                           document, count=1).encode("utf-8")
    return mutate


def drop_meta(html: bytes) -> bytes:
    document, hits = META_RE.subn("", html.decode("utf-8"), count=1)
    assert hits == 1, "删 meta 的样本没命中：夹具坏了"
    return document.encode("utf-8")


def payload_of(html: bytes) -> dict:
    return json.loads(PAYLOAD_RE.search(html.decode("utf-8")).group(2))


def rewrite_payload(mutate_payload) -> "function":
    """改载荷必须按渲染器同一套转义写回去；否则页面先被 DS_PARSE 抓走＝不算证。"""
    def mutate(html: bytes) -> bytes:
        document = html.decode("utf-8")
        match = PAYLOAD_RE.search(document)
        assert match, "内嵌 dataset 载荷不在了：这个篡改样本无效"
        payload = json.loads(match.group(2))
        mutate_payload(payload)
        text = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
        text = text.replace(">", "\\u003e").replace("&", "\\u0026")
        return (document[:match.start(2)] + text + document[match.end(2):]).encode("utf-8")
    return mutate


_ENGINE: list[str] = []


def engine_error() -> str:
    source = (ROOT / "assets" / "spa-layout.js").read_text(encoding="utf-8")
    if not _ENGINE:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("about:blank")
            _ENGINE.append(page.evaluate(
                "(s) => { try { new Function(s); return ''; } catch (e) { return String(e).slice(0,160); } }",
                source))
            browser.close()
    return _ENGINE[0]


def check_in_browser(html_path: pathlib.Path, run_dataset: dict) -> dict:
    if engine_error():
        raise AssertionError("夹具前提不成立：assets/spa-layout.js 在 Chromium 里解析不过（%s）"
                             "⇒ 读者页没有 UI，本用例不去断言门的判定" % engine_error())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            with tempfile.TemporaryDirectory() as shots:
                return visual_qa.check_spa_page(
                    page, html_path, "zh-formal", {"width": 1440, "height": 900},
                    pathlib.Path(shots) / "shot.png", run_dataset=run_dataset)
        finally:
            browser.close()


def gate_codes(dataset: dict, *, profile: str = FORMAL, mutate=None) -> list[str]:
    """渲染（可篡改）后真浏览器跑发布用的那条检查路径，返回它点名的码集合。"""
    html_path, folder = render(dataset, profile=profile, mutate=mutate)
    try:
        return codes(check_in_browser(html_path, dataset)["failures"])
    finally:
        folder.cleanup()


class ScopeAllowlistTeeth(unittest.TestCase):
    """P0-1：顶层允许清单＋未登记键阻断。"""

    def test_registered_fixture_projects_cleanly(self):
        data, report = project(fixture_dataset())
        self.assertTrue(report["enforced"])
        self.assertEqual(report["top_level_unregistered"], [])
        self.assertEqual(rps._scan_en(data), [], "正对照载荷里就不该有英文形状键")
        self.assertEqual(data["reader_language_scope"], rps.SCOPE_VALUE)

    def test_unregistered_top_level_key_aborts_build(self):
        data = fixture_dataset()
        # 键名刻意不带任何英文形状：证明拦它的是「没登记」，不是「名字像英文」。
        data["brand_new_face"] = {"anything": "旧金山"}
        with self.assertRaises(rps.ScopeError) as caught:
            project(data)
        self.assertEqual(caught.exception.code, "scope_payload_key_unregistered")

    def test_excluded_english_faces_are_dropped_and_registered(self):
        data = fixture_dataset()
        data["prose_en"] = {"a1": "English prose"}
        data["en_text_replacements"] = {"旧金山": "San Francisco"}
        projected, report = project(data)
        self.assertNotIn("prose_en", projected)
        self.assertNotIn("en_text_replacements", projected)
        ledger = dropped_ledger(projected, report)
        self.assertIn("prose_en", ledger, "剔了却没登记＝静默丢弃")
        self.assertIn("en_text_replacements", ledger, "剔了却没登记＝静默丢弃")

    def test_source_counts_does_not_ship_anymore(self):
        """2026-11-02 实测缺陷：provider 统计是「标识键＋数字值」的面，剥它＝删记录。"""
        data = fixture_dataset()
        data["source_counts"] = {"by_provider": {"en.wikivoyage.org": 188},
                                 "by_status": {"verified": 574}}
        projected, report = project(data)
        self.assertNotIn("source_counts", projected)
        self.assertIn("source_counts", report["top_level_dropped_registered"])


class NestedEnglishStripTeeth(unittest.TestCase):
    """P0-1：任意深度的英文形状键剔除并登记；数字值命中改判为阻断。

    业主 2026-11-03 裁②之后加了一条硬约束：注入点必须落在**没被豁免**的父路径上。
    map_targets.*.names.en 现在是机读面（标识／URL 构造输入），它的牙齿在
    test_v422_machine_readable_exempt.py 里单独量；这一类测的是「其余 *_en 一处都不许留」。
    """

    def test_deep_injection_is_stripped_and_registered(self):
        key = deep_inject_key()
        data = fixture_dataset()
        data[key] = [{"names": {"zh": "洛杉矶", "en": "Los Angeles"},
                      "deep": [{"foo_en": "pending", "english_notes": "pending",
                                "bar": {"en": "x"}}]}]
        projected, report = project(data)
        shapes = report["nested_en_stripped"]
        self.assertTrue(any(shape.endswith(".names.en") for shape in shapes), shapes)
        self.assertTrue(any(shape.endswith(".foo_en") for shape in shapes), shapes)
        self.assertTrue(any(shape.endswith(".english_notes") for shape in shapes), shapes)
        self.assertTrue(any(shape.endswith(".en") for shape in shapes), shapes)
        self.assertEqual(rps._scan_en(projected, exempt=rps.machine_readable_exempt_paths(FORMAL)),
                         [], "剥离后仍残留英文形状键")
        self.assertEqual(report["nested_en_total"], sum(shapes.values()))
        self.assertEqual(report["machine_readable_kept_total"], 0,
                         "没走豁免路径却登记了保留＝豁免清单漏了形状校验")

    def test_numeric_en_shaped_value_blocks(self):
        """菲律宾那一处的形状：键名像英文面，值却是统计数字 ⇒ 静默剥离会丢 188 条。"""
        key = allowed_key()
        data = fixture_dataset()
        data[key] = {"薄荷岛|某个实体": {"by_provider": {"en.wikivoyage.org": 188}}}
        with self.assertRaises(rps.ScopeError) as caught:
            project(data)
        self.assertEqual(caught.exception.code, "scope_numeric_value_key_stripped")

    def test_real_runs_project_without_numeric_hits(self):
        """两地真实数据集复测：现行口径的剥离与保留计数（登记值来自量，不来自手打）。

        2026-11-03 裁②之后的口径换了对象：同一份 dataset，剥掉的少了、保留的就是
        $.map_targets.*.names.en 那一条精确路径。对账恒等式先于数字本身——
        「剥离 94 ＋ 保留 198 ＝ 旧的 292」必须逐字成立，否则说明豁免顺带动了别的面。
        """
        measured = {}
        for kind, folder, before in (("CA", "travel_scope_run_202701_usa_california_v422_001", 292),
                                     ("PH", "travel_scope_run_202702_philippines_visayas_v422_001", 253)):
            matches = sorted((RUNS / folder).rglob("dataset.json")) if (RUNS / folder).is_dir() else []
            self.assertTrue(matches, "真实 run dataset 不在盘上：%s ⇒ 不许静默跳过" % folder)
            dataset = json.loads(matches[0].read_bytes().decode("utf-8"))
            projected, report = project(dataset)
            kept = report["machine_readable_kept"]
            self.assertEqual(sorted(kept), ["$.map_targets.*.names.en"],
                             "%s 豁免保留出现了登记之外的形状：%s" % (kind, sorted(kept)))
            self.assertEqual(report["nested_en_total"] + sum(kept.values()), before,
                             "%s 剥掉的＋豁免留下的必须等于豁免前实测的 %d 处（现行顺序口径），"
                             "实测剥 %s＋留 %s" % (kind, before, report["nested_en_total"],
                                                   sum(kept.values())))
            measured[kind] = {"stripped": report["nested_en_total"],
                              "kept": kept["$.map_targets.*.names.en"]}
            self.assertNotIn("source_counts", projected)
            self.assertEqual(report["top_level_unregistered"], [])
        # 2026-11-03 实测（豁免后现行口径）：加州剥 94 留 198，第二地剥 58 留 195。
        self.assertEqual(measured, {"CA": {"stripped": 94, "kept": 198},
                                    "PH": {"stripped": 58, "kept": 195}},
                         "剥离/保留计数与合同登记不一致（合同 payload_scope.authority "
                         "与 machine_readable_exempt_paths）")


class ScopeSelfProof(unittest.TestCase):
    """闭集里每个码都必须被自己打到，缺一个就说明那条判据是装饰。"""

    def test_every_documented_code_is_reachable(self):
        seen = set()
        data = fixture_dataset()
        data["brand_new_face"] = {}
        seen.add(self._expect(data, "scope_payload_key_unregistered"))
        data = fixture_dataset()
        data[allowed_key()] = {"A|b": {"by": {"en.x": 1}}}
        seen.add(self._expect(data, "scope_numeric_value_key_stripped"))
        original_strip = rps._strip_en
        rps._strip_en = lambda node, trail, patterns, hits, examples, *rest: node
        try:
            seen.add(self._expect(self._with_nested_en(), "scope_en_key_left_in_payload"))
        finally:
            rps._strip_en = original_strip
        # 豁免位上的坏值必须被豁免自己的码拦下（业主 2026-11-03 裁②：豁免不等于免检）
        seen.add(self._expect(self._with_exempt_value("Los Ángeles 旧金山"),
                              "scope_exempt_value_rejected"))
        seen.add(self._expect(self._with_exempt_value(""), "scope_exempt_value_rejected"))
        for bad_entry in ([{"path_segments": []}],
                          [{"path_segments": ["map_targets", "*", "names", "en"],
                            "value_checks": ["made_up_check"]}]):
            with self.assertRaises(rps.ScopeError) as caught:
                rps._compile_exemptions(bad_entry)
            self.assertEqual(caught.exception.code, "scope_exempt_path_shape_unregistered")
            seen.add(caught.exception.code)
        data = fixture_dataset()
        data["reader_profile"] = "no-such-profile"
        with self.assertRaises(rps.ScopeError) as caught:
            rps.profile_scope("no-such-profile")
        self.assertEqual(caught.exception.code, "scope_profile_mismatch")
        seen.add(caught.exception.code)
        with tempfile.TemporaryDirectory() as folder:
            empty = pathlib.Path(folder) / "contract.json"
            empty.write_bytes(b'{"version": "x"}')
            with self.assertRaises(rps.ScopeError) as caught:
                rps.scope_contract(empty)
            self.assertEqual(caught.exception.code, "scope_contract_missing")
            seen.add(caught.exception.code)
        original_scope = rps.profile_scope
        rps.profile_scope = lambda profile: {}
        try:
            seen.add(self._expect(fixture_dataset(), "scope_allowlist_missing"))
        finally:
            rps.profile_scope = original_scope
        self.assertEqual(seen, set(rps.ERROR_CODES),
                         "登记的错误码没有一条打不到：闭集与牙齿必须一一对应")

    def _with_nested_en(self) -> dict:
        """注入点必须落在**没有被豁免**的父路径上：map_targets.*.names.en 是业主 2026-11-03
        裁②登记的机读面（标识／URL 构造输入），拿它测残留等于在测一条合同允许出货的面。"""
        data = fixture_dataset()
        data["section_media"] = [{"caption_en": "pending english caption"}]
        return data

    def _with_exempt_value(self, value) -> dict:
        """豁免路径上的坏值：段序列命中登记豁免，但值过不了复检 ⇒ 必须由豁免自己的码拦下。"""
        data = fixture_dataset()
        data[allowed_key()] = {"洛杉矶|某个实体": {"names": {"cn": "洛杉矶", "en": value}}}
        return data

    def _expect(self, data: dict, code: str) -> str:
        with self.assertRaises(rps.ScopeError) as caught:
            project(data)
        self.assertEqual(caught.exception.code, code, "%s 应该由 %s 拦下" % (caught.exception, code))
        return code

    def test_leftover_guard_is_not_decorative(self):
        """把剥离器换成恒等函数 ⇒ 残留自检必须自己响，否则「剥干净」只是渲染器自述。"""
        original = rps._strip_en
        rps._strip_en = lambda node, trail, patterns, hits, examples, *rest: node
        try:
            self._expect(self._with_nested_en(), "scope_en_key_left_in_payload")
        finally:
            rps._strip_en = original

    def test_reverse_check_flags_relabelled_payload(self):
        """门禁侧反向核对：声明 zh_only 却带英文／带未登记键，各自一条问题。"""
        payload = {"reader_profile": FORMAL, "names": {"en": "x"}, "surprise": {}}
        check = rps.assert_scope_declared(payload, FORMAL)
        self.assertFalse(check["ok"])
        self.assertTrue(any(item.startswith("scope_not_declared") for item in check["problems"]))
        self.assertTrue(any(item.startswith("nested_en_present") for item in check["problems"]))
        self.assertTrue(any(item.startswith("top_level_unregistered") for item in check["problems"]))


class FormalArtifactDomTeeth(unittest.TestCase):
    """ZH-1／ZH-4：DOM 无英文入口 与 载荷无英文数据 是两条独立判据，各自一个码。"""

    def test_positive_control_formal_artifact_is_clean(self):
        data = fixture_dataset()
        found = gate_codes(data)
        for code in ("SPA_ZH_FORMAL_TOGGLE_PRESENT", "SPA_ZH_FORMAL_EXCLUDED_PAYLOAD_KEY_PRESENT",
                     "SPA_ZH_FORMAL_PAYLOAD_SCOPE_WRONG", "SPA_READER_PROFILE_UNDECLARED",
                     "SPA_READER_PROFILE_MISMATCH", "SPA_READER_PROFILE_UNREGISTERED"):
            self.assertNotIn(code, found, "正对照不该触发 %s（触发了＝门是焊死的红灯）" % code)

    def test_relabelled_bilingual_artifact_still_ships_a_toggle(self):
        """业主明令禁止的形状：双语 HTML 换个 meta 标签就当我们发布了中文正式件。"""
        data = fixture_dataset()
        data["prose_en"] = {"a1": "English prose"}
        html_path, folder = render(data, profile="en-audit")
        try:
            tampered = set_meta(FORMAL)(html_path.read_bytes())
            tampered = rewrite_payload(lambda p: p.__setitem__("reader_profile", FORMAL))(tampered)
            mutated = folder.name
            out = pathlib.Path(mutated) / "relabeled.html"
            out.write_bytes(tampered)
            result = check_in_browser(out, data)
        finally:
            folder.cleanup()
        found = codes(result["failures"])
        self.assertIn("SPA_ZH_FORMAL_TOGGLE_PRESENT", found,
                      "DOM 里 #lang-btn 还在，正式档必须点名它")
        self.assertEqual(result["zh_formal"]["lang_btn_count"], 1)

    def test_meta_and_payload_must_agree(self):
        html_path, folder = render(fixture_dataset())
        try:
            tampered = set_meta("en-audit")(html_path.read_bytes())
            out = pathlib.Path(folder.name) / "mismatch.html"
            out.write_bytes(tampered)
            found = codes(check_in_browser(out, fixture_dataset())["failures"])
        finally:
            folder.cleanup()
        self.assertIn("SPA_READER_PROFILE_MISMATCH", found)

    def test_missing_meta_declaration_blocks(self):
        found = gate_codes(fixture_dataset(), mutate=drop_meta)
        self.assertIn("SPA_READER_PROFILE_UNDECLARED", found)

    def test_unregistered_profile_blocks(self):
        """声明一个没登记的档位：meta 与载荷一致也不能放行（未登记＝没有合同）。"""
        html_path, folder = render(fixture_dataset())
        try:
            tampered = set_meta("fr-formal")(html_path.read_bytes())
            tampered = rewrite_payload(lambda p: p.__setitem__("reader_profile", "fr-formal"))(tampered)
            out = pathlib.Path(folder.name) / "unregistered.html"
            out.write_bytes(tampered)
            found = codes(check_in_browser(out, fixture_dataset())["failures"])
        finally:
            folder.cleanup()
        self.assertIn("SPA_READER_PROFILE_UNREGISTERED", found)

    def test_pending_english_key_injected_into_formal_payload(self):
        """载荷面单独证：候审英文显示面键被塞进正式件 ⇒ 点名 excluded 那条码。"""
        found = gate_codes(fixture_dataset(), mutate=rewrite_payload(
            lambda p: p.__setitem__("prose_en", {"a1": "English prose"})))
        self.assertIn("SPA_ZH_FORMAL_EXCLUDED_PAYLOAD_KEY_PRESENT", found)

    def test_nested_english_smuggled_into_formal_payload(self):
        """换一个没在排除清单里的嵌套字段名也一样点名（scope 反向核对）。"""
        def smuggle(payload: dict) -> None:
            payload.setdefault("map_targets", {})["旧金山|某实体"] = {
                "names": {"zh": "旧金山", "en": "San Francisco"}, "foo_en": "pending"}

        found = gate_codes(fixture_dataset(), mutate=rewrite_payload(smuggle))
        self.assertIn("SPA_ZH_FORMAL_PAYLOAD_SCOPE_WRONG", found)

    def test_formal_artifact_does_not_run_english_walk(self):
        """正式档「没跑英文遍历」必须是记录在案的结论，不是缺字段。"""
        html_path, folder = render(fixture_dataset())
        try:
            result = check_in_browser(html_path, fixture_dataset())
        finally:
            folder.cleanup()
        walk = result.get("english_mode_walk")
        self.assertIsInstance(walk, dict, "英文态遍历记录整块都不在：缺证据不等于没问题")
        self.assertIs(walk.get("ran"), False)
        self.assertTrue(walk.get("reason"))


class DeliveryDirectoryAudit(unittest.TestCase):
    """ZH-4：候审档产物写进任何正式 outputs/release 目录即阻断，名单读注册表。"""

    def _gate_errors(self, directory: pathlib.Path) -> list[str]:
        errors: list[str] = []
        warnings: list[str] = []
        delivery_gate._check_spa_english_mode(directory, errors, warnings)
        return errors

    def test_audit_artifact_in_delivery_directory_blocks(self):
        self.assertEqual(AUDIT_CODE, "SPA_AUDIT_PROFILE_IN_FORMAL_DIR",
                         "合同没登记这条码＝门读的名单与实现脱节")
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "fixture-travel-guide.html"
            sr.render_spa_document(out, copy.deepcopy(fixture_dataset()), reader_profile="en-audit")
            errors = self._gate_errors(pathlib.Path(folder))
            hits = [item for item in errors if item.startswith(AUDIT_CODE)]
            self.assertTrue(hits, "en-audit 产物坐在交付目录里却没被点名：%s" % errors[:3])

    def test_formal_artifact_does_not_trigger_the_audit_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "fixture-travel-guide.html"
            sr.render_spa_document(out, copy.deepcopy(fixture_dataset()), reader_profile=FORMAL)
            errors = self._gate_errors(pathlib.Path(folder))
            self.assertFalse([item for item in errors if item.startswith(AUDIT_CODE)],
                             "正式档自己不该触发候审档规则：%s" % [e[:80] for e in errors[:3]])

    def test_unregistered_profile_is_not_the_audit_rule(self):
        """名单只认注册表：没登记的档位不能靠这条码蒙过去（该走 UNREGISTERED 那条）。"""
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "fixture-travel-guide.html"
            sr.render_spa_document(out, copy.deepcopy(fixture_dataset()), reader_profile=FORMAL)
            out.write_bytes(set_meta("fr-formal")(out.read_bytes()))
            errors = self._gate_errors(pathlib.Path(folder))
            self.assertFalse([item for item in errors if item.startswith(AUDIT_CODE)])
            self.assertTrue([item for item in errors
                             if item.startswith("SPA_READER_PROFILE_UNREGISTERED")], errors[:3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
