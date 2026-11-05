# -*- coding: utf-8 -*-
"""v4.2.2 V6-Q/V6-R/V6-S/V6-T/V6-T2 的执行型牙齿（全部由 V6-D 端到端实跑暴露）。

五件事各自都对应一次真实的读者可见后果，不是重构口味：

  V6-R 交付几何下限只有一个登记来源（业主裁决前的既有 640×360 数值，未放宽）。
       产图侧过去读不到它，于是等比缩档自己产出 1000×333 再被媒体门判死——读者失去那张照片。
  V6-Q 未登记/低于下限的图不许内联进读者页，而是登记成媒体缺口（行留在审计面，字节不进载荷）。
       加州 v4.2.0/v4.2.1 成品一直内联着两张 asset-manifest 里查无来源的图（511KB）。
  V6-S 图片资产校验逐张清点到底，不在首个异常处停止。
       一份只写一条问题的报告读起来像「只有这一条问题」。
  V6-T 撤回与 Checklist 冲突的 MAP_LEVEL_SEARCH_CANDIDATE（NAMED_SEARCH 本该有搜索按钮），
       同一规则的第二套实现留在 visual_qa 里，就会把唯一正确的诚实实现判成 FAIL。
  V6-T2 IMG_TOO_WIDE 与几何下限的冲突改成按登记复算，并把 read_by 补成现场重测的读者名单。
       钳制档 1081×360 本来就不可能同时满足两条规则；名单漏登记的一侧迟早退回裸数。

约定：本文件不写发布树产物，全部落到临时目录。
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

import local_media_gate as lmg        # noqa: E402
import map_gate_v422 as mg422         # noqa: E402
import prepare_media as pm            # noqa: E402
import single_file_policy as sfp      # noqa: E402
import spa_renderer as sr             # noqa: E402
import visual_qa as vq                # noqa: E402
from PIL import Image                  # noqa: E402


def write_jpeg(path: Path, width: int, height: int, seed: int = 7) -> Path:
    """造一张有真实纹理的图（纯色会被真实性门判成占位图，测试要的是几何而不是内容质量）。"""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(0, width, 3):
            pixels[x, y] = ((x * seed + y) % 256, (y * 3 + x) % 256, (x + y + seed) % 251)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92, subsampling=0)
    return path


class GeometryFloorRegistrationTests(unittest.TestCase):
    def test_floor_is_one_registry_two_readers(self):
        floor = sfp.delivered_geometry_floor()
        self.assertEqual(floor, (640, 360), "数值必须与 v4.2.1 起生效的既有下限一致：本轮不放宽")
        block = json.loads((ROOT / "references" / "single-file-delivery-policy.json")
                           .read_text(encoding="utf-8")
                           )["delivered_rendition_ladder"]["min_delivered_geometry"]
        self.assertIn("scripts/prepare_media.py", block["read_by"])
        self.assertIn("scripts/local_media_gate.py", block["read_by"])
        self.assertTrue(str(block.get("measured_consequence") or "").strip(),
                        "钳制的字节代价必须登记，否则「档位由登记决定」又变成半句话")

    def test_local_media_gate_has_no_bare_geometry_numbers(self):
        body = (SCRIPTS / "local_media_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("width < 640 or height < 360", body,
                         "媒体门里留着裸数就是第二套下限：产图侧读不到它才会产出被自己拒掉的图")
        self.assertIn("delivered_geometry_floor()", body)

    def test_ladder_id_bumped_and_history_explains_why(self):
        policy = json.loads((ROOT / "references" / "single-file-delivery-policy.json")
                            .read_text(encoding="utf-8"))
        block = policy["delivered_rendition_ladder"]
        self.assertEqual(block["id"], sfp.LADDER_ID)
        withdrawn = [row.get("id") for row in block["revision_history"] if row.get("withdrawn")]
        self.assertIn("v4.2.2-delivered-rendition-ladder-3", withdrawn,
                      "被取代的档位必须留下撤回理由，否则下一轮还会重犯")


FLOOR_ACCESSORS = ("delivered_geometry_floor", "min_delivered_height_px", "min_delivered_width_px")


class GeometryFloorReaderClosureTests(unittest.TestCase):
    """read_by 必须是「现场重测出来的读者名单」，不是当初随手写下的四个字符串。

    V6-T2 之所以要补登记：spa_renderer 与 visual_qa 早就在读这条下限，名单里却没有它们。
    漏登记的读者不会报错，只会在下一轮被重写成裸数——V0-L11 的成因就是这个。
    """

    def registry(self):
        return json.loads((ROOT / "references" / "single-file-delivery-policy.json")
                          .read_text(encoding="utf-8")
                          )["delivered_rendition_ladder"]["min_delivered_geometry"]

    def actual_readers(self):
        readers = set()
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name.startswith("test_") or path.name == "single_file_policy.py":
                continue        # 定义方本身不算读者：它提供读数，不消费规则
            source = path.read_text(encoding="utf-8")
            if any(accessor in source for accessor in FLOOR_ACCESSORS):
                readers.add("scripts/" + path.name)
        return readers

    def test_registered_readers_are_really_reading(self):
        readers = self.actual_readers()
        for name in self.registry()["read_by"]:
            self.assertIn(name, readers,
                          "%s 登记为几何下限的读者，但现场重测不到它读数：名单里写了不做" % name)

    def test_every_actual_reader_is_registered(self):
        registered = set(self.registry()["read_by"])
        missing = sorted(self.actual_readers() - registered)
        self.assertEqual(missing, [],
                         "这些模块在读交付几何下限却没登记：%s——不登记就是给它留一条退回裸数的路" % missing)


class WideSlotVersusGeometryFloorTests(unittest.TestCase):
    """IMG_TOO_WIDE 与「高度不许跌破下限」是同一条交付档的两面，冲突时放行哪一边必须有登记依据。"""

    def dom_image(self, name, width, height):
        return {"name": name, "src": "asset://sha256:" + name, "width": width, "height": height,
                "complete": True, "srcset": False, "sizes": False, "inline": True,
                "on_first_screen": True, "inline_bytes": 50_000}

    class StubPage:
        def __init__(self, images):
            self.images = images

        def evaluate(self, script):        # check_embedded_image_supply 只取一次 DOM
            return self.images

    def qa(self, images):
        failures, result = [], {}
        vq.check_embedded_image_supply(self.StubPage(images), failures, result, dataset={})
        return failures, result

    def test_cap_itself_is_untouched(self):
        budgets = sfp.load_policy()["budgets"]
        self.assertEqual(vq.MAX_DELIVERED_IMG_WIDTH,
                         int(budgets["max_delivered_image_width_px"]),
                         "宽度上限只能等于登记值：抬上限来吞掉超宽图就是把门槛悄悄降低")
        self.assertLess(vq.MAX_DELIVERED_IMG_WIDTH, 1600, "登记值仍是 1000px，本轮没有放宽")

    def test_clamped_panorama_is_not_blamed_as_too_wide(self):
        failures, result = self.qa([self.dom_image("big_sur_bixby_bridge.jpg", 1081, 360)])
        self.assertEqual([item for item in failures if item.startswith("IMG_TOO_WIDE")], [],
                         "1081×360 是按登记的 clamp_rule 产出的档：压回 1000px 只剩 333px 高，"
                         "媒体门会判 too small，读者就看不到这张照片——视觉门不该惩罚它")
        self.assertEqual(len(result["images_wide_by_geometry_clamp"]), 1,
                         "放行必须留痕：报告里看不出哪张是被钳制档放行的，下轮就会被当成漏判")

    def test_an_image_that_could_have_been_smaller_still_blocks(self):
        # 2000×1500 压到 1000px 仍有 750px 高；1001×400 压到 1000px 仍有 399px 高。
        for name, width, height in (("wide_poster.jpg", 2000, 1500), ("just_over.jpg", 1001, 400)):
            failures, result = self.qa([self.dom_image(name, width, height)])
            wide = [item for item in failures if item.startswith("IMG_TOO_WIDE")]
            self.assertEqual(len(wide), 1, "%s 能同时满足两条登记规则，必须仍算缺陷" % name)
            self.assertIn(name, wide[0])
            self.assertIn("1000px", wide[0], "报出来的必须是登记上限，不是另一个数字")
            self.assertEqual(result["images_wide_by_geometry_clamp"], [])

    def test_split_predicate_recomputes_the_registered_rule(self):
        cap, floor = vq.MAX_DELIVERED_IMG_WIDTH, sfp.delivered_geometry_floor()[1]
        images = [self.dom_image("n.jpg", 900, 600), self.dom_image("c.jpg", 1081, 360),
                  self.dom_image("b.jpg", 2000, 1500)]
        allowed, blocking = vq.split_over_wide_images(images, cap_px=cap, floor_height_px=floor)
        self.assertEqual([item["name"] for item in allowed], ["c.jpg"])
        self.assertEqual([item["name"] for item in blocking], ["b.jpg"],
                         "不超宽的图不进任何一个名单：放行与缺陷只针对超过上限的那几张")

    def test_conflict_rule_is_registered_not_invented_in_the_gate(self):
        block = self.registry_block()
        conflict = block["width_cap_conflict"]
        for key in ("rule", "why_registered", "measured_consequence", "read_by"):
            self.assertTrue(str(conflict.get(key) or "").strip(), "宽度冲突条款缺 %s" % key)
        self.assertIn("scripts/visual_qa.py", conflict["read_by"])
        self.assertIn("max_delivered_image_width_px", conflict["rule"],
                      "放行判据必须写成登记值之间的算式，不能是 visual_qa 里的私有常数")

    def registry_block(self):
        return json.loads((ROOT / "references" / "single-file-delivery-policy.json")
                          .read_text(encoding="utf-8")
                          )["delivered_rendition_ladder"]["min_delivered_geometry"]


class PrepareMediaClampTests(unittest.TestCase):
    def prepare(self, width: int, height: int):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_jpeg(root / "src.jpg", width, height)
            out = root / "out"
            result = pm.prepare_asset(source, out, slot="hero")
            self.assertEqual(len(result["renditions"]), 1, "每槽只出一档（登记的 tier_count_note）")
            return result, result["renditions"][0]

    def test_ultrawide_source_is_clamped_to_keep_the_floor(self):
        result, row = self.prepare(1600, 533)      # 实测的 Bixby 大桥全景形状
        self.assertGreaterEqual(row["height"], sfp.delivered_geometry_floor()[1],
                                "等比缩档不许把交付高度压到登记下限之下")
        self.assertTrue(row["geometry_floor_clamped"], "钳制必须写进产图记录，否则审计看不出来")
        self.assertIn("geometry_floor_clamped", row["transform"])
        self.assertLessEqual(row["width"], result["source_width"], "钳制不等于放大")

    def test_source_already_below_floor_is_not_upscaled(self):
        result, row = self.prepare(1600, 186)      # 实测的 Twin Peaks 条幅形状
        self.assertFalse(row["geometry_floor_clamped"],
                         "源本身不达标时不放大：插值不还给读者细节，那条图走 V6-Q 的媒体缺口")
        self.assertEqual(row["width"], 1000)
        self.assertLess(row["height"], sfp.delivered_geometry_floor()[1])
        self.assertLessEqual(row["bytes"], sfp.rendition_ladder()["max_delivered_image_decoded_bytes"])


class MediaGapProjectionTests(unittest.TestCase):
    """读者页不许内联「拿不出证据」的图；但剔除必须留下可对账的缺口记录。"""

    def build(self, tmp: Path) -> dict:
        assets = tmp / "assets"
        write_jpeg(assets / "editorial" / "registered.jpg", 900, 600, seed=11)
        write_jpeg(assets / "editorial" / "unregistered.jpg", 900, 600, seed=23)
        write_jpeg(assets / "editorial" / "panorama.jpg", 1000, 116, seed=37)
        renditions = {
            "assets/editorial/registered.jpg": [
                {"label": "w900", "width": 900, "height": 600, "bytes": 20480,
                 "path": "assets/editorial/registered.jpg", "file": "registered.jpg"}],
            "assets/editorial/panorama.jpg": [
                {"label": "w1000", "width": 1000, "height": 116, "bytes": 30720,
                 "path": "assets/editorial/panorama.jpg", "file": "panorama.jpg"}],
        }
        return {"country": "测试国", "duration_days": 2, "route_budgets": {},
                "media_renditions": renditions,
                "editorial_media": [
                    {"image": "assets/editorial/registered.jpg", "title_cn": "合规图",
                     "route": "R1", "destination": "D1"},
                    {"image": "assets/editorial/unregistered.jpg", "title_cn": "无来源图",
                     "route": "R1", "destination": "D1"},
                    {"image": "assets/editorial/panorama.jpg", "title_cn": "超下限图",
                     "route": "R2", "destination": "D2"}]}

    def test_unregistered_and_below_floor_images_never_enter_the_reader_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.build(root)
            adapted = sr._adapt_spa_dataset(json.loads(json.dumps(dataset)), "inline",
                                           assets_dir=root / "assets", run_asset_dir=root)
            kept = [str(item["image"]) for item in adapted.get("editorial_media") or []]
            self.assertEqual(len(kept), 1, "无证据/超下限的整行都不进读者载荷：半张图比没图更糟")
            self.assertTrue(kept[0].startswith("asset://sha256:"),
                            "留下的那张必须已经指向登记字节，而不是留着走文件的路径引用")
            gaps = {gap["asset"]: gap["kind"] for gap in adapted.get("media_gaps") or []}
            self.assertEqual(gaps, {"assets/editorial/unregistered.jpg":
                                    "MEDIA_UNREGISTERED_IN_MANIFEST",
                                    "assets/editorial/panorama.jpg":
                                    "MEDIA_BELOW_GEOMETRY_FLOOR"})
            blobs = json.dumps(adapted.get("asset_blobs") or {}, ensure_ascii=False)
            for asset in gaps:
                digest = __import__("hashlib").sha256(
                    (root / asset).read_bytes()).hexdigest()
                self.assertNotIn(digest[:16], blobs, "%s 的字节仍被内联，剔除只是说说" % asset)
            for gap in adapted.get("media_gaps") or []:
                self.assertTrue(gap.get("withheld_row"),
                                "缺口记录必须指回被剔的那一行（标题/列表/序号），否则审计无从复核")
                self.assertGreater(gap.get("source_bytes", 0), 0, "缺了多少字节必须可见")

    def test_gap_rule_does_not_fire_when_no_manifest_is_registered(self):
        """没有清单＝没有登记面可对账，本轮口径不适用；不许把它变成「无清单就全删」。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jpeg(root / "assets" / "editorial" / "one.jpg", 800, 600)
            dataset = {"country": "测试国", "duration_days": 1, "route_budgets": {},
                       "editorial_media": [{"image": "assets/editorial/one.jpg",
                                            "title_cn": "无清单图", "route": "R", "destination": "D"}]}
            adapted = sr._adapt_spa_dataset(dataset, "inline", assets_dir=root / "assets",
                                      run_asset_dir=root)
            self.assertEqual(len(adapted.get("editorial_media") or []), 1)
            self.assertFalse(adapted.get("media_gaps"))

    def test_audit_dataset_is_never_mutated_by_the_gap_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.build(root)
            snapshot = json.dumps(dataset, sort_keys=True, ensure_ascii=False)
            sr._adapt_spa_dataset(dataset, "inline", assets_dir=root / "assets",
                                      run_asset_dir=root)
            self.assertEqual(json.dumps(dataset, sort_keys=True, ensure_ascii=False), snapshot,
                             "投影只作用于渲染副本：审计面的行一条不许少")


class FullPopulationSweepTests(unittest.TestCase):
    def editorial_entry(self, name: str) -> dict:
        return {"image": "assets/editorial/%s.jpg" % name, "title_cn": name,
                "route": "R1", "destination": "D1"}

    def test_every_bad_asset_is_reported_not_only_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("one", "two", "three"):
                write_jpeg(root / "assets" / "editorial" / ("%s.jpg" % name), 800, 600)
            (root / "asset-manifest.json").write_text(
                json.dumps({"assets": []}, ensure_ascii=False), encoding="utf-8")
            findings: list[str] = []
            lmg.validate_editorial_media(root, [self.editorial_entry(name) for name in
                                                ("one", "two", "three")], [],
                                         collect=findings)
            self.assertEqual(len(findings), 3,
                             "三张都没有登记证据，报告必须给三条：一条＝假装只找到一条")
            for name in ("one", "two", "three"):
                self.assertIn("assets/editorial/%s.jpg" % name, " ".join(findings),
                              "%s 没被点名，读者就不知道少的是哪张图" % name)

    def test_collectless_callers_keep_the_historical_raise_semantics(self):
        """生成器等老调用方不传 collect：必须仍然抛错，而不是静默变成「查完再说」。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "asset-manifest.json").write_text(json.dumps({"assets": []}),
                                                      encoding="utf-8")
            with self.assertRaises(ValueError):
                lmg.validate_editorial_media(root, [], [])

class WithdrawnSearchCandidateRuleTests(unittest.TestCase):
    def named_search_targets(self):
        return {"旧金山|Apple Park Visitor Center": {
            "target_id": "t-1", "canonical_name": "Apple Park Visitor Center",
            "display_name_cn": "苹果公园访客中心", "target_level": "search_candidate",
            "link_mode": "NAMED_SEARCH", "identity_status": "UNVERIFIED",
            "coordinate_status": "VERIFIED", "google_resolution_status": "NOT_OBSERVED",
            "google_url": "https://www.google.com/maps/search/?api=1&query=Apple%20Park",
            "map_link_url": "https://www.google.com/maps/search/?api=1&query=Apple%20Park",
            "map_link_by_provider": {"google": {"link_mode": "NAMED_SEARCH",
                                                "map_link_url":
                                                "https://www.google.com/maps/search/"
                                                "?api=1&query=Apple%20Park"}},
        }}

    def test_honest_named_search_button_is_no_longer_a_failure(self):
        failures, result = [], {}
        vq.check_embedded_map_contract({"map_targets": self.named_search_targets(),
                                        "demo_mode": False}, failures, result)
        self.assertEqual([item for item in failures
                          if item.startswith("MAP_LEVEL_SEARCH_CANDIDATE")], [],
                         "合同要求 NAMED_SEARCH 给搜索入口，视觉门却把「有按钮」判成缺陷")
        self.assertEqual(result["map_search_candidates"], 1,
                         "仍然要数得出来：读者页有几颗搜索档按钮是交付报告的分母")

    def test_withdrawn_rule_has_no_leftover_copy_in_the_release(self):
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            self.assertNotIn('MAP_LEVEL_SEARCH_CANDIDATE|',
                             path.read_text(encoding="utf-8"),
                             "“%s 仍在发射被撤回的旧错误码（撤回要连实现一起撤，注释里引用它不算残留）”" % path.name)

    def test_the_real_teeth_stay_in_the_map_gate(self):
        """撤回的是冲突的旧条，不是撤掉文案约束：登记文案逐字核对必须仍然住在地图门禁里。"""
        body = (SCRIPTS / "map_gate_v422.py").read_text(encoding="utf-8")
        for code in ("GATE_DOM_COPY_DIFFERS", "GATE_DOM_LINK_MODE_DIFFERS",
                     "GATE_DOM_HREF_DIFFERS", "GATE_DOM_HREF_UNEXPECTED"):
            self.assertIn(code, body, "%s 没了＝按钮文案与档位不再被逐字对账" % code)
        self.assertTrue(mg422.load_gate(), "门禁配置必须仍可加载")


if __name__ == "__main__":
    unittest.main()
