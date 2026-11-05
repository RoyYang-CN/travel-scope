# -*- coding: utf-8 -*-
"""v4.2.2 R3B：正式无图状态（designed_no_photo_state）的 dataset／门禁／DOM 执行型牙齿。

业主 2026-11-03 第三轮裁示的原话是这些用例的出处：

  「采用现有 designed_no_photo_state，不再发明第二套无图机制。」
  「无图行必须有登记过的 no_photo_reason_code 和存在的证据文件；image 必须为空；不得存在作者、
   许可、摘要、源 URL 等图片字段；asset manifest 不得有对应资产行；DOM 不得出现 <img>、asset://
   或 JS fallback；DOM 必须有 data-media-state="designed_no_photo_state"；页面明确显示
   「暂无已核验图片」，不能表现成图片加载失败；不得用生成的写实图片、SVG 假封面或其他地点图片填充。」
  「必须锁住：20 = 18 photographic + 2 designed_no_photo，不得通过删除分母或合并槽位降低比例；
   再增加一条无图状态就会超过 deep 上限。」
  「修正后酒店/咖啡两行不应再产生 media_gaps。」

形状约定（与本项目其它门一致）：

* 每条负测都要求「被点名的码」和「被点名的槽位」同时出现——被别的码拦下＝不算证；
* DOM 那几条走 render_spa_document ＋ 真 Chromium，取值面与发布 QA 共用同一段 JS
  （visual_qa.NO_PHOTO_STATE_DOM_JS）：QA 说 PASS 与测试说 PASS 必须是同一件事；
* 现场复算那组直接读加州正式 run 与 .temp 隔离区，登记值（20=18+2、行计数与交付字节见
  media-policy.ratio_lock.measured_ca_2026_11_03.r3c_live_row_counts_2026_11_03、退役 15 件）
  与实物不一致就红——不是拿夹具证明"规则可行"然后放真实交付物漂移。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import local_media_gate as lmg                      # noqa: E402
import test_v421_english_source as base             # noqa: E402
import visual_qa                                    # noqa: E402
from playwright.sync_api import sync_playwright      # noqa: E402
from spa_renderer import render_spa_document         # noqa: E402
from test_v422_media_lineage import write_jpeg       # noqa: E402
from test_v422_single_file_delivery import code_lines  # noqa: E402

ROOT = SCRIPTS.parent
CA_RUN = ROOT.parent / "release_runs" / "travel_scope_run_202701_usa_california_v422_zh_001"
QUARANTINE = Path(r"D:/文档/项目开发/Travel-Scope/.temp/v422_honest_map/ZH_RELEASE_3/"
                  "superseded/quarantine/travel_scope_run_202701_usa_california_v422_zh_001")
DEST = "旧金山"
EVIDENCE_REL = "evidence/media-lineage-remediation.json"
POLICY = lmg.no_photo_policy()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class NoPhotoRun:
    """一棵最小 run：咖啡馆槽位有合规图，酒店槽位按登记写法声明正式无图。"""

    def __init__(self, tmp: Path):
        self.root = tmp
        (tmp / "evidence").mkdir(parents=True, exist_ok=True)
        (tmp / "assets" / "section").mkdir(parents=True, exist_ok=True)
        (tmp / "media_prepared" / "originals").mkdir(parents=True, exist_ok=True)
        (tmp / "evidence" / "media-review.txt").write_text(
            "分区图接触表复核（夹具）2026-11-03\n"
            "- 旧金山咖啡馆门面：确认为咖啡馆外摆，不是酒店立面，也不是别处的替身。\n",
            encoding="utf-8")
        blob = write_jpeg(tmp / "media_prepared" / "originals" / "sf_cafes.jpg", 720, 480, seed=13)
        (tmp / "assets" / "section" / "sf_cafes.jpg").write_bytes(blob)
        self.cafes_asset = {"local_file": "assets/section/sf_cafes.jpg", "category": "SECTION_MEDIA",
                            "destination": DEST, "modules": ["cafes"], "module_category": "food",
                            "primary_module": "cafes", "display_role": "destination_atmosphere",
                            "selection_level": "same_destination_same_category_reference",
                            "source_provider": "local_verified",
                            "source_page": "https://images.example.org/sf-cafe-front.jpg",
                            "license": "CC BY 4.0", "author": "Example Photographer",
                            "retrieved_at": "2026-10-20", "verification_status": "verified",
                            "verification_evidence": "evidence/media-review.txt",
                            "sha256": hashlib.sha256(blob).hexdigest()}
        self.assets = [self.cafes_asset]
        self._write("asset-manifest.json", {"schema_version": 1, "assets": self.assets})
        self._write("dataset.json", {"country": "美国"})
        self.retired = ["assets/section/sf_hotels.jpg"]
        self._write(EVIDENCE_REL, {"schema": "travel-scope.media-lineage-remediation/1",
                                   "removed_from_run": list(self.retired)})

    def _write(self, rel: str, obj) -> None:
        (self.root / rel).write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))

    def no_photo_row(self, **overrides) -> dict:
        row = {"destination": DEST, "modules": ["hotels"], "primary_module": "hotels",
               "module_category": "accommodation", "selection_level": lmg.NO_PHOTO_STATE_VALUE,
               "asset_role": lmg.NO_PHOTO_STATE_VALUE, "image": POLICY["image_value"],
               "no_photo_reason_code": POLICY["reason_code_closed_set"][0],
               "no_photo_evidence": EVIDENCE_REL}
        assert list(row) == list(POLICY["allowed_fields"]), "夹具写法必须先等于登记写法"
        row.update(overrides)
        return row

    def cafes_row(self) -> dict:
        return {"destination": DEST, "modules": ["cafes"], "primary_module": "cafes",
                "module_category": "food", "asset_role": "destination_atmosphere",
                "selection_level": "same_destination_same_category_reference",
                "image": "assets/section/sf_cafes.jpg", "focal_point": "50% 50%"}

    def section_media(self) -> list:
        return [self.cafes_row(), self.no_photo_row()]

    def coverage(self) -> list:
        return [("hotels", [[DEST, "Hotel A", "Hotel A EN", "商务酒店"]]),
                ("cafes", [[DEST, "Cafe A", "Cafe A EN", "咖啡馆"]])]

    def findings(self, section_media=None, require_complete: bool = True,
                 manifest_rows: list | None = None) -> list[str]:
        if manifest_rows is not None:
            self._write("asset-manifest.json", {"schema_version": 1, "assets": manifest_rows})
        out: list[str] = []
        lmg.validate_section_media(self.root, section_media if section_media is not None
                                   else self.section_media(), self.coverage(),
                                   require_complete=require_complete, collect=out)
        return out


class GateJudgementTests(unittest.TestCase):
    """业主数据面四条：字段闭集／image 为空／理由码与证据文件／清单不留资产行。"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.fx = NoPhotoRun(Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.fx.retired = ["assets/section/sf_hotels.jpg"]
        self.fx._write(EVIDENCE_REL, {"schema": "x", "removed_from_run": list(self.fx.retired)})
        self.fx._write("asset-manifest.json", {"schema_version": 1, "assets": [self.fx.cafes_asset]})

    def test_compliant_row_passes_and_still_counts_in_the_denominator(self):
        # 这条是其余负测的正对照：夹具不成立时，任何"被拦下"都不算证据。
        self.assertEqual(self.fx.findings(), [], "合规夹具被报问题＝尺子或夹具坏了")

    def test_extra_source_field_is_blocked(self):
        row = self.fx.no_photo_row()
        row["author"] = "Bernard Gagnon"
        found = self.fx.findings([self.fx.cafes_row(), row])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_FIELDS_UNREGISTERED") and "author" in f
                            for f in found), found)

    def test_missing_evidence_field_is_blocked(self):
        row = self.fx.no_photo_row()
        row.pop("no_photo_evidence")
        found = self.fx.findings([self.fx.cafes_row(), row])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_FIELDS_UNREGISTERED")
                            and "no_photo_evidence" in f for f in found), found)

    def test_non_empty_image_is_blocked(self):
        found = self.fx.findings([self.fx.cafes_row(), self.fx.no_photo_row(image="assets/section/sf_hotels.jpg")])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_IMAGE_NOT_EMPTY") and "hotels" in f
                            for f in found), found)

    def test_invented_reason_code_is_blocked(self):
        found = self.fx.findings([self.fx.cafes_row(),
                                  self.fx.no_photo_row(no_photo_reason_code="WE_FEEL_IT_IS_FINE")])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_REASON_CODE_UNREGISTERED")
                            and "WE_FEEL_IT_IS_FINE" in f for f in found), found)

    def test_absent_evidence_file_is_blocked(self):
        (self.fx.root / EVIDENCE_REL).unlink()
        found = self.fx.findings([self.fx.cafes_row(), self.fx.no_photo_row()])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_EVIDENCE_MISSING")
                            and EVIDENCE_REL in f for f in found), found)

    def test_evidence_as_absolute_or_remote_path_is_blocked(self):
        for value in ("https://example.org/evidence.json", "../outside.json"):
            found = self.fx.findings([self.fx.cafes_row(), self.fx.no_photo_row(no_photo_evidence=value)])
            self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_EVIDENCE_MISSING") for f in found),
                            "%s 不该被当成 run 内证据：%s" % (value, found))

    def test_old_image_path_in_any_field_is_blocked(self):
        # 把旧图路径塞进「证据文件」这一格：文件真实存在，所以只有点名图片字节的那条码才算数。
        old = self.fx.root / "assets" / "section" / "sf_hotels.jpg"
        write_jpeg(old, 700, 455, seed=5)
        found = self.fx.findings([self.fx.cafes_row(),
                                  self.fx.no_photo_row(no_photo_evidence="assets/section/sf_hotels.jpg")])
        codes = [f.split("|")[0] for f in found]
        self.assertIn("SECTION_NO_PHOTO_IMAGE_SOURCE_PRESENT", codes, found)
        old.unlink()

    def test_manifest_row_left_for_the_no_photo_slot_is_blocked(self):
        stale = dict(self.fx.cafes_asset)
        stale.update({"local_file": "assets/section/sf_hotels.jpg", "modules": ["hotels"],
                      "module_category": "accommodation", "primary_module": "hotels",
                      "destination": DEST, "category": "SECTION_MEDIA"})
        found = self.fx.findings([self.fx.cafes_row(), self.fx.no_photo_row()],
                                 manifest_rows=[self.fx.cafes_asset, stale])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_ASSET_ROW_PRESENT")
                            and "assets/section/sf_hotels.jpg" in f for f in found), found)

    def test_role_and_level_must_agree(self):
        found = self.fx.findings([self.fx.cafes_row(),
                                  self.fx.no_photo_row(asset_role="destination_atmosphere")])
        self.assertTrue(any(f.startswith("SECTION_NO_PHOTO_ROLE_LEVEL_DISAGREE") for f in found), found)

    def test_deleting_the_slot_does_not_shrink_the_denominator(self):
        # 业主：不得通过删除分母或合并槽位降低比例。删掉整行＝缺槽位，不是「占比变干净」。
        found = self.fx.findings([self.fx.cafes_row()])
        self.assertTrue(any("Missing required section-media slots" in f and "hotels:%s" % DEST in f
                            for f in found), found)

    def test_duplicate_slot_merge_is_blocked(self):
        found = self.fx.findings([self.fx.cafes_row(), self.fx.no_photo_row(),
                                  self.fx.no_photo_row(modules=["hotels", "cafes"])])
        self.assertTrue(any("Duplicate section-media slot" in f for f in found), found)

    def test_vocabulary_is_read_from_the_registry_not_a_hardcoded_copy(self):
        # 若词表还在代码里抄一份，改登记面不会有下面两种反应。
        with mock.patch.dict(lmg.MEDIA_POLICY, {"display_roles": ["only_this_role"]}):
            found = self.fx.findings([self.fx.cafes_row(), self.fx.no_photo_row()])
        self.assertTrue(any("Invalid section-media role/selection level" in f for f in found),
                        "改登记词表后门禁无反应＝代码里还留着第二套词表")
        with mock.patch.dict(lmg.MEDIA_POLICY, {"display_roles": sorted(
                set(POLICY["allowed_fields"]) | {"made_up_role"}),
                "selection_levels": [lmg.NO_PHOTO_STATE_VALUE, "made_up_level"]}):
            quiet = [f for f in self.fx.findings([self.fx.no_photo_row(asset_role="made_up_role",
                                                                      selection_level="made_up_level")])
                     if f.startswith("SECTION_NO_PHOTO_FIELDS_UNREGISTERED")]
        self.assertEqual(quiet, [], "登记面新加的合法角色被字段闭集之外误伤：%s" % quiet)

    def test_policy_block_absent_or_incomplete_raises(self):
        with mock.patch.object(lmg, "MEDIA_POLICY", {}):
            with self.assertRaises(ValueError) as ctx:
                lmg.no_photo_policy()
            self.assertIn("SECTION_NO_PHOTO_POLICY_UNREGISTERED", str(ctx.exception))
        thin = json.loads(json.dumps(lmg.MEDIA_POLICY))
        thin["designed_no_photo_state"].pop("dom")
        with mock.patch.object(lmg, "MEDIA_POLICY", thin):
            with self.assertRaises(ValueError) as ctx:
                lmg.no_photo_policy()
        self.assertIn("SECTION_NO_PHOTO_POLICY_INCOMPLETE", str(ctx.exception))

    def test_validate_section_media_fails_loudly_without_the_registry(self):
        thin = json.loads(json.dumps(lmg.MEDIA_POLICY))
        thin.pop("designed_no_photo_state")
        with mock.patch.object(lmg, "MEDIA_POLICY", thin):
            with self.assertRaises(ValueError) as ctx:
                self.fx.findings()
        self.assertIn("SECTION_NO_PHOTO_POLICY_UNREGISTERED", str(ctx.exception))


class MediaGapContradictionTests(unittest.TestCase):
    """业主：修正后酒店/咖啡两行不应再产生 media_gaps。缺口是异常扣留，不是数据层决定。"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.fx = NoPhotoRun(Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_retired_asset_cannot_reappear_as_a_media_gap(self):
        gaps = [{"kind": "MEDIA_UNREGISTERED_IN_MANIFEST", "asset": "assets/section/sf_hotels.jpg",
                 "detail": "夹具"}]
        errors, metrics = lmg.verify_media_gaps(gaps, {"assets": []}, self.fx.root, "",
                                                section_media=self.fx.section_media())
        self.assertEqual([e.split("|")[0] for e in errors], ["SECTION_NO_PHOTO_MEDIA_GAP_CONTRADICTION"],
                         "必须是它自己点名的那条门：%s" % errors)
        self.assertIn("sf_hotels.jpg", errors[0])
        self.assertEqual(metrics["no_photo_retired_assets_known"], 1)

    def test_a_genuine_gap_still_gets_its_own_verdict(self):
        # 正对照：加了退役判定不能把真缺口的复算也一起废掉。
        errors, _ = lmg.verify_media_gaps([{"kind": "MEDIA_UNREGISTERED_IN_MANIFEST",
                                            "asset": "assets/section/other.jpg", "detail": "夹具"}],
                                          {"assets": []}, self.fx.root, "",
                                          section_media=self.fx.section_media())
        self.assertEqual(errors, [], errors)
        errors2, _ = lmg.verify_media_gaps([{"kind": "SOMETHING_ELSE",
                                             "asset": "assets/section/other.jpg"}],
                                           {"assets": []}, self.fx.root, "",
                                           section_media=self.fx.section_media())
        self.assertTrue(any(e.startswith("MEDIA_GAP_UNJUSTIFIED") for e in errors2), errors2)


class RegistryClosureTests(unittest.TestCase):
    """登记面 ⇄ 代码双向核对；比例规则只有一个持有人；渲染层文案与登记逐字一致。"""

    def test_emitted_and_registered_codes_are_the_same_set(self):
        code = code_lines(ROOT / "scripts" / "local_media_gate.py")
        emitted = set(re.findall(r"\bSECTION_NO_PHOTO_[A-Z_]+\b", code))
        registered = set(POLICY["blocking_codes"]) | set(POLICY["policy_readiness_codes"])
        self.assertEqual(registered - emitted, set(), "死登记：登记了却没有任何代码路径 emit")
        self.assertEqual(emitted - registered, set(), "词表被绕过：代码发了登记面没有的码")

    def test_ratio_rule_has_exactly_one_holder(self):
        holders = sorted(p.name for p in SCRIPTS.glob("*.py")
                         if "max_designed_no_photo_ratio" in code_lines(p) and not p.name.startswith("test_"))
        self.assertEqual(holders, ["formal_data_gate.py"],
                         "占比上限又被人抄了第二份实现：%s" % holders)

    def test_registered_ca_measurement_is_at_the_line_not_under_it(self):
        lock = POLICY["ratio_lock"]["measured_ca_2026_11_03"]
        depth_rule = json.loads((ROOT / "references" / "run-quality-policy.json")
                                .read_text(encoding="utf-8"))["research_depth"]["deep"]
        self.assertEqual(lock["depth"], "deep")
        self.assertEqual(lock["max_designed_no_photo_ratio"], float(depth_rule["max_designed_no_photo_ratio"]))
        self.assertEqual(lock["section_slots"], lock["photographic"] + lock["designed_no_photo"])
        self.assertAlmostEqual(lock["designed_no_photo"] / lock["section_slots"],
                               lock["max_designed_no_photo_ratio"], places=6)
        self.assertEqual(lock["headroom"], 0)
        # 第三条无图行必然越过上限：比较符是 ratio > maximum（同一条既有实现），0.15 严格大于 0.10。
        self.assertGreater(3 / lock["section_slots"], lock["max_designed_no_photo_ratio"])

    def test_no_photo_state_is_not_a_generated_image_role(self):
        providers = lmg.MEDIA_POLICY["providers"]["generated"]["allowed_roles"]
        self.assertNotIn(lmg.NO_PHOTO_STATE_VALUE, providers,
                         "「无图状态」挂在 generated 角色下＝允许生成图顶着无图的名进页面")
        self.assertIn(lmg.NO_PHOTO_STATE_VALUE, lmg.MEDIA_POLICY["selection_levels"])
        self.assertIn(lmg.NO_PHOTO_STATE_VALUE, lmg.MEDIA_POLICY["display_roles"])

    def test_renderer_copy_equals_the_registry(self):
        js = (ROOT / "assets" / "spa-layout.js").read_text(encoding="utf-8")
        dom = POLICY["dom"]
        for label in (dom["visible_label"]["cn"], dom["visible_label"]["en"]):
            self.assertIn(label, js, "渲染层文案与登记面漂移：%s" % label)
        self.assertIn("mediaState:'%s'" % dom["attribute_value"], js.replace(" ", "").replace("'", "'"),
                      "DOM 属性由 dataset.mediaState 生成，值必须就是登记值")
        self.assertIn("no-photo", js)
        css = (ROOT / "assets" / "spa-layout.css").read_text(encoding="utf-8")
        self.assertIn(".branch-visual.no-photo", css)
        self.assertEqual(js.count(dom["visible_label"]["cn"]), 1,
                         "同一条文案在渲染层出现多次＝第二套写法，改一处漏一处")

    def test_state_decision_lives_in_one_place_per_side(self):
        js = (ROOT / "assets" / "spa-layout.js").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"function sectionMediaState\(", js)), 1)
        code = code_lines(ROOT / "scripts" / "local_media_gate.py")
        self.assertEqual(code.count("def is_no_photo_row("), 1)
        self.assertNotIn("allowed_roles = {'verified_exact_place'", code,
                         "词表的硬编码副本回来了：角色/档位只能读登记面")


class DomExecutionTests(unittest.TestCase):
    """DOM 四条走真浏览器：属性在／文案在／没有图／数量与 dataset 一致。"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.fx = NoPhotoRun(Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def dataset(self) -> dict:
        return base._dataset(hotels=[[DEST, "湾区商务酒店", "Bay Business Hotel", "商务酒店",
                                      "900-1400", "4.4", "900", "37.7,-122.4", "", "",
                                      "靠近联合广场，步行可达地铁"]],
                             section_media=[self.fx.no_photo_row()])

    def probe(self, tamper_js: str = "") -> dict:
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / "probe-no-photo.html"
            render_spa_document(html, self.dataset(), reader_profile="zh-formal")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(html.as_uri(), wait_until="load")
                page.wait_for_timeout(220)
                page.evaluate("() => document.querySelectorAll('#main .panel')"
                              ".forEach(p => p.hidden = false)")
                page.wait_for_timeout(120)
                if tamper_js:
                    page.evaluate(tamper_js)
                marks = page.evaluate(visual_qa.NO_PHOTO_STATE_DOM_JS)
                failures: list[str] = []
                result: dict = {}
                visual_qa.check_rendered_image_registration(
                    page, self.dataset(), {"assets": []}, failures, result, manifest_required=True)
                html_text = html.read_text(encoding="utf-8")
                browser.close()
        codes = [f.split("|")[0] for f in failures]
        return {"marks": marks, "errors": errors, "codes": codes, "result": result,
                "html": html_text, "failures": failures}

    def test_dom_renders_the_registered_state_with_no_image(self):
        state = self.probe()
        self.assertEqual(state["errors"], [], "页面报错时任何断言都不成立")
        marks = [m for m in state["marks"] if m["state"] == POLICY["dom"]["attribute_value"]]
        self.assertEqual(len(marks), 1, marks)
        self.assertEqual(marks[0]["imgCount"], 0, "无图槽位里画出了 img")
        self.assertFalse(marks[0]["assetRef"], "无图槽位里还留着 asset://／内联字节")
        self.assertIn(POLICY["dom"]["visible_label"]["cn"], marks[0]["text"])
        self.assertNotIn("加载失败", marks[0]["text"])
        self.assertEqual([c for c in state["codes"] if c.startswith("IMG_RENDERED_NO_PHOTO")], [])
        metric = state["result"]["designed_no_photo_state"]
        self.assertEqual(metric["declared_slots"], [[DEST, "hotels"]])
        self.assertEqual(metric["dom_marked"], 1)
        self.assertEqual(metric["photographic_slots"], 0)
        # 交付字节面也必须干净：这一页不许内联那份退役字节的任何摘要
        self.assertNotIn("assets/section/sf_hotels.jpg", state["html"])

    def test_missing_attribute_is_caught(self):
        state = self.probe("() => document.querySelectorAll('[data-media-state]')"
                           ".forEach(e => e.removeAttribute('data-media-state'))")
        self.assertIn("IMG_RENDERED_NO_PHOTO_SLOT_UNMARKED", state["codes"], state["failures"])

    def test_image_inside_the_marked_slot_is_caught(self):
        state = self.probe("() => { const e = document.querySelector('[data-media-state]');"
                           " const img = document.createElement('img');"
                           " img.src = 'data:image/png;base64,aW1n';"
                           " img.dataset.assetDigest = 'fallback';"
                           " e.appendChild(img); }")
        self.assertIn("IMG_RENDERED_NO_PHOTO_HAS_IMAGE", state["codes"], state["failures"])

    def test_label_replaced_by_load_failure_copy_is_caught(self):
        state = self.probe("() => { const e = document.querySelector('[data-media-state] .no-photo-label');"
                           " e.textContent = '图片加载失败'; }")
        self.assertIn("IMG_RENDERED_NO_PHOTO_LABEL_MISSING", state["codes"], state["failures"])

    def test_extra_dom_state_without_data_support_is_caught(self):
        state = self.probe("() => { const span = document.createElement('span');"
                           " span.setAttribute('data-media-state', 'designed_no_photo_state');"
                           " span.textContent = '暂无已核验图片';"
                           " document.body.appendChild(span); }")
        self.assertIn("IMG_RENDERED_NO_PHOTO_STATE_MISMATCH", state["codes"], state["failures"])

    def test_empty_slot_is_not_the_same_thing_as_no_photo_state(self):
        # 真的空槽位（没有无图声明）仍走原来的 advisory，不被无图判据顶名。
        dataset = self.dataset()
        dataset["section_media"] = [{"destination": DEST, "modules": ["hotels"],
                                     "primary_module": "hotels", "module_category": "accommodation",
                                     "asset_role": "destination_atmosphere",
                                     "selection_level": "same_destination_same_category_reference",
                                     "image": ""}]
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / "probe-empty-slot.html"
            render_spa_document(html, copy.deepcopy(dataset), reader_profile="zh-formal")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(html.as_uri(), wait_until="load")
                page.wait_for_timeout(200)
                failures: list[str] = []
                result: dict = {}
                visual_qa.check_rendered_image_registration(
                    page, dataset, {"assets": []}, failures, result, manifest_required=True)
                browser.close()
        codes = [f.split("|")[0] for f in failures]
        self.assertEqual([c for c in codes if c.startswith("IMG_RENDERED_NO_PHOTO")], [], failures)
        self.assertEqual(result["designed_no_photo_state"]["declared_slots"], [])
        self.assertEqual(result["image_registration"]["empty_dataset_slots"], [DEST],
                         "真·空槽位必须仍然登记进 IMG_DATASET_SLOT_EMPTY，不能因为本轮改动而蒸发")


class LiveCaliforniaStateTests(unittest.TestCase):
    """现场复算：加州正式 run 的三行结果必须逐字等于登记面登记的那组数。"""

    @classmethod
    def setUpClass(cls):
        if not CA_RUN.is_dir():
            raise unittest.SkipTest("加州正式 run 不在盘上：%s" % CA_RUN)
        cls.data = json.loads((CA_RUN / "dataset.json").read_bytes().decode("utf-8"))
        cls.manifest = json.loads((CA_RUN / "asset-manifest.json").read_bytes().decode("utf-8"))
        cls.evidence = json.loads((CA_RUN / EVIDENCE_REL).read_bytes().decode("utf-8"))
        cls.no_photo = [r for r in cls.data["section_media"] if lmg.is_no_photo_row(r)]

    def test_locked_ratio_equals_the_live_run(self):
        lock = POLICY["ratio_lock"]["measured_ca_2026_11_03"]
        # R3D 之后登记格换成 r3d_live_row_counts_2026_11_04：清单 27 行、editorial 14 行、
        # section_media 17 行但展开槽位仍是 20（业主裁示 B 的复用）。r3c 那一格留在登记面作历史锚点。
        registered = lock["r3d_live_row_counts_2026_11_04"]
        section = self.data["section_media"]
        # 槽位只按唯一实现展开；这里再数一遍 len(section) 就是第二把尺子。
        slots, no_photo = lmg.section_slot_denominator(section)
        live = {"section_slots": slots,
                "photographic_slots": slots - no_photo,
                "designed_no_photo_slots": no_photo,
                "section_media_rows": len(section)}
        self.assertEqual(live, {k: registered[k] for k in live},
                         "登记的 20=18+2（17 行展开）与现场不一致：要么有人改了媒体面没重测，要么比例锁被动过")
        # 行计数不写死：33→29 那次（R3C 退出四条死登记）证明硬写的数字一定会漂。
        # 现场复算必须对上登记格 r3d_live_row_counts_2026_11_04，交付字节还要与链条自述互证。
        chain = json.loads((CA_RUN / "media_prepared" / "media-manifest.json").read_bytes().decode("utf-8"))
        counts = {"editorial_rows": len(self.data["editorial_media"]),
                  "manifest_rows": len(self.manifest["assets"]),
                  "delivered_image_bytes_total": sum((CA_RUN / r["local_file"]).stat().st_size
                                                     for r in self.manifest["assets"])}
        self.assertEqual(counts, {k: registered[k] for k in counts},
                         "现场行计数／交付字节与登记值不一致 ⇒ 有人改了媒体面没重测")
        self.assertEqual(chain.get("assets"), registered["manifest_rows"],
                         "链条自述的资产数与清单行数不等 ⇒ 两张面孔没一起老")
        self.assertEqual(chain.get("rendition_bytes"), counts["delivered_image_bytes_total"],
                         "链条字节合计与在盘交付档求和不等 ⇒ 交付字节口径漂移")

    def test_no_photo_rows_use_exactly_the_registered_representation(self):
        self.assertEqual(len(self.no_photo), 2)
        forbidden = {"author", "license", "license_url", "commons_page", "sha256", "image_srcset",
                     "focal_point", "caption_cn", "caption_en", "retrieved_at"}
        for row in self.no_photo:
            self.assertEqual(list(row), list(POLICY["allowed_fields"]),
                             "字段或顺序与业主裁示不一致：%s" % list(row))
            self.assertEqual(row["image"], POLICY["image_value"])
            self.assertEqual(row["no_photo_reason_code"], POLICY["reason_code_closed_set"][0])
            self.assertEqual(forbidden & set(row), set())
            self.assertTrue((CA_RUN / row["no_photo_evidence"]).is_file())
            self.assertEqual(lmg.check_no_photo_row(row, CA_RUN, [], POLICY), [],
                             "现场行过不了自己点名的判据")

    def test_sf_twin_peaks_exited_without_becoming_a_no_photo_row_or_a_gap(self):
        blob = json.dumps(self.data, ensure_ascii=False)
        self.assertNotIn("sf_twin_peaks", blob)
        titles = [str(row.get("source_file_title") or "") for row in self.manifest["assets"]]
        self.assertFalse([t for t in titles if "Twin Peaks" in t],
                         "清单里还留着 Twin Peaks 的资产行，来源快照就会再长出这三条")
        for row in self.data["editorial_media"]:
            self.assertTrue(str(row.get("image") or ""), "编辑轮播里出现空 image 行＝无图状态被误用了")

    def test_the_route_that_lost_the_hero_still_has_three_editorial_images(self):
        counts = {}
        for row in self.data["editorial_media"]:
            counts[str(row.get("route"))] = counts.get(str(row.get("route")), 0) + 1
        self.assertEqual(sorted(set(counts.values())), [3, 4],
                         "每条路线仍有 ≥3 张，deep 下限 6 张由总数 15 张满足：%s" % counts)

    def test_retired_bytes_are_gone_and_quarantine_digests_recompute(self):
        removed = self.evidence["removed_from_run"]
        self.assertEqual(len(removed), len(self.evidence["quarantine"]))
        for item in self.evidence["quarantine"]:
            self.assertFalse((CA_RUN / item["path"]).is_file(),
                             "退役字节还在正式 run 里：%s" % item["path"])
            copy = Path(item["quarantine"])
            self.assertTrue(copy.is_file(), "隔离区缺件：%s" % copy)
            self.assertEqual(digest(copy), item["sha256"], "隔离副本摘要与登记不符：%s" % item["path"])

    def test_media_audit_of_the_live_run_reports_no_no_photo_violation(self):
        coverage = [(key, self.data.get(key, []))
                    for key in ("hotels", "restaurants", "cafes", "attractions", "dive_sites")]
        found: list[str] = []
        lmg.validate_section_media(CA_RUN, self.data["section_media"], coverage,
                                   require_complete=True, collect=found,
                                   editorial_media=self.data["editorial_media"])
        self.assertEqual([f for f in found if f.startswith("SECTION_NO_PHOTO")], [], found)
        retired = lmg.no_photo_retired_assets(self.data["section_media"], CA_RUN)
        self.assertEqual(len(retired), 15, "退役清册条数变了：要么证据文件被改，要么隔离面漂了")


class SlotDenominatorTests(unittest.TestCase):
    """R3D 裁示 B 的分母口径：无图占比按展开后的 (destination, module) 槽位算，不按行数算。

    业主 2026-11-04 裁示 B 原话：「denominator still 20 slots, not row count」。
    登记面 media-policy.json::designed_no_photo_state.ratio_lock.rule 早就写了同一件事
    （「分母是按覆盖要求应声明的 section 槽位数，不是当前声明了几行」），
    但 formal_data_gate 那把尺子当时用的是 len(section_media)——
    三组同类别槽位按裁示合并成一行后，行数 20→17，2 个无图槽位被量成 11.8%＞10%，
    合法的复用反而被当成缺图率上升。这组用例钉的是：合并改行数，不许改分母。
    """

    def _rows(self, no_photo_slots: int):
        """17 行＝12 个单槽行＋3 个双槽合并行；展开后仍是 18 个有图槽＋no_photo_slots 个无图槽。"""
        rows = []
        for index in range(12):
            rows.append({"destination": "测试地%d" % index, "modules": ["attractions"],
                         "primary_module": "attractions", "module_category": "sights",
                         "selection_level": "same_destination_same_category_reference",
                         "asset_role": "destination_atmosphere"})
        for index in range(3):            # 业主裁示 B 的合法复用：一行覆盖 restaurants＋cafes
            rows.append({"destination": "合并地%d" % index, "modules": ["restaurants", "cafes"],
                         "primary_module": "restaurants", "module_category": "food",
                         "selection_level": "same_destination_same_category_reference",
                         "asset_role": "destination_atmosphere"})
        for index in range(no_photo_slots):
            rows.append({"destination": "无图地%d" % index, "modules": ["hotels"],
                         "primary_module": "hotels", "module_category": "accommodation",
                         "selection_level": lmg.NO_PHOTO_STATE_VALUE, "asset_role": lmg.NO_PHOTO_STATE_VALUE})
        return rows

    def test_merged_rows_keep_twenty_slots_even_though_there_are_seventeen_rows(self):
        rows = self._rows(2)
        self.assertEqual(len(rows), 17, "行数本身要变，否则测不到两把尺子的差别")
        slots, no_photo = lmg.section_slot_denominator(rows)
        self.assertEqual((slots, no_photo), (20, 2),
                         "17 行展开必须是 20 个槽位、2 个无图槽位（业主裁示 B 的分母）")
        self.assertGreater(no_photo / float(len(rows)), 0.10,
                           "按行数算是 11.8%＞10%——这正是旧尺子把复用误判成缺图的现场")

    def test_gate_uses_the_slot_denominator_so_the_owner_authorized_merge_passes(self):
        from test_formal_data_gate import audit, fixture
        data, manifest, scope, corridors, assets = fixture()
        data["section_media"] = self._rows(2)
        result = audit(data, manifest, scope, corridors, assets)
        ratio_errors = [e for e in result["errors"] if "设计缺图状态占比" in e]
        self.assertEqual(ratio_errors, [], "2/20＝10% 恰好贴线，合并三组同类别槽位不该把它顶过上限")

    def test_a_third_no_photo_slot_still_blocks_under_the_slot_denominator(self):
        from test_formal_data_gate import audit, fixture
        data, manifest, scope, corridors, assets = fixture()
        data["section_media"] = self._rows(3)
        slots, no_photo = lmg.section_slot_denominator(data["section_media"])
        self.assertEqual((slots, no_photo), (21, 3))
        result = audit(data, manifest, scope, corridors, assets)
        self.assertTrue(any("设计缺图状态占比" in e for e in result["errors"]),
                        "第三条无图槽位必须被占比门拦下——分母换口径不许顺手把门放宽")

    def test_denominator_helper_is_the_only_place_the_expansion_is_written(self):
        """展开算法只住 local_media_gate；formal_data_gate 调它，不再自己数 modules。"""
        gate = code_lines(SCRIPTS / "formal_data_gate.py")      # code_lines 交回一个字符串
        self.assertIn("section_slot_denominator", gate,
                      "formal_data_gate 没有调用唯一实现 ⇒ 又变成两把尺子")
        for own in ("len(mods", "len(item.get(\"modules\")", "for item in section_media"):
            self.assertNotIn(own, gate,
                             "formal_data_gate 里出现了第二份槽位展开：%s" % own)


if __name__ == "__main__":
    unittest.main()
