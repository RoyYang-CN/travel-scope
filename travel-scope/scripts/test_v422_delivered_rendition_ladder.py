# -*- coding: utf-8 -*-
"""v4.2.2 V6-C：交付档由登记决定（single-file-delivery-policy.json::delivered_rendition_ladder）。

业主 2026-10-30 裁决走「重编交付图」：不抬围栏、不改单文件形态、不放宽门禁。这条裁决要能落地，
必须满足三件事，本文件逐件测：

  1. 档位与预算只有一个来源——prepare_media 里那行裸常数必须消失，登记一改产图就跟着改；
  2. 登记必须自洽——单图上限＝内联上限×1024、总预算×4/3 必须小于围栏、DOM 侧全页预算必须
     等于同一个数；以前 4,194,304 与围栏各写各的，谁也没被拿去对账；
  3. 两条新门禁真的有牙——超限交付图与未声明档位的交付记录都必须报错，chosen 档必须实测可行。

渲染/产图都用合成图，不读历史 run，也不写发布树。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

import local_media_gate as lmg          # noqa: E402
import prepare_media as pm              # noqa: E402
import self_contained_audit as sfa      # noqa: E402
import single_file_policy as sfp        # noqa: E402

POLICY_PATH = ROOT / "references" / "single-file-delivery-policy.json"
POLICY_TEXT = POLICY_PATH.read_text(encoding="utf-8")
POLICY = json.loads(POLICY_TEXT)
LADDER = POLICY["delivered_rendition_ladder"]


def write_policy(mutate):
    cfg = copy.deepcopy(POLICY)
    mutate(cfg)
    path = Path(tempfile.mkdtemp()) / "single-file-delivery-policy.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class RegisterSelfConsistencyTests(unittest.TestCase):
    """登记的每个数字都要能被另一条登记核对，否则它只是一个没人对账的常数。"""

    def test_policy_loads(self):
        self.assertTrue(sfp.load_policy())

    def test_per_image_cap_equals_inline_cap_times_1024(self):
        cap = POLICY["media_delivery"]["default_max_inline_kb"] * 1024
        self.assertEqual(LADDER["budgets"]["max_delivered_image_decoded_bytes"], cap,
                         "单图上限若大于内联上限，就允许了一张注定进不了单文件的交付图")

    def test_per_image_cap_drift_blocks(self):
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.load_policy(write_policy(
                lambda cfg: cfg["delivered_rendition_ladder"]["budgets"].__setitem__(
                    "max_delivered_image_decoded_bytes",
                    cfg["delivered_rendition_ladder"]["budgets"][
                        "max_delivered_image_decoded_bytes"] + 1)))

    def test_total_budget_must_fit_inside_the_fence(self):
        total = LADDER["budgets"]["total_delivered_image_decoded_bytes_max"]
        fence = POLICY["budgets"]["max_delivered_file_bytes"]
        self.assertLess(total * 4 // 3, fence,
                        "图片按 4/3 内联膨胀后必须仍然留在围栏内，否则这条登记本身就破围栏")

    def test_total_budget_drift_blocks(self):
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.load_policy(write_policy(
                lambda cfg: cfg["delivered_rendition_ladder"]["budgets"].__setitem__(
                    "total_delivered_image_decoded_bytes_max",
                    POLICY["budgets"]["max_delivered_file_bytes"])))

    def test_dom_side_total_budget_is_the_same_number(self):
        self.assertEqual(POLICY["budgets"]["total_inline_budget_bytes"],
                         LADDER["budgets"]["total_delivered_image_decoded_bytes_max"],
                         "全页图片预算与交付总预算以前是两份数（4,194,304 vs 围栏反推值），"
                         "两份都自称权威＝没有权威")

    def test_chosen_ladder_is_measured_and_viable(self):
        chosen = LADDER["measured_sweep"]["chosen"]
        rows = [row for row in LADDER["measured_sweep"]["rows"] if row["ladder_name"] == chosen]
        self.assertTrue(rows, "chosen 档必须有实测行")
        for row in rows:
            self.assertEqual(row["audit_status"], "PASS", "%s 上 chosen 档的字节账单不是 PASS" % row["run"])
            self.assertFalse(row["over_fence"], "%s 上 chosen 档超围栏" % row["run"])
            self.assertFalse(row["over_total_budget"], "%s 上 chosen 档超交付总预算" % row["run"])
            self.assertTrue(row["self_contained_in_dom"],
                            "%s 上 chosen 档仍有走文件引用或假封面" % row["run"])
            self.assertEqual(row["prepare_status"], "PASS", "%s 上产图报告 FAIL" % row["run"])
            self.assertEqual(row["install_status"], "PASS", "%s 上双跳链装配 FAIL" % row["run"])
            self.assertLessEqual(row["max_single_delivered_image_bytes"],
                                 LADDER["budgets"]["max_delivered_image_decoded_bytes"],
                                 "chosen 档自己就得守单图上限")
            self.assertLessEqual(row["delivered_decoded_bytes"],
                                 LADDER["budgets"]["total_delivered_image_decoded_bytes_max"],
                                 "chosen 档自己就得守总预算")
            self.assertEqual(row["images_over_per_image_cap"], 0)
            self.assertEqual(row["dom"]["file"], 0)
            self.assertEqual(row["dom"]["fallback"], 0)

    def test_sweep_rows_come_from_the_shipping_pipeline(self):
        """登记数字必须来自会出货的那条路径——V6-C 用手工口径登记，真管线当场 exit 2，就是这条。"""
        self.assertIn("install_run_media", LADDER["measured_sweep"]["path"])
        for row in LADDER["measured_sweep"]["rows"]:
            for key in ("manifest_rows", "delivered_files", "prepare_status", "install_status",
                        "dom", "container_bytes", "viable"):
                self.assertIn(key, row, "%s 的行缺 %s（口径不完整）" % (row["ladder_name"], key))

    def test_chosen_ladder_is_the_only_one_viable_everywhere_it_must_be(self):
        chosen = LADDER["measured_sweep"]["chosen"]
        for run, viable in LADDER["measured_sweep"]["viable_ladders_by_run"].items():
            self.assertIn(chosen, viable, "chosen 档必须在每棵 run 都被实测为可行：%s" % run)
        tightest = min((row for row in LADDER["measured_sweep"]["rows"]
                        if row["ladder_name"] == chosen), key=lambda r: r["fence_margin_bytes"])
        self.assertGreater(tightest["fence_margin_bytes"], 0,
                           "%s 的围栏余量已经非正，chosen 档不能算可行" % tightest["run"])

    def test_single_tier_per_slot_is_explained(self):
        for slot, spec in LADDER["slots"].items():
            self.assertEqual(len(spec["tiers"]), 1,
                             "%s 出多档时，第二档在全内联下单文件里是死字节；要改必须先有裁决" % slot)
        self.assertTrue(str(LADDER.get("tier_count_note") or "").strip())

    def test_missing_tier_count_note_blocks(self):
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.load_policy(write_policy(
                lambda cfg: cfg["delivered_rendition_ladder"].__setitem__("tier_count_note", "")))

    def test_duplicate_tier_labels_block(self):
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.load_policy(write_policy(lambda cfg: cfg["delivered_rendition_ladder"]["slots"][
                "hero"]["tiers"].append({"label": "w1200", "max_width_px": 1200,
                                         "jpeg_quality": 40})))

    def test_slot_set_must_match_the_producer(self):
        self.assertEqual(sorted(LADDER["slots"]), sorted(sfp.LADDER_SLOTS))
        # slot_for 只会产出这两个槽位；产不出登记里的槽位＝登记是空话
        for display_role, expect in (("route_hero", "hero"), ("section_cover", "destination_atmosphere")):
            self.assertEqual(pm.slot_for({"display_role": display_role}), expect)


class NoSecondCopyTests(unittest.TestCase):
    def test_prepare_media_has_no_local_ladder_constants(self):
        """档位表只能来自登记。查 AST 而不是查文本：说明文字里引用旧常数不是违规。"""
        path = SCRIPTS / "prepare_media.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        local_tuples = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple) and any(
                    isinstance(item, ast.Constant) and item.value == "w1200" for item in node.elts):
                local_tuples.append(ast.get_source_segment(
                    path.read_text(encoding="utf-8"), node))
        self.assertEqual(local_tuples, [],
                         "产图模块里再留一份档位表（哪怕是模块级常数），改登记不改这里就会静默按旧档出货")
        assignments = [target.id for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Name)]
        self.assertNotIn("RENDITIONS", assignments)
        self.assertNotIn("SLOT_RENDITIONS", assignments)
        source = path.read_text(encoding="utf-8")
        self.assertIn("single_file_policy.rendition_ladder()", source)

    def test_prepare_media_reads_the_register(self):
        source = (SCRIPTS / "prepare_media.py").read_text(encoding="utf-8")
        self.assertIn("single_file_policy.rendition_ladder()", source)


class ProduceTests(unittest.TestCase):
    def make_source(self, path, width=1600, height=900, quality_noise=40):
        image = Image.new("RGB", (width, height))
        pixels = image.load()
        for y in range(height):
            for x in range(0, width, 3):
                pixels[x, y] = ((x * 7 + y) % 256, (y * 3) % 256, (x + y * quality_noise) % 256)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=95)
        path.write_bytes(buf.getvalue())
        return path

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_tiers_come_from_the_register_and_are_labelled(self):
        source = self.make_source(self.dir / "art.jpg")
        entry = pm.prepare_asset(source, self.dir / "out", slot="hero")
        labels = [row["label"] for row in entry["renditions"]]
        self.assertEqual(labels, [tier[0] for tier in pm.slot_tiers("hero")],
                         "产出的档位必须正好是登记声明的那几条，不多不少")
        for row in entry["renditions"]:
            self.assertIn(sfp.LADDER_ID, row["transform"],
                          "交付记录要能说出自己是按哪一版档位产的，否则双跳摘要只证明没被换过")
        self.assertEqual(entry["source_sha256"], hashlib.sha256(
            source.read_bytes()).hexdigest(), "源图哈希必须留住，重编不是换图")

    def test_unknown_slot_is_refused_not_defaulted(self):
        source = self.make_source(self.dir / "x.jpg", width=400, height=300)
        with self.assertRaises(ValueError):
            pm.prepare_asset(source, self.dir / "out", slot="popup_thing")

    def test_over_per_image_cap_refuses_to_ship(self):
        """一张比登记单图上限还大的交付图＝单文件里必然漏图，产图侧就要拒绝出货。"""
        original = pm.ladder
        pm.ladder = lambda: dict(original(), max_delivered_image_decoded_bytes=2048)
        try:
            source = self.make_source(self.dir / "big.jpg", width=1200, height=900)
            with self.assertRaises(ValueError) as caught:
                pm.prepare_asset(source, self.dir / "out", slot="hero")
            self.assertIn("IMG_DELIVERED_OVER_INLINE_CAP", str(caught.exception))
        finally:
            pm.ladder = original

    def test_prepare_run_reports_total_over_budget(self):
        original = pm.ladder
        pm.ladder = lambda: dict(original(), total_delivered_image_decoded_bytes_max=1)
        try:
            run = self.dir / "run"
            (run / "assets").mkdir(parents=True)
            for name in ("a.jpg", "b.jpg"):
                self.make_source(run / "assets" / name, width=900, height=600)
            (run / "asset-manifest.json").write_text(json.dumps({"assets": [
                {"local_file": "assets/a.jpg", "display_role": "section_cover",
                 "sha256": hashlib.sha256((run / "assets" / "a.jpg").read_bytes()).hexdigest()},
                {"local_file": "assets/b.jpg", "display_role": "section_cover",
                 "sha256": hashlib.sha256((run / "assets" / "b.jpg").read_bytes()).hexdigest()},
            ]}), encoding="utf-8")
            report = pm.prepare_run(run, self.dir / "prepared")
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any(item.startswith("SFD_DELIVERED_TOTAL_OVER_BUDGET")
                                for item in report["errors"]), report["errors"])
            self.assertEqual(report["ladder_id"], sfp.LADDER_ID)
        finally:
            pm.ladder = original


class EncodeRegistrationTests(unittest.TestCase):
    """编码旗标也是交付档：登记改了产图就得跟着改，登记不自洽就谁也别想出货。

    这条测试是 V6-D 的第一次端到端跑逼出来的——尺寸/质量/预算都登记了，唯独 JPEG 编码旗标没有，
    于是 PIL 默认的 4:2:0 把一张真全景照的色彩熵压到真实性门下限之下，读者拿不到那张图。
    """

    def test_encode_block_is_registered_and_explained(self):
        encode = LADDER["encode"]
        self.assertIn(encode["subsampling"], sfp.ALLOWED_SUBSAMPLING)
        for key in ("optimize", "progressive"):
            self.assertIsInstance(encode[key], bool)
        for key in ("why_registered", "measured_consequence"):
            self.assertTrue(str(encode.get(key) or "").strip(),
                            "旗标值登记了但没人说明它为什么是这个值，等于又埋一个裸常数")

    def test_bogus_subsampling_blocks_the_policy(self):
        for bad in (3, -1, "0"):
            with self.assertRaises(sfp.SingleFilePolicyError):
                sfp.load_policy(write_policy(
                    lambda cfg, value=bad: cfg["delivered_rendition_ladder"]["encode"]
                    .__setitem__("subsampling", value)))

    def test_missing_encode_block_blocks_the_policy(self):
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.load_policy(write_policy(
                lambda cfg: cfg["delivered_rendition_ladder"].pop("encode")))

    def test_encode_flags_are_not_hard_coded_in_the_producer(self):
        """save() 的编码参数只能取自登记；写死数字就是第二个实现，改登记会静默按旧旗标出货。"""
        path = SCRIPTS / "prepare_media.py"
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        literals = []
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in ("subsampling", "optimize",
                                                             "progressive"):
                if isinstance(node.value, ast.Constant):
                    literals.append((node.arg, node.value.value))
        self.assertEqual(literals, [],
                         "产图模块里给 JPEG 旗标写了裸常数：%s——交付档的三分之一又回到代码里了"
                         % literals)
        self.assertIn('encode["subsampling"]', text)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_swapping_the_registered_subsampling_changes_the_output(self):
        original = pm.ladder
        source = self.dir / "art.jpg"
        image = Image.new("RGB", (1600, 900))
        pixels = image.load()
        for y in range(900):
            for x in range(1600):
                pixels[x, y] = ((x * 7 + y) % 256, (y * 3) % 256, (x + y * 40) % 256)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=95)
        source.write_bytes(buf.getvalue())
        seen = {}
        try:
            for value in (0, 1, 2):
                pm.ladder = (lambda inner=original, sub=value: dict(
                    inner(), encode={"subsampling": sub, "optimize": True, "progressive": True}))
                entry = pm.prepare_asset(source, self.dir / ("out%d" % value), slot="hero")
                row = entry["renditions"][0]
                seen[value] = (row["delivered_sha256"], row["bytes"])
                self.assertIn("subsampling=%d" % value, row["transform"],
                              "交付记录要写清自己是被哪一组编码旗标产出来的")
        finally:
            pm.ladder = original
        self.assertEqual(len({sha for sha, _ in seen.values()}), 3,
                         "三个 subsampling 产出同一份字节——说明登记没被真正读进去")

    def test_authenticity_pass_carries_its_own_measurement(self):
        """过线与不过线都得报出数字：只看 PASS/FAIL 无法判断离登记下限还剩多少余量。"""
        floor = float(lmg.MEDIA_POLICY["authenticity_gate"]["min_color_entropy"])
        source = self.dir / "photo.jpg"
        image = Image.new("RGB", (600, 400))
        pixels = image.load()
        for y in range(400):
            for x in range(600):
                pixels[x, y] = ((x * 13 + y * 5) % 256, (x ^ y) % 256, (x * 3 + y * 11) % 256)
        image.save(source, format="JPEG", quality=90, subsampling=0)
        ok, reason = lmg.check_image_authenticity(source, {"display_role": "x"})
        self.assertTrue(ok, reason)
        self.assertIn("color_entropy=", reason)
        reported = float(reason.split("color_entropy=")[1].split("|")[0])
        self.assertGreaterEqual(reported, floor)

    def test_chosen_rows_record_the_quantity_the_gate_judges(self):
        """总预算比的是产物内联解码字节，不是清单交付档之和；两个量都要留在行里。"""
        chosen = LADDER["measured_sweep"]["chosen"]
        for row in LADDER["measured_sweep"]["rows"]:
            if row["ladder_name"] != chosen:
                continue
            for key in ("decoded_blob_bytes_in_artifact", "delivered_decoded_bytes",
                        "budget_quantity_note"):
                self.assertIn(key, row, "%s 行缺 %s" % (row["run"], key))
            self.assertEqual(row["over_total_budget"],
                             row["decoded_blob_bytes_in_artifact"] >
                             LADDER["budgets"]["total_delivered_image_decoded_bytes_max"],
                             "%s 的 over_total_budget 不是按门禁比较的那个量算的" % row["run"])
            self.assertFalse(row["over_total_budget"],
                             "%s 上 chosen 档的产物内联解码字节超登记总预算" % row["run"])


class GateTests(unittest.TestCase):
    def manifest_with(self, root: Path, size: int, transform: str):
        payload = root / "delivered.jpg"
        payload.write_bytes(b"\xff\xd8" + b"\x00" * max(0, size - 2))
        return {"assets": [{"local_file": "delivered.jpg", "transform": transform,
                           "renditions": [{"label": "w1200", "transform": transform,
                                           "sha256": "0" * 64, "file": "delivered.jpg"}]}]}

    def test_clean_delivery_passes(self):
        root = Path(tempfile.mkdtemp())
        cap = LADDER["budgets"]["max_delivered_image_decoded_bytes"]
        errors, metrics = lmg.check_delivered_rendition_budget(
            self.manifest_with(root, cap - 1024, "%s|thumbnail_aspect_preserve" % sfp.LADDER_ID),
            root)
        self.assertEqual(errors, [])
        self.assertEqual(metrics["delivered_over_per_image_cap"], 0)
        self.assertEqual(metrics["delivered_ladder_unregistered"], 0)

    def test_oversized_delivered_image_blocks(self):
        root = Path(tempfile.mkdtemp())
        cap = LADDER["budgets"]["max_delivered_image_decoded_bytes"]
        errors, metrics = lmg.check_delivered_rendition_budget(
            self.manifest_with(root, cap + 4096, "%s|x" % sfp.LADDER_ID), root)
        self.assertTrue(any(item.startswith("IMG_DELIVERED_OVER_INLINE_CAP") for item in errors),
                        errors)
        self.assertEqual(metrics["delivered_over_per_image_cap"], 1)

    def test_unlabelled_delivery_blocks_even_when_small(self):
        """小但没有档位声明的交付图：字节合规， provenance 不合规——双跳摘要管不到「按哪版档产的」。"""
        root = Path(tempfile.mkdtemp())
        errors, metrics = lmg.check_delivered_rendition_budget(
            self.manifest_with(root, 2048, "thumbnail_aspect_preserve(width=1200,quality=72)"),
            root)
        self.assertTrue(any(item.startswith("IMG_DELIVERED_LADDER_UNREGISTERED")
                            for item in errors), errors)
        self.assertEqual(metrics["delivered_ladder_unregistered"], 1)

    def test_measured_total_over_budget_blocks_the_artifact(self):
        measured = {"file_bytes": 100, "blob_table_keys": 30, "decoded_blob_bytes":
                    LADDER["budgets"]["total_delivered_image_decoded_bytes_max"] + 1,
                    "dead_blobs": [], "dangling_asset_refs": [], "masked_img_refs": [],
                    "declared_media_cap_kb": POLICY["media_delivery"]["default_max_inline_kb"]}
        codes = [item.split("|")[0] for item in sfa.findings(measured, POLICY)]
        self.assertIn("SFD_DELIVERED_TOTAL_OVER_BUDGET", codes)

    def test_new_codes_are_registered_blocking(self):
        for code in ("SFD_DELIVERED_TOTAL_OVER_BUDGET", "IMG_DELIVERED_OVER_INLINE_CAP",
                     "IMG_DELIVERED_LADDER_UNREGISTERED"):
            self.assertEqual(sfp.severity(code, POLICY), "blocking", code)

    def test_emitted_codes_are_all_registered(self):
        """两个模块现在都会 emit 交付档错误码：任何一边写出没登记的新码都必须炸，而不是静默算结论。"""
        blocking, advisory = sfp.split_findings([
            "SFD_DELIVERED_TOTAL_OVER_BUDGET|x", "IMG_DELIVERED_OVER_INLINE_CAP|x",
            "IMG_DELIVERED_LADDER_UNREGISTERED|x"], POLICY)
        self.assertEqual(len(blocking), 3)
        with self.assertRaises(sfp.SingleFilePolicyError):
            sfp.split_findings(["IMG_DELIVERED_INVENTED|x"], POLICY)


if __name__ == "__main__":
    unittest.main()
